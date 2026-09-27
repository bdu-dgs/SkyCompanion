"""Phone-only control preserves session freshness and never needs a desktop viewer."""
import sys
from pathlib import Path
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from fastapi import HTTPException
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.live import LiveHub, authenticated_mobile
from app.voice import VoiceOutbox

class MobileTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.
        self.hub = LiveHub(detector=SimpleNamespace(profile='test'), clock=lambda:self.now)
        self.hub.model = {'state':'ready'}
    def tearDown(self):
        self.hub.executor.shutdown(wait=False)
        self.hub.evidence_executor.shutdown(wait=False)
    def arm(self):
        return self.hub.mobile_command({'command':'start_analysis','corridor':[[.35,.45],[.65,.45],[.9,1],[.1,1]]})
    def frame(self, number=1, width=800, height=400):
        self.hub.accept_frame(SimpleNamespace(session_id=self.hub.session_id,frame_id=number,width=width,height=height,orientation=1,received_at=self.now))
    def test_phone_arms_next_session_and_portrait_pauses(self):
        self.arm(); self.hub.begin('screen_video_test'); self.frame()
        self.assertTrue(self.hub.analysis_enabled)
        self.assertIsNotNone(self.hub.corridor)
        self.frame(2,400,800)
        self.assertFalse(self.hub.analysis_enabled)
        self.frame(3)
        self.assertTrue(self.hub.analysis_enabled)
        self.hub.end(self.hub.session_id)
        self.hub.begin('screen_video_test'); self.frame()
        self.assertFalse(self.hub.analysis_enabled)
    def test_arm_expires_and_missing_corridor_rejected(self):
        with self.assertRaises(ValueError): self.hub.mobile_command({'command':'start'})
        self.arm(); self.now += 121; self.hub.begin('screen_video_test'); self.frame()
        self.assertFalse(self.hub.analysis_enabled)
    def test_repeat_does_not_refresh_observation_deadline(self):
        self.hub.voice.phone=VoiceOutbox(lambda:self.now)
        self.hub.voice.select('phone')
        self.hub.analysis_enabled=True
        self.hub.latest_event={'id':'old','direction':'left','ttl_ms':1500,'priority':'obstacle'}
        self.hub.latest_event_deadline=100.4
        self.hub.latest_risk_at=99.
        self.hub.latest_capture_uptime_ms=99000
        self.hub.risk_monitor.describe=lambda now: {'state':'occupied','direction':'left','ttl_ms':max(0,int((100.4-now)*1000))}
        self.hub.mobile_command({'command':'repeat'})
        event=self.hub.voice.phone.pending[0]['event']
        self.assertLessEqual(event['ttl_ms'],400)
        self.assertNotEqual(event['id'],'old')
        self.now += 1
        result=self.hub.mobile_command({'command':'repeat'})
        self.assertEqual(result['speech']['code'],'no_recent_alert')
    def test_describe_stale_and_empty_never_claim_safe(self):
        self.assertEqual(self.hub.mobile_command({'command':'describe'})['speech']['code'],'vision_unavailable')
        self.hub.analysis_enabled=True; self.hub.latest_risk_at=100.; self.hub.latest_risk={'state':'unconfirmed'}; self.hub.scene_description.update([],100.)
        self.assertEqual(self.hub.mobile_command({'command':'describe'})['speech']['code'],'no_stable_objects')
        self.now += 2
        self.assertEqual(self.hub.mobile_command({'command':'describe'})['speech']['code'],'vision_unavailable')
    def test_auth_rejects_missing_credentials_and_browser_origin(self):
        with patch('app.live.read_config', return_value={'token':'test-pairing'}):
            for headers in ({},{'authorization':'Bearer test-pairing','origin':'https://example.com'}):
                with self.assertRaises(HTTPException): authenticated_mobile(SimpleNamespace(headers=headers))
            authenticated_mobile(SimpleNamespace(headers={'authorization':'Bearer test-pairing'}))

if __name__=='__main__': unittest.main()
