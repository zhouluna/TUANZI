"""Stable sleeping poses with continuous, local chest breathing.

LUNA ZHOU, 2026-11-03: avoid looping low-rate morph frames during naps.
"""

from dataclasses import dataclass, field
import json
import logging
import math
from pathlib import Path
import random

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QImage, QPainter, QPixmap, QPolygonF, QTransform

LOG = logging.getLogger("tuanzi")
BREATH_SECONDS = 4.8


def chest_offset(x: float, y: float, elapsed: float,
                 region: tuple[float, float, float, float], amplitude: float) -> QPointF:
    """Compact smooth deformation; points outside the chest stay fixed."""
    center_x, center_y, radius_x, radius_y = region
    distance = ((x - center_x) / radius_x) ** 2 + ((y - center_y) / radius_y) ** 2
    weight = max(0.0, 1.0 - distance) ** 3
    breath = (1.0 - math.cos(elapsed * math.tau / BREATH_SECONDS)) * .5
    return QPointF((x - center_x) * .008 * breath * weight,
                   -amplitude * breath * weight)


@dataclass
class SleepPose:
    name: str
    label: str
    image: QPixmap
    chest: tuple[float, float, float, float]
    amplitude: float = 3.5
    tiles: list = field(default_factory=list)

    def prepare(self) -> None:
        source = self.image.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
        self.tiles.clear()
        for y in range(0, source.height(), 32):
            for x in range(0, source.width(), 32):
                width, height = min(32, source.width() - x), min(32, source.height() - y)
                tile = source.copy(x, y, width, height)
                if not any(bytes(tile.constBits())[3::4]):
                    continue
                corners = ((x, y), (x + width, y), (x + width, y + height), (x, y + height))
                polygon = QPolygonF([QPointF(0, 0), QPointF(width, 0),
                                     QPointF(width, height), QPointF(0, height)])
                self.tiles.append((QPixmap.fromImage(tile), polygon, corners))


@dataclass
class Nap:
    pose: SleepPose
    duration: float | None
    elapsed: float = 0.0

    def advance(self, delta: float) -> None:
        self.elapsed += max(0.0, delta)

    @property
    def finished(self) -> bool:
        return self.duration is not None and self.elapsed >= self.duration

    def wake(self) -> None:
        # Keep this pose and its breath phase when leaving persistent rest.
        self.duration = self.elapsed + 1.2


def choose_pose(poses: dict[str, SleepPose], previous: str = "",
                requested: str = "") -> SleepPose:
    if requested in poses:
        return poses[requested]
    candidates = [pose for name, pose in poses.items() if name != previous]
    return random.choice(candidates or list(poses.values()))


def load_sleep_poses(folder: Path) -> dict[str, SleepPose]:
    poses = {}
    try:
        entries = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        for entry in entries:
            path = (folder / entry["image"]).resolve()
            if not path.is_relative_to(folder.resolve()):
                raise ValueError("Sleep pose outside asset directory")
            image = QPixmap(str(path))
            chest = tuple(float(value) for value in entry["chest"])
            if image.isNull() or image.width() != 768 or image.height() != 512:
                raise ValueError(f"Invalid sleep pose: {path}")
            if len(chest) != 4 or min(chest[2:]) <= 0:
                raise ValueError("Invalid chest region")
            pose = SleepPose(entry["id"], entry["label"], image, chest,
                             float(entry.get("amplitude", 3.5)))
            pose.prepare()
            poses[pose.name] = pose
    except (OSError, ValueError, KeyError, TypeError):
        LOG.exception("睡姿资源无法载入，保留原睡眠动作")
    return poses


def draw_sleep(painter: QPainter, nap: Nap, target: QRectF) -> None:
    pose = nap.pose
    painter.save()
    painter.translate(target.left(), target.top())
    painter.scale(target.width() / pose.image.width(), target.height() / pose.image.height())
    base = painter.worldTransform()
    for tile, source, corners in pose.tiles:
        points = QPolygonF([QPointF(x, y) + chest_offset(x, y, nap.elapsed, pose.chest, pose.amplitude)
                            for x, y in corners])
        transform = QTransform.quadToQuad(source, points)
        if transform is not None:
            painter.setWorldTransform(transform * base)
            painter.drawPixmap(0, 0, tile)
    painter.restore()
