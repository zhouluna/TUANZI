"""Regression coverage for pursuit direction and packaged action frames."""

import hashlib
import json
import random
import unittest
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter

from desktop_pet.app import PetWindow
from desktop_pet.animations import draw_frame, load_clips, locate_eyes
from desktop_pet.butterfly import ButterflyScene
from desktop_pet.resources import required_assets
from scripts.interpolate_plan import choose_factor, frame_delay, keyframe_slot, loops_back_to_start, output_frame_count

ROOT = Path(__file__).resolve().parent.parent
# Sparse sources before offline interpolation. Cycle length is count × delay.
SPARSE_ACTIONS = {
    "nuzzle": (12, 150),
    "eat": (12, 160),
    "wave": (12, 130),
    "purr": (12, 180),
    "ball": (12, 140),
    "pounce": (12, 105),
    "groom_fur": (8, 220),
    "groom": (16, 180),
}


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
        animations = ROOT / "assets" / "animations"
        manifest = json.loads((animations / "manifest.json").read_text(encoding="utf-8"))
        clips = load_clips(animations)
        by_id = {entry["id"]: entry for entry in manifest}
        for name, (count, delay) in SPARSE_ACTIONS.items():
            with self.subTest(clip=name):
                factor = choose_factor(delay)
                entry = by_id[name]
                clip = clips[name]
                self.assertEqual(len(clip.frames), output_frame_count(count, factor))
                self.assertEqual(clip.duration_ms, frame_delay(delay, factor))
                self.assertAlmostEqual(clip.seconds, count * delay / 1000)
                self.assertEqual(clip.frame_index(clip.seconds), 0)
                self.assertEqual(len(entry["eye_positions"]), len(entry["frames"]))
                self.assertNotIn("source_bounds", entry)
                for index in range(count):
                    slot = keyframe_slot(index, factor)
                    relative = f"keyframes/{name}/{index:02d}.png"
                    self.assertEqual(entry["frames"][slot], relative)
                    self.assertEqual(rgba_digest(QImage(str(animations / relative))), rgba_digest(clip.frames[slot].toImage()))
                if not loops_back_to_start(name):
                    last = f"keyframes/{name}/{count - 1:02d}.png"
                    self.assertEqual(entry["frames"][-1], last)
                    self.assertGreater(entry["frames"].count(last), 1)
                for frame in clip.frames:
                    self.assertFalse(frame.isNull())
                    self.assertTrue(frame.hasAlphaChannel())
                    self.assertEqual(frame.height(), 512)
                    self.assertGreaterEqual(frame.width(), 512)
                    self.assertLessEqual(frame.width(), 1024)
                    self.assertEqual(frame.toImage().pixelColor(0, 0).alpha(), 0)
                sampled = clip.frames[factor // 2].toImage()
                detected = [[round(float(part), 4) for part in eye] for eye in locate_eyes(sampled)]
                self.assertEqual(detected, entry["eye_positions"][factor // 2])
        for name, count, delay in (("walk", 64, 16), ("run", 48, 16), ("bed", 1, 1000)):
            self.assertEqual(len(clips[name].frames), count)
            self.assertEqual(clips[name].duration_ms, delay)
            self.assertNotIn("eye_positions", by_id[name])
        groom = clips["groom"]
        canvas = QImage(groom.frames[0].width(), groom.frames[0].height(), QImage.Format.Format_RGBA8888)
        canvas.fill(Qt.GlobalColor.transparent)
        painter = QPainter(canvas)
        draw_frame(painter, groom, min(5, len(groom.frames) - 1), QRectF(0, 0, canvas.width(), canvas.height()), 0.2, 0.1)
        painter.end()
        self.assertEqual(canvas.pixelColor(0, 0).alpha(), 0)
        self.assertGreater(opaque_samples(canvas), 40)
        self.assertTrue(any("groom" in path.as_posix() for path in required_assets(ROOT)))
        self.assertEqual(hashlib.sha256((ROOT / "assets/sprites/tuanzi-approved.png").read_bytes()).hexdigest(), "94282b3c05984e5f1fd0af1e85ca63ade1f71ba4c832d2d3023aabc47f098041")


def rgba_digest(image: QImage) -> str:
    image = image.convertToFormat(QImage.Format.Format_RGBA8888)
    width = image.width()
    rows = [bytes(image.constScanLine(y))[:width * 4] for y in range(image.height())]
    return hashlib.sha256(b"".join(rows)).hexdigest()


def opaque_samples(image: QImage) -> int:
    hits = 0
    for y in range(0, image.height(), 8):
        for x in range(0, image.width(), 8):
            if image.pixelColor(x, y).alpha() > 200:
                hits += 1
    return hits


if __name__ == "__main__":
    unittest.main()
