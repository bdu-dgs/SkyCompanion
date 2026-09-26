import unittest

import numpy as np
import torch

from sky_companion import Frame, LatestFrame, SceneRules, mono_ms, signal_color, wall_ms, warning_text


class FakeBoxes:
    def __init__(self, rows):
        self.xyxy = torch.tensor([r[:4] for r in rows], dtype=torch.float32).reshape(-1, 4)
        self.cls = torch.tensor([r[4] for r in rows], dtype=torch.float32)
        self.conf = torch.tensor([r[5] for r in rows], dtype=torch.float32)
        self.id = torch.tensor([r[6] for r in rows], dtype=torch.float32) if rows else None

    def __len__(self):
        return len(self.cls)


class FakeResult:
    names = {0: "person", 9: "traffic light"}

    def __init__(self, rows, names=None):
        self.boxes = FakeBoxes(rows)
        if names is not None:
            self.names = names


class PrototypeChecks(unittest.TestCase):
    def frame(self, number):
        timestamp = number * 100
        now = mono_ms() + timestamp
        return Frame(number, timestamp, wall_ms(), now, now, np.zeros((100, 100, 3), np.uint8))

    def test_latest_slot_overwrites_old_frame_and_finishes(self):
        mailbox = LatestFrame()
        mailbox.put(self.frame(1))
        mailbox.put(self.frame(2))
        mailbox.finish()
        self.assertEqual(mailbox.dropped, 1)
        self.assertEqual(mailbox.get().frame_id, 2)
        self.assertIsNone(mailbox.get())

    def test_corridor_confirmation_outside_person_and_cooldown(self):
        rules = SceneRules([.4, .3, .6, .3, .7, 1, .3, 1], .35, 5)
        rules._camera_motion = lambda _: "moving"
        rules._road_boundary = lambda _: {"candidate_visible": False}
        outside = [0, 40, 15, 90, 0, .9, 10]
        inside = [45, 40, 55, 90, 0, .9, 11]
        _, scene, hazards, warning = rules.evaluate(self.frame(0), FakeResult([outside, inside]))
        self.assertFalse(hazards[0]["in_path"])
        self.assertTrue(hazards[1]["in_path"])
        self.assertFalse(warning["speak"])
        self.assertEqual(scene["roadway_proximity"], "unknown")
        _, _, hazards, warning = rules.evaluate(self.frame(1), FakeResult([outside, inside]))
        self.assertTrue(warning["speak"])
        self.assertEqual(warning["target_id"], 11)
        self.assertEqual(warning["avoid_direction"], "unknown")
        self.assertEqual(hazards[1]["approaching"], "unknown")
        _, _, _, warning = rules.evaluate(self.frame(2), FakeResult([outside, inside]))
        self.assertFalse(warning["speak"])
        self.assertIn("cooldown", warning["reason"])

    def test_tiny_light_is_unknown(self):
        image = np.zeros((100, 100, 3), np.uint8)
        image[10:18, 10:17] = (0, 0, 255)
        self.assertEqual(signal_color(image, [10, 10, 17, 18]), "unknown")

    def test_english_cues_are_short_and_report_object_position(self):
        self.assertEqual(warning_text("person", "left"), "Stop. Pedestrian left.")
        self.assertEqual(warning_text("car", "right"), "Stop. Car right.")
        self.assertEqual(warning_text("vehicle", "right"), "Stop. Vehicle right.")
        self.assertEqual(warning_text("obstacle", "center"), "Stop. Obstacle ahead.")

    def test_moving_camera_default_never_claims_person_approaches(self):
        rules = SceneRules([.4, .3, .6, .3, .7, 1, .3, 1], .35, 5)
        rules._camera_motion = lambda _: "stable"  # A short quiet flow interval is insufficient.
        rules._road_boundary = lambda _: {"candidate_visible": False}
        approaches = []
        for n, half_width in enumerate([3, 4, 5, 6]):
            row = [50-half_width, 40, 50+half_width, 75+n*5, 0, .9, 1]
            _, _, hazards, _ = rules.evaluate(self.frame(n), FakeResult([row]))
            approaches.append(hazards[0]["approaching"])
        self.assertEqual(approaches, ["unknown"] * 4)

    def test_stairs_require_a_separate_model_two_tracked_frames_and_corridor(self):
        rules = SceneRules([.4, .3, .6, .3, .7, 1, .3, 1], .35, 5)
        rules._camera_motion = lambda _: "moving"
        rules._road_boundary = lambda _: {"candidate_visible": False}
        empty = FakeResult([])
        _, scene, _, warning = rules.evaluate(self.frame(0), empty)
        self.assertEqual(scene["stairs"]["status"], "unknown")
        self.assertFalse(warning["speak"])
        outside = FakeResult([[0, 55, 20, 75, 0, .9, 2]], {0: "stairs"})
        _, _, hazards, warning = rules.evaluate(self.frame(1), empty, outside)
        self.assertFalse(hazards[0]["in_path"])
        self.assertFalse(warning["speak"])
        inside = FakeResult([[40, 55, 60, 75, 0, .9, 3]], {0: "stairs"})
        _, scene, hazards, warning = rules.evaluate(self.frame(2), empty, inside)
        self.assertEqual(scene["stairs"]["status"], "model_detection")
        self.assertEqual(hazards[0]["type"], "stairs")
        self.assertFalse(warning["speak"])
        _, _, hazards, warning = rules.evaluate(self.frame(3), empty, inside)
        self.assertTrue(warning["speak"])
        self.assertEqual(warning["text"], "Stop. Obstacle ahead.")
        self.assertEqual(warning["priority"], 3)
        self.assertEqual(warning["avoid_direction"], "unknown")
        self.assertEqual(hazards[0]["approaching"], "unknown")


if __name__ == "__main__":
    unittest.main()
