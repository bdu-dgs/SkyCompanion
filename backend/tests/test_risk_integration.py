"""Real hub/outbox state transitions with synthetic observations, not field safety tests."""
import asyncio
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.live import LiveHub, Outbox
from app.voice import VoiceOutbox, safe_event

FULL = [[0,0],[1,0],[1,1],[0,1]]
B = dict(label='pole', x=.45, y=.2, w=.08, h=.7, confidence=.8)


class RiskIntegration(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.now = 100.
        self.h = LiveHub(detector=SimpleNamespace(profile='test'), clock=lambda:self.now)
        self.h.model = {'state':'ready'}
        self.h.connection='connected'; self.h.capture='receiving'; self.h.analysis_enabled=True
        self.h.corridor=FULL
        self.h.voice.phone=VoiceOutbox(lambda:self.now); self.h.voice.select('both')
        self.h.viewer_out=Outbox()
    def tearDown(self):
        self.h.executor.shutdown(wait=False); self.h.evidence_executor.shutdown(wait=False)
    def observe(self, boxes=None):
        self.h.latest_risk=self.h.risk_monitor.update([B] if boxes is None else boxes,FULL,self.now)
        self.h.latest_risk_at=self.now; self.h.latest_capture_uptime_ms=self.now*1000
        self.h.last_frame=self.now; self.h.last_heartbeat=self.now
    def confirm(self):
        for delta in (0,.2,.3):
            self.now+=delta; self.observe()
    async def test_health_transition_is_single_and_recovery_is_bounded(self):
        self.observe(); self.h.refresh_perception()
        self.now+=.6; self.observe(); self.h.refresh_perception()
        self.assertEqual(len(self.h._health_event_history),1)
        self.now+=1.6; self.h.check_freshness()
        self.assertEqual(self.h.state()['perception']['status'],'unavailable')
        self.assertIsNone(self.h.state()['risk']['risk_level'])
        self.assertEqual(self.h.voice.phone.pending[0]['event']['speech_code'],'perception_unavailable')
        self.h.check_freshness(); self.h.check_freshness()
        self.assertEqual(len(self.h._health_event_history),2)
        self.observe(); self.h.refresh_perception()
        self.now+=.6; self.observe(); self.h.refresh_perception()
        self.assertEqual(self.h.voice.phone.pending[0]['event']['speech_code'],'perception_restored')
    async def test_repeat_mac_only_and_ack_do_not_clear_risk(self):
        self.confirm(); self.h.voice.select('mac'); self.h.voice.phone=None
        reply=self.h.mobile_command({'command':'repeat'})
        self.assertIsNone(reply['speech'])
        queued=[p for p in self.h.viewer_out.controls if p['type']=='voice_event']
        self.assertEqual(queued[-1]['event']['schema_version'],2)
        self.assertEqual(queued[-1]['event']['direction_frame'],'camera_image')
        self.h.mobile_command({'command':'acknowledge'})
        self.assertEqual(self.h.current_risk()['risk_level'],'R2')
        self.now+=.2; self.observe([])
        self.assertEqual(self.h.mobile_command({'command':'repeat'})['speech']['code'],'no_recent_alert')
        self.assertEqual(self.h.mobile_command({'command':'explain'})['speech']['code'],'risk_unresolved')
    async def test_transport_timeout_does_not_cut_short_fault_notice(self):
        self.observe(); self.h.refresh_perception()
        self.now+=.6; self.observe(); self.h.refresh_perception()
        self.now+=1.6; self.h.check_freshness()
        self.h.voice.phone.stop_message=None  # receiver already consumed the fault stop
        self.now+=.6; self.h.check_freshness()
        self.assertIsNone(self.h.voice.phone.stop_message)
        self.assertEqual(self.h.voice.phone.pending[0]['event']['speech_code'],'perception_unavailable')
    async def test_expired_visual_event_never_replayed_in_browser_queue(self):
        out=Outbox(); sent=[]
        out.put({'type':'voice_event','event':{'id':'old','ttl_ms':1}})
        await asyncio.sleep(.01)
        task=asyncio.create_task(out.pump(SimpleNamespace(send_json=lambda message:sent.append(message))))
        await asyncio.sleep(.01); task.cancel(); await asyncio.gather(task,return_exceptions=True)
        self.assertEqual(sent,[])
    async def test_false_alert_without_fresh_frame_does_not_claim_saved(self):
        reply=await self.h.handle_command({'command':'report_false_alert'})
        self.assertFalse(reply['ok']); self.assertEqual(reply['speech']['code'],'no_evidence')
    async def test_stale_explanation_is_fresh_status_not_refreshed_visual_evidence(self):
        self.confirm(); self.now+=1.6
        reply=self.h.mobile_command({'command':'explain'})['speech']
        self.assertEqual(reply,{'code':'risk_unresolved','ttl_ms':1500,'direction':None})
        self.assertNotIn('captured_uptime_ms',reply)
    async def test_stop_removes_queued_visual_explanation_and_precedes_controls(self):
        out=Outbox()
        out.put({'type':'command_reply','speech':{'code':'risk_explanation','ttl_ms':1400}})
        out.put({'type':'state','session_id':'s','revision':1})
        out.put({'type':'voice_stop','reason':'context_changed'})
        self.assertEqual([p['type'] for p in out.controls],['voice_stop'])
    async def test_revision_invalidation_discards_old_corridor_frame(self):
        out=Outbox()
        out.put({'type':'frame','session_id':'s','revision':1})
        out.put({'type':'state','session_id':'s','revision':2})
        self.assertIsNone(out.frame)
    async def test_voice_schema_and_capture_are_required(self):
        event={'id':'x','schema_version':2,'speech_code':'camera_obstacle','direction':'left',
               'direction_frame':'camera_image','risk_level':'R2','priority':'obstacle','ttl_ms':1500}
        self.h.voice.publish(event)
        self.assertIsNone(self.h.voice.phone.pending)
        self.h.voice.publish(event,captured_uptime_ms=100000)
        self.assertEqual(self.h.voice.phone.pending[0]['event']['asset'],'risk_camera_obstacle_left')
        for bad in ({'risk_level':'R0'},{'priority':'urgent'},{'direction_frame':'wearer'}, {'ttl_ms':float('nan')}):
            self.assertIsNone(safe_event({**event,**bad}))


if __name__=='__main__': unittest.main()
