import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, call, patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("iphone_launch_screen", ROOT / "scripts/launch_screen.py")
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.device = {"udid": "device-00000001", "name": "Test phone", "transport": "wired", "connection_state": "connected"}

    def test_only_connected_usb_devices_are_selected_and_single_device_does_not_prompt(self):
        other = dict(self.device, transport="network")
        offline = dict(self.device, connection_state="unavailable")
        self.assertEqual(launcher.connected_devices({"devices": [self.device, other, offline]}), [self.device])
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(launcher.choose_device([self.device], Mock(side_effect=AssertionError("Unexpected prompt"))), self.device)

    def test_multiple_devices_invalid_input_cancel_and_missing_devices(self):
        second = dict(self.device, udid="device-00000002")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(launcher.choose_device([self.device, second], Mock(side_effect=["0", "bad", "2"])), second)
            self.assertIsNone(launcher.choose_device([self.device, second], lambda prompt: "q"))
        with self.assertRaises(launcher.LauncherError):
            launcher.choose_device([])

    def test_healthy_service_and_existing_start_or_recovery_are_reused(self):
        with contextlib.redirect_stdout(io.StringIO()), patch.object(launcher, "wda") as wda, patch.object(launcher, "wait_for_job") as wait:
            launcher.start_service({"service": {"ready": True}, "jobs": []})
            wda.assert_not_called()
            wait.assert_not_called()
            for action in ("start", "recover"):
                launcher.start_service({"service": {"ready": False}, "jobs": [{"id": "active", "state": "running", "action": action}]})
                wait.assert_called_with("active", starting=True)
            wda.assert_not_called()

    def test_missing_build_builds_once_then_starts_and_keeps_other_configuration(self):
        missing = {"ok": False, "error": "Run build successfully for this configuration"}
        with contextlib.redirect_stdout(io.StringIO()), patch.object(launcher, "wda", side_effect=[missing, {"ok": True, "job_id": "build"}, {"ok": True, "service": {"ready": True}}]) as invoke, patch.object(launcher, "wait_for_job") as wait:
            launcher.start_service({"service": {"ready": False}, "jobs": []})
            self.assertEqual(invoke.call_args_list, [call("start"), call("build"), call("start")])
            wait.assert_called_once_with("build")

    def test_startup_verifies_ready_before_opening_and_always_prints_actual_url(self):
        runtime = Mock()
        runtime.call.return_value = {"ready": True}
        browser = {"browser_url": "http://127.0.0.1:23456/", "browser_opened": False}
        output = io.StringIO()
        with contextlib.redirect_stdout(output), patch.object(launcher, "prepare_environment"), \
                patch.object(launcher, "wda", side_effect=[{"ok": True}, {"ok": True, "devices": [self.device]}]), \
                patch.object(launcher, "select_configuration", return_value={}), patch.object(launcher, "start_service"), \
                patch.object(launcher, "Runtime", return_value=runtime), patch.object(launcher, "BrowserManager") as manager:
            manager.return_value.start.return_value = browser
            launcher.main(["--no-open"])
            manager.return_value.start.assert_called_once_with(open_browser=False)
        runtime.call.assert_called_once_with("pua_ready", {"recover": True, "screenshot": False})
        runtime.close.assert_called_once()
        self.assertIn(browser["browser_url"], output.getvalue())

    def test_not_ready_never_opens_a_browser(self):
        runtime = Mock()
        runtime.call.return_value = {"ready": False, "state": "recovery_required"}
        with contextlib.redirect_stdout(io.StringIO()), patch.object(launcher, "prepare_environment"), \
                patch.object(launcher, "wda", side_effect=[{"ok": True}, {"ok": True, "devices": [self.device]}]), \
                patch.object(launcher, "select_configuration", return_value={}), patch.object(launcher, "start_service"), \
                patch.object(launcher, "Runtime", return_value=runtime), patch.object(launcher, "BrowserManager") as manager:
            with self.assertRaises(launcher.LauncherError):
                launcher.main(["--no-open"])
            manager.assert_not_called()

    def test_desktop_shortcut_uses_home_and_preserves_a_backup_of_its_owned_entry(self):
        with tempfile.TemporaryDirectory(prefix="desktop user ") as directory:
            home = Path(directory)
            root = home / "Projects/iPhone use"
            root.mkdir(parents=True)
            shutil.copy2(ROOT / "启动iPhone屏幕.command", root)
            with patch.object(launcher.Path, "home", return_value=home), patch.object(launcher, "PROJECT_ROOT", root), contextlib.redirect_stdout(io.StringIO()):
                path = launcher.install_desktop_launcher()
                body = path.read_text()
                self.assertIn('"$HOME"/', body)
                self.assertNotIn(str(home), body)
                self.assertIn("启动iPhone屏幕.command", body)
                self.assertEqual(path.stat().st_mode & 0o777, 0o700)
                launcher.install_desktop_launcher()
                self.assertFalse(list(path.parent.glob("*.bak-*")))
                path.write_text("# iPhone Use desktop launcher\n# previous version\n")
                launcher.install_desktop_launcher()
                self.assertTrue(list(path.parent.glob("*.bak-*")))
                path.write_text("Unrelated personal script")
                with self.assertRaises(launcher.LauncherError):
                    launcher.install_desktop_launcher()
                self.assertEqual(path.read_text(), "Unrelated personal script")

    def test_manual_and_desktop_entries_work_with_spaces_quotes_and_a_sparse_path(self):
        with tempfile.TemporaryDirectory(prefix="another user's home ") as directory:
            home = Path(directory)
            root = home / "Applications/iPhone Use"
            scripts = root / "scripts"
            scripts.mkdir(parents=True)
            shared = root / "启动iPhone屏幕.command"
            shutil.copy2(ROOT / shared.name, shared)
            (scripts / "launch_screen.py").write_text(
                "import json, sys\nfrom pathlib import Path\n"
                "print(json.dumps({'root': str(Path(__file__).resolve().parents[1]), 'args': sys.argv[1:]}))\n"
                "sys.exit(7)\n")
            with patch.object(launcher.Path, "home", return_value=home), patch.object(launcher, "PROJECT_ROOT", root), contextlib.redirect_stdout(io.StringIO()):
                desktop = launcher.install_desktop_launcher()
            env = dict(os.environ, HOME=str(home), PATH="/usr/bin:/bin")
            for entry in (shared, desktop):
                with self.subTest(entry=entry.name, directory=entry.parent):
                    result = subprocess.run([str(entry), "--no-open", "argument with spaces"], cwd=home,
                                            env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=10)
                    self.assertEqual(result.returncode, 7, result.stderr)
                    self.assertEqual(json.loads(result.stdout), {"root": str(root.resolve()), "args": ["--no-open", "argument with spaces"]})

    def test_detached_manual_entry_explains_that_the_project_is_missing(self):
        with tempfile.TemporaryDirectory(prefix="detached phone launcher ") as directory:
            shared = Path(directory) / "启动iPhone屏幕.command"
            shutil.copy2(ROOT / shared.name, shared)
            result = subprocess.run([str(shared)], stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 1)
            self.assertIn("完整项目目录", result.stderr)
            self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
