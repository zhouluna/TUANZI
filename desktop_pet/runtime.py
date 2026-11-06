"""Resource and writable-data paths for source, Windows and macOS bundles.

LUNA ZHOU, 2026-11-06: keep user files outside installed application bundles.
"""

import getpass
import hashlib
import os
from pathlib import Path
import sys

from PySide6.QtCore import QStandardPaths


def resource_directory() -> Path:
    # PyInstaller preserves __file__ inside its private resource directory.
    return Path(__file__).resolve().parent.parent


def data_directory() -> Path:
    override = os.environ.get("TUANZI_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    if not getattr(sys, "frozen", False):
        return resource_directory() / ".local"
    location = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.GenericDataLocation)
    if not location:
        raise RuntimeError("系统未提供可写的用户数据目录")
    return Path(location) / "TuanziPet"


def instance_server_name(resources: Path, data: Path, *, frozen: bool | None = None) -> str:
    packaged = getattr(sys, "frozen", False) if frozen is None else frozen
    # Copies/upgrades of an installed app share one instance. Source checkouts
    # retain their prior endpoint; Finder launches need no controlling terminal.
    identity = data.resolve() if packaged else resources.resolve()
    try:
        user = getpass.getuser()
    except (OSError, KeyError):
        user = str(Path.home())
    digest = hashlib.sha256((str(identity) + "|" + user).encode()).hexdigest()[:16]
    return "TuanziRealisticDesktopPet-" + digest
