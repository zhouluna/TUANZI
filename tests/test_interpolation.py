"""Timing plan for offline in-place interpolation."""

import random
import unittest

from tuanzi_shared.activity import plan_steps, sleep_uses_recorded_breath
from scripts.interpolate_plan import (
    choose_factor,
    frame_delay,
    keyframe_slot,
    loops_back_to_start,
    output_frame_count,
)


class InterpolationPlanTests(unittest.TestCase):
    def test_factors_keep_the_original_cycle(self):
        originals = {
            "nuzzle": (12, 150),
            "eat": (12, 160),
            "wave": (12, 130),
            "purr": (12, 180),
            "ball": (12, 140),
            "pounce": (12, 105),
            "groom_fur": (8, 220),
            "groom": (16, 180),
        }
        for name, (count, delay) in originals.items():
            with self.subTest(clip=name):
                factor = choose_factor(delay)
                produced = output_frame_count(count, factor)
                slice_ms = frame_delay(delay, factor)
                self.assertGreaterEqual(slice_ms, 20)
                self.assertLessEqual(slice_ms, 40)
                self.assertEqual(produced * slice_ms, count * delay)
                self.assertEqual(keyframe_slot(0, factor), 0)
                self.assertEqual(keyframe_slot(count - 1, factor), (count - 1) * factor)

    def test_known_smooth_delays(self):
        self.assertEqual((choose_factor(180), frame_delay(180, choose_factor(180))), (6, 30))
        self.assertEqual((choose_factor(220), frame_delay(220, choose_factor(220))), (10, 22))
        self.assertEqual((choose_factor(105), frame_delay(105, choose_factor(105))), (3, 35))
        self.assertTrue(loops_back_to_start("groom"))
        self.assertFalse(loops_back_to_start("pounce"))

    def test_recorded_nest_breath_replaces_the_still_bed(self):
        steps = plan_steps(["walk"], 16, available={"walk", "groom", "nest-breath"}, rng=random.Random(4))
        chosen = {step["clip"] for step in steps}
        self.assertIn("nest-breath", chosen)
        self.assertNotIn("bed", chosen)
        self.assertTrue(sleep_uses_recorded_breath("", {"nest-breath"}))
        self.assertFalse(sleep_uses_recorded_breath("belly", {"nest-breath"}))
        self.assertFalse(sleep_uses_recorded_breath("", set()))

    def test_dense_and_unsplittable_delays_are_rejected(self):
        with self.assertRaises(ValueError):
            choose_factor(16)
        with self.assertRaises(ValueError):
            choose_factor(23)


if __name__ == "__main__":
    unittest.main()
