# LUNA ZHOU, 2026-11-06: native, self-contained Windows/macOS builds.
import os
from pathlib import Path
import sys

ROOT = Path(SPECPATH).parent
sys.path.insert(0, str(ROOT))
from desktop_pet.resources import required_assets
from desktop_pet import __version__

stage = Path(os.environ["TUANZI_BUILD_STAGE"])
datas = [(str(path), str(path.relative_to(ROOT).parent)) for path in required_assets(ROOT)]
datas.append((str(stage / "runtime-assets.json"), "."))
datas.extend((str(path), str(path.relative_to(stage).parent))
             for path in (stage / "THIRD_PARTY_NOTICES").rglob("*") if path.is_file())
is_mac = sys.platform == "darwin"
icon = str(stage / ("tuanzi.icns" if is_mac else "tuanzi.ico"))

a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")], pathex=[str(ROOT)],
    binaries=[], datas=datas, hiddenimports=[], hookspath=[], hooksconfig={},
    runtime_hooks=[], excludes=["PyQt5", "PyQt6", "PySide2", "numpy", "cv2", "matplotlib"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True, name="Tuanzi", debug=False,
    strip=False, upx=False, console=bool(os.environ.get("TUANZI_BUILD_CONSOLE")), icon=icon,
    target_arch=os.environ.get("TUANZI_TARGET_ARCH") or None,
    codesign_identity=os.environ.get("TUANZI_CODESIGN_IDENTITY") or None,
)
collection = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="Tuanzi")
if is_mac:
    app = BUNDLE(
        collection, name="Tuanzi.app", icon=icon,
        bundle_identifier="com.lunazhou.tuanzipet",
        info_plist={
            "CFBundleDisplayName": "团子桌面宠物",
            "CFBundleShortVersionString": __version__, "CFBundleVersion": __version__,
            "LSMinimumSystemVersion": "14.0", "NSHighResolutionCapable": True,
            "LSUIElement": True, "LSApplicationCategoryType": "public.app-category.entertainment",
        },
    )
