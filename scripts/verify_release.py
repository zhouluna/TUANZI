"""Exercise the shipped executable from an isolated, unrelated directory.

LUNA ZHOU, 2026-11-06. The running development pet and its settings are untouched.
"""

import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from desktop_pet import __version__


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, help="Extract and test an actual Windows ZIP")
    parser.add_argument("--visible", action="store_true", help="Use the real desktop instead of Qt offscreen")
    options = parser.parse_args()
    architecture = "arm64" if platform.machine().lower() in ("arm64", "aarch64") else "x64"
    system = "macos" if sys.platform == "darwin" else "windows"
    label = f"Tuanzi-{__version__}-{system}-{architecture}"
    states = []
    with tempfile.TemporaryDirectory(prefix="Tuanzi-verify-") as temporary:
        work = Path(temporary) / "移动后的目录 with spaces"
        work.mkdir()
        if options.archive:
            if sys.platform != "win32":
                parser.error("--archive currently validates Windows ZIPs")
            with zipfile.ZipFile(options.archive) as archive:
                if archive.testzip():
                    raise ValueError("Release ZIP failed CRC validation")
                for name in archive.namelist():
                    if not (work / name).resolve().is_relative_to(work.resolve()):
                        raise ValueError("Unsafe release archive path")
                archive.extractall(work)
            executable = work / "Tuanzi/Tuanzi.exe"
        else:
            executable = ROOT / "dist" / ("Tuanzi.app/Contents/MacOS/Tuanzi" if sys.platform == "darwin" else "Tuanzi/Tuanzi.exe")
        if not executable.is_file():
            raise FileNotFoundError(executable)
        environment = os.environ.copy()
        environment["TUANZI_DATA_DIR"] = str(work / "user-data")
        for key in ("PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV", "QT_PLUGIN_PATH", "QML2_IMPORT_PATH"):
            environment.pop(key, None)
        if options.visible:
            environment.pop("QT_QPA_PLATFORM", None)
        else:
            environment["QT_QPA_PLATFORM"] = "offscreen"
        sequence = 0

        def invoke(*arguments):
            nonlocal sequence
            sequence += 1
            report = work / f"reply-{sequence}.json"
            result = subprocess.run([str(executable), *arguments, "--report", str(report)],
                                    cwd=work, env=environment, timeout=25, check=False)
            if report.is_file():
                try:
                    value = json.loads(report.read_text(encoding="utf-8"))
                except ValueError:
                    return None
                if result.returncode == 0:
                    return value
            return None

        check = invoke("--self-check")
        if check is None or not check.get("ok") or not check.get("integrity_index"):
            raise RuntimeError("Relocated bundle integrity/Qt check failed")
        process = subprocess.Popen([str(executable)], cwd=work, env=environment)
        try:
            deadline = time.monotonic() + 90
            status = None
            while time.monotonic() < deadline and process.poll() is None:
                status = invoke("--status")
                if status and status.get("running"):
                    break
                time.sleep(.25)
            if not status or not status.get("running"):
                raise RuntimeError("Bundled app failed to start")
            states.append(status)
            original_pid = status["pid"]
            for action in ("bed-belly", "bed-buried", "bed-side", "bed-curled"):
                status = invoke("--action", action)
                if status is None or status.get("sleep_pose") != action[4:]:
                    raise RuntimeError(f"Bundled sleep action failed: {action}")
                states.append(status)
            paused = invoke("--action", "pause")
            time.sleep(.25)
            held = invoke("--status")
            if paused is None or held is None or held["rest_elapsed"] != paused["rest_elapsed"]:
                raise RuntimeError("Pause did not hold the real bundled animation")
            invoke("--action", "pause")
            for action in ("groom", "groom_fur", "walk", "run", "butterfly"):
                status = invoke("--action", action)
                if status is None or status["motion"] != action:
                    raise RuntimeError(f"Bundled action failed: {action}")
                states.append(status)
            invoke("--action", "bed-belly")
            time.sleep(.2)
            invoke("--action", "snapshot")
            screenshot = work / "user-data/render-preview.png"
            if not screenshot.is_file():
                raise RuntimeError("Bundled QWidget render preview was not created")
            shutil.copy2(screenshot, ROOT / "release" / (label + "-preview.png"))
            revealed = invoke()
            if revealed is None or revealed["pid"] != original_pid:
                raise RuntimeError("Repeated launch did not reuse the existing instance")
            invoke("--quit")
            process.wait(timeout=10)
            persisted = json.loads((work / "user-data/settings.json").read_text(encoding="utf-8"))
            if "size" not in persisted:
                raise RuntimeError("Packaged settings were not saved")
            report = {"ok": True, "system": system, "architecture": architecture,
                      "relocated_zip": bool(options.archive), "isolated_user_data": True,
                      "native_desktop": options.visible, "qt_self_check": check,
                      "single_instance": True, "pause": True, "settings_saved": True,
                      "states": states}
            (ROOT / "release" / (label + "-launch-check.json")).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps({"ok": True, "actions_checked": len(states) - 1, "system": system, "relocated_zip": bool(options.archive)}), flush=True)
        finally:
            if process.poll() is None:
                invoke("--quit")
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    process.wait(timeout=10)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
