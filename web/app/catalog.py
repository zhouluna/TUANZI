"""Clips the pet is allowed to play. Paths come from the manifests on disk."""

from __future__ import annotations

import json
from pathlib import Path

from .config import ASSETS

NEST_BREATH_ID = "nest-breath"
NEST_BREATH_CYCLE_MS = 4800
MEDIA = "/media"


def _read_json(path: Path) -> list:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return data if isinstance(data, list) else []


def animation_clips() -> list[dict]:
    folder = ASSETS / "animations"
    clips = []
    for entry in _read_json(folder / "manifest.json"):
        if not isinstance(entry, dict) or not entry.get("id") or not entry.get("frames"):
            continue
        frames = []
        for relative in entry["frames"]:
            if isinstance(relative, str) and not relative.startswith(("/", "\\")) and ".." not in relative:
                frames.append(f"{MEDIA}/animations/{relative}")
        if not frames:
            continue
        clips.append({
            "id": entry["id"],
            "label": entry.get("label") or entry["id"],
            "duration_ms": int(entry.get("duration") or 80),
            "frames": frames,
            "stride_pixels": float(entry.get("stride_pixels") or 0),
            "available": True,
        })
    known = {clip["id"] for clip in clips}
    if NEST_BREATH_ID not in known:
        clips.append({
            "id": NEST_BREATH_ID,
            "label": "猫窝呼吸",
            "duration_ms": 40,
            "frames": [],
            "stride_pixels": 0,
            "available": False,
            "cycle_ms": NEST_BREATH_CYCLE_MS,
            "note": "以后把约 4.8 秒的透明 PNG 序列写进 animations/manifest.json，id 用 nest-breath。现在不占位。",
        })
    return clips


def sleep_poses() -> list[dict]:
    folder = ASSETS / "sleep-v2"
    poses = []
    for entry in _read_json(folder / "manifest.json"):
        image = entry.get("image") if isinstance(entry, dict) else None
        if not image or ".." in image:
            continue
        poses.append({"id": entry.get("id"), "label": entry.get("label") or entry.get("id"), "image": f"{MEDIA}/sleep-v2/{image}"})
    return poses


def available_ids() -> set[str]:
    ids = {clip["id"] for clip in animation_clips() if clip.get("available")}
    ids.update({"butterfly", "tail", "tilt", "hop"})
    return ids
