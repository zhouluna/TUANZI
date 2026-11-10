"""Transparent desktop companion using the approved, unmodified cat artwork."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import random
import sys
import time

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QColor, QCursor, QFont, QIcon, QImage, QPainter, QPixmap, QPolygonF, QTransform
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon, QWidget

from tuanzi_shared.activity import sleep_uses_recorded_breath
from .animations import draw_frame, draw_long_body, load_clips
from .butterfly import ButterflyOverlay, ButterflyScene, load_butterfly_frames
from .chat import ChatDialog
from .remote import RemotePlan, configured as api_configured
from .sleeping import Nap, choose_pose, draw_sleep, load_sleep_poses
from . import __version__
from .runtime import data_directory, instance_server_name, resource_directory


ROOT = resource_directory()
ARTWORK = ROOT / "assets" / "sprites" / "tuanzi-approved.png"
LOCAL = data_directory()
SETTINGS = LOCAL / "settings.json"
# A desktop session under a different Windows account must not claim this
# user's single-instance endpoint (e.g. an isolated development desktop).
SERVER_NAME = instance_server_name(ROOT, LOCAL)
SIZES = {"小号": 210, "标准": 280, "大号": 370}
BED_ENTRY_FRAMES, BED_SLEEP_FRAMES, BED_WAKE_FRAMES = 16, 32, 16
LOG = logging.getLogger("tuanzi")
HELP_TEXT = "拖动：移动位置\n单击：撒娇回应\n双击：和团子说话\n右键 → 自由漫游：自然慢走、停留观察、偶尔小跑\n右键 → 动作：走路、奔跑、捉蝴蝶、猫窝睡觉等\n右键 → 偶遇蝴蝶：开启 / 关闭自动捉蝴蝶场景\n右键 → 自主活动：开启 / 关闭其他随机动作\n右键 → 休息一下：在猫窝持续睡觉，再次操作唤醒\n右键 → 暂停动作：暂停 / 继续当前动作、移动和蝴蝶\n右键 → 动作 → 回到待机：停止动作，暂歇一会儿\n托盘图标：单击找回团子\n\n自然闲逛使用短距离弧线路线，逐渐加速、减速，大多数时间慢走，偶尔小跑。会在桌面工作区范围内停留和观察。自主活动的间隔有长有短，不是固定节拍。\n\n捉蝴蝶包含发现、追逐、伸爪扑捉和目送飞走，结束后恢复闲逛。拖动、打开菜单、休息或暂停时停止移动。\n\n眼睛不眨眼，平时看鼠标，捉蝴蝶时看蝴蝶；识别不到双眼的帧保留原图。打呼噜暂无声音。AI 帧间仍可能有轻微形变。\n\n位置、大小和各项开关会自动记住。设置了 TUANZI_API_URL 以后，桌面团子和网页团子共用同一个接口。"


class PetWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.settings = self.load_settings()
        self.source = QPixmap(str(ARTWORK))
        if self.source.isNull():
            raise RuntimeError(f"无法读取宠物形象：{ARTWORK}")
        self.pet_height = self.settings.get("size", 280)
        if self.pet_height not in SIZES.values():
            self.pet_height = 280
        self.on_top = self.settings.get("on_top", True) is not False
        self.sleeping = False
        self.rest_elapsed = 0.0
        self.paused = False
        self.started = time.monotonic()
        self.reaction_started = -100.0
        self.motion = ""
        self.motion_started = -100.0
        self.gaze_x = 0.0
        self.gaze_y = 0.0
        self.clips = load_clips(ROOT / "assets" / "animations")
        # LUNA ZHOU, 2026-11-03: time-driven breathing and varied long naps.
        self.sleep_poses = load_sleep_poses(ROOT / "assets" / "sleep-v2")
        self.nap = None
        self.last_sleep_pose = ""
        self.active_clip = None
        self.clip_elapsed = 0.0
        self.clip_loops = 1
        self.walk_direction = 1
        self.walk_position = QPointF()
        self.walk_target = None
        self.walk_speed = 0.0
        self.walk_base_speed = self.pet_height * .23
        self.walk_origin = QPointF()
        self.walk_control = QPointF()
        self.walk_progress = 0.0
        self.walk_length = 1.0
        self.walk_heading = random.uniform(0, math.tau)
        self.playback_rate = 1.0
        self.butterfly_frames = load_butterfly_frames(ROOT / "assets" / "scenes" / "butterfly")
        self.butterfly_scene = None
        self.butterfly_overlay = None
        self.butterfly_enabled = self.settings.get("butterfly_enabled", True) is not False
        self.next_butterfly = time.monotonic() + random.uniform(40, 70)
        self.roaming_enabled = self.settings.get("roaming_enabled", True) is not False and "walk" in self.clips
        self.next_roam = time.monotonic() + 2.0
        self.last_tick = time.monotonic()
        self.auto_actions = self.settings.get("auto_actions", True) is not False
        self.recent_motions = []
        self.next_activity = time.monotonic() + 2.0
        self.auto_resume_at = 0.0
        self.ambient_elapsed = 0.0
        self.next_motion = time.monotonic() + random.uniform(10, 18)
        self.bubble_until = 0.0
        self.bubble_text = ""
        self.drag_anchor = None
        self.press_position = None
        self.dragged = False
        self.menu_open = False
        self.closing = False
        self.tray = None
        self.chat = None
        self.nest_breathing = False
        self.remote = RemotePlan()
        # LUNA ZHOU, 2026-11-10: a lone click still pets; a double-click cancels it and opens chat.
        self.click_timer = QTimer(self)
        self.click_timer.setSingleShot(True)
        self.click_timer.timeout.connect(self.pet)

        self.setWindowTitle("团子 · 写实桌面宠物")
        self.setWindowFlags(self.window_flags())
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setToolTip("拖动移动团子 · 单击摸摸 · 双击说话 · 右键打开菜单")
        self.setWindowIcon(QIcon(self.source))
        self.resize_pet()
        self.build_mesh()
        self.restore_position()
        self.tray = self.create_tray()
        self.refresh_tray_menu()
        self.timer = QTimer(self)
        # LUNA ZHOU, 2026-11-03: smooth gait playback and desktop movement.
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self.animate)
        self.timer.start()
        self.greeting_timer = QTimer(self)
        self.greeting_timer.setInterval(45000)
        self.greeting_timer.timeout.connect(self.idle_greeting)
        self.greeting_timer.start()
        self.remote.start()
        self.say("团子来陪你啦，右键看看吧", 5)

    @staticmethod
    def load_settings() -> dict:
        try:
            data = json.loads(SETTINGS.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def save_settings(self) -> None:
        data = {"x": self.x(), "y": self.y(), "size": self.pet_height, "on_top": self.on_top, "auto_actions": self.auto_actions, "roaming_enabled": self.roaming_enabled, "butterfly_enabled": self.butterfly_enabled}
        try:
            LOCAL.mkdir(parents=True, exist_ok=True)
            temporary = SETTINGS.with_suffix(".tmp")
            temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(SETTINGS)
        except OSError:
            LOG.exception("保存设置失败")

    def window_flags(self):
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window
        if self.on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        return flags

    def resize_pet(self) -> None:
        self.pet_width = round(self.pet_height * self.source.width() / self.source.height())
        # LUNA ZHOU, 2026-11-03: leave room for the longer trunk and stride.
        widest = max((clip.frames[0].width() for clip in self.clips.values()), default=768)
        self.setFixedSize(max(self.pet_width, round(self.pet_height * max(1.87, widest / 448))) + 28, round(self.pet_height * 1.12) + 86)
        self.scaled = self.source.scaled(
            round(self.pet_width * self.devicePixelRatioF() * 1.04),
            round(self.pet_height * self.devicePixelRatioF() * 1.04),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.artwork_cache_key = None

    def build_mesh(self) -> None:
        """Cache transparent image tiles for small, continuous joint deformations."""
        self.mesh = []
        source_image = self.source.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
        step = 72
        for outer_y in range(0, self.source.height(), step):
            for outer_x in range(0, self.source.width(), step):
                outer_width = min(step, self.source.width() - outer_x)
                outer_height = min(step, self.source.height() - outer_y)
                # Fine tiles only around the eyes, to move the original pupils
                # without moving the eye outline or drawing replacement eyes.
                near_eyes = any(outer_x < eye_x + 36 and outer_x + outer_width > eye_x - 36 and outer_y < eye_y + 32 and outer_y + outer_height > eye_y - 32 for eye_x, eye_y in ((875, 281), (1009, 241)))
                tile_step = 12 if near_eyes else step
                for y in range(outer_y, outer_y + outer_height, tile_step):
                    for x in range(outer_x, outer_x + outer_width, tile_step):
                        width = min(tile_step, outer_x + outer_width - x)
                        height = min(tile_step, outer_y + outer_height - y)
                        image = source_image.copy(x, y, width, height)
                        if not any(bytes(image.constBits())[3::4]):
                            continue
                        tile = QPixmap.fromImage(image)
                        polygon = QPolygonF([QPointF(0, 0), QPointF(width, 0), QPointF(width, height), QPointF(0, height)])
                        corners = [(x, y), (x + width, y), (x + width, y + height), (x, y + height)]
                        self.mesh.append((tile, polygon, corners))

    def deform(self, x: float, y: float, head_angle: float, tail_phase: float) -> QPointF:
        u, v = x / self.source.width(), y / self.source.height()
        for eye_x, eye_y, radius_x, radius_y in ((875, 281, 32, 27), (1009, 241, 29, 28)):
            radius_squared = ((x - eye_x) / radius_x) ** 2 + ((y - eye_y) / radius_y) ** 2
            if radius_squared < 1:
                influence = (1 - radius_squared) ** 2
                u += self.gaze_x * 6 * influence / self.source.width()
                v += self.gaze_y * 4 * influence / self.source.height()
        # Neck influence fades smoothly into the chest; tail influence fades at its base.
        head_weight = max(0.0, min(1.0, (0.45 - v) / 0.18))
        if head_weight:
            angle = math.radians(head_angle) * head_weight
            dx, dy = u - .755, v - .38
            u, v = .755 + dx * math.cos(angle) - dy * math.sin(angle), .38 + dx * math.sin(angle) + dy * math.cos(angle)
        tail_weight = max(0.0, min(1.0, (.44 - u) / .37)) ** 1.6
        tail_weight *= max(0.0, min(1.0, (v - .74) / .08))
        v += tail_phase * .026 * tail_weight
        u += tail_phase * .006 * tail_weight
        return QPointF(u * self.pet_width - self.pet_width / 2, v * self.pet_height - self.pet_height)

    def draw_artwork(self, painter: QPainter, head_angle: float, tail_phase: float) -> None:
        if abs(head_angle) < .01 and abs(tail_phase) < .01 and abs(self.gaze_x) < .01 and abs(self.gaze_y) < .01:
            draw_long_body(painter, self.scaled, QRectF(-self.pet_width / 2, -self.pet_height, self.pet_width, self.pet_height))
            return
        key = (round(head_angle, 1), round(tail_phase, 2), round(self.gaze_x, 2), round(self.gaze_y, 2), self.pet_height, self.devicePixelRatioF())
        if key != self.artwork_cache_key:
            ratio = self.devicePixelRatioF()
            self.artwork_cache = QPixmap(round((self.pet_width + 24) * ratio), round((self.pet_height + 24) * ratio))
            self.artwork_cache.setDevicePixelRatio(ratio)
            self.artwork_cache.fill(Qt.GlobalColor.transparent)
            mesh_painter = QPainter(self.artwork_cache)
            mesh_painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            mesh_painter.translate(self.pet_width / 2 + 12, self.pet_height + 12)
            base = mesh_painter.worldTransform()
            for tile, source_polygon, corners in self.mesh:
                target = QPolygonF([self.deform(x, y, head_angle, tail_phase) for x, y in corners])
                transform = QTransform.quadToQuad(source_polygon, target)
                if transform is not None:
                    mesh_painter.setWorldTransform(transform * base)
                    mesh_painter.drawPixmap(0, 0, tile)
            mesh_painter.end()
            self.artwork_cache_key = key
        draw_long_body(painter, self.artwork_cache, QRectF(-self.pet_width / 2 - 12, -self.pet_height - 12, self.pet_width + 24, self.pet_height + 24))

    def perform_motion(self, motion: str, announce: bool = True) -> None:
        requested_pose = motion[4:] if motion.startswith("bed-") else ""
        if requested_pose:
            motion = "bed"
        if motion == "nest-breath":
            motion = "bed"
        if motion == "butterfly":
            self.start_butterfly()
            return
        self.end_butterfly()
        self.sleeping = False
        self.paused = False
        self.finish_clip()
        self.motion, self.motion_started = motion, time.monotonic()
        self.last_tick = time.monotonic()
        self.active_clip = self.clips.get(motion)
        self.clip_elapsed = 0.0
        self.auto_resume_at = 0.0
        self.recent_motions = (self.recent_motions + [motion])[-3:]
        self.clip_loops = {"walk": 2, "nuzzle": 2, "eat": 3, "wave": 2, "purr": 3, "ball": 3, "groom": 2, "groom_fur": 2, "bed": 1}.get(motion, 1)
        if motion == "bed" and self.sleep_poses:
            pose = choose_pose(self.sleep_poses, self.last_sleep_pose, requested_pose)
            self.last_sleep_pose = pose.name
            self.nap = Nap(pose, random.uniform(45, 90))
            self.rest_elapsed = 0.0
            # LUNA ZHOU, 2026-11-10: a keyed nest loop replaces the chest morph
            # unless the user asked for one of the still poses.
            self.nest_breathing = sleep_uses_recorded_breath(requested_pose, set(self.clips))
            if self.nest_breathing:
                self.active_clip = self.clips.get("nest-breath")
        if motion in ("walk", "run"):
            self.choose_walk_target()
        else:
            self.next_motion = time.monotonic() + random.uniform(25, 45)
        captions = {"tail": "尾巴轻轻摇～", "tilt": "嗯？你在叫我吗", "hop": "喵！开心一下", "nuzzle": "蹭蹭，呼噜呼噜…", "walk": "出去溜达两步～", "eat": "开饭啦，啊呜～", "wave": "嗨，今天也陪着你", "purr": "呼噜呼噜…", "ball": "让我拨一下小球～"}
        if announce:
            self.say({"run": "开心地小跑一下～", "groom": "舔舔小爪，洗洗脸～", "groom_fur": "把毛毛舔得整整齐齐～", "bed": "钻进小窝，睡一会儿～"}.get(motion, captions.get(motion, "喵～")), 2.5)
        self.refresh_tray_menu()

    def finish_clip(self) -> None:
        locomotion = self.active_clip and self.active_clip.name in ("walk", "run")
        if locomotion:
            self.save_settings()
        self.active_clip = None
        self.nap = None
        self.nest_breathing = False
        self.clip_elapsed = 0.0
        self.motion = ""
        self.walk_target = None
        self.walk_speed = 0.0
        self.playback_rate = 1.0
        # Random short transitions rather than a fixed action list followed
        # by a long static-photo pause after every action.
        # LUNA ZHOU, 2026-11-10: mix short, medium and long gaps. Not a fixed loop.
        planned = getattr(self, "planned_pause", None)
        self.planned_pause = None
        if isinstance(planned, (int, float)) and 0.4 <= planned <= 24:
            gap = float(planned)
        else:
            roll = random.random()
            if roll < 0.45:
                gap = random.uniform(0.4, 1.6)
            elif roll < 0.8:
                gap = random.uniform(2.0, 7.0)
            else:
                gap = random.uniform(9.0, 24.0)
        self.next_activity = time.monotonic() + gap
        self.next_roam = time.monotonic() + random.choices((random.uniform(2, 4), random.uniform(5, 9), random.uniform(10, 16)), weights=(6, 3, 1))[0]

    def choose_activity(self) -> str | None:
        """Weighted random choices, with variety and no predetermined order."""
        choices = []
        if self.roaming_enabled:
            choices.extend((name, weight) for name, weight in (("walk", 8), ("run", 2)) if name in self.clips)
        if self.auto_actions:
            choices.extend((name, weight) for name, weight in (("nuzzle", 3), ("wave", 1), ("purr", 2), ("ball", 2), ("groom", 3), ("groom_fur", 3), ("eat", .7), ("bed", 10)) if name in self.clips)
            choices.extend((("tail", 1), ("tilt", 1)))
        if not choices:
            return None
        varied = [choice for choice in choices if choice[0] not in self.recent_motions[-2:]] or choices
        return random.choices([name for name, _ in varied], weights=[weight for _, weight in varied])[0]

    def resolve_activity(self) -> str | None:
        """Prefer one clip the shared API already chose; otherwise the local mix."""
        remote = getattr(self, "remote", None)
        plan = remote.take_plan() if remote is not None else None
        clip = plan.get("clip") if isinstance(plan, dict) else None
        allowed = clip in self.clips or clip in {"tail", "tilt", "hop", "butterfly"}
        if clip == "nest-breath" and clip not in self.clips:
            allowed = False
        if allowed:
            pause = plan.get("pause_ms")
            if isinstance(pause, (int, float)):
                self.planned_pause = max(0.4, min(24.0, float(pause) / 1000))
            return "bed" if clip == "bed" else clip
        return self.choose_activity()

    def use_ambient_animation(self) -> bool:
        return not self.sleeping and not self.motion and (self.auto_actions or self.roaming_enabled) and time.monotonic() >= self.auto_resume_at and "purr" in self.clips

    def stop_motion(self) -> None:
        self.end_butterfly()
        self.sleeping = False
        self.finish_clip()
        self.reaction_started = -100.0
        self.next_motion = time.monotonic() + random.uniform(25, 45)
        self.next_roam = time.monotonic() + 8.0
        self.auto_resume_at = self.next_activity = time.monotonic() + 8.0
        self.update()

    def walking_bounds(self):
        screen = QApplication.screenAt(self.frameGeometry().center()) or QApplication.primaryScreen()
        if screen is None:
            return None
        area = screen.availableGeometry()
        return (area.left(), area.top(), max(area.left(), area.right() - self.width() + 1), max(area.top(), area.bottom() - self.height() + 1))

    def choose_walk_target(self) -> None:
        self.keep_on_screen()
        bounds = self.walking_bounds()
        self.walk_position = QPointF(self.pos())
        self.walk_speed = 0.0
        if bounds is None:
            self.walk_target = None
            return
        left, top, right, bottom = bounds
        self.walk_origin = QPointF(self.pos())
        self.walk_progress = 0.0
        running = self.active_clip and self.active_clip.name == "run"
        self.walk_base_speed = self.pet_height * (random.uniform(.95, 1.25) if running else random.uniform(.23, .32))
        minimum_distance = min(90.0, math.hypot(right - left, bottom - top) * .25)
        for attempt in range(16):
            heading = self.walk_heading + random.uniform(-1.1, 1.1) if attempt < 5 and random.random() < .8 else random.uniform(0, math.tau)
            distance = self.pet_height * (random.uniform(1.6, 3.4) if running else random.uniform(.5, 1.6))
            if not running and random.random() < .12:
                distance *= 1.8
            target = QPointF(max(left, min(self.x() + math.cos(heading) * distance, right)), max(top, min(self.y() + math.sin(heading) * distance, bottom)))
            if math.hypot(target.x() - self.x(), target.y() - self.y()) >= minimum_distance:
                break
        self.walk_target = target
        dx, dy = target.x() - self.x(), target.y() - self.y()
        length = max(1.0, math.hypot(dx, dy))
        bend = random.uniform(-1, 1) * min(70.0, length * .18)
        self.walk_control = QPointF(max(left, min((self.x() + target.x()) / 2 - dy / length * bend, right)), max(top, min((self.y() + target.y()) / 2 + dx / length * bend, bottom)))
        self.walk_length = length * 1.04
        self.walk_heading = math.atan2(dy, dx)
        if abs(target.x() - self.x()) > 1:
            self.walk_direction = 1 if target.x() > self.x() else -1

    def move_walking(self, delta: float) -> None:
        bounds = self.walking_bounds()
        if bounds is None:
            self.finish_clip()
            return
        if self.walk_target is None:
            self.choose_walk_target()
        if self.walk_target is None:
            self.finish_clip()
            return
        left, top, right, bottom = bounds
        self.walk_target.setX(max(left, min(self.walk_target.x(), right)))
        self.walk_target.setY(max(top, min(self.walk_target.y(), bottom)))
        dx = self.walk_target.x() - self.walk_position.x()
        dy = self.walk_target.y() - self.walk_position.y()
        remaining = math.hypot(dx, dy)
        desired_speed = min(self.walk_base_speed, max(10.0, remaining * 1.5))
        self.walk_speed += (desired_speed - self.walk_speed) * min(1.0, delta * 4)
        distance = min(remaining, self.walk_speed * delta)
        self.walk_progress = min(1.0, self.walk_progress + distance / self.walk_length)
        if self.walk_progress >= .999 or remaining <= max(1.0, distance):
            self.move(round(self.walk_target.x()), round(self.walk_target.y()))
            self.finish_clip()
            return
        previous_position = QPointF(self.walk_position)
        t = self.walk_progress
        self.walk_position = self.walk_origin * (1 - t) ** 2 + self.walk_control * (2 * (1 - t) * t) + self.walk_target * t ** 2
        tangent_x = (self.walk_control.x() - self.walk_origin.x()) * (1 - t) + (self.walk_target.x() - self.walk_control.x()) * t
        if abs(tangent_x) > 1:
            self.walk_direction = 1 if tangent_x > 0 else -1
        traveled = math.hypot(self.walk_position.x() - previous_position.x(), self.walk_position.y() - previous_position.y())
        self.advance_gait(traveled, delta)
        self.move(round(max(left, min(self.walk_position.x(), right))), round(max(top, min(self.walk_position.y(), bottom))))

    def advance_gait(self, distance: float, delta: float) -> None:
        """Drive footfall phase from traveled distance, including acceleration.

        A stationary cat holds its stance. Short steps at startup and stopping
        no longer play a minimum-speed loop that makes the paws slide.
        """
        clip = self.active_clip
        if clip is None:
            return
        stride = clip.stride_pixels * self.pet_height / 448
        if stride > 0:
            elapsed = distance / stride * clip.seconds
        else:
            elapsed = delta * self.walk_speed / max(1.0, self.walk_base_speed)
        self.playback_rate = elapsed / max(.001, delta)
        self.clip_elapsed = (self.clip_elapsed + elapsed) % clip.seconds

    def set_roaming(self, enabled: bool) -> None:
        self.roaming_enabled = enabled and "walk" in self.clips
        if self.roaming_enabled:
            self.perform_motion("walk")
        elif self.active_clip and self.active_clip.name in ("walk", "run"):
            self.stop_motion()
        self.save_settings()
        self.refresh_tray_menu()

    def toggle_auto_actions(self) -> None:
        self.auto_actions = not self.auto_actions
        self.next_activity = time.monotonic() + random.uniform(.2, .8)
        self.next_motion = time.monotonic() + random.uniform(25, 45)
        self.save_settings()
        self.refresh_tray_menu()

    def start_butterfly(self) -> None:
        if not self.butterfly_frames or "pounce" not in self.clips:
            self.say("小蝴蝶还没有准备好", 3)
            return
        self.stop_motion()
        screen = QApplication.screenAt(self.frameGeometry().center()) or QApplication.primaryScreen()
        if screen is None:
            return
        self.sleeping = self.paused = False
        self.butterfly_scene = ButterflyScene(QRectF(self.geometry()), QRectF(screen.availableGeometry()), self.pet_height, self.walk_direction)
        if self.butterfly_overlay is None:
            self.butterfly_overlay = ButterflyOverlay(self, self.butterfly_frames)
        self.walk_position = QPointF(self.pos())
        self.walk_speed = 0.0
        self.motion, self.motion_started = "butterfly", time.monotonic()
        self.auto_resume_at = 0.0
        self.recent_motions = (self.recent_motions + ["butterfly"])[-3:]
        self.last_tick = time.monotonic()
        self.say("咦，一只小蝴蝶！", 3)
        self.refresh_tray_menu()

    def end_butterfly(self) -> None:
        if self.butterfly_scene is not None:
            self.butterfly_scene = None
            self.next_butterfly = time.monotonic() + random.uniform(100, 180)
            self.save_settings()
        if self.butterfly_overlay is not None:
            self.butterfly_overlay.hide()

    def toggle_butterfly_encounters(self) -> None:
        self.butterfly_enabled = not self.butterfly_enabled
        self.save_settings()
        self.refresh_tray_menu()

    def advance_butterfly(self, delta: float) -> None:
        scene = self.butterfly_scene
        stage = scene.advance(delta, QRectF(self.geometry()), self.walk_direction)
        if scene.elapsed >= scene.duration:
            self.end_butterfly()
            self.finish_clip()
            self.next_roam = time.monotonic() + random.uniform(4, 8)
            self.next_motion = time.monotonic() + random.uniform(25, 45)
            return
        # LUNA ZHOU, 2026-11-03: stop near the butterfly instead of
        # running backwards to preserve an artificial following distance.
        previous_position = QPointF(self.walk_position)
        if stage == "chase":
            self.move_chasing(delta, scene.position)
        # Hysteresis avoids repeatedly switching walk/run near one threshold.
        running = self.walk_speed > self.pet_height * (.35 if scene.pose == "run" else .50)
        pose = ("run" if "run" in self.clips and running else "walk") if stage == "chase" else "pounce" if stage == "pounce" else ""
        if scene.pose != pose:
            phase = self.clip_elapsed / self.active_clip.seconds if self.active_clip and self.active_clip.name in ("walk", "run") else 0.0
            scene.pose = pose
            self.active_clip = self.clips.get(pose)
            self.clip_elapsed = phase * self.active_clip.seconds if self.active_clip and pose in ("walk", "run") else 0.0
        if self.active_clip:
            if stage == "chase":
                traveled = math.hypot(self.walk_position.x() - previous_position.x(), self.walk_position.y() - previous_position.y())
                self.advance_gait(traveled, delta)
            elif pose == "pounce":
                self.clip_elapsed = min((scene.elapsed - scene.stage_started) / 2 * self.active_clip.seconds, self.active_clip.seconds - .001)
        if stage != "chase":
            self.walk_speed = 0.0
        self.butterfly_overlay.present(scene.position, scene.elapsed, max(52, round(self.pet_height * .24)), max(0.0, min(1.0, (scene.duration - scene.elapsed) / .8)))

    def move_chasing(self, delta: float, butterfly: QPointF) -> bool:
        bounds = self.walking_bounds()
        if bounds is None:
            return False
        offset = butterfly.x() - (self.walk_position.x() + self.width() / 2)
        # A small dead zone prevents turning back and forth as it flutters
        # around the cat's head. Only pursue a target ahead of the nose.
        if offset * self.walk_direction < -self.pet_height * .25:
            self.walk_direction *= -1
            self.walk_speed = 0.0
        direction = self.walk_direction
        left, top, right, bottom = bounds
        target_x = butterfly.x() - self.width() / 2 - direction * self.pet_height * .75
        target_y = butterfly.y() - self.height() + self.pet_height * .84
        target = QPointF(max(left, min(target_x, right)), max(top, min(target_y, bottom)))
        self.walk_target = target
        difference = target - self.walk_position
        stopping_distance = self.pet_height * (.04 if self.walk_speed > 1 else .10)
        if difference.x() * direction <= stopping_distance:
            self.walk_target = None
            self.walk_speed = 0.0
            return False
        remaining = math.hypot(difference.x(), difference.y())
        desired = min(self.pet_height * .85, remaining * 2)
        self.walk_speed += (desired - self.walk_speed) * min(1.0, delta * 4)
        if remaining > .5:
            self.walk_position += difference * (min(remaining, self.walk_speed * delta) / remaining)
            self.move(round(max(left, min(self.walk_position.x(), right))), round(max(top, min(self.walk_position.y(), bottom))))
            return True
        return False

    def restore_position(self) -> None:
        x, y = self.settings.get("x"), self.settings.get("y")
        if isinstance(x, int) and isinstance(y, int):
            self.move(x, y)
            self.keep_on_screen()
        else:
            self.go_home()

    def keep_on_screen(self) -> None:
        screen = QApplication.screenAt(self.frameGeometry().center()) or QApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        x = max(area.left(), min(self.x(), area.right() - self.width() + 1))
        y = max(area.top(), min(self.y(), area.bottom() - self.height() + 1))
        self.move(x, y)

    def go_home(self) -> None:
        self.stop_motion()
        screen = QApplication.screenAt(self.frameGeometry().center()) or QApplication.primaryScreen()
        if screen:
            area = screen.availableGeometry()
            self.move(area.right() - self.width() - 22, area.bottom() - self.height() - 10)
        self.save_settings()

    def create_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return None
        tray = QSystemTrayIcon(QIcon(self.source), self)
        tray.setToolTip("团子 · 单击找回，右键打开菜单")
        tray.activated.connect(self.tray_activated)
        tray.setContextMenu(self.build_menu())
        tray.show()
        return tray

    def tray_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.reveal()

    def build_menu(self) -> QMenu:
        menu = QMenu(self)
        menu.setStyleSheet("QMenu { background: #faf8f4; color: #403b35; border: 1px solid #ded8cd; padding: 6px; font: 10pt 'Microsoft YaHei'; } QMenu::item { padding: 7px 22px; border-radius: 5px; } QMenu::item:selected { background: #e7e9dd; } QMenu::separator { height: 1px; background: #e5dfd5; margin: 5px; }")
        title = menu.addAction("团子 · 今天也陪着你")
        title.setEnabled(False)
        menu.addSeparator()
        menu.addAction("摸摸团子", self.pet)
        menu.addAction("和团子说话", self.open_chat)
        movements = menu.addMenu("动作")
        for name in ("walk", "run", "nuzzle", "eat", "wave", "purr", "ball", "groom", "groom_fur", "bed", "nest-breath"):
            if name in self.clips:
                movements.addAction(self.clips[name].label, lambda checked=False, value=name: self.perform_motion(value))
        if self.sleep_poses:
            sleeping_poses = movements.addMenu("选择睡姿")
            for pose in self.sleep_poses.values():
                sleeping_poses.addAction(pose.label, lambda checked=False, value=pose.name: self.perform_motion("bed-" + value))
        catch = movements.addAction("捉蝴蝶", self.start_butterfly)
        catch.setEnabled(bool(self.butterfly_frames) and "pounce" in self.clips)
        movements.addSeparator()
        for label, motion in (("轻摇尾巴", "tail"), ("歪头看看", "tilt"), ("开心蹦一下", "hop")):
            movements.addAction(label, lambda checked=False, value=motion: self.perform_motion(value))
        movements.addSeparator()
        movements.addAction("回到待机", self.stop_motion)
        autonomous = menu.addAction("自主活动")
        autonomous.setCheckable(True)
        autonomous.setChecked(self.auto_actions)
        autonomous.triggered.connect(self.toggle_auto_actions)
        roaming = menu.addAction("自由漫游")
        roaming.setCheckable(True)
        roaming.setChecked(self.roaming_enabled)
        roaming.setEnabled("walk" in self.clips)
        roaming.triggered.connect(self.set_roaming)
        encounters = menu.addAction("偶遇蝴蝶")
        encounters.setCheckable(True)
        encounters.setChecked(self.butterfly_enabled)
        encounters.triggered.connect(self.toggle_butterfly_encounters)
        sleep_action = menu.addAction("休息一下")
        sleep_action.setCheckable(True)
        sleep_action.setChecked(self.sleeping or self.nap is not None)
        sleep_action.triggered.connect(self.toggle_sleep)
        pause_action = menu.addAction("暂停动作")
        pause_action.setCheckable(True)
        pause_action.setChecked(self.paused)
        pause_action.triggered.connect(self.toggle_pause)
        menu.addSeparator()
        sizes = menu.addMenu("宠物大小")
        group = QActionGroup(sizes)
        group.setExclusive(True)
        for name, height in SIZES.items():
            action = QAction(name, sizes)
            action.setCheckable(True)
            action.setChecked(self.pet_height == height)
            action.triggered.connect(lambda checked=False, value=height: self.change_size(value))
            group.addAction(action)
            sizes.addAction(action)
        top = menu.addAction("始终置顶")
        top.setCheckable(True)
        top.setChecked(self.on_top)
        top.triggered.connect(self.toggle_top)
        menu.addAction("回到屏幕右下角", self.go_home)
        if self.tray:
            menu.addAction("暂时藏起来（托盘找回）", self.hide)
        menu.addAction("使用说明", self.show_help)
        menu.addSeparator()
        menu.addAction("退出团子", self.quit_pet)
        return menu

    def refresh_tray_menu(self) -> None:
        if self.tray:
            old = self.tray.contextMenu()
            self.tray.setContextMenu(self.build_menu())
            if old:
                old.deleteLater()

    def reveal(self) -> None:
        self.keep_on_screen()
        self.showNormal()
        self.raise_()
        self.say("我在这里呀", 3)

    def change_size(self, height: int) -> None:
        self.stop_motion()
        bottom_right = self.geometry().bottomRight()
        self.pet_height = height
        self.resize_pet()
        self.move(bottom_right.x() - self.width() + 1, bottom_right.y() - self.height() + 1)
        self.keep_on_screen()
        self.save_settings()
        self.refresh_tray_menu()
        self.update()

    def toggle_top(self) -> None:
        position = self.pos()
        self.on_top = not self.on_top
        self.setWindowFlags(self.window_flags())
        self.move(position)
        self.show()
        self.save_settings()
        self.refresh_tray_menu()

    def toggle_sleep(self) -> None:
        if self.sleep_poses:
            if self.nap is not None and (self.sleeping or self.motion == "bed"):
                self.sleeping = False
                self.paused = False
                self.nap.wake()
            else:
                self.perform_motion("bed", announce=False)
                self.sleeping = True
                self.nap.duration = None
            self.say("团子安静陪着你…" if self.sleeping else "醒啦，继续陪你", 3)
            self.refresh_tray_menu()
            self.update()
            return
        was_sleeping = self.sleeping
        self.stop_motion()
        self.sleeping = not was_sleeping
        self.rest_elapsed = 0.0
        if not self.sleeping and "bed" in self.clips:
            self.perform_motion("bed", announce=False)
            self.clip_elapsed = (len(self.active_clip.frames) - BED_WAKE_FRAMES) * self.active_clip.duration_ms / 1000
        self.say("团子安静陪着你…" if self.sleeping else "醒啦，继续陪你", 3)
        self.refresh_tray_menu()
        self.update()

    def bed_rest_time(self) -> float:
        clip = self.clips.get("bed")
        if clip is None:
            return 0.0
        entry = BED_ENTRY_FRAMES * clip.duration_ms / 1000
        breath = BED_SLEEP_FRAMES * clip.duration_ms / 1000
        return self.rest_elapsed if self.rest_elapsed < entry else entry + (self.rest_elapsed - entry) % breath

    def toggle_pause(self) -> None:
        self.paused = not self.paused
        self.refresh_tray_menu()
        self.update()

    def say(self, text: str, seconds: float = 2.5) -> None:
        self.bubble_text = text
        self.bubble_until = time.monotonic() + seconds
        self.update()

    def pet(self) -> None:
        if self.sleeping or self.nap is not None:
            self.say("轻轻摸摸，团子在休息", 3)
        else:
            self.perform_motion("nuzzle")
            self.reaction_started = time.monotonic()
            self.say(random.choice(("喵～ 好舒服", "呼噜呼噜…", "今天也要开心呀", "蹭蹭你的手～")))

    def idle_greeting(self) -> None:
        # Only speak while the pointer is on the pet; no periodic desktop popups.
        if self.isVisible() and self.underMouse() and not self.sleeping and self.nap is None and not self.menu_open:
            self.say("忙累了，记得休息一下呀", 3)

    def animate(self) -> None:
        now = time.monotonic()
        delta = min(.15, max(0.0, now - self.last_tick))
        self.last_tick = now
        if not self.isVisible() or self.isMinimized():
            if self.butterfly_overlay is not None:
                self.butterfly_overlay.hide()
            return
        if self.nap is not None and not self.paused and not self.menu_open and self.drag_anchor is None:
            self.nap.advance(delta)
            self.rest_elapsed = self.nap.elapsed
        elif self.nap is None and self.sleeping and not self.paused:
            self.rest_elapsed += delta
        if not self.paused and not self.sleeping:
            cursor = self.mapFromGlobal(self.butterfly_scene.position.toPoint() if self.butterfly_scene is not None else QCursor.pos())
            eye_x = self.width() / 2 + self.pet_width * .218
            eye_y = self.height() - 13 - self.pet_height * .884
            target_x = 0.0 if self.motion == "bed" else math.tanh((cursor.x() - eye_x) / 180)
            target_y = 0.0 if self.motion == "bed" else math.tanh((cursor.y() - eye_y) / 160)
            gaze_rate = 1 - math.exp(-delta * 4.2)
            self.gaze_x += (target_x - self.gaze_x) * gaze_rate
            self.gaze_y += (target_y - self.gaze_y) * gaze_rate
        elif self.sleeping:
            self.gaze_x *= .9
            self.gaze_y *= .9
        if not self.paused and not self.sleeping and not self.menu_open and self.drag_anchor is None:
            if self.active_clip is None and self.use_ambient_animation():
                self.ambient_elapsed += delta
            if self.butterfly_scene is not None:
                self.advance_butterfly(delta)
            elif self.active_clip:
                if self.nap is not None and self.motion == "bed":
                    self.clip_elapsed = self.nap.elapsed
                    if self.nap.finished:
                        self.finish_clip()
                elif self.active_clip.name in ("walk", "run"):
                    self.move_walking(delta)
                else:
                    self.clip_elapsed += delta
                    if self.clip_elapsed >= self.active_clip.seconds * self.clip_loops:
                        self.finish_clip()
                        self.next_motion = now + random.uniform(25, 45)
            elif self.motion in ("tail", "tilt", "hop"):
                if now - self.motion_started >= {"tail": 3, "tilt": 2.4, "hop": .85}[self.motion]:
                    self.finish_clip()
            elif self.auto_actions and self.butterfly_enabled and self.butterfly_frames and "pounce" in self.clips and now >= max(self.next_butterfly, self.auto_resume_at):
                self.start_butterfly()
            elif now >= max(self.next_activity, self.auto_resume_at):
                activity = self.resolve_activity()
                if activity:
                    self.perform_motion(activity, announce=False)
        remote = getattr(self, "remote", None)
        if remote is not None and not self.paused:
            for note in remote.take_reminders():
                self.say(note, 5)
        if self.isVisible():
            # Most completed activities chain in the same tick, so they do
            # not flash a default seated photo between every two motions.
            if not self.paused and not self.sleeping and not self.menu_open and self.drag_anchor is None and self.active_clip is None and not self.motion and time.monotonic() >= max(self.next_activity, self.auto_resume_at):
                activity = self.resolve_activity()
                if activity:
                    self.perform_motion(activity, announce=False)
            self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        now = time.monotonic()
        phase = 0.0 if self.paused else math.sin((now - self.started) * math.tau / (6 if self.sleeping else 4))
        scale_y = 1 + phase * (0.003 if self.sleeping else 0.006)
        reaction_age = now - self.reaction_started
        age = now - self.motion_started
        head_angle = tail_phase = hop = 0.0
        if not self.paused:
            if self.motion == "tail" and 0 <= age < 3:
                tail_phase = math.sin(age * math.tau / 1.5) * math.sin(math.pi * age / 3)
            elif self.motion in ("tilt", "nuzzle") and 0 <= age < 2.4:
                head_angle = math.sin(math.pi * age / 2.4) ** 2 * (5 if self.motion == "tilt" else -4)
                tail_phase = math.sin(age * math.tau / 2.4) * .4
            elif self.motion == "hop" and 0 <= age < .85:
                hop = math.sin(math.pi * age / .85) * self.pet_height * .065
            if self.butterfly_scene is not None and self.butterfly_scene.stage in ("notice", "watch"):
                head_angle = math.sin(self.butterfly_scene.elapsed * 1.3) * 3
        lean = 0.0
        if not self.paused and not self.sleeping and 0 <= reaction_age <= 1.6:
            lean = math.sin(reaction_age * math.tau / 1.6) * 2 * (1 - reaction_age / 1.6)
        render_clip, render_elapsed = self.active_clip, self.clip_elapsed
        if self.sleeping and "bed" in self.clips:
            render_clip = self.clips["bed"]
            # LUNA ZHOU, 2026-11-03: enter the bed once, then loop only
            # its closed-eye breathing phase until the user wakes the cat.
            render_elapsed = self.bed_rest_time()
        elif render_clip is None and self.use_ambient_animation():
            render_clip, render_elapsed = self.clips["purr"], self.ambient_elapsed
        nest = self.clips.get("nest-breath") if getattr(self, "nest_breathing", False) else None
        if self.nap is not None and (self.sleeping or self.motion == "bed") and nest is not None:
            side = self.pet_height * 512 / 448
            frame_width = nest.frames[0].width() / 512 * side
            target = QRectF((self.width() - frame_width) / 2, self.height() - 13 - side * 480 / 512, frame_width, side)
            draw_frame(painter, nest, nest.frame_index(self.nap.elapsed), target, 0.0, 0.0)
        elif self.nap is not None and (self.sleeping or self.motion == "bed"):
            side = self.pet_height * 512 / 448
            target = QRectF((self.width() - side * 1.5) / 2, self.height() - 13 - side * 480 / 512, side * 1.5, side)
            draw_sleep(painter, self.nap, target)
        elif render_clip:
            ambient = self.active_clip is None and not self.sleeping
            if ambient:
                painter.save()
                painter.translate(self.width() / 2, self.height() - 13)
                painter.scale(1.0, scale_y)
                painter.translate(-self.width() / 2, 13 - self.height())
            side = self.pet_height * 512 / 448
            frame_width = render_clip.frames[0].width() / 512 * side
            target = QRectF((self.width() - frame_width) / 2, self.height() - 13 - side * 480 / 512, frame_width, side)
            draw_frame(painter, render_clip, render_clip.frame_index(render_elapsed), target, self.gaze_x, self.gaze_y, render_clip.name in ("walk", "run", "pounce") and self.walk_direction < 0)
            if ambient:
                painter.restore()
        else:
            # Transform only at render time; never rewrite the approved image.
            painter.save()
            painter.translate(self.width() / 2, self.height() - 13 - hop)
            painter.rotate(lean)
            painter.scale(1.0, scale_y)
            self.draw_artwork(painter, head_angle, tail_phase)
            painter.restore()
        if now < self.bubble_until:
            painter.setFont(QFont("Microsoft YaHei", 9))
            metrics = painter.fontMetrics()
            text = metrics.elidedText(self.bubble_text, Qt.TextElideMode.ElideRight, self.width() - 42)
            width = min(self.width() - 16, metrics.horizontalAdvance(text) + 26)
            rect = QRectF((self.width() - width) / 2, 15, width, 34)
            painter.setPen(QColor("#ddd7cd"))
            painter.setBrush(QColor(255, 253, 248, 246))
            painter.drawRoundedRect(rect, 13, 13)
            painter.setPen(QColor("#51493f"))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
        if self.sleeping:
            painter.setFont(QFont("Microsoft YaHei", 12))
            painter.setPen(QColor("#8e9d9c"))
            painter.drawText(QPointF(self.width() * .70, 85), "z Z")

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            if self.nap is None:
                self.stop_motion()
            self.drag_anchor = event.globalPosition().toPoint() - self.pos()
            self.press_position = event.globalPosition().toPoint()
            self.dragged = False
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self.drag_anchor is not None and self.press_position is not None:
            delta = event.globalPosition().toPoint() - self.press_position
            if not self.dragged and delta.manhattanLength() > QApplication.startDragDistance():
                self.stop_motion()
                self.dragged = True
            if self.dragged:
                self.move(event.globalPosition().toPoint() - self.drag_anchor)
            event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_anchor = None
            self.press_position = None
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            if self.dragged:
                self.keep_on_screen()
                self.next_roam = time.monotonic() + 5.0
                self.auto_resume_at = self.next_activity = time.monotonic() + 5.0
                self.save_settings()
            else:
                self.click_timer.start(220)
            event.accept()

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            # LUNA ZHOU, 2026-11-10: chat replaces the old double-click sleep toggle.
            self.click_timer.stop()
            self.open_chat()
            event.accept()

    def open_chat(self) -> None:
        if self.chat is None:
            self.chat = ChatDialog(self)
        self.chat.show()
        self.chat.raise_()
        self.chat.activateWindow()

    def contextMenuEvent(self, event) -> None:
        self.menu_open = True
        menu = self.build_menu()
        menu.exec(event.globalPos())
        menu.deleteLater()
        self.menu_open = False

    def hideEvent(self, event) -> None:
        if self.butterfly_overlay is not None:
            self.butterfly_overlay.hide()
        super().hideEvent(event)

    def save_snapshot(self) -> None:
        self.grab().save(str(LOCAL / "render-preview.png"))
        if self.butterfly_overlay is not None and self.butterfly_overlay.isVisible():
            area = self.geometry().united(self.butterfly_overlay.geometry()).adjusted(-16, -16, 16, 16)
            image = QImage(area.width(), area.height(), QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(QColor("#343a38"))
            painter = QPainter(image)
            painter.drawPixmap(self.pos() - area.topLeft(), self.grab())
            painter.drawPixmap(self.butterfly_overlay.pos() - area.topLeft(), self.butterfly_overlay.grab())
            painter.end()
            image.save(str(LOCAL / "scene-preview.png"))

    def show_help(self) -> None:
        QMessageBox.information(self, "团子 · 使用说明", HELP_TEXT)

    def status(self) -> dict:
        status = {"running": True, "pid": os.getpid(), "visible": self.isVisible(), "minimized": self.isMinimized(), "size": self.pet_height, "position": [self.x(), self.y()], "on_top": self.on_top, "paused": self.paused, "sleeping": self.sleeping, "motion": self.motion, "gaze": [round(self.gaze_x, 3), round(self.gaze_y, 3)], "ai_actions": list(self.clips), "active_clip": self.active_clip.name if self.active_clip else None, "frame": self.active_clip.frame_index(self.clip_elapsed) if self.active_clip else None, "clip_elapsed": round(self.clip_elapsed, 3), "auto_actions": self.auto_actions, "roaming_enabled": self.roaming_enabled, "walk_target": [round(self.walk_target.x()), round(self.walk_target.y())] if self.walk_target is not None else None, "walking_bounds": self.walking_bounds(), "walking_speed": round(self.walk_speed, 1), "butterfly_enabled": self.butterfly_enabled, "butterfly_stage": self.butterfly_scene.stage if self.butterfly_scene is not None else None, "butterfly_elapsed": round(self.butterfly_scene.elapsed, 2) if self.butterfly_scene is not None else None, "butterfly_position": [round(self.butterfly_scene.position.x()), round(self.butterfly_scene.position.y())] if self.butterfly_scene is not None else None, "artwork_sha256": hashlib.sha256(ARTWORK.read_bytes()).hexdigest()}
        ambient = self.active_clip is None and self.use_ambient_animation()
        status.update({"recent_actions": list(self.recent_motions), "ambient_animation": "purr" if ambient else None, "ambient_frame": self.clips["purr"].frame_index(self.ambient_elapsed) if ambient else None, "facing": self.walk_direction, "playback_rate": round(self.playback_rate, 3), "next_activity_in": round(max(0.0, max(self.next_activity, self.auto_resume_at) - time.monotonic()), 2)})
        status.update({"rest_elapsed": round(self.rest_elapsed, 3), "bed_rest_frame": self.clips["bed"].frame_index(self.bed_rest_time()) if self.sleeping and self.nap is None and "bed" in self.clips else None})
        status.update({"api_configured": api_configured(), "chat_open": bool(self.chat and self.chat.isVisible())})
        status.update({"sleep_pose": self.nap.pose.name if self.nap else None,
                       "sleep_pose_label": self.nap.pose.label if self.nap else None,
                       "sleep_duration": round(self.nap.duration, 2) if self.nap and self.nap.duration is not None else None,
                       "sleep_renderer": "continuous-chest" if self.nap else None})
        return status

    def run_action(self, action: str) -> None:
        actions = {
            "show": self.reveal,
            "home": self.go_home,
            "pet": self.pet,
            "rest": self.toggle_sleep,
            "pause": self.toggle_pause,
            "stop": self.stop_motion,
            "auto": self.toggle_auto_actions,
            "butterfly-auto": self.toggle_butterfly_encounters,
            "roam-on": lambda: self.set_roaming(True),
            "roam-off": lambda: self.set_roaming(False),
            "small": lambda: self.change_size(210),
            "standard": lambda: self.change_size(280),
            "large": lambda: self.change_size(370),
            "snapshot": self.save_snapshot,
            "chat": self.open_chat,
        }
        callback = actions.get(action)
        if callback:
            callback()
        elif action in ("tail", "tilt", "hop", "nuzzle", "walk", "run", "eat", "wave", "purr", "ball", "groom", "groom_fur", "bed", "butterfly") or action in {"bed-" + name for name in self.sleep_poses}:
            self.perform_motion(action)

    def quit_pet(self) -> None:
        self.closing = True
        self.end_butterfly()
        self.save_settings()
        if getattr(self, "remote", None) is not None:
            self.remote.stop()
        self.timer.stop()
        if self.tray:
            self.tray.hide()
        QApplication.instance().quit()

    def closeEvent(self, event) -> None:
        self.quit_pet()
        event.accept()


def send_to_existing(command: str) -> str | None:
    socket = QLocalSocket()
    socket.connectToServer(SERVER_NAME)
    if not socket.waitForConnected(750):
        return None
    socket.write(command.encode("ascii") + b"\n")
    socket.flush()
    if socket.waitForReadyRead(2000):
        response = bytes(socket.readAll()).decode("utf-8")
        socket.disconnectFromServer()
        return response
    socket.abort()
    return ""


def main() -> int:
    parser = argparse.ArgumentParser(description="团子写实桌面宠物")
    parser.add_argument("--version", action="version", version="团子 " + __version__)
    parser.add_argument("--self-check", action="store_true", help="检查打包资源和 Qt 运行环境后退出")
    parser.add_argument("--report", type=Path, help="将运行状态或自检结果写入 JSON 文件")
    parser.add_argument("--status", action="store_true", help="读取运行状态")
    parser.add_argument("--quit", action="store_true", help="退出正在运行的团子")
    parser.add_argument("--action", choices=("home", "pet", "rest", "pause", "stop", "auto", "roam-on", "roam-off", "small", "standard", "large", "snapshot", "chat", "tail", "tilt", "hop", "nuzzle", "walk", "run", "eat", "wave", "purr", "ball", "groom", "groom_fur", "bed", "bed-belly", "bed-buried", "bed-side", "bed-curled", "butterfly", "butterfly-auto"), help="向正在运行的团子发送动作；snapshot 导出应用自身渲染预览")
    options = parser.parse_args()
    LOCAL.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=LOCAL / "tuanzi.log", encoding="utf-8", level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sys.excepthook = lambda kind, value, trace: LOG.error("运行时异常", exc_info=(kind, value, trace))
    if options.self_check:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
    app = QApplication(sys.argv[:1])
    app.setApplicationName("团子桌面宠物")
    app.setQuitOnLastWindowClosed(False)
    def reply(data: str) -> None:
        if options.report:
            options.report.parent.mkdir(parents=True, exist_ok=True)
            options.report.write_text(data.strip() + "\n", encoding="utf-8")
        if sys.stdout:
            print(data.strip())

    if options.self_check:
        from .diagnostics import check_bundle
        result = check_bundle(ROOT)
        if options.report is None:
            options.report = LOCAL / "self-check.json"
        reply(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["ok"] else 1
    command = "status" if options.status else "quit" if options.quit else options.action or "show"
    existing = send_to_existing(command)
    if existing is not None:
        reply(existing)
        return 0 if existing else 1
    if options.status or options.quit or options.action:
        reply(json.dumps({"running": False}))
        return 1
    server = QLocalServer()
    if not server.listen(SERVER_NAME):
        LOG.error("无法创建单实例服务：%s", server.errorString())
        return 1
    try:
        window = PetWindow()
    except Exception as error:
        LOG.exception("启动失败")
        QMessageBox.critical(None, "团子启动失败", str(error))
        return 1
    clients = set()

    def connected():
        while server.hasPendingConnections():
            client = server.nextPendingConnection()
            clients.add(client)
            buffer = bytearray()

            def receive(sock=client, data=buffer):
                data.extend(bytes(sock.readAll()))
                if b"\n" not in data:
                    return
                action = bytes(data).split(b"\n", 1)[0]
                data.clear()
                window.run_action(action.decode("ascii", errors="replace"))
                response = json.dumps(window.status(), ensure_ascii=False).encode("utf-8")
                sock.write(response + b"\n")
                sock.flush()
                sock.disconnectFromServer()
                if action == b"quit":
                    QTimer.singleShot(100, window.quit_pet)

            def disconnected(sock=client):
                clients.discard(sock)
                sock.deleteLater()

            client.readyRead.connect(receive)
            client.disconnected.connect(disconnected)
            if client.bytesAvailable():
                receive()

    server.newConnection.connect(connected)
    app.aboutToQuit.connect(server.close)
    app.aboutToQuit.connect(window.save_settings)
    app.screenRemoved.connect(lambda screen: QTimer.singleShot(100, window.keep_on_screen))
    window.show()
    LOG.info("团子已启动：%s", window.status())
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
