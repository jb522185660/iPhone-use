import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("iphone_use_install_plugin", ROOT / "scripts/install_plugin.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class PluginInstallTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="iphone use upgrade ")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        self.home = self.root / "custom codex home"
        env = patch.dict(os.environ, {"CODEX_HOME": str(self.home)})
        env.start()
        self.addCleanup(env.stop)
        self.cache = installer.cache_directory()

    def package(self, version, content="old runtime", name="iphone-use"):
        root = self.cache / version
        (root / "server").mkdir(parents=True, exist_ok=True)
        (root / "plugin.json").write_text(json.dumps({"name": name, "version": version}))
        (root / "server/iphone_use.py").write_text(content)
        (root / "server/iphone_use.py").chmod(0o750)
        return root

    def test_upgrade_restores_removed_versions_and_preserves_new_package_and_modes(self):
        old = self.package("0.3.15")
        previous = self.package("0.4.0", "previous runtime")
        unrelated = self.home / "plugins/cache/another-market/another-plugin/1.0.0/file"
        unrelated.parent.mkdir(parents=True)
        unrelated.write_text("unrelated")

        def upgrade(*args, **kwargs):
            shutil.rmtree(self.cache)
            self.package("0.4.1", "new runtime")
            return Mock(returncode=0)

        with patch.object(installer.subprocess, "run", side_effect=upgrade) as run:
            self.assertEqual(installer.install_plugin(), 0)
        run.assert_called_once_with(["codex", "plugin", "add", "iphone-use@iphone-use-local", "--json"], check=False)
        self.assertEqual((old / "server/iphone_use.py").read_text(), "old runtime")
        self.assertEqual((previous / "server/iphone_use.py").read_text(), "previous runtime")
        self.assertEqual((old / "server/iphone_use.py").stat().st_mode & 0o777, 0o750)
        self.assertEqual((self.cache / "0.4.1/server/iphone_use.py").read_text(), "new runtime")
        self.assertEqual(unrelated.read_text(), "unrelated")

    def test_same_version_replacement_is_not_overwritten(self):
        current = self.package("0.4.1")

        def upgrade(*args, **kwargs):
            shutil.rmtree(current)
            self.package("0.4.1", "updated same version")
            return Mock(returncode=0)

        with patch.object(installer.subprocess, "run", side_effect=upgrade):
            self.assertEqual(installer.install_plugin(), 0)
        self.assertEqual((current / "server/iphone_use.py").read_text(), "updated same version")

    def test_failed_install_restores_cache_and_returns_failure_status(self):
        old = self.package("0.4.0")

        def failed(*args, **kwargs):
            shutil.rmtree(self.cache)
            return Mock(returncode=9)

        with patch.object(installer.subprocess, "run", side_effect=failed):
            self.assertEqual(installer.install_plugin(), 9)
        self.assertEqual((old / "server/iphone_use.py").read_text(), "old runtime")

    def test_interrupted_install_also_restores_cache(self):
        old = self.package("0.4.0")

        def interrupted(*args, **kwargs):
            shutil.rmtree(self.cache)
            raise KeyboardInterrupt()

        with patch.object(installer.subprocess, "run", side_effect=interrupted), self.assertRaises(KeyboardInterrupt):
            installer.install_plugin()
        self.assertTrue((old / "server/iphone_use.py").is_file())

    def test_first_install_does_not_require_or_create_an_old_cache(self):
        with patch.object(installer.subprocess, "run", return_value=Mock(returncode=0)):
            self.assertEqual(installer.install_plugin(), 0)
        self.assertFalse(self.cache.exists())

    def test_unrecognized_directories_are_not_restored(self):
        self.package("1.0.0", name="another-plugin")
        self.package("local-development")
        malformed = self.package("0.1.0")
        (malformed / "plugin.json").write_text("[]")

        def upgrade(*args, **kwargs):
            shutil.rmtree(self.cache)
            return Mock(returncode=0)

        with patch.object(installer.subprocess, "run", side_effect=upgrade):
            self.assertEqual(installer.install_plugin(), 0)
        self.assertFalse(self.cache.exists())

    def test_symlink_cache_root_is_rejected_before_install(self):
        external = self.root / "external cache"
        external.mkdir()
        self.cache.parent.mkdir(parents=True)
        self.cache.symlink_to(external, target_is_directory=True)
        with patch.object(installer.subprocess, "run") as run, self.assertRaisesRegex(RuntimeError, "symlink"):
            installer.install_plugin()
        run.assert_not_called()

    def test_version_symlinks_are_skipped_and_nested_links_are_not_dereferenced(self):
        old = self.package("0.4.0")
        outside = self.root / "outside"
        outside.write_text("external contents")
        (old / "external-link").symlink_to(outside)
        (self.cache / "0.3.15").symlink_to(old, target_is_directory=True)

        def upgrade(*args, **kwargs):
            shutil.rmtree(self.cache)
            return Mock(returncode=0)

        with patch.object(installer.subprocess, "run", side_effect=upgrade):
            self.assertEqual(installer.install_plugin(), 0)
        self.assertTrue((old / "external-link").is_symlink())
        self.assertEqual((old / "external-link").readlink(), outside)
        self.assertFalse(os.path.lexists(self.cache / "0.3.15"))
        self.assertEqual(outside.read_text(), "external contents")

    def test_dangling_target_created_during_install_is_not_overwritten(self):
        old = self.package("0.4.0")

        def upgrade(*args, **kwargs):
            shutil.rmtree(old)
            old.symlink_to(self.root / "absent", target_is_directory=True)
            return Mock(returncode=0)

        with patch.object(installer.subprocess, "run", side_effect=upgrade):
            self.assertEqual(installer.install_plugin(), 0)
        self.assertTrue(old.is_symlink())

    def test_restore_failure_retains_private_backup_and_reports_its_location(self):
        self.package("0.4.0")
        backup = self.root / "recovery backup"
        backup.mkdir(mode=0o700)
        stderr = io.StringIO()
        with (patch.object(installer.tempfile, "mkdtemp", return_value=str(backup)),
              patch.object(installer.subprocess, "run", return_value=Mock(returncode=0)),
              patch.object(installer, "restore_versions", side_effect=OSError("disk full")),
              contextlib.redirect_stderr(stderr), self.assertRaisesRegex(OSError, "disk full")):
            installer.install_plugin()
        self.assertEqual((backup / "0.4.0/server/iphone_use.py").read_text(), "old runtime")
        self.assertIn(str(backup), stderr.getvalue())

    def test_cli_preserves_json_stdout_and_restores_old_cache_with_spaces_in_home(self):
        old = self.package("0.4.0")
        bin_dir = self.root / "fake cli"
        bin_dir.mkdir()
        cli = bin_dir / "codex"
        cli.write_text("#!/usr/bin/env python3\n" +
            "import json, os, pathlib, shutil, sys\n" +
            "assert sys.argv[1:] == ['plugin','add','iphone-use@iphone-use-local','--json']\n" +
            "cache=pathlib.Path(os.environ['CODEX_HOME'])/'plugins/cache/iphone-use-local/iphone-use'\n" +
            "shutil.rmtree(cache)\n" +
            "print(json.dumps({'pluginId':'iphone-use@iphone-use-local','installedPath':str(cache/'0.4.1')}))\n")
        cli.chmod(0o700)
        env = {**os.environ, "PATH": str(bin_dir) + os.pathsep + os.environ.get("PATH", "")}
        result = subprocess.run([sys.executable, str(ROOT / "scripts/install_plugin.py")],
                                env=env, capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout)["pluginId"], "iphone-use@iphone-use-local")
        self.assertEqual(result.stderr, "")
        self.assertTrue((old / "server/iphone_use.py").is_file())


if __name__ == "__main__":
    unittest.main()
