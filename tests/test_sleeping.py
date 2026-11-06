"""Sleep smoothness, variety and autonomy regression checks."""

import hashlib
import math
from pathlib import Path
import random
import time
from types import SimpleNamespace
import unittest

from PySide6.QtCore import QPointF
from PySide6.QtGui import QGuiApplication

from desktop_pet.app import PetWindow
from desktop_pet.sleeping import BREATH_SECONDS, Nap, chest_offset, choose_pose, load_sleep_poses

ROOT = Path(__file__).resolve().parent.parent


class SleepingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QGuiApplication.instance() or QGuiApplication([])
        cls.poses = load_sleep_poses(ROOT / "assets" / "sleep-v2")

    def test_continuous_breath_keeps_bed_fixed(self):
        for pose in self.poses.values():
            with self.subTest(pose=pose.name):
                x, y, _, _ = pose.chest
                points = [chest_offset(x, y, index / 60, pose.chest, pose.amplitude)
                          for index in range(math.ceil(BREATH_SECONDS * 60) + 1)]
                self.assertGreater(max(point.y() for point in points) - min(point.y() for point in points), 3)
                self.assertLess(max((second - first).manhattanLength()
                                    for first, second in zip(points, points[1:])), .06)
                self.assertEqual(chest_offset(x, y, 0, pose.chest, pose.amplitude),
                                 chest_offset(x, y, BREATH_SECONDS, pose.chest, pose.amplitude))
                # No coarse 60 ms texture hold: successive interior samples move.
                self.assertNotEqual(points[60], points[61])
                for bed_x in range(0, 769, 32):
                    self.assertEqual(chest_offset(bed_x, 480, 2.4, pose.chest, pose.amplitude), QPointF())

    def test_nap_clock_and_wake_preserve_pose(self):
        pose = self.poses["belly"]
        whole, split = Nap(pose, None), Nap(pose, None)
        whole.advance(13.7)
        split.advance(6.2)
        split.advance(7.5)
        self.assertAlmostEqual(whole.elapsed, split.elapsed)
        self.assertFalse(whole.finished)
        whole.wake()
        self.assertIs(whole.pose, pose)
        self.assertAlmostEqual(whole.elapsed, 13.7)
        self.assertAlmostEqual(whole.duration, 14.9)
        whole.advance(1.19)
        self.assertFalse(whole.finished)
        whole.advance(.02)
        self.assertTrue(whole.finished)
        finite = Nap(pose, 45, 44.984)
        finite.advance(.016)
        self.assertTrue(finite.finished)

    def test_sleep_is_common_and_respects_activity_switches(self):
        state = random.getstate()
        try:
            random.seed(211)
            cat = SimpleNamespace(clips=dict.fromkeys(("walk", "run", "nuzzle", "wave", "purr", "ball", "groom", "groom_fur", "eat", "bed")),
                                  roaming_enabled=True, auto_actions=True, recent_motions=[])
            choices = [PetWindow.choose_activity(cat) for _ in range(4000)]
            share = choices.count("bed") / len(choices)
            self.assertGreater(share, .2)
            self.assertLess(share, .4)
            cat.recent_motions = ["bed"]
            self.assertNotIn("bed", [PetWindow.choose_activity(cat) for _ in range(100)])
            cat.auto_actions = False
            self.assertEqual({PetWindow.choose_activity(cat) for _ in range(100)}, {"walk", "run"})
            cat.roaming_enabled = False
            self.assertIsNone(PetWindow.choose_activity(cat))
        finally:
            random.setstate(state)

    def test_packaged_sleep_poses_and_random_variety(self):
        self.assertEqual(set(self.poses), {"belly", "buried", "side", "curled"})
        fingerprints = set()
        for pose in self.poses.values():
            self.assertEqual((pose.image.width(), pose.image.height()), (768, 512))
            self.assertGreater(len(pose.tiles), 40)
            image = pose.image.toImage()
            self.assertEqual(image.pixelColor(0, 0).alpha(), 0)
            fingerprints.add(hashlib.sha256(bytes(image.constBits())).hexdigest())
        self.assertEqual(len(fingerprints), 4)
        state = random.getstate()
        try:
            random.seed(95)
            previous, selected = "", set()
            for _ in range(60):
                pose = choose_pose(self.poses, previous)
                self.assertNotEqual(pose.name, previous)
                previous = pose.name
                selected.add(pose.name)
            self.assertEqual(selected, set(self.poses))
            self.assertIs(choose_pose(self.poses, "belly", "belly"), self.poses["belly"])
        finally:
            random.setstate(state)
        self.assertEqual(hashlib.sha256((ROOT / "assets/sprites/tuanzi-approved.png").read_bytes()).hexdigest(),
                         "94282b3c05984e5f1fd0af1e85ca63ade1f71ba4c832d2d3023aabc47f098041")

    def test_pause_freezes_breath_and_wake_resumes(self):
        cat = SimpleNamespace(last_tick=time.monotonic() - .03, nap=Nap(self.poses["buried"], None, 7.2),
                              paused=True, sleeping=True, menu_open=False, drag_anchor=None,
                              isVisible=lambda: True, isMinimized=lambda: False, update=lambda: None,
                              gaze_x=0, gaze_y=0, rest_elapsed=7.2, sleep_poses=self.poses, motion="bed",
                              say=lambda *args: None, refresh_tray_menu=lambda: None)
        PetWindow.animate(cat)
        self.assertEqual(cat.nap.elapsed, 7.2)
        cat.paused = False
        cat.last_tick = time.monotonic() - .03
        PetWindow.animate(cat)
        self.assertGreater(cat.nap.elapsed, 7.22)
        elapsed = cat.nap.elapsed
        cat.menu_open = True
        cat.last_tick = time.monotonic() - .03
        PetWindow.animate(cat)
        self.assertEqual(cat.nap.elapsed, elapsed)
        nap = cat.nap
        for persistent in (True, False):
            with self.subTest(persistent=persistent):
                cat.sleeping = persistent
                cat.paused = True
                PetWindow.toggle_sleep(cat)
                self.assertIs(cat.nap, nap)
                self.assertFalse(cat.sleeping)
                self.assertFalse(cat.paused)
                self.assertAlmostEqual(cat.nap.elapsed, elapsed)
                self.assertAlmostEqual(cat.nap.duration - elapsed, 1.2)


if __name__ == "__main__":
    unittest.main()
