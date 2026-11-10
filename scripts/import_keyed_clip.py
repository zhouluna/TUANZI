"""Turn a green-screen action video into a transparent PNG clip.

LUNA ZHOU, 2026-11-10.

The desktop and web pets only play PNG sequences. This script drops the
audio, keys the green screen, despills the edge, and writes frames the
existing loader accepts: height 512, width 512–1024, straight alpha.

It does not crossfade the loop. If the last frame is already the first
pose, that duplicate is dropped so the cycle does not hesitate.

Example
-------
python scripts/import_keyed_clip.py \\
  --video assets/animations/sources/groom.mp4 \\
  --id groom --label 舔爪洗脸 --fps 24
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

ANIMATIONS = ROOT / "assets" / "animations"
FRAME_MS = 42  # nearest integer to 1000/24; the loader stores one integer delay
OUTPUT_HEIGHT = 512
MIN_WIDTH = 512
MAX_WIDTH = 1024
LOOP_DUPLICATE = 6.0


def key_rgb(rgb: np.ndarray) -> np.ndarray:
    """Straight RGBA. Green-screen pixels become transparent; fur spill is pulled back.

    ``diff`` is green minus the stronger of red and blue. The screen sits
    near 250. White fur and the beige bed sit near 0. A soft ramp between
    14 and 42 keeps whiskers and the bed rim without a hard bite.
    """
    image = rgb.astype(np.float32)
    red, green, blue = image[:, :, 0], image[:, :, 1], image[:, :, 2]
    diff = green - np.maximum(red, blue)
    alpha = np.clip((42.0 - diff) / (42.0 - 14.0), 0.0, 1.0)
    limit = np.maximum(red, blue)
    # Pale fur picks up screen light. Darker olive irises are left alone.
    fur_spill = (limit > 150.0) & (diff > 4.0)
    green = np.where(fur_spill, np.minimum(green, limit + 1.0), green)
    green = np.where(alpha < 0.97, np.minimum(green, limit), green)
    color = np.stack([red, green, blue], axis=-1)
    premul = color * alpha[:, :, None]
    straight = np.zeros_like(color)
    visible = alpha > (1.0 / 255.0)
    straight[visible] = np.clip(premul[visible] / alpha[visible, None], 0.0, 255.0)
    output = np.zeros(image.shape[:2] + (4,), dtype=np.uint8)
    output[:, :, :3] = np.rint(straight).astype(np.uint8)
    output[:, :, 3] = np.rint(np.clip(alpha, 0.0, 1.0) * 255.0).astype(np.uint8)
    output[:, :, 3] = np.where(output[:, :, 3] < 6, 0, output[:, :, 3])
    output[:, :, :3] = np.where(output[:, :, 3:4] == 0, 0, output[:, :, :3])
    return output


def fit_canvas(rgba: np.ndarray) -> np.ndarray:
    """Scale to the loader's 512-tall window without stretching."""
    image = Image.fromarray(rgba, "RGBA")
    scale = OUTPUT_HEIGHT / image.height
    width = int(round(image.width * scale))
    height = OUTPUT_HEIGHT
    if width > MAX_WIDTH:
        scale = MAX_WIDTH / image.width
        width = MAX_WIDTH
        height = int(round(image.height * scale))
    resized = image.resize((width, height), Image.Resampling.LANCZOS)
    if width >= MIN_WIDTH and height == OUTPUT_HEIGHT:
        return np.asarray(resized)
    canvas = Image.new("RGBA", (max(width, MIN_WIDTH), OUTPUT_HEIGHT), (0, 0, 0, 0))
    canvas.paste(resized, ((canvas.width - width) // 2, (OUTPUT_HEIGHT - height) // 2))
    return np.asarray(canvas)


def extract_frames(video: Path, folder: Path) -> list[Path]:
    folder.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg", "-y", "-i", str(video),
        "-map", "0:v:0", "-an",
        "-fps_mode", "passthrough",
        str(folder / "%04d.png"),
    ]
    subprocess.run(command, check=True, capture_output=True)
    return sorted(folder.glob("*.png"))


def mean_abs(left: np.ndarray, right: np.ndarray) -> float:
    return float(np.abs(left.astype(np.int16) - right.astype(np.int16)).mean())


def quality(rgba: np.ndarray) -> dict:
    alpha = rgba[:, :, 3]
    opaque = alpha > 200
    edge = (alpha > 12) & (alpha < 230)
    red = rgba[:, :, 0].astype(np.int16)
    green = rgba[:, :, 1].astype(np.int16)
    blue = rgba[:, :, 2].astype(np.int16)
    spill = green - np.maximum(red, blue)
    return {
        "width": int(rgba.shape[1]),
        "height": int(rgba.shape[0]),
        "corner_alpha": int(alpha[0, 0]),
        "opaque": float(opaque.mean()),
        "spill_opaque": float(spill[opaque].mean()) if opaque.any() else 99.0,
        "spill_edge": float(spill[edge].mean()) if edge.any() else 0.0,
    }


def acceptable(report: dict) -> bool:
    return (
        report["height"] == OUTPUT_HEIGHT
        and MIN_WIDTH <= report["width"] <= MAX_WIDTH
        and report["corner_alpha"] == 0
        and 0.12 <= report["opaque"] <= 0.8
        and report["spill_opaque"] < 8
        and report["spill_edge"] < 6
    )


def bake_eyes(paths: list[Path]) -> list[list[list[float]]]:
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QGuiApplication, QImage
    from desktop_pet.animations import locate_eyes

    if QGuiApplication.instance() is None:
        QGuiApplication([])
    baked = []
    for path in paths:
        image = QImage(str(path))
        baked.append([[round(float(part), 4) for part in eye] for eye in locate_eyes(image)])
    return baked


def update_manifest(clip_id: str, label: str, frames: list[str], eyes: list, body_extended: bool) -> None:
    manifest_path = ANIMATIONS / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entry = next((item for item in manifest if item.get("id") == clip_id), None)
    if entry is None:
        entry = {"id": clip_id, "label": label}
        manifest.append(entry)
    preserved = {key: value for key, value in entry.items() if key not in {"duration", "frames", "eye_positions", "body_extended"}}
    preserved["label"] = label or preserved.get("label") or clip_id
    preserved["duration"] = FRAME_MS
    preserved["frames"] = frames
    preserved["eye_positions"] = eyes
    if body_extended:
        preserved["body_extended"] = True
    elif "body_extended" in preserved and clip_id != "bed":
        preserved.pop("body_extended", None)
    index = manifest.index(entry) if entry in manifest else len(manifest) - 1
    manifest[index] = preserved
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def import_clip(video: Path, clip_id: str, label: str, output_name: str, body_extended: bool, write: bool) -> dict:
    with tempfile.TemporaryDirectory(prefix="tuanzi-key-") as temporary:
        sources = extract_frames(video, Path(temporary))
        if len(sources) < 8:
            raise SystemExit(f"{clip_id}: only {len(sources)} frames decoded")
        first = np.asarray(Image.open(sources[0]).convert("RGB"))
        last = np.asarray(Image.open(sources[-1]).convert("RGB"))
        seam = mean_abs(first, last)
        if seam < LOOP_DUPLICATE:
            sources = sources[:-1]
        keyed = []
        reports = []
        for path in sources:
            rgba = fit_canvas(key_rgb(np.asarray(Image.open(path).convert("RGB"))))
            report = quality(rgba)
            reports.append(report)
            if not acceptable(report):
                raise SystemExit(f"{clip_id}: frame {path.name} failed the matte check {report}")
            keyed.append(rgba)
    destination = ANIMATIONS / "frames" / output_name
    if write:
        if destination.exists():
            shutil.rmtree(destination)
        destination.mkdir(parents=True)
        names = []
        for index, rgba in enumerate(keyed):
            name = f"{index:03d}.png"
            Image.fromarray(rgba, "RGBA").save(destination / name, compress_level=9)
            names.append(f"frames/{output_name}/{name}")
        eyes = bake_eyes([destination / Path(name).name for name in names])
        update_manifest(clip_id, label, names, eyes, body_extended)
    summary = {
        "id": clip_id,
        "frames": len(keyed),
        "duration_ms": FRAME_MS,
        "cycle_ms": len(keyed) * FRAME_MS,
        "size": [reports[0]["width"], reports[0]["height"]],
        "opaque": round(sum(item["opaque"] for item in reports) / len(reports), 4),
        "spill_opaque": round(max(item["spill_opaque"] for item in reports), 3),
        "spill_edge": round(max(item["spill_edge"] for item in reports), 3),
        "loop_seam_mad": round(seam, 3),
        "dropped_duplicate_end": seam < LOOP_DUPLICATE,
        "usable": True,
    }
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--id", required=True)
    parser.add_argument("--label", default="")
    parser.add_argument("--output", help="Frame folder name under assets/animations/frames")
    parser.add_argument("--body-extended", action="store_true", help="Do not stretch the torso; use for the bed")
    parser.add_argument("--write", action="store_true", help="Write frames and point the manifest at them")
    args = parser.parse_args()
    if not args.video.is_file():
        raise SystemExit(f"Missing video: {args.video}")
    import_clip(args.video, args.id, args.label, args.output or args.id, args.body_extended, args.write)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
