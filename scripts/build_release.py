"""Build, self-check and archive a native desktop pet distribution.

LUNA ZHOU, 2026-11-06. Run on the OS for which the app is being built.
"""

import argparse
import hashlib
from importlib import metadata
import os
from pathlib import Path
import platform
import shutil
import struct
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from desktop_pet import __version__
from scripts.release_support import asset_index, build_environment, source_files, write_json, write_zip


def make_icons(stage: Path) -> None:
    from PySide6.QtCore import QBuffer, QIODevice, QRect, Qt
    from PySide6.QtGui import QGuiApplication, QImage, QPainter
    app = QGuiApplication.instance() or QGuiApplication([])
    source = QImage(str(ROOT / "assets/sprites/tuanzi-approved.png"))
    if source.isNull():
        raise ValueError("Approved icon artwork is missing")
    iconset = stage / "tuanzi.iconset"
    iconset.mkdir()
    pngs = {}
    for size in (16, 32, 64, 128, 256, 512, 1024):
        canvas = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
        canvas.fill(Qt.GlobalColor.transparent)
        image = source.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        painter = QPainter(canvas)
        painter.drawImage((size - image.width()) // 2, (size - image.height()) // 2, image)
        painter.end()
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        canvas.save(buffer, "PNG")
        pngs[size] = bytes(buffer.data())
        for logical in (16, 32, 128, 256, 512):
            if size == logical:
                canvas.save(str(iconset / f"icon_{logical}x{logical}.png"))
            if size == logical * 2:
                canvas.save(str(iconset / f"icon_{logical}x{logical}@2x.png"))
    sizes = (16, 32, 48, 64, 128, 256)
    # An ICO may contain PNG image entries, avoiding a Pillow build dependency.
    sizes = tuple(size for size in sizes if size in pngs)
    offset = 6 + 16 * len(sizes)
    directory, content = [], []
    for size in sizes:
        payload = pngs[size]
        directory.append(struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(payload), offset))
        content.append(payload)
        offset += len(payload)
    (stage / "tuanzi.ico").write_bytes(struct.pack("<HHH", 0, 1, len(sizes)) + b"".join(directory + content))
    if sys.platform == "darwin":
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(stage / "tuanzi.icns")], check=True)


def copy_notices(stage: Path) -> None:
    folder = stage / "THIRD_PARTY_NOTICES"
    folder.mkdir()
    license_file = Path(sys.base_prefix) / "LICENSE.txt"
    if not license_file.is_file():
        license_file = Path(sys.base_prefix) / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "LICENSE.txt"
    if license_file.is_file():
        shutil.copy2(license_file, folder / "Python-LICENSE.txt")
    for package in ("PySide6-Essentials", "shiboken6"):
        distribution = metadata.distribution(package)
        for entry in distribution.files or []:
            if "license" in str(entry).lower() and distribution.locate_file(entry).is_file():
                destination = folder / package / str(entry)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(distribution.locate_file(entry), destination)
    for path in (ROOT / "packaging/licenses").glob("*"):
        if path.is_file():
            shutil.copy2(path, folder / path.name)
    (folder / "NOTICE.txt").write_text(
        "Tuanzi Desktop Pet uses CPython, Qt/PySide6 and shiboken6.\n"
        "Qt/PySide6 upstream: https://code.qt.io/pyside/pyside-setup.git/\n"
        "Qt upstream: https://code.qt.io/qt/qtbase.git/\n"
        "Distributed Qt libraries remain dynamically linked and are not modified.\n"
        "See the accompanying upstream license texts and package metadata.\n", encoding="utf-8")


def native_executable(bundle: Path) -> Path:
    return bundle / "Contents/MacOS/Tuanzi" if sys.platform == "darwin" else bundle / "Tuanzi.exe"


def verify_bundle(bundle: Path, stage: Path) -> Path:
    report = stage / "self-check.json"
    environment = os.environ.copy()
    environment["TUANZI_DATA_DIR"] = str(stage / "verification-data")
    result = subprocess.run([str(native_executable(bundle)), "--self-check", "--report", str(report)],
                            env=environment, timeout=120, check=False)
    import json
    if result.returncode != 0 or not report.is_file() or not json.loads(report.read_text(encoding="utf-8"))["ok"]:
        raise RuntimeError(f"Bundled executable self-check failed; see {report}")
    return report


def install_mac(bundle: Path, launch: bool) -> Path:
    target = Path.home() / "Applications" / "Tuanzi.app"
    target.parent.mkdir(exist_ok=True)
    incoming = target.with_name(".Tuanzi-install-" + uuid.uuid4().hex + ".app")
    # ditto retains frameworks' symlinks, signatures and executable permissions.
    subprocess.run(["ditto", str(bundle), str(incoming)], check=True)
    backup = target.with_name("Tuanzi-Previous-" + time.strftime("%Y%m%d-%H%M%S") + ".app")
    if target.exists():
        old_exe = native_executable(target)
        if old_exe.is_file():
            subprocess.run([str(old_exe), "--quit"], check=False, timeout=15)
            time.sleep(.3)
        target.rename(backup)
    try:
        incoming.rename(target)
    except OSError:
        if backup.exists() and not target.exists():
            backup.rename(target)
        raise
    if launch:
        subprocess.run(["open", str(target)], check=True)
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-only", action="store_true", help="Export the one-click deployment source without a native build")
    parser.add_argument("--install", action="store_true", help="Install the built macOS app to ~/Applications")
    parser.add_argument("--launch", action="store_true", help="Launch after --install")
    options = parser.parse_args()
    if options.install and (sys.platform != "darwin" or options.source_only):
        parser.error("--install requires a native macOS build")
    if options.launch and not options.install:
        parser.error("--launch requires --install")
    release = ROOT / "release"
    release.mkdir(exist_ok=True)
    source_zip = release / f"Tuanzi-{__version__}-macos-one-click.zip"
    write_zip(source_zip, [(path, "Tuanzi-Mac-Setup/" + path.relative_to(ROOT).as_posix()) for path in source_files(ROOT)])
    print(f"One-click deployment source: {source_zip}", flush=True)
    if not options.source_only:
        if sys.platform not in ("win32", "darwin"):
            parser.error("Native build supports Windows and macOS")
        stage = ROOT / ".build" / ("release-" + uuid.uuid4().hex[:10])
        stage.mkdir(parents=True)
        write_json(stage / "runtime-assets.json", asset_index(ROOT))
        make_icons(stage)
        copy_notices(stage)
        environment = build_environment(stage)
        subprocess.run([sys.executable, "-I", "-m", "PyInstaller", "--noconfirm", "--distpath", str(ROOT / "dist"),
                        "--workpath", str(stage / "work"), str(ROOT / "packaging/tuanzi.spec")],
                       cwd=ROOT, env=environment, check=True)
        bundle = ROOT / "dist" / ("Tuanzi.app" if sys.platform == "darwin" else "Tuanzi")
        checked = verify_bundle(bundle, stage)
        architecture = "arm64" if platform.machine().lower() in ("arm64", "aarch64") else "x64"
        system = "macos" if sys.platform == "darwin" else "windows"
        label = f"Tuanzi-{__version__}-{system}-{architecture}"
        archive = release / (label + ".zip")
        if sys.platform == "darwin":
            subprocess.run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(bundle), str(archive)], check=True)
        else:
            (bundle / "一键启动.cmd").write_bytes(b'@echo off\r\nstart "" "%~dp0Tuanzi.exe"\r\n')
            (bundle / "创建桌面快捷方式.cmd").write_text(
                '@echo off\nset "TUANZI_INSTALL_ROOT=%~dp0"\n'
                'powershell.exe -NoProfile -Command "$w = New-Object -ComObject WScript.Shell; '
                '$s = $w.CreateShortcut((Join-Path ([Environment]::GetFolderPath(\'Desktop\')) \'Tuanzi.lnk\')); '
                '$s.TargetPath = Join-Path $env:TUANZI_INSTALL_ROOT \'Tuanzi.exe\'; '
                '$s.WorkingDirectory = $env:TUANZI_INSTALL_ROOT; $s.IconLocation = $s.TargetPath; $s.Save()"\n', encoding="ascii")
            (bundle / "使用说明.txt").write_text(
                "团子桌面宠物 1.0.0\n\n完整解压后，双击 Tuanzi.exe 或 一键启动.cmd。\n"
                "无需安装 Python，无需联网，无需管理员权限。整个文件夹请一起保留。\n"
                "可双击 创建桌面快捷方式.cmd 创建启动入口。右键团子可选择动作、睡姿、大小或退出。\n"
                "配置和日志位于用户本地数据目录 TuanziPet，不写入程序目录。\n", encoding="utf-8")
            write_zip(archive, [(path, "Tuanzi/" + path.relative_to(bundle).as_posix())
                                for path in sorted(bundle.rglob("*")) if path.is_file()])
        shutil.copy2(checked, release / (label + "-self-check.json"))
        write_json(release / (label + "-build.json"), {
            "version": __version__, "system": system, "architecture": architecture,
            "python": platform.python_version(), "pyinstaller": metadata.version("pyinstaller"),
            "PySide6-Essentials": metadata.version("PySide6-Essentials"), "asset_count": len(asset_index(ROOT)),
        })
        print(f"Native application: {archive}", flush=True)
        if options.install:
            print(f"Installed: {install_mac(bundle, options.launch)}", flush=True)
    checksums = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(release.glob("*.zip"))}
    (release / "SHA256SUMS.txt").write_text("".join(f"{digest}  {name}\n" for name, digest in checksums.items()), encoding="ascii")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
