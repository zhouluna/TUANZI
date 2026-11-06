"""Small deterministic helpers for release payloads and source export.

LUNA ZHOU, 2026-11-06.
"""

import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import zipfile

from desktop_pet.resources import required_assets


def build_environment(stage: Path) -> dict[str, str]:
    environment = os.environ.copy()
    environment["TUANZI_BUILD_STAGE"] = str(stage)
    environment["PYINSTALLER_CONFIG_DIR"] = str(stage.parent / "pyinstaller-cache")
    for key in ("QT_PLUGIN_PATH", "QML2_IMPORT_PATH", "PYTHONPATH", "PYTHONHOME"):
        environment.pop(key, None)
    environment.pop("TUANZI_BUILD_CONSOLE", None)
    if sys.platform == "win32":
        # Qt uses the Windows system ICU. Unrelated image/PDF tools on PATH
        # can otherwise make PyInstaller collect an incompatible ICU DLL.
        windows = Path(environment.get("SystemRoot", r"C:\Windows"))
        environment["PATH"] = os.pathsep.join(str(path) for path in (
            Path(sys.executable).parent, Path(sys.base_prefix), windows / "System32", windows))
    return environment


def asset_index(root: Path) -> dict[str, str]:
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in required_assets(root)}


def source_files(root: Path) -> list[Path]:
    root = root.resolve()
    files = set(required_assets(root))
    for folder, extensions in (("desktop_pet", {".py"}), ("tests", {".py"}), (".github/workflows", {".yml", ".yaml"}),
                               ("docs/images", {".png", ".gif"})):
        for path in (root / folder).rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix in extensions:
                files.add(path)
    for name in ("requirements-build.txt", "launcher.py", "tuanzi.spec", "uv-macos.env"):
        path = root / "packaging" / name
        if path.is_file():
            files.add(path)
    files.update(path for path in (root / "packaging/licenses").glob("*.txt") if path.is_file())
    for name in ("README.md", "DEPLOY.md", "requirements.txt", "start-pet.cmd", "setup-pet.cmd",
                 "build-windows.cmd", "deploy-macos.command", "scripts/build_release.py",
                 "scripts/release_support.py", "scripts/verify_release.py"):
        path = root / name
        if path.is_file():
            files.add(path)
    for path in files:
        if not path.resolve().is_relative_to(root):
            raise ValueError(f"Release source escapes project: {path}")
    return sorted(files)


def write_zip(destination: Path, entries: list[tuple[Path, str]]) -> None:
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path, name in entries:
            if Path(name).is_absolute() or ".." in Path(name).parts:
                raise ValueError("Unsafe archive name")
            executable = path.suffix == ".command"
            info = zipfile.ZipInfo(name.replace("\\", "/"))
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | (0o755 if executable else 0o644)) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            data = path.read_bytes()
            if executable:
                data = data.replace(b"\r\n", b"\n")
            archive.writestr(info, data)
    temporary.replace(destination)


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
