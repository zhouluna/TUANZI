"""Regression coverage for pursuit direction and packaged grooming actions."""

import hashlib
import random
import unittest
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QGuiApplication

from desktop_pet.app import PetWindow
from desktop_pet.animations import load_clips
from desktop_pet.butterfly import ButterflyScene

ROOT = Path(__file__).resolve().parent.parent


class ChaseHarness:
    pet_height = 280
    move_chasing = PetWindow.move_chasing

    def __init__(self, x=600, y=350, direction=1):
        self.walk_position = QPointF(x, y)
        self.walk_direction = direction
        self.walk_speed = 120.0
        self.walk_target = None
        self.position = QPointF(x, y)

    def width(self):
        return 470

    def height(self):
        return 366

    def walking_bounds(self):
        return (0, 0, 1450, 714)

    def move(self, x, y):
        self.position = QPointF(x, y)

    def geometry(self):
        return QRectF(self.position.x(), self.position.y(), self.width(), self.height())


class PetActionTests(unittest.TestCase):
    def test_nearby_butterfly_stops_without_backing(self):
        for facing in (-1, 1):
            with self.subTest(facing=facing):
                cat = ChaseHarness(direction=facing)
                before = QPointF(cat.walk_position)
                butterfly = QPointF(before.x() + cat.width() / 2 + facing * 140, 400)
                self.assertFalse(cat.move_chasing(.033, butterfly))
                self.assertEqual(cat.walk_position, before)
                self.assertEqual(cat.walk_speed, 0)

    def test_butterfly_behind_turns_before_pursuit(self):
        for facing in (-1, 1):
            with self.subTest(facing=facing):
                cat = ChaseHarness(direction=facing)
                before = QPointF(cat.walk_position)
                butterfly = QPointF(before.x() + cat.width() / 2 - facing * 400, 400)
                self.assertTrue(cat.move_chasing(.033, butterfly))
                self.assertEqual(cat.walk_direction, -facing)
                self.assertGreater((cat.walk_position.x() - before.x()) * cat.walk_direction, 0)

    def test_complete_scenes_never_run_backwards_or_leave_screen(self):
        moved = 0
        state = random.getstate()
        try:
            for seed in range(12):
                for start in ((600, 350), (0, 0), (1450, 714)):
                    random.seed(seed)
                    cat = ChaseHarness(*start, direction=1 if seed % 2 else -1)
                    scene = ButterflyScene(cat.geometry(), QRectF(0, 0, 1920, 1080), cat.pet_height, cat.walk_direction)
                    stages = set()
                    while scene.elapsed < scene.duration:
                        stage = scene.advance(.033, cat.geometry(), cat.walk_direction)
                        stages.add(stage)
                        if stage != "chase":
                            cat.walk_speed = 0
                            continue
                        before = QPointF(cat.walk_position)
                        moving = cat.move_chasing(.033, scene.position)
                        dx = cat.walk_position.x() - before.x()
                        self.assertGreaterEqual(dx * cat.walk_direction, 0, (seed, start, scene.elapsed))
                        self.assertGreaterEqual(cat.position.x(), 0)
                        self.assertLessEqual(cat.position.x(), 1450)
                        self.assertGreaterEqual(cat.position.y(), 0)
                        self.assertLessEqual(cat.position.y(), 714)
                        if moving:
                            moved += 1
                            self.assertGreater(dx * cat.walk_direction, 0)
                    self.assertEqual(stages, {"notice", "chase", "pounce", "watch"})
        finally:
            random.setstate(state)
        self.assertGreater(moved, 100)

    def test_grooming_frames_and_idle_identity(self):
        app = QGuiApplication.instance() or QGuiApplication([])
        clips = load_clips(ROOT / "assets" / "animations")
        for name, count in (("groom", 16), ("groom_fur", 8)):
            with self.subTest(clip=name):
                self.assertIn(name, clips)
                clip = clips[name]
                self.assertEqual(len(clip.frames), count)
                for frame in clip.frames:
                    self.assertFalse(frame.isNull())
                    self.assertTrue(frame.hasAlphaChannel())
                    self.assertEqual(frame.height(), 512)
                    self.assertEqual(frame.toImage().pixelColor(0, 0).alpha(), 0)
                self.assertEqual(clip.frame_index(clip.seconds), 0)
        self.assertEqual(hashlib.sha256((ROOT / "assets/sprites/tuanzi-approved.png").read_bytes()).hexdigest(), "94282b3c05984e5f1fd0af1e85ca63ade1f71ba4c832d2d3023aabc47f098041")


if __name__ == "__main__":
    unittest.main()
