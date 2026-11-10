"""Distance-driven gait and autonomous activity regression checks."""

import random
import time
from types import SimpleNamespace
import unittest

from desktop_pet.app import PetWindow


class GaitActivityTests(unittest.TestCase):
    def test_gait_distance_sync(self):
        def cat(height=280):
            return SimpleNamespace(active_clip=SimpleNamespace(seconds=1.024, stride_pixels=160), pet_height=height, clip_elapsed=.2, walk_speed=60, walk_base_speed=80, playback_rate=1)

        stopped = cat()
        PetWindow.advance_gait(stopped, 0, .016)
        self.assertEqual(stopped.clip_elapsed, .2)
        self.assertEqual(stopped.playback_rate, 0)
        whole, split, large = cat(), cat(), cat(560)
        PetWindow.advance_gait(whole, 30, .1)
        PetWindow.advance_gait(split, 15, .05)
        PetWindow.advance_gait(split, 15, .05)
        PetWindow.advance_gait(large, 60, .1)
        self.assertAlmostEqual(whole.clip_elapsed, split.clip_elapsed)
        self.assertAlmostEqual(whole.clip_elapsed, large.clip_elapsed)
        self.assertNotEqual(whole.clip_elapsed, .2)
        looped = cat()
        PetWindow.advance_gait(looped, 100, .4)
        self.assertAlmostEqual(looped.clip_elapsed, .2)

    @staticmethod
    def activity_cat():
        return SimpleNamespace(clips=dict.fromkeys(("walk", "run", "nuzzle", "wave", "purr", "ball", "groom", "groom_fur", "eat")), roaming_enabled=True, auto_actions=True, recent_motions=[])

    def test_random_activity_variety(self):
        state = random.getstate()
        try:
            streams = []
            for seed in (23, 81, 23):
                random.seed(seed)
                cat = self.activity_cat()
                sequence = []
                for _ in range(120):
                    name = PetWindow.choose_activity(cat)
                    self.assertNotIn(name, cat.recent_motions[-2:])
                    sequence.append(name)
                    cat.recent_motions = (cat.recent_motions + [name])[-3:]
                self.assertGreaterEqual(len(set(sequence)), 9)
                streams.append(sequence)
            self.assertEqual(streams[0], streams[2])
            self.assertNotEqual(streams[0], streams[1])
        finally:
            random.setstate(state)

    def test_activity_toggles(self):
        cat = self.activity_cat()
        cat.roaming_enabled = False
        for _ in range(80):
            self.assertNotIn(PetWindow.choose_activity(cat), ("walk", "run"))
        cat.auto_actions = False
        self.assertIsNone(PetWindow.choose_activity(cat))
        cat.roaming_enabled = True
        self.assertIn(PetWindow.choose_activity(cat), ("walk", "run"))

    def test_transition_keeps_ambient_animation(self):
        cat = self.activity_cat()
        cat.active_clip = SimpleNamespace(name="walk")
        cat.save_settings = lambda: None
        cat.auto_resume_at = 0
        cat.sleeping = False
        start = time.monotonic()
        PetWindow.finish_clip(cat)
        self.assertIsNone(cat.active_clip)
        self.assertGreaterEqual(cat.next_activity, start)
        self.assertLessEqual(cat.next_activity - start, 24.5)
        self.assertTrue(PetWindow.use_ambient_animation(cat))
        cat.auto_resume_at = time.monotonic() + 8
        self.assertFalse(PetWindow.use_ambient_animation(cat))
        cat.auto_resume_at = 0
        cat.sleeping = True
        self.assertFalse(PetWindow.use_ambient_animation(cat))


if __name__ == "__main__":
    unittest.main()
