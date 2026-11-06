"""Headless verification of the real bundled Qt runtime and asset payload."""

import hashlib
import json
from pathlib import Path
import platform
import sys

from PySide6.QtCore import qVersion
from PySide6.QtGui import QImage

from .resources import required_assets


def check_bundle(root: Path) -> dict:
    report = {"ok": False, "platform": sys.platform, "architecture": platform.machine(),
              "python": platform.python_version(), "qt": qVersion(), "errors": []}
    try:
        files = required_assets(root)
        index_path = root / "runtime-assets.json"
        expected = json.loads(index_path.read_text(encoding="utf-8")) if index_path.is_file() else None
        seen = set()
        for path in files:
            relative = path.relative_to(root).as_posix()
            seen.add(relative)
            if expected is not None:
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                if expected.get(relative) != digest:
                    report["errors"].append(f"Asset integrity mismatch: {relative}")
            if path.suffix.lower() == ".png" and QImage(str(path)).isNull():
                report["errors"].append(f"Image could not be decoded: {relative}")
        if expected is not None and set(expected) != seen:
            report["errors"].append("Asset index differs from the runtime manifests")
        report["asset_count"] = len(files)
        report["asset_bytes"] = sum(path.stat().st_size for path in files)
        report["integrity_index"] = expected is not None
        report["artwork_sha256"] = hashlib.sha256((root / "assets/sprites/tuanzi-approved.png").read_bytes()).hexdigest()
        report["actions"] = [entry["id"] for entry in json.loads((root / "assets/animations/manifest.json").read_text(encoding="utf-8"))]
        report["sleep_poses"] = [entry["id"] for entry in json.loads((root / "assets/sleep-v2/manifest.json").read_text(encoding="utf-8"))]
        report["ok"] = not report["errors"]
    except (OSError, ValueError, KeyError, TypeError) as error:
        report["errors"].append(str(error))
    return report
