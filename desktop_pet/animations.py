"""Load the approved AI frame sequences and preserve gaze inside each pose."""

from dataclasses import dataclass
import json
import logging
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QImage, QPainter, QPixmap, QPolygonF, QTransform

LOG = logging.getLogger("tuanzi")

# LUNA ZHOU, 2026-11-03: lengthen the trunk without widening the face.
BODY_EXTENSION = .24


def draw_long_body(painter: QPainter, frame: QPixmap, target: QRectF, horizontal: bool = False) -> None:
    """Extend the trunk band while retaining the head and paws' scale.

    Seated poses keep the same foot baseline; walking poses extend around
    their center. This changes rendering without rewriting original artwork.
    """
    width, height = frame.width(), frame.height()
    if horizontal:
        start, end = width * .30, width * .65
        extra = (end - start) * BODY_EXTENSION
        bands = ((0, start, -extra / 2, start),
                 (start, end - start, start - extra / 2, end - start + extra),
                 (end, width - end, end + extra / 2, width - end))
        for source, length, destination, extent in bands:
            painter.drawPixmap(QRectF(target.left() + destination / width * target.width(), target.top(), extent / width * target.width(), target.height()), frame, QRectF(source, 0, length, height))
    else:
        start, end = height * .40, height * .82
        extra = (end - start) * BODY_EXTENSION
        bands = ((0, start, -extra, start),
                 (start, end - start, start - extra, end - start + extra),
                 (end, height - end, end, height - end))
        for source, length, destination, extent in bands:
            painter.drawPixmap(QRectF(target.left(), target.top() + destination / height * target.height(), target.width(), extent / height * target.height()), frame, QRectF(0, source, width, length))


@dataclass
class Clip:
    name: str
    label: str
    duration_ms: int
    frames: list[QPixmap]
    eyes: list[list[tuple[float, float, float, float]]]
    stride_pixels: float = 0.0
    body_extended: bool = False

    @property
    def seconds(self) -> float:
        return len(self.frames) * self.duration_ms / 1000

    def frame_index(self, elapsed: float) -> int:
        return int(elapsed * 1000 / self.duration_ms) % len(self.frames)


def locate_eyes(image: QImage) -> list[tuple[float, float, float, float]]:
    """Locate the two green irises; uncertain detections leave the photo intact."""
    image = image.convertToFormat(QImage.Format.Format_RGBA8888)
    pixels, width, height = bytes(image.constBits()), image.width(), image.height()
    candidates = set()
    for y in range(int(height * .08), int(height * .75)):
        for x in range(int(width * .2), int(width * .95)):
            offset = (y * width + x) * 4
            red, green, blue, alpha = pixels[offset:offset + 4]
            if alpha > 180 and green - red > 7 and green - blue > 14 and 35 < green < 225:
                candidates.add((x, y))
    components = []
    while candidates:
        first = candidates.pop()
        stack, points = [first], [first]
        while stack:
            x, y = stack.pop()
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, -1), (1, -1), (-1, 1)):
                neighbor = (x + dx, y + dy)
                if neighbor in candidates:
                    candidates.remove(neighbor)
                    stack.append(neighbor)
                    points.append(neighbor)
        if len(points) < 6:
            continue
        left, right = min(p[0] for p in points), max(p[0] for p in points)
        top, bottom = min(p[1] for p in points), max(p[1] for p in points)
        if 3 <= right - left <= 40 and 3 <= bottom - top <= 35:
            components.append((len(points), ((left + right) / 2, (top + bottom) / 2, (right - left) / 2 + 2, (bottom - top) / 2 + 2)))
    components.sort(reverse=True)
    for _, first in components:
        for _, second in components:
            if 12 < abs(first[0] - second[0]) < 110 and abs(first[1] - second[1]) < 45:
                return sorted([first, second])
    return []


def load_clips(folder: Path) -> dict[str, Clip]:
    try:
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        LOG.warning("AI 动作资源不存在或无法读取，继续使用待机形象")
        return {}
    clips = {}
    frame_cache = {}
    for entry in manifest:
        try:
            frames, eyes = [], []
            for relative in entry["frames"]:
                path = (folder / relative).resolve()
                if not path.is_relative_to(folder.resolve()):
                    raise ValueError("Frame path outside asset folder")
                # Repeated breathing phases can share the same immutable
                # texture instead of decoding and storing duplicate images.
                if path not in frame_cache:
                    image = QImage(str(path))
                    if image.isNull() or not 512 <= image.width() <= 1024 or image.height() != 512:
                        raise ValueError(f"Invalid animation frame: {path}")
                    frame_cache[path] = (QPixmap.fromImage(image), locate_eyes(image))
                frame, eye_positions = frame_cache[path]
                frames.append(frame)
                eyes.append(eye_positions)
            duration = int(entry["duration"])
            if not frames or not 12 <= duration <= 1000:
                raise ValueError("Invalid frame count or duration")
            stride = float(entry.get("stride_pixels", 0))
            if not 0 <= stride <= 2048:
                raise ValueError("Invalid stride distance")
            clip = Clip(entry["id"], entry["label"], duration, frames, eyes, stride, entry.get("body_extended", False) is True)
            clips[clip.name] = clip
            LOG.info("载入 AI 动作 %s：%s 帧，%s 帧识别双眼", clip.name, len(frames), sum(bool(pair) for pair in eyes))
        except (OSError, ValueError, TypeError, KeyError):
            LOG.exception("跳过无法读取的 AI 动作")
    return clips


def draw_frame(painter: QPainter, clip: Clip, frame_index: int, target: QRectF, gaze_x: float, gaze_y: float, mirrored: bool = False, long_body: bool = True) -> None:
    frame = clip.frames[frame_index]
    if long_body:
        # Apply gaze before extending the torso so the eyes follow the head.
        if clip.eyes[frame_index] and (abs(gaze_x) > .001 or abs(gaze_y) > .001):
            layer = QPixmap(frame.size())
            layer.fill(Qt.GlobalColor.transparent)
            layer_painter = QPainter(layer)
            layer_painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            draw_frame(layer_painter, clip, frame_index, QRectF(0, 0, frame.width(), frame.height()), -gaze_x if mirrored else gaze_x, gaze_y, long_body=False)
            layer_painter.end()
        else:
            layer = frame
        painter.save()
        if mirrored:
            painter.translate(target.center().x() * 2, 0)
            painter.scale(-1, 1)
        if clip.body_extended:
            painter.drawPixmap(target, layer, QRectF(layer.rect()))
        else:
            draw_long_body(painter, layer, target, clip.name in ("walk", "run"))
        painter.restore()
        return
    painter.save()
    painter.translate(target.left(), target.top())
    painter.scale(target.width() / frame.width(), target.height() / frame.height())
    if mirrored:
        painter.translate(frame.width(), 0)
        painter.scale(-1, 1)
        gaze_x = -gaze_x
    painter.drawPixmap(0, 0, frame)
    base = painter.worldTransform()
    for center_x, center_y, radius_x, radius_y in clip.eyes[frame_index]:
        left, top = int(center_x - radius_x - 1), int(center_y - radius_y - 1)
        right, bottom = int(center_x + radius_x + 2), int(center_y + radius_y + 2)

        def warp(x, y):
            distance = ((x - center_x) / radius_x) ** 2 + ((y - center_y) / radius_y) ** 2
            weight = max(0.0, 1 - distance) ** 2
            return QPointF(x + gaze_x * radius_x * .18 * weight, y + gaze_y * radius_y * .15 * weight)

        for y in range(top, bottom, 3):
            for x in range(left, right, 3):
                width, height = min(3, right - x), min(3, bottom - y)
                source = QPolygonF([QPointF(0, 0), QPointF(width, 0), QPointF(width, height), QPointF(0, height)])
                target_polygon = QPolygonF([warp(x, y), warp(x + width, y), warp(x + width, y + height), warp(x, y + height)])
                transform = QTransform.quadToQuad(source, target_polygon)
                if transform is not None:
                    painter.setWorldTransform(transform * base)
                    painter.drawPixmap(QRectF(0, 0, width, height), frame, QRectF(x, y, width, height))
        painter.setWorldTransform(base)
    painter.restore()
