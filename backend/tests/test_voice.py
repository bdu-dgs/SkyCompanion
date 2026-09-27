import asyncio
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from fastapi import WebSocketDisconnect

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.voice import VoiceChannel, VoiceOutbox
from app import live


class Clock:
    value = 100.
    def __call__(self): return self.value


def event(identifier='a', priority='obstacle', ttl_ms=1500):
    return dict(id=identifier, direction='left', priority=priority, ttl_ms=ttl_ms,
                text='train', category_naming_enabled=True, schema_version=2, speech_code='camera_obstacle', direction_frame='camera_image', risk_level='R2')


class VoiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_queue_replaces_old_events_but_test_cannot_displace_obstacle(self):
        clock = Clock(); out = VoiceOutbox(clock)
        out.put(dict(type='voice_event', event=event('old')))
        out.put(dict(type='voice_event', event=event('new')))
        out.put(dict(type='voice_event', event=event('test', 'test')))
        self.assertEqual(out.pending[0]['event']['id'], 'new')
        out.put(dict(type='voice_stop'))
        self.assertIsNone(out.pending)

    async def test_expired_before_socket_send_is_dropped(self):
        clock = Clock(); out = VoiceOutbox(clock); sent = []
        async def send(message): sent.append(message)
        out.put(dict(type='voice_event', event=event()))
        clock.value += 2
        task = asyncio.create_task(out.pump(SimpleNamespace(send_json=send)))
        await asyncio.sleep(.01)
        task.cancel(); await asyncio.gather(task, return_exceptions=True)
        self.assertEqual(sent, [])

    async def test_routing_age_and_unvalidated_names(self):
        clock = Clock(); voice = VoiceChannel(clock); voice.phone = VoiceOutbox(clock)
        voice.publish(event())
        self.assertIsNone(voice.phone.pending)
        voice.select('both'); voice.publish(event(), 400, 99000)
        delivered = voice.phone.pending[0]['event']
        self.assertEqual(delivered['ttl_ms'], 1100)
        self.assertEqual(delivered['text'], 'Caution. Possible obstacle on the left in the camera view. Your direction is unverified.')
        self.assertFalse(delivered['category_naming_enabled'])
        voice.acknowledge(dict(event_id='a', stage='started'))
        self.assertEqual(voice.last_ack['measurement'], 'receiver_API_callback_not_acoustic_onset')
        with self.assertRaises(ValueError): voice.acknowledge(dict(event_id='old-unknown', stage='started'))
        voice.select('mac')
        self.assertIsNone(voice.phone.pending)
        voice.select('phone'); voice.publish(event('stale'), 1600)
        self.assertIsNone(voice.phone.pending)

    async def test_voice_socket_requires_token_and_cleans_up_real_receiver(self):
        incoming = asyncio.Queue(); outgoing = asyncio.Queue(); closed = []
        async def accept(): pass
        async def close(**kw): closed.append(kw)
        async def receive():
            item = await incoming.get()
            if item is None: raise WebSocketDisconnect()
            return json.dumps(item)
        socket = SimpleNamespace(headers={'authorization':'Bearer wrong'}, accept=accept, close=close,
                                 receive_text=receive, send_json=outgoing.put)
        clock = Clock(); voice = VoiceChannel(clock)
        states = []
        hub = SimpleNamespace(voice=voice, clock=clock, publish_state=lambda:states.append(voice.state()))
        with patch.object(live, 'read_config', return_value={'token':'test-only'}), patch.object(live, 'hub', hub):
            await live.voice_socket(socket)
            self.assertEqual(closed[-1]['code'], 1008)
            self.assertIsNone(voice.phone)
            socket.headers['authorization'] = 'Bearer test-only'
            task = asyncio.create_task(live.voice_socket(socket))
            initial = await asyncio.wait_for(outgoing.get(), 1)
            self.assertEqual(initial, {'type':'voice_state','output':'off'})
            self.assertTrue(voice.state()['phone_connected'])
            voice.select('phone'); voice.publish(event(), captured_uptime_ms=99000)
            while (message := await asyncio.wait_for(outgoing.get(), 1))['type'] != 'voice_event': pass
            self.assertEqual(message['event']['asset'], 'risk_camera_obstacle_left')
            await incoming.put({'type':'voice_ack','event_id':'a','stage':'completed'})
            await asyncio.sleep(.01)
            self.assertEqual(voice.last_ack['stage'], 'completed')
            await incoming.put(None)
            await asyncio.wait_for(task, 1)
            self.assertFalse(voice.state()['phone_connected'])


if __name__ == '__main__': unittest.main()
