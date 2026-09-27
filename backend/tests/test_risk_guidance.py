"""Scenario tests for image evidence, lifecycle, physical gating and speech policy."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.obstacle_risk import MAX_TRACKS, REASON_CODES, RiskMonitor

FULL = [[0, 0], [1, 0], [1, 1], [0, 1]]
CENTER = [[.3, .4], [.7, .4], [.7, 1], [.3, 1]]


def box(label='pole', x=.4, y=.35, w=.08, h=.55, confidence=.8):
    return dict(label=label, x=x, y=y, w=w, h=h, confidence=confidence)


def confirm(monitor, boxes, corridor=FULL, offset=0., context=None, slow=False):
    for t in ((0., .2, .5, .8, 1.2) if slow else (0., .2, .5)):
        result = monitor.update(boxes, corridor, offset+t, context)
    return result


class RiskGuidanceTests(unittest.TestCase):
    def test_no_corridor_or_no_conflict_never_means_safe(self):
        monitor = RiskMonitor(ordinary_alert_gap_s=0)
        result = monitor.update([box()], None, 0.)
        self.assertIsNone(result['risk_level'])
        for boxes in ([], [box('tree')], [box('traffic light')], [box(x=.02)]):
            result = confirm(RiskMonitor(ordinary_alert_gap_s=0), boxes, CENTER)
            self.assertEqual(result['risk_level'], 'R0')
            self.assertIn('does not mean', result['text'])
            self.assertIsNone(result['event'])

    def test_image_evidence_is_not_distance_or_heading_and_input_preserved(self):
        monitor = RiskMonitor(ordinary_alert_gap_s=0)
        boxes = [box('person', x=.5, y=.45, w=.035, h=.12),
                 box('concrete block', x=.2, y=.86, w=.25, h=.07)]
        before = copy.deepcopy(boxes)
        result = confirm(monitor, boxes)
        self.assertEqual(result['direction'], 'left')
        self.assertEqual(result['risk_level'], 'R2')
        self.assertEqual(result['evidence']['kind'], 'low_object_candidate')
        self.assertIsNone(result['evidence']['metric_distance'])
        self.assertEqual(result['evidence']['nearest_basis'], 'image_geometry_proxy_not_meters')
        self.assertEqual(result['direction_frame'], 'camera_image')
        self.assertEqual(result['evidence_confidence'], dict(presence='supported', path='image_proxy', category='unconfirmed', distance='unknown'))
        self.assertFalse(result['evidence']['ground_contact_confirmed'])
        self.assertEqual(before, boxes)

    def test_camera_only_runtime_cannot_make_r3_even_large_or_vehicle(self):
        for b in (box(w=.6, h=.6), box('train'), box('pothole'), box('overhead obstacle', y=.1, w=.3, h=.2)):
            result = confirm(RiskMonitor(ordinary_alert_gap_s=0), [b])
            self.assertEqual(result['risk_level'], 'R2')
            self.assertEqual(result['event']['priority'], 'obstacle')
            self.assertNotIn('stop', result['text'].lower())

    def test_surface_drop_overhead_vehicle_have_distinct_consequences(self):
        for label, consequence in [('stairs', 'surface'), ('pothole', 'drop'), ('overhead obstacle', 'overhead'), ('car', 'vehicle')]:
            b = box(label, y=.1 if consequence == 'overhead' else .8, w=.2,
                    h=.15 if consequence == 'overhead' else .08)
            result = confirm(RiskMonitor(ordinary_alert_gap_s=0), [b], CENTER)
            self.assertEqual(result['evidence']['hazard_consequence'], consequence)
            self.assertEqual(result['event']['speech_code'], 'camera_obstacle')
            self.assertFalse(result['event']['category_naming_enabled'])
        for label, code in [('stairs', 'camera_surface'), ('car', 'camera_vehicle'), ('overhead obstacle', 'camera_overhead')]:
            b = box(label, y=.1 if label == 'overhead obstacle' else .5, w=.2, h=.2)
            result = confirm(RiskMonitor(named_labels=[label]), [b])
            self.assertEqual(result['event']['speech_code'], code)

    def test_two_objects_reordering_preserves_tracks_and_direction(self):
        monitor = RiskMonitor(ordinary_alert_gap_s=0)
        left, right = box(x=.2), box(x=.7)
        first = confirm(monitor, [left, right])
        for t in (.7, .9, 1.1):
            result = monitor.update([right, left], FULL, t)
            self.assertEqual(result['track_id'], first['track_id'])
        self.assertEqual(len(monitor.tracks), 2)

    def test_unconfirmed_nearer_object_does_not_erase_confirmed_track(self):
        monitor = RiskMonitor(ordinary_alert_gap_s=0)
        existing = box(x=.2, y=.45, h=.4)
        previous = confirm(monitor, [existing])
        result = monitor.update([box(x=.7, y=.15, h=.8), existing], FULL, .7)
        self.assertEqual(result['track_id'], previous['track_id'])

    def test_occlusion_never_clears_and_acknowledgement_never_resolves(self):
        monitor = RiskMonitor(ordinary_alert_gap_s=0)
        first = confirm(monitor, [box()])
        self.assertEqual(monitor.acknowledge()['code'], 'risk_acknowledged')
        for t in (.6, 2., 9., 100.):
            result = monitor.update([], FULL, t)
            self.assertEqual(result['lifecycle'], 'occluded_unresolved')
            self.assertEqual(result['risk_level'], first['risk_level'])
            self.assertTrue(result['acknowledged'])
            self.assertIsNone(result['event'])
            self.assertIsNone(monitor.describe(t+.1)['direction'])
            self.assertEqual(monitor.explain(t+.1)['code'], 'risk_unresolved')
        self.assertLessEqual(len(monitor.tracks), MAX_TRACKS)
        self.assertIsNotNone(monitor.unresolved_summary)

    def test_visible_lower_risk_target_cannot_erase_unresolved_higher_risk(self):
        monitor = RiskMonitor(ordinary_alert_gap_s=0)
        first = confirm(monitor, [box(x=.1)])
        result = confirm(monitor, [box(x=.7, y=.45, w=.04, h=.12)], offset=.7)
        self.assertEqual(result['risk_level'], 'R2')
        self.assertEqual(result['track_id'], first['track_id'])
        self.assertEqual(result['lifecycle'], 'occluded_unresolved')
        self.assertIsNone(result['direction'])
        self.assertIsNone(result['event'])

    def test_unresolved_summary_survives_memory_bound(self):
        monitor = RiskMonitor(ordinary_alert_gap_s=0)
        confirm(monitor, [box()])
        monitor.update([], FULL, 10.)
        for i in range(100):
            monitor.update([box(x=.01, w=.01)], FULL, 11.+i)
        self.assertLessEqual(len(monitor.tracks), MAX_TRACKS)
        self.assertEqual(monitor.last_result['lifecycle'], 'occluded_unresolved')

    def test_no_periodic_repeat_after_eight_seconds(self):
        monitor = RiskMonitor(ordinary_alert_gap_s=0)
        self.assertIsNotNone(confirm(monitor, [box()])['event'])
        for i in range(1, 100):
            result = monitor.update([box()], FULL, .5+i*.2)
            self.assertIsNone(result['event'])

    def test_new_relevance_is_not_suppressed_by_old_global_timer(self):
        monitor = RiskMonitor(ordinary_alert_gap_s=0)
        original = box(x=.15, y=.45, w=.04, h=.12)
        confirm(monitor, [original], slow=True)
        result = confirm(monitor, [original, box(x=.75)], offset=1.4)
        self.assertIsNotNone(result['event'])
        self.assertIn('new_relevance', result['event']['reason_codes'])

    def test_tracked_outside_to_inside_alerts_on_relevance(self):
        monitor = RiskMonitor(ordinary_alert_gap_s=0)
        result = confirm(monitor, [box(x=.12, w=.2)], CENTER)
        key = next(iter(monitor.tracks))
        self.assertEqual(result['risk_level'], 'R0')
        for t, x in [(.7, .18), (.9, .24), (1.2, .3), (1.4, .3)]:
            result = monitor.update([box(x=x, w=.2)], CENTER, t)
            if result['event']:
                self.assertEqual(result['event']['track_id'], key)
                break
        else:
            self.fail('No entry event')

    def test_visible_separation_resolves_only_image_conflict(self):
        monitor = RiskMonitor(ordinary_alert_gap_s=0)
        confirm(monitor, [box(x=.35, w=.2)], CENTER)
        for t, x in [(.7,.28), (.9,.21), (1.1,.14), (1.3,.07), (1.5,0.), (1.8,0.)]:
            result = monitor.update([box(x=x, w=.2)], CENTER, t)
        self.assertEqual(result['lifecycle'], 'image_conflict_resolved')
        self.assertEqual(result['risk_level'], 'R0')
        self.assertIn('does not mean', result['text'])
        self.assertNotIn('passed', result['text'])

    def test_risk_upgrade_and_material_direction_change_alert(self):
        monitor = RiskMonitor(ordinary_alert_gap_s=0)
        b = box(x=.43, y=.45, w=.04, h=.12)
        first = confirm(monitor, [b], slow=True)
        self.assertEqual(first['risk_level'], 'R1')
        result = monitor.update([{**b, 'h':.25}], FULL, 1.4)
        self.assertEqual(result['risk_level'], 'R2')
        self.assertIn('risk_upgrade', result['event']['reason_codes'])
        # Track gradual travel with overlap; a bin-boundary jitter cannot alert.
        monitor = RiskMonitor(ordinary_alert_gap_s=0)
        confirm(monitor, [box(x=.2, w=.3)])
        events = []
        for i, x in enumerate([.23,.26,.29,.32,.35,.38,.41,.44,.47,.5,.5,.5,.5]):
            result = monitor.update([box(x=x, w=.3)], FULL, .7+i*.2)
            if result['event']:
                events.append(result['event'])
        self.assertTrue(any('direction_change' in e['reason_codes'] for e in events))

    def test_equal_risk_boxes_do_not_serially_announce(self):
        monitor = RiskMonitor(ordinary_alert_gap_s=0)
        boxes = [box(x=.2), box(x=.7)]
        first = confirm(monitor, boxes)
        self.assertIsNotNone(first['event'])
        for i in range(20):
            result = monitor.update(list(reversed(boxes)), FULL, .7+i*.2)
            self.assertIsNone(result['event'])
            self.assertEqual(result['track_id'], first['track_id'])

    def test_lower_risk_new_target_cannot_distract_from_persistent_high_risk(self):
        monitor = RiskMonitor(ordinary_alert_gap_s=0)
        first = box(x=.2)
        confirm(monitor, [first])
        result = confirm(monitor, [first, box(x=.7, y=.45, w=.04, h=.12)], offset=.7)
        self.assertEqual(result['risk_level'], 'R2')
        self.assertIsNone(result['event'])

    def test_acknowledgement_suppresses_direction_only_but_not_risk_upgrade(self):
        monitor = RiskMonitor(ordinary_alert_gap_s=0)
        confirm(monitor, [box(x=.2, w=.3)])
        monitor.acknowledge()
        for i, x in enumerate([.23,.26,.29,.32,.35,.38,.41,.44,.47,.5,.5,.5,.5]):
            result = monitor.update([box(x=x, w=.3)], FULL, .7+i*.2)
            self.assertIsNone(result['event'])
        monitor = RiskMonitor(ordinary_alert_gap_s=0)
        b = box(x=.43, y=.45, w=.04, h=.12)
        confirm(monitor, [b], slow=True)
        monitor.acknowledge()
        result = monitor.update([{**b, 'h':.25}], FULL, 1.4)
        self.assertIn('risk_upgrade', result['event']['reason_codes'])

    def test_quiet_suppresses_r1_but_not_r2_or_upgrade(self):
        monitor = RiskMonitor(ordinary_alert_gap_s=0)
        self.assertEqual(monitor.set_quiet(True)['code'], 'quiet_enabled')
        distant = box(x=.43, y=.45, w=.04, h=.12)
        result = confirm(monitor, [distant], slow=True)
        self.assertEqual(result['risk_level'], 'R1')
        self.assertIsNone(result['event'])
        result = monitor.update([{**distant, 'h':.25}], FULL, 1.4)
        self.assertEqual(result['event']['risk_level'], 'R2')

    def test_duplicate_timestamp_cannot_confirm_or_replay(self):
        monitor = RiskMonitor(ordinary_alert_gap_s=0)
        for _ in range(10):
            self.assertEqual(monitor.update([box()], FULL, 0)['state'], 'confirming')
        monitor.update([box()], FULL, .2)
        first = monitor.update([box()], FULL, .5)
        self.assertIsNotNone(first['event'])
        self.assertIsNone(monitor.update([box()], FULL, .5)['event'])

    def test_missing_frames_interrupt_tentative_confirmation(self):
        monitor = RiskMonitor(ordinary_alert_gap_s=0)
        monitor.update([box()], FULL, 0.)
        monitor.update([], FULL, .1)
        monitor.update([box()], FULL, .2)
        result = monitor.update([box()], FULL, .5)
        self.assertEqual(result['state'], 'confirming')
        self.assertIsNone(result['event'])

    def test_unstable_label_never_names_even_allowlisted(self):
        monitor = RiskMonitor(named_labels=['pole', 'train'])
        monitor.update([box('pole')], FULL, 0)
        monitor.update([box('train')], FULL, .2)
        result = monitor.update([box('pole')], FULL, .5)
        self.assertFalse(result['event']['category_naming_enabled'])
        self.assertEqual(result['event']['speech_code'], 'camera_obstacle')

    def test_stale_describe_and_explain_withhold_old_direction(self):
        monitor = RiskMonitor(ordinary_alert_gap_s=0)
        confirm(monitor, [box(x=.2)])
        fresh = monitor.describe(.6)
        self.assertEqual(fresh['schema_version'], 2)
        self.assertEqual(fresh['direction'], 'left')
        self.assertLess(fresh['ttl_ms'], 1500)
        explanation = monitor.explain(.6)
        self.assertEqual(explanation['code'], 'risk_explanation')
        self.assertTrue(set(explanation['reason_codes']) <= REASON_CODES)
        stale = monitor.explain(2.1)
        self.assertEqual(stale['code'], 'risk_unresolved')
        self.assertIsNone(stale['direction'])
        self.assertEqual(stale['ttl_ms'], 0)
        monitor.reset()
        self.assertEqual(monitor.describe(3.)['code'], 'vision_unavailable')

    def test_r3_requires_target_binding_freshness_all_validation_and_full_budget(self):
        monitor = RiskMonitor(ordinary_alert_gap_s=0)
        first = confirm(monitor, [box()])
        key = first['track_id']
        context = dict(track_id=key, observed_at_s=.7, wearer_heading_validated=True,
            path_validated=True, distance_validated=True, closing_speed_validated=True,
            distance_m=1., closing_speed_m_s=1., frame_age_s=.1, processing_latency_s=.1,
            speech_latency_s=.3, reaction_time_s=.7, stopping_time_s=.5)
        for removed in ['track_id','path_validated','distance_validated','closing_speed_validated','wearer_heading_validated','reaction_time_s','speech_latency_s']:
            invalid = dict(context); invalid.pop(removed)
            self.assertIsNone(monitor._physical_evidence(invalid, key, .7), removed)
        for change in [dict(track_id='other'), dict(observed_at_s=-5), dict(observed_at_s=3),
                       dict(distance_m=float('nan')), dict(closing_speed_m_s=0), dict(reaction_time_s=-1)]:
            self.assertIsNone(monitor._physical_evidence({**context, **change}, key, .7))
        result = monitor.update([box()], FULL, .7, context)
        self.assertEqual(result['risk_level'], 'R3')
        self.assertEqual(result['event']['priority'], 'urgent')
        self.assertIn('validated_ttc_budget', result['reason_codes'])
        self.assertEqual(result['evidence_confidence']['distance'], 'validated')
        self.assertAlmostEqual(result['evidence']['ttc_budget_s'], 1.7)
        # A physically distant object does not qualify for urgent priority.
        result = monitor.update([box()], FULL, .9, {**context, 'distance_m':10.})
        self.assertEqual(result['risk_level'], 'R2')

    def test_fragmented_ids_do_not_repeat_same_spatial_message(self):
        monitor = RiskMonitor(ordinary_alert_gap_s=0)
        first = confirm(monitor, [box(x=.43)])
        self.assertIsNotNone(first['event'])
        previous = first['track_id']
        for offset in (2., 4., 8., 16.):
            result = confirm(monitor, [box(x=.43)], offset=offset)
            self.assertNotEqual(result['track_id'], previous)
            self.assertIsNone(result['event'])
            previous = result['track_id']
        self.assertEqual(len(monitor.episode_spoken), 1)
        # User-requested repeat remains a fresh structured description.
        self.assertEqual(monitor.describe(16.6)['code'], 'camera_obstacle')
        self.assertGreater(monitor.describe(16.6)['ttl_ms'], 0)

    def test_target_switch_same_direction_suppressed_but_new_direction_once(self):
        monitor = RiskMonitor(ordinary_alert_gap_s=0)
        original = box(x=.02, y=.45, w=.08, h=.25)
        first = confirm(monitor, [original])
        self.assertEqual(first['direction'], 'left')
        # More visually relevant, non-overlapping target in the same image side.
        dominant = box(x=.22, y=.1, w=.08, h=.88)
        result = confirm(monitor, [original, dominant], offset=.7)
        self.assertNotEqual(first['track_id'], result['track_id'])
        self.assertIsNone(result['event'])
        result = confirm(monitor, [box(x=.75)], offset=2.5)
        self.assertEqual(result['event']['direction'], 'right')
        result = confirm(monitor, [box(x=.75)], offset=5.)
        self.assertIsNone(result['event'])

    def test_episode_signatures_clear_after_evidenced_resolution_or_reset(self):
        monitor = RiskMonitor(ordinary_alert_gap_s=0)
        confirm(monitor, [box(x=.35, w=.2)], CENTER)
        self.assertTrue(monitor.episode_spoken)
        for t, x in [(.7,.28), (.9,.21), (1.1,.14), (1.3,.07), (1.5,0.), (1.8,0.)]:
            result = monitor.update([box(x=x, w=.2)], CENTER, t)
        self.assertEqual(result['lifecycle'], 'image_conflict_resolved')
        self.assertFalse(monitor.episode_spoken)
        result = confirm(monitor, [box(x=.35, w=.2)], CENTER, offset=3.)
        self.assertIsNotNone(result['event'])
        monitor.reset()
        self.assertFalse(monitor.episode_spoken)
        self.assertIsNotNone(confirm(monitor, [box(x=.35, w=.2)], CENTER, offset=4.)['event'])

    def test_risk_upgrade_bypasses_prior_episode_signature(self):
        monitor = RiskMonitor(ordinary_alert_gap_s=0)
        distant = box(x=.43, y=.45, w=.04, h=.12)
        confirm(monitor, [distant], slow=True)
        # The episode may already contain an R2 signature from another target.
        monitor.episode_spoken.add(('R2', 'camera_obstacle', 'ahead'))
        result = monitor.update([{**distant, 'h':.25}], FULL, 1.4)
        self.assertIn('risk_upgrade', result['event']['reason_codes'])

    def test_new_validated_urgent_target_bypasses_episode_signature(self):
        monitor = RiskMonitor(ordinary_alert_gap_s=0)
        first = confirm(monitor, [box(x=.43)])
        def physical(key, now):
            return dict(track_id=key, observed_at_s=now, wearer_heading_validated=True,
                path_validated=True, distance_validated=True, closing_speed_validated=True,
                distance_m=1., closing_speed_m_s=1., frame_age_s=.1, processing_latency_s=.1,
                speech_latency_s=.3, reaction_time_s=.7, stopping_time_s=.5)
        result = monitor.update([box(x=.43)], FULL, .7, physical(first['track_id'], .7))
        self.assertEqual(result['event']['risk_level'], 'R3')
        monitor.update([box(x=.43)], FULL, 2.)
        new_key = max(monitor.tracks, key=lambda k: monitor.tracks[k]['first_seen'])
        self.assertNotEqual(first['track_id'], new_key)
        monitor.update([box(x=.43)], FULL, 2.2)
        result = monitor.update([box(x=.43)], FULL, 2.5, physical(new_key, 2.5))
        self.assertEqual(result['event']['risk_level'], 'R3')
        self.assertEqual(result['event']['track_id'], new_key)

    def test_default_gap_allows_only_one_same_level_alert_within_eight_seconds(self):
        monitor = RiskMonitor()
        events = [confirm(monitor, [box(x=.1)])['event']]
        for offset, x in [(1., .75), (2., .43), (4., .75), (6., .43)]:
            result = confirm(monitor, [box(x=x)], offset=offset)
            events.append(result['event'])
        self.assertEqual(sum(event is not None for event in events), 1)
        # No old message is queued: current fresh primary is evaluated after gap.
        result = confirm(monitor, [box(x=.75)], offset=8.2)
        self.assertIsNotNone(result['event'])
        self.assertEqual(result['event']['direction'], 'right')
        self.assertEqual(result['event']['observed_at_s'], 8.7)
        # Identical episode signatures remain suppressed beyond any time gap.
        result = confirm(monitor, [box(x=.75)], offset=20.)
        self.assertIsNone(result['event'])

    def test_gated_target_that_disappears_never_plays_later(self):
        monitor = RiskMonitor()
        confirm(monitor, [box(x=.1)])
        self.assertIsNone(confirm(monitor, [box(x=.75)], offset=1.)['event'])
        for now in (2., 8.5, 10., 30.):
            result = monitor.update([], FULL, now)
            self.assertIsNone(result['event'])
            self.assertEqual(result['lifecycle'], 'occluded_unresolved')
        self.assertEqual(monitor.episode_spoken, {('R2', 'camera_obstacle', 'left')})

    def test_r1_hold_and_risk_escalation_bypass_default_gap(self):
        monitor = RiskMonitor()
        distant = box(x=.43, y=.45, w=.04, h=.12)
        for now in (0., .2, .5, .8, 1.1):
            result = monitor.update([distant], FULL, now)
            self.assertEqual(result['state'], 'confirming')
            self.assertIsNone(result['event'])
        result = monitor.update([distant], FULL, 1.2)
        self.assertEqual(result['event']['risk_level'], 'R1')
        result = monitor.update([{**distant, 'h':.25}], FULL, 1.4)
        self.assertEqual(result['event']['risk_level'], 'R2')
        self.assertIn('risk_upgrade', result['event']['reason_codes'])
        # New higher-risk targets also bypass the gap without claiming tracking identity.
        monitor = RiskMonitor()
        confirm(monitor, [distant], slow=True)
        result = confirm(monitor, [distant, box(x=.75)], offset=1.4)
        self.assertEqual(result['event']['risk_level'], 'R2')

    def test_r2_uses_short_hold_and_quiet_does_not_consume_ordinary_gap(self):
        self.assertIsNotNone(confirm(RiskMonitor(), [box()])['event'])
        monitor = RiskMonitor()
        monitor.set_quiet(True)
        distant = box(x=.43, y=.45, w=.04, h=.12)
        self.assertIsNone(confirm(monitor, [distant], slow=True)['event'])
        self.assertFalse(monitor.episode_spoken)
        monitor.set_quiet(False)
        self.assertIsNotNone(monitor.update([distant], FULL, 1.4)['event'])

    def test_ordinary_gap_is_configurable_and_validated(self):
        monitor = RiskMonitor(ordinary_alert_gap_s=2.)
        confirm(monitor, [box(x=.1)])
        self.assertIsNone(confirm(monitor, [box(x=.75)], offset=1.)['event'])
        for now in (1.7, 1.9, 2.1, 2.3):
            self.assertIsNone(monitor.update([box(x=.75)], FULL, now)['event'])
        self.assertIsNotNone(monitor.update([box(x=.75)], FULL, 2.5)['event'])
        for invalid in (-1, float('nan'), float('inf'), True, '8'):
            with self.assertRaises(ValueError):
                RiskMonitor(ordinary_alert_gap_s=invalid)

    def test_invalid_input_and_malformed_mask_do_not_crash_or_change_predictions(self):
        invalid = [None, 'bad box', box(x=float('nan')), box(h=-1), dict(label='pole')]
        self.assertEqual(confirm(RiskMonitor(ordinary_alert_gap_s=0), invalid)['risk_level'], 'R0')
        valid = {**box(), 'polygon': [[0,0], [float('inf'),1], [1,1]]}
        self.assertEqual(confirm(RiskMonitor(ordinary_alert_gap_s=0), [valid])['state'], 'occupied')


if __name__ == '__main__':
    unittest.main()
