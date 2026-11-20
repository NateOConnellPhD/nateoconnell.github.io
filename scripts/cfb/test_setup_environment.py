"""Offline checks for the disposable environment installer's archive boundary."""

import copy
import tarfile
import unittest
from unittest.mock import Mock, patch

import setup_environment as setup


def member(name, target=None):
    result = tarfile.TarInfo(name)
    if target is not None:
        result.type = tarfile.SYMTYPE
        result.linkname = target
    return result


class SetupTests(unittest.TestCase):
    def test_internal_runtime_symlink_allowed(self):
        setup.validate_members([member("python/bin/python3.12"), member("python/bin/python3", "python3.12")])

    def test_file_path_escape_rejected(self):
        for name in ("/tmp/file", "python/../../file", "elsewhere/file"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                setup.validate_members([member(name)])

    def test_link_escape_rejected(self):
        for target in ("../../../file", "/tmp/file"):
            with self.subTest(target=target), self.assertRaises(ValueError):
                setup.validate_members([member("python/lib/link", target)])

    def test_extraction_through_link_rejected(self):
        with self.assertRaises(ValueError):
            setup.validate_members([member("python/lib/link", "../bin"), member("python/lib/link/file")])

    def test_special_file_rejected(self):
        device = member("python/device")
        device.type = tarfile.CHRTYPE
        with self.assertRaises(ValueError):
            setup.validate_members([device])

    def test_asset_must_be_exact_architecture_with_digest(self):
        asset = {"name": "cpython-3.12.12+20251120-aarch64-apple-darwin-install_only_stripped.tar.gz",
                 "size": 30_000_000, "digest": "sha256:" + "0" * 64,
                 "browser_download_url": "https://github.com/astral-sh/python-build-standalone/releases/download/test/runtime.tar.gz"}
        self.assertEqual(setup.choose_asset({"assets": [asset]}), asset)
        for update in ({"digest": None}, {"size": 200_000_000},
                       {"browser_download_url": "https://example.com/runtime.tar.gz"},
                       {"name": asset["name"].replace("aarch64", "x86_64")}):
            with self.subTest(update=update), self.assertRaises(ValueError):
                setup.choose_asset({"assets": [dict(copy.deepcopy(asset), **update)]})

    def test_existing_task_directory_preserved_without_network(self):
        existing = Mock()
        existing.exists.return_value = True
        with patch.object(setup, "ROOT", existing), patch.object(setup, "request") as network, \
                patch.object(setup.platform, "system", return_value="Darwin"), \
                patch.object(setup.platform, "machine", return_value="arm64"):
            with self.assertRaisesRegex(RuntimeError, "Preserving existing files"):
                setup.main()
            network.assert_not_called()
            existing.mkdir.assert_not_called()


if __name__ == "__main__":
    unittest.main()
