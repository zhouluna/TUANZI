"""Enumerate only assets actually used by the shipped pet."""

import json
from pathlib import Path


def required_assets(root: Path) -> list[Path]:
    """Fail closed on missing files and paths escaping their manifest folder."""
    root = root.resolve()
    assets = root / "assets"
    required = {assets / "sprites" / "tuanzi-approved.png"}
    for relative, key in (("animations", "frames"), ("sleep-v2", "image")):
        # Keep logical bundle paths: macOS PyInstaller links Frameworks/assets
        # to Resources/assets. Resolve only when checking containment.
        folder = assets / relative
        manifest = folder / "manifest.json"
        required.add(manifest)
        entries = json.loads(manifest.read_text(encoding="utf-8"))
        if not isinstance(entries, list) or not entries:
            raise ValueError(f"Invalid asset manifest: {manifest}")
        for entry in entries:
            paths = entry[key] if key == "frames" else [entry[key]]
            if not isinstance(paths, list) or not paths:
                raise ValueError(f"Missing asset paths: {manifest}")
            for name in paths:
                if not isinstance(name, str) or not name:
                    raise ValueError(f"Invalid asset name: {manifest}")
                path = folder / name
                if not path.resolve().is_relative_to(folder.resolve()):
                    raise ValueError(f"Asset outside manifest directory: {name}")
                required.add(path)
    required.update(assets / "scenes" / "butterfly" / f"{index:02}.png" for index in range(8))
    for path in required:
        if not path.resolve().is_relative_to(assets.resolve()) or not path.is_file():
            raise ValueError(f"Missing or unsafe runtime asset: {path}")
    return sorted(required)
