"""Build smoother in-place action sequences from the sparse keyframes.

LUNA ZHOU, 2026-11-10.

The player keeps decoding PNG frames. This script only rewrites the
sequences it loads. It does not synthesize video at runtime and it does
not call a hosted model.

Keyframe copies live in ``assets/animations/keyframes/<id>/``. The first
run copies them out of the manifest before replacing playback frames.
Later runs always read that folder, so interpolation is not applied twice.

Examples
--------
python -m pip install -r requirements.txt -r scripts/requirements-interpolate.txt
python scripts/interpolate_actions.py --dry-run
python scripts/interpolate_actions.py
python scripts/interpolate_actions.py --clips groom groom_fur
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import urllib.request

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Qt reads the platform plugin when PySide6 is imported. Headless playback
# baking has no window, so select offscreen before that import.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from desktop_pet.animations import locate_eyes
from scripts.interpolate_plan import (
    choose_factor,
    frame_delay,
    loops_back_to_start,
    output_frame_count,
    UNCHANGED,
)

from PySide6.QtGui import QGuiApplication, QImage

ANIMATIONS = ROOT / "assets" / "animations"
KEYFRAMES = ANIMATIONS / "keyframes"
REPORT_PATH = ANIMATIONS / "interpolation.json"
ARCHIVE_PATH = KEYFRAMES / "original-entries.json"
MODEL_URL = "https://huggingface.co/edgetools/rife/resolve/main/rife49.onnx"
MODEL_SHA256 = "76e4cef9ab42fa7dd4e8f6e4aba47462051e3faa969e4bca6479784fbab0ac6f"
MODEL_NAME = "Practical-RIFE 4.9 (ONNX, MIT)"


def model_cache_path() -> Path:
    override = os.environ.get("TUANZI_RIFE_MODEL")
    if override:
        return Path(override)
    return Path.home() / ".cache" / "tuanzi" / "rife49.onnx"


def ensure_model(path: Path) -> Path:
    if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == MODEL_SHA256:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".partial")
    print(f"Downloading {MODEL_NAME}\n  {MODEL_URL}", flush=True)
    try:
        urllib.request.urlretrieve(MODEL_URL, temporary)
    except OSError as error:
        raise SystemExit(
            f"Could not download the interpolation model ({error}). "
            f"Place the ONNX file at {path} or pass --model. Expected sha256 {MODEL_SHA256}."
        ) from error
    digest = hashlib.sha256(temporary.read_bytes()).hexdigest()
    if digest != MODEL_SHA256:
        temporary.unlink(missing_ok=True)
        raise SystemExit(f"Model checksum mismatch: {digest}")
    temporary.replace(path)
    return path


def load_manifest() -> list[dict]:
    return json.loads((ANIMATIONS / "manifest.json").read_text(encoding="utf-8"))


def load_archive() -> dict:
    if not ARCHIVE_PATH.is_file():
        return {}
    data = json.loads(ARCHIVE_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit(f"Invalid keyframe archive: {ARCHIVE_PATH}")
    return data


def save_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def keyframe_paths(clip_id: str, entry: dict, archive: dict) -> list[Path]:
    """Return the sparse source frames, copying them aside on the first run."""
    folder = KEYFRAMES / clip_id
    stored = sorted(folder.glob("*.png"), key=lambda path: int(path.stem)) if folder.is_dir() else []
    if stored:
        if clip_id not in archive:
            raise SystemExit(f"{clip_id}: keyframes exist but {ARCHIVE_PATH.name} has no original entry")
        expected = len(archive[clip_id]["frames"])
        if len(stored) != expected:
            raise SystemExit(f"{clip_id}: found {len(stored)} keyframes, archive expects {expected}")
        return stored
    folder.mkdir(parents=True, exist_ok=True)
    copied = []
    for index, relative in enumerate(entry["frames"]):
        source = ANIMATIONS / relative
        if not source.is_file():
            raise SystemExit(f"Missing source frame: {source}")
        destination = folder / f"{index:02d}.png"
        destination.write_bytes(source.read_bytes())
        copied.append(destination)
    archive[clip_id] = json.loads(json.dumps(entry))
    save_json(ARCHIVE_PATH, archive)
    return copied


def read_rgba(path: Path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("RGBA"))


def pad_to_multiple(chw: np.ndarray, multiple: int = 32) -> tuple[np.ndarray, int, int]:
    _channels, height, width = chw.shape
    pad_h = (multiple - height % multiple) % multiple
    pad_w = (multiple - width % multiple) % multiple
    if pad_h or pad_w:
        chw = np.pad(chw, ((0, 0), (0, pad_h), (0, pad_w)))
    return np.ascontiguousarray(chw, dtype=np.float32), height, width


def run_rife(session, left: np.ndarray, right: np.ndarray, timestep: float) -> np.ndarray:
    def pack(image: np.ndarray) -> tuple[np.ndarray, int, int]:
        chw, height, width = pad_to_multiple(np.transpose(image, (2, 0, 1)))
        return chw[None], height, width

    left_batch, height, width = pack(left)
    right_batch, _, _ = pack(right)
    output = session.run(None, {
        "img0": left_batch,
        "img1": right_batch,
        "timestep": np.array([timestep], dtype=np.float32),
    })[0]
    return np.transpose(output[0, :, :height, :width], (1, 2, 0))


def synthesize(session, left: np.ndarray, right: np.ndarray, timestep: float) -> np.ndarray:
    """Interpolate premultiplied color and alpha, then restore straight alpha."""
    left_alpha = left[:, :, 3:4].astype(np.float32) / 255.0
    right_alpha = right[:, :, 3:4].astype(np.float32) / 255.0
    left_rgb = left[:, :, :3].astype(np.float32) / 255.0 * left_alpha
    right_rgb = right[:, :, :3].astype(np.float32) / 255.0 * right_alpha
    color = np.clip(run_rife(session, left_rgb, right_rgb, timestep), 0.0, 1.0)
    alpha_image = np.clip(run_rife(session, np.repeat(left_alpha, 3, axis=2), np.repeat(right_alpha, 3, axis=2), timestep), 0.0, 1.0)
    alpha = np.clip(alpha_image.mean(axis=2), 0.0, 1.0)
    straight = np.zeros_like(color)
    visible = alpha > (4.0 / 255.0)
    straight[visible] = np.clip(color[visible] / alpha[visible, None], 0.0, 1.0)
    frame = np.zeros((*alpha.shape, 4), dtype=np.uint8)
    frame[:, :, :3] = np.round(straight * 255.0)
    frame[:, :, 3] = np.round(alpha * 255.0)
    frame[:, :, 3][frame[:, :, 3] < 4] = 0
    frame[:, :, :3][frame[:, :, 3] == 0] = 0
    for y, x in ((0, 0), (0, -1), (-1, 0), (-1, -1)):
        if left[y, x, 3] == 0 and right[y, x, 3] == 0 and frame[y, x, 3] <= 40:
            frame[y, x] = 0
    return frame


def coverage(image: np.ndarray, threshold: int = 128) -> float:
    return float(np.mean(image[:, :, 3] > threshold))


def partial_ratio(image: np.ndarray) -> float:
    alpha = image[:, :, 3]
    return float(np.mean((alpha > 16) & (alpha < 240)))


def linear_partial_ratio(left: np.ndarray, right: np.ndarray) -> float:
    alpha = (left[:, :, 3].astype(np.float32) + right[:, :, 3].astype(np.float32)) * 0.5
    return float(np.mean((alpha > 16.0) & (alpha < 240.0)))


def quality_problem(mid: np.ndarray, left: np.ndarray, right: np.ndarray) -> str:
    """Reject double exposures. A moved paw should not leave both poses on screen."""
    if mid.shape != left.shape:
        return "shape"
    if int(mid[0, 0, 3]) > 40 or int(mid[-1, -1, 3]) > 40:
        return "corner"
    cov0, cov1, cov_mid = coverage(left), coverage(right), coverage(mid)
    union = float(np.mean((left[:, :, 3] > 128) | (right[:, :, 3] > 128)))
    if union > max(cov0, cov1) + 0.05 and cov_mid > max(cov0, cov1) + 0.045 and cov_mid > union * 0.82:
        return "double-exposure"
    partial_mid = partial_ratio(mid)
    if partial_mid > 0.07 and partial_mid > max(partial_ratio(left), partial_ratio(right)) + 0.035 and partial_mid > linear_partial_ratio(left, right) * 0.55:
        return "ghost-alpha"
    return ""


def relative_to_animations(path: Path) -> str:
    return path.resolve().relative_to(ANIMATIONS.resolve()).as_posix()


def clear_playback_frames(clip_id: str) -> None:
    folder = ANIMATIONS / "frames" / clip_id
    if not folder.is_dir():
        return
    for path in folder.glob("*.png"):
        path.unlink()


def write_frame(path: Path, image: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(image, "RGBA").save(path, compress_level=9)


def open_session(model: Path):
    import onnxruntime as ort

    options = ort.SessionOptions()
    options.intra_op_num_threads = os.cpu_count() or 1
    options.inter_op_num_threads = 1
    return ort.InferenceSession(str(model), sess_options=options, providers=["CPUExecutionProvider"])


def interpolate_clip(session, clip_id: str, entry: dict, keys: list[Path], reject_dir: Path | None) -> dict:
    loop = loops_back_to_start(clip_id)
    original_count = len(keys)
    if original_count != len(entry["frames"]):
        raise SystemExit(f"{clip_id}: {original_count} keyframe files, archive lists {len(entry['frames'])}")
    original_delay = int(entry["duration"])
    factor = choose_factor(original_delay)
    delay = frame_delay(original_delay, factor)
    pictures = [read_rgba(path) for path in keys]
    playback: list[str] = []
    rejected: list[dict] = []
    partials: list[float] = []
    ordinal = 0
    gaps = original_count if loop else original_count - 1

    def add_key(index: int) -> None:
        playback.append(relative_to_animations(keys[index]))

    def add_between(start: int, end: int) -> None:
        nonlocal ordinal
        for step in range(1, factor):
            timestep = step / factor
            mid = synthesize(session, pictures[start], pictures[end], timestep)
            problem = quality_problem(mid, pictures[start], pictures[end])
            partials.append(partial_ratio(mid))
            if problem:
                fallback = start if timestep < 0.5 else end
                if reject_dir is not None:
                    reject_dir.mkdir(parents=True, exist_ok=True)
                    write_frame(reject_dir / f"{clip_id}-{start:02d}-{end:02d}-{step}.png", mid)
                mid = pictures[fallback]
                rejected.append({"from": start, "to": end, "step": step, "reason": problem})
            destination = ANIMATIONS / "frames" / clip_id / f"{ordinal:03d}.png"
            write_frame(destination, mid)
            playback.append(relative_to_animations(destination))
            ordinal += 1

    for index in range(gaps):
        add_key(index)
        add_between(index, (index + 1) % original_count)
    if not loop:
        for _ in range(factor):
            add_key(original_count - 1)
    expected = output_frame_count(original_count, factor)
    if len(playback) != expected or len(playback) * delay != original_count * original_delay:
        raise RuntimeError(f"{clip_id}: expected {expected} frames and the original cycle, built {len(playback)}")
    return {
        "id": clip_id,
        "loop": loop,
        "factor": factor,
        "before": {"frames": original_count, "duration_ms": original_delay, "cycle_ms": original_count * original_delay},
        "after": {"frames": len(playback), "duration_ms": delay, "cycle_ms": len(playback) * delay},
        "playback": playback,
        "rejected": rejected,
        "max_partial_alpha": max(partials) if partials else 0.0,
    }


def original_entry(clip_id: str, entry: dict, archive: dict) -> dict:
    stored = archive.get(clip_id)
    return stored if isinstance(stored, dict) else entry


def bake_eyes(paths: list[str]) -> list[list[list[float]]]:
    if QGuiApplication.instance() is None:
        QGuiApplication([])
    cache = {}
    baked = []
    for relative in paths:
        if relative not in cache:
            image = QImage(str(ANIMATIONS / relative))
            if image.isNull():
                raise SystemExit(f"Could not read frame while baking eyes: {relative}")
            cache[relative] = [[round(float(part), 4) for part in eye] for eye in locate_eyes(image)]
        baked.append(cache[relative])
    return baked


def apply_result(entry: dict, result: dict, eyes: list) -> dict:
    updated = {key: value for key, value in entry.items() if key not in {"source_bounds", "eye_positions"}}
    updated["duration"] = result["after"]["duration_ms"]
    updated["frames"] = result["playback"]
    updated["eye_positions"] = eyes
    return updated


def public_result(result: dict) -> dict:
    return {
        "loop": result["loop"],
        "factor": result["factor"],
        "before": result["before"],
        "after": result["after"],
        "rejected_frames": len(result["rejected"]),
        "rejected": result["rejected"],
        "max_partial_alpha": round(result["max_partial_alpha"], 5),
    }


def selected_entries(manifest: list[dict], clips: set[str] | None) -> list[dict]:
    chosen = []
    for entry in manifest:
        clip_id = entry["id"]
        if clip_id in UNCHANGED:
            continue
        if clips is not None and clip_id not in clips:
            continue
        chosen.append(entry)
    if clips is not None:
        found = {entry["id"] for entry in chosen}
        missing = clips - found - set(UNCHANGED)
        if missing:
            raise SystemExit(f"Unknown clip id: {', '.join(sorted(missing))}")
    return chosen


def dry_run(manifest: list[dict], clips: set[str] | None) -> None:
    archive = load_archive()
    print(f"{'clip':<12} {'loop':<6} {'before':<16} {'after':<16} cycle")
    for entry in manifest:
        clip_id = entry["id"]
        if clip_id in UNCHANGED:
            if clips is None or clip_id in clips:
                print(f"{clip_id:<12} skip   {UNCHANGED[clip_id]}")
            continue
        if clips is not None and clip_id not in clips:
            continue
        source = original_entry(clip_id, entry, archive)
        count = len(source["frames"])
        duration = int(source["duration"])
        factor = choose_factor(duration)
        delay = frame_delay(duration, factor)
        total = output_frame_count(count, factor)
        print(f"{clip_id:<12} {str(loops_back_to_start(clip_id)):<6} {count}×{duration} ms{'':<6} {total}×{delay} ms{'':<5} {count * duration} ms")


def interpolate(clips: set[str] | None, model: Path, reject_dir: Path | None) -> dict:
    manifest = load_manifest()
    archive = load_archive()
    session = open_session(model)
    results = {}
    by_id = {entry["id"]: entry for entry in manifest}
    for entry in selected_entries(manifest, clips):
        clip_id = entry["id"]
        source = original_entry(clip_id, entry, archive)
        keys = keyframe_paths(clip_id, source, archive)
        archive = load_archive()
        clear_playback_frames(clip_id)
        print(f"Interpolating {clip_id} ({len(keys)} keyframes)...", flush=True)
        result = interpolate_clip(session, clip_id, source, keys, reject_dir)
        eyes = bake_eyes(result["playback"])
        by_id[clip_id] = apply_result(source if clip_id in archive else entry, result, eyes)
        # Preserve fields from the archived original (label, description) and
        # drop playback-only keys that belonged to a previous dense manifest.
        results[clip_id] = public_result(result)
        print(
            f"  {result['before']['frames']}×{result['before']['duration_ms']} ms -> "
            f"{result['after']['frames']}×{result['after']['duration_ms']} ms, "
            f"rejected {len(result['rejected'])}, max partial alpha {result['max_partial_alpha']:.4f}",
            flush=True,
        )
    updated = [by_id[entry["id"]] for entry in manifest]
    save_json(ANIMATIONS / "manifest.json", updated)
    report = {}
    if REPORT_PATH.is_file() and clips is not None:
        previous = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
        if isinstance(previous.get("clips"), dict):
            report = previous["clips"]
    report.update(results)
    save_json(REPORT_PATH, {
        "model": {"name": MODEL_NAME, "url": MODEL_URL, "sha256": MODEL_SHA256},
        "delay_policy_ms": {"min": 20, "max": 40, "target": 30},
        "unchanged": UNCHANGED,
        "clips": report,
    })
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clips", nargs="*", help="Clip ids to rebuild. Default: every sparse in-place clip.")
    parser.add_argument("--dry-run", action="store_true", help="Print the timing plan and write nothing")
    parser.add_argument("--model", type=Path, help="RIFE ONNX file. Defaults to the cache, downloading if needed.")
    parser.add_argument("--reject-dir", type=Path, help="Where to save frames that failed the ghost check")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    clips = set(args.clips) if args.clips else None
    if args.dry_run:
        dry_run(load_manifest(), clips)
        return 0
    model = args.model if args.model else ensure_model(model_cache_path())
    if not model.is_file():
        raise SystemExit(f"Model not found: {model}")
    digest = hashlib.sha256(model.read_bytes()).hexdigest()
    if digest != MODEL_SHA256:
        raise SystemExit(f"Refusing model {model}: sha256 {digest}, expected {MODEL_SHA256}")
    interpolate(clips, model, args.reject_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
