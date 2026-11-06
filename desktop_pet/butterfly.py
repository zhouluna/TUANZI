"""A bounded, click-through butterfly and a short notice/chase/pounce scene."""

import math
from pathlib import Path
import random

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import QWidget


def load_butterfly_frames(folder: Path) -> list[QPixmap]:
    frames = [QPixmap(str(folder / f"{index:02}.png")) for index in range(8)]
    return frames if all(not frame.isNull() for frame in frames) else []


class ButterflyOverlay(QWidget):
    def __init__(self, owner: QWidget, frames: list[QPixmap]):
        super().__init__(owner, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowDoesNotAcceptFocus | Qt.WindowType.WindowTransparentForInput)
        self.setWindowTitle("团子 · 小蝴蝶")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.frames = frames
        self.frame_index = 0
        self.setFixedSize(76, 76)
        self.opacity = 1.0

    def present(self, position: QPointF, elapsed: float, size: int, opacity: float = 1.0):
        self.setFixedSize(size, size)
        self.move(round(position.x() - size / 2), round(position.y() - size / 2))
        self.frame_index = int(elapsed / .065) % len(self.frames)
        self.opacity = opacity
        if not self.isVisible():
            self.show()
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.setOpacity(self.opacity)
        painter.drawPixmap(self.rect(), self.frames[self.frame_index])


class ButterflyScene:
    duration = 18.0

    def __init__(self, cat: QRectF, area: QRectF, pet_height: int, direction: int):
        self.area = area
        self.pet_height = pet_height
        self.direction = direction
        self.elapsed = 0.0
        self.stage = "notice"
        self.stage_started = 0.0
        self.pose = ""
        self.position = self.clamp(self.paw(cat, direction) + QPointF(direction * pet_height * .22, -pet_height * .1))
        self.start = QPointF(self.position)
        self.first = self.clamp(self.start + QPointF(direction * pet_height * random.uniform(.8, 1.5), pet_height * random.uniform(-.2, .25)))
        self.second = self.clamp(self.start + QPointF(-direction * pet_height * random.uniform(.6, 1.1), pet_height * random.uniform(-.1, .4)))
        self.departure = self.clamp(self.second + QPointF(direction * pet_height * .9, -pet_height * .75))
        self.catch_end = QPointF(self.first)
        self.second_start = QPointF(self.first)

    def clamp(self, point: QPointF) -> QPointF:
        margin = min(50.0, self.area.width() / 4, self.area.height() / 4)
        return QPointF(max(self.area.left() + margin, min(point.x(), self.area.right() - margin)), max(self.area.top() + margin, min(point.y(), self.area.bottom() - margin)))

    def paw(self, cat: QRectF, direction: int) -> QPointF:
        return QPointF(cat.center().x() + direction * self.pet_height * .45, cat.bottom() - self.pet_height * .78)

    @staticmethod
    def between(first: QPointF, second: QPointF, progress: float) -> QPointF:
        progress = max(0.0, min(1.0, progress))
        eased = progress * progress * (3 - 2 * progress)
        return first * (1 - eased) + second * eased

    def advance(self, delta: float, cat: QRectF, direction: int) -> str:
        self.elapsed = min(self.duration, self.elapsed + delta)
        t = self.elapsed
        if t < 2:
            stage, base = "notice", self.start
        elif t < 6:
            stage, base = "chase", self.between(self.start, self.first, (t - 2) / 4)
        elif t < 8:
            stage, base = "pounce", self.between(self.first, self.clamp(self.paw(cat, direction)), (t - 6) / .65)
            self.second_start = QPointF(base)
        elif t < 13:
            stage, base = "chase", self.between(self.second_start, self.second, (t - 8) / 5)
        elif t < 15:
            stage, base = "pounce", self.between(self.second, self.clamp(self.paw(cat, direction)), (t - 13) / .65)
            self.catch_end = QPointF(base)
        else:
            stage, base = "watch", self.between(self.catch_end, self.departure, (t - 15) / 3)
        if stage != self.stage:
            self.stage, self.stage_started = stage, t
        self.position = self.clamp(base + QPointF(math.sin(t * 3.7) * 9, math.sin(t * 5.1) * 8))
        return stage
