"""Release regressions: readonly bundles, private data and native asset paths."""

import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from PySide6.QtGui import QGuiApplication, QImage

from desktop_pet import runtime
from desktop_pet.diagnostics import check_bundle
from desktop_pet.resources import required_assets
from scripts.release_support import asset_index, build_environment, source_files, write_zip


def make_project(root):
    files = ["sprites/tuanzi-approved.png", "animations/frames/00.png", "sleep-v2/buried.png"]
    files += [f"scenes/butterfly/{index:02}.png" for index in range(8)]
    for name in files:
        path = root / "assets" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        image = QImage(16, 16, QImage.Format.Format_RGBA8888)
        image.fill(0xFFFFFFFF)
        image.save(str(path))
    (root / "assets/animations/manifest.json").write_text(json.dumps([{"id": "walk", "frames": ["frames/00.png"]}]), encoding="utf-8")
    (root / "assets/sleep-v2/manifest.json").write_text(json.dumps([{"id": "buried", "image": "buried.png"}]), encoding="utf-8")


class DeploymentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QGuiApplication.instance() or QGuiApplication([])

    def test_user_data_separate_from_resources(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            resources, user = root / "Readonly.app/Contents/Frameworks", root / "User Data"
            with patch.dict(os.environ, {"TUANZI_DATA_DIR": ""}), patch.object(runtime, "resource_directory", return_value=resources):
                with patch.object(sys, "frozen", False, create=True):
                    self.assertEqual(runtime.data_directory(), resources / ".local")
                with patch.object(sys, "frozen", True, create=True), patch.object(runtime.QStandardPaths, "writableLocation", return_value=str(user)):
                    self.assertEqual(runtime.data_directory(), user / "TuanziPet")
                    self.assertFalse(runtime.data_directory().is_relative_to(resources))
                    self.assertFalse(resources.exists())
                override = root / "移动后的目录" / "isolated data"
                with patch.dict(os.environ, {"TUANZI_DATA_DIR": str(override)}):
                    self.assertEqual(runtime.data_directory(), override)

    def test_windows_build_ignores_unrelated_native_tool_dlls(self):
        with patch.dict(os.environ, {"PATH": "unrelated-pdf-tools;unrelated-qt-tools", "QT_PLUGIN_PATH": "foreign-plugins", "PYTHONPATH": "foreign-python"}), patch.object(sys, "platform", "win32"):
            environment = build_environment(Path("staging"))
            self.assertNotIn("unrelated-pdf-tools", environment["PATH"])
            self.assertNotIn("unrelated-qt-tools", environment["PATH"])
            self.assertIn(str(Path(sys.base_prefix)), environment["PATH"])
            self.assertIn("System32", environment["PATH"])
            self.assertNotIn("QT_PLUGIN_PATH", environment)
            self.assertNotIn("PYTHONPATH", environment)
            self.assertEqual(os.environ["QT_PLUGIN_PATH"], "foreign-plugins")

    def test_frozen_instance_identity_survives_app_relocation(self):
        first, second, data = Path("first-copy"), Path("moved-copy"), Path("user-data")
        with patch.object(runtime.getpass, "getuser", return_value="alice"), patch.object(os, "getlogin", side_effect=OSError("no terminal")):
            original = runtime.instance_server_name(first, data, frozen=True)
            self.assertEqual(original, runtime.instance_server_name(second, data, frozen=True))
            self.assertNotEqual(original, runtime.instance_server_name(first, Path("other-user-data"), frozen=True))
            self.assertNotEqual(runtime.instance_server_name(first, data, frozen=False), runtime.instance_server_name(second, data, frozen=False))
        with patch.object(runtime.getpass, "getuser", return_value="bob"):
            self.assertNotEqual(original, runtime.instance_server_name(first, data, frozen=True))

    def test_runtime_asset_paths_keep_mac_bundle_links(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            physical, logical = base / "Resources", base / "Frameworks"
            make_project(physical)
            logical.mkdir()
            link, target = logical / "assets", physical / "assets"
            if os.name == "nt":
                result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)
            else:
                link.symlink_to(target, target_is_directory=True)
            files = required_assets(logical)
            self.assertEqual(len(files), 13)
            self.assertTrue(all(path.is_relative_to(logical) for path in files))
            self.assertTrue(all(path.is_file() for path in files))
            self.assertEqual(set(asset_index(logical)), {path.relative_to(physical).as_posix() for path in required_assets(physical)})

    def test_missing_and_escaping_assets_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            make_project(root)
            manifest = root / "assets/animations/manifest.json"
            original = manifest.read_text(encoding="utf-8")
            manifest.write_text(json.dumps([{"id": "walk", "frames": ["../../private.png"]}]), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "outside manifest"):
                required_assets(root)
            manifest.write_text(original, encoding="utf-8")
            (root / "assets/scenes/butterfly/03.png").unlink()
            with self.assertRaisesRegex(ValueError, "Missing or unsafe"):
                required_assets(root)

    def test_bundle_self_check_detects_tampering(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            make_project(root)
            (root / "runtime-assets.json").write_text(json.dumps(asset_index(root)), encoding="utf-8")
            good = check_bundle(root)
            self.assertTrue(good["ok"], good["errors"])
            self.assertTrue(good["integrity_index"])
            self.assertEqual(good["actions"], ["walk"])
            self.assertEqual(good["sleep_poses"], ["buried"])
            image = QImage(20, 20, QImage.Format.Format_RGBA8888)
            image.fill(0xFF008800)
            changed = root / "assets/sprites/tuanzi-approved.png"
            image.save(str(changed))
            altered = check_bundle(root)
            self.assertFalse(altered["ok"])
            self.assertIn("Asset integrity mismatch: assets/sprites/tuanzi-approved.png", altered["errors"])
            changed.write_bytes(b"not an image")
            broken = check_bundle(root)
            self.assertFalse(broken["ok"])
            self.assertIn("Image could not be decoded: assets/sprites/tuanzi-approved.png", broken["errors"])

    def test_source_export_excludes_private_and_preview_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            make_project(root)
            for name in (".local/settings.json", ".git/config", "previews/wardrobe-v1/01.png",
                         "node_modules/private.js", "packaging/private-key.pem", "desktop_pet/.env",
                         "desktop_pet/__pycache__/cached.py", "README.md", "packaging/uv-macos.env", "desktop_pet/runtime.py"):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("example", encoding="utf-8")
            launcher = root / "deploy-macos.command"
            launcher.write_bytes(b"#!/bin/bash\r\necho Tuanzi\r\n")
            members = source_files(root)
            relative = {path.relative_to(root).as_posix() for path in members}
            self.assertIn("deploy-macos.command", relative)
            self.assertIn("packaging/uv-macos.env", relative)
            self.assertIn("desktop_pet/runtime.py", relative)
            self.assertFalse(any(name.startswith((".local/", ".git/", "previews/", "node_modules/")) for name in relative))
            self.assertNotIn("packaging/private-key.pem", relative)
            self.assertNotIn("desktop_pet/.env", relative)
            self.assertFalse(any("__pycache__" in name for name in relative))
            archive = root / "deploy.zip"
            write_zip(archive, [(path, "Tuanzi/" + path.relative_to(root).as_posix()) for path in members])
            with zipfile.ZipFile(archive) as exported:
                entry = exported.getinfo("Tuanzi/deploy-macos.command")
                self.assertEqual(stat.S_IMODE(entry.external_attr >> 16), 0o755)
                self.assertNotIn(b"\r", exported.read(entry))
                self.assertEqual({name.removeprefix("Tuanzi/") for name in exported.namelist()}, relative)
            with self.assertRaisesRegex(ValueError, "Unsafe archive name"):
                write_zip(root / "unsafe.zip", [(launcher, "../escape.command")])


if __name__ == "__main__":
    unittest.main()
