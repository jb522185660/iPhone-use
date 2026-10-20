import concurrent.futures
import fcntl
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import shutil
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
from wda_browser import BrowserManager, MAX_REQUEST_BYTES, make_server, revision
from wda_client import WDAError
from iphone_use import Runtime
from wda_environment import prepare_environment


class FakeRuntime:
    def __init__(self):
        self.calls = []
        self.entered = threading.Event()
        self.release = threading.Event()
        self.block = False

    def call(self, name, args):
        self.calls.append((name, args))
        if name == "pua_screen_action" and self.block:
            self.entered.set()
            self.release.wait(3)
        return {"frame": None, "frame_available": False} if name == "pua_screen_frame" else {"ok": True, **args}


class BrowserHTTPTests(unittest.TestCase):
    def setUp(self):
        self.runtime = FakeRuntime()
        self.server = make_server(self.runtime, "test-token", 0)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        self.thread.start()
        self.origin = "http://127.0.0.1:" + str(self.server.server_port)

    def tearDown(self):
        self.runtime.release.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)

    def request(self, method="POST", path="/api", data=None, headers=None, raw=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=4)
        default = {"Origin": self.origin, "Authorization": "Bearer test-token", "Content-Type": "application/json"}
        default.update(headers or {})
        payload = raw if raw is not None else json.dumps(data or {"name": "pua_screen_frame", "arguments": {}})
        try:
            connection.request(method, path, body=payload if method == "POST" else None, headers=default)
            response = connection.getresponse()
            body = response.read()
            return response.status, dict(response.getheaders()), body
        finally:
            connection.close()

    def test_page_is_same_self_contained_renderer_with_browser_transport_and_headers(self):
        status, headers, body = self.request("GET", "/")
        source = (Path(__file__).resolve().parents[1] / "assets/phone-screen.html").read_bytes()
        self.assertEqual(status, 200)
        self.assertEqual(body, source.replace(b'<html lang="zh-CN">', b'<html lang="zh-CN" data-transport="browser">', 1))
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(headers["Referrer-Policy"], "no-referrer")
        self.assertEqual(headers["X-Frame-Options"], "DENY")
        self.assertEqual(self.runtime.calls, [])

    def test_health_and_frame_do_not_control_phone_and_frames_are_structured_only(self):
        status, _, data = self.request("GET", "/health")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(data)["app"], "iphone-use-browser")
        self.assertEqual(self.runtime.calls, [])
        status, _, data = self.request(data={"name": "pua_screen_frame", "arguments": {"after_seq": 7}})
        result = json.loads(data)
        self.assertEqual(status, 200)
        self.assertEqual(result["content"], [])
        self.assertFalse(result["isError"])
        self.assertEqual(self.runtime.calls, [("pua_screen_frame", {"after_seq": 7})])

    def test_each_toolbar_action_and_pointer_are_delegated_once(self):
        calls = [{"action": action} for action in ("refresh", "home", "screenshot", "viewport")]
        calls += [{"action": "tap", "x": 20, "y": 30, "width": 390, "height": 844},
                  {"action": "drag", "x": 20, "y": 30, "to_x": 40, "to_y": 80, "width": 390, "height": 844, "duration": 0.2}]
        for args in calls:
            status, _, data = self.request(data={"name": "pua_screen_action", "arguments": args})
            self.assertEqual(status, 200)
            self.assertFalse(json.loads(data)["isError"])
        self.assertEqual(self.runtime.calls, [("pua_screen_action", args) for args in calls])

    def test_host_origin_and_token_fail_before_any_backend_call(self):
        for headers in ({"Host": "evil.example"}, {"Origin": "https://evil.example"},
                        {"Authorization": "Bearer wrong"}, {"Origin": "null"}):
            with self.subTest(headers=headers):
                self.assertEqual(self.request(headers=headers)[0], 403)
        self.assertEqual(self.request("GET", "/", headers={"Host": "evil.example"})[0], 403)
        self.assertEqual(self.runtime.calls, [])

    def test_session_bootstrap_requires_same_origin_custom_header_and_never_controls_phone(self):
        for path in ("/", "/health"):
            status, _, body = self.request("GET", path)
            self.assertEqual(status, 200)
            self.assertNotIn(b"test-token", body)
        self.assertEqual(self.request("GET", "/session")[0], 403)
        for headers in ({"Host": "evil.example"}, {"Origin": "https://evil.example"},
                        {"Origin": "null"}, {"Sec-Fetch-Site": "cross-site"}, {"Sec-Fetch-Site": "same-site"}):
            with self.subTest(headers=headers):
                self.assertEqual(self.request("GET", "/session", headers={"X-iPhone-Use": "browser", **headers})[0], 403)
        status, headers, body = self.request("GET", "/session", headers={"X-iPhone-Use": "browser", "Sec-Fetch-Site": "same-origin"})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"app": "iphone-use-browser", "token": "test-token"})
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertNotIn("Access-Control-Allow-Origin", headers)
        self.assertEqual(self.request("OPTIONS", "/session", headers={"Origin": "https://evil.example", "Access-Control-Request-Headers": "X-iPhone-Use"})[0], 501)
        self.assertEqual(self.runtime.calls, [])

    def test_no_arbitrary_tools_files_or_get_mutations(self):
        for name in ("pua_type_text", "pua_setup", "pua_screen", "__dict__"):
            self.assertEqual(self.request(data={"name": name})[0], 403)
        for path in ("/wrong/", "/test-token/", "/test-token/../../config.json", "/api"):
            self.assertEqual(self.request("GET", path)[0], 404)
        self.assertEqual(self.runtime.calls, [])

    def test_bad_json_body_size_and_coordinates_leave_service_usable(self):
        for raw in (b"{", b"[]", b'{"name":"pua_screen_frame","arguments":{"after_seq":NaN}}'):
            self.assertEqual(self.request(raw=raw)[0], 400)
        self.assertEqual(self.request(raw=b"x" * (MAX_REQUEST_BYTES + 1))[0], 413)
        self.assertEqual(self.request(headers={"Content-Type": "text/plain"})[0], 400)
        status, _, data = self.request(data={"name": "pua_screen_action", "arguments": {"action": "tap", "x": -1}})
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(data)["isError"])
        self.assertEqual(self.runtime.calls, [])
        self.assertEqual(self.request()[0], 200)

    def test_second_action_is_refused_without_queue_and_frame_remains_available(self):
        self.runtime.block = True
        with concurrent.futures.ThreadPoolExecutor() as executor:
            first = executor.submit(self.request, data={"name": "pua_screen_action", "arguments": {"action": "home"}})
            self.assertTrue(self.runtime.entered.wait(2))
            _, _, data = self.request(data={"name": "pua_screen_action", "arguments": {"action": "home"}})
            self.assertEqual(json.loads(data)["structuredContent"]["error"]["code"], "device_busy")
            self.assertEqual(self.request()[0], 200)
            self.runtime.release.set()
            self.assertEqual(first.result()[0], 200)
        self.assertEqual(sum(name == "pua_screen_action" for name, _ in self.runtime.calls), 1)

    def test_uncertain_mutation_is_returned_without_replay(self):
        with patch.object(self.runtime, "call", side_effect=WDAError("action_uncertain", "Timed out", uncertain=True)) as call:
            _, _, data = self.request(data={"name": "pua_screen_action", "arguments": {"action": "home"}})
        self.assertTrue(json.loads(data)["structuredContent"]["error"]["uncertain"])
        call.assert_called_once()


class BrowserLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="iphone browser space ")
        self.addCleanup(self.temp.cleanup)
        self.manager = BrowserManager(self.temp.name)
        env = patch.dict(os.environ, {"IPHONE_USE_ANALYTICS": "0", "IPHONE_USE_BROWSER": "0"})
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(self.manager.stop)

    def test_repeated_starts_stop_and_restart_use_one_owned_worker_and_new_token(self):
        first = self.manager.start(port=0)
        self.assertTrue(first["running"])
        self.assertFalse(first["reused"])
        second = self.manager.start(port=0)
        self.assertEqual(second["pid"], first["pid"])
        self.assertEqual(second["browser_url"], first["browser_url"])
        self.assertTrue(second["reused"])
        self.assertEqual(self.manager.path.stat().st_mode & 0o777, 0o600)
        token = self.manager._status()["token"]
        port = urlsplit(first["browser_url"]).port
        self.assertEqual(first["browser_url"], "http://127.0.0.1:" + str(port) + "/")
        self.assertNotIn("token", first)
        self.assertTrue(self.manager.stop()["stopped"])
        self.assertFalse(self.manager.status()["running"])
        third = self.manager.start(port=port)
        self.assertEqual(third["browser_url"], first["browser_url"])
        self.assertNotEqual(self.manager._status()["token"], token)
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
        try:
            for credential, expected in ((token, 403), (self.manager._status()["token"], 200)):
                connection.request("POST", "/api", body='{"name":"pua_screen_frame"}',
                    headers={"Origin": "http://127.0.0.1:" + str(port), "Content-Type": "application/json", "Authorization": "Bearer " + credential})
                response = connection.getresponse()
                self.assertEqual(response.status, expected)
                response.read()
        finally:
            connection.close()

    def test_legacy_token_record_is_recognized_for_owned_worker_upgrade(self):
        record = {"browser_url": "http://127.0.0.1:18101/old-token/", "token": "old-token", "pid": 123, "instance": "old-instance"}
        self.manager.path.write_text(json.dumps(record))
        with patch("wda_browser.request_json", return_value={"app": "iphone-use-browser", "pid": 123, "instance": "old-instance"}) as request:
            self.assertTrue(self.manager.status()["running"])
            request.assert_called_once_with(record["browser_url"] + "health")
        self.manager.path.unlink()

    def test_backend_only_update_changes_worker_revision(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("server/iphone_use.py", "assets/phone-screen.html", "tooling/screen-stream.mjs"):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("first")
            with patch("wda_browser.ROOT", root):
                before = revision()
                (root / "server/iphone_use.py").write_text("updated backend")
                self.assertNotEqual(revision(), before)

    def test_other_listener_is_preserved_and_browser_chooses_a_free_port(self):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            port = listener.getsockname()[1]
            result = self.manager.start(port=port)
            self.assertNotIn(":" + str(port) + "/", result["browser_url"])
            self.assertGreaterEqual(listener.fileno(), 0)

    def test_browser_open_failure_keeps_service_and_clickable_link(self):
        with patch("wda_browser.webbrowser.open", return_value=False):
            result = self.manager.start(open_browser=True, port=0)
        self.assertTrue(result["running"])
        self.assertFalse(result["browser_opened"])
        self.assertTrue(result["browser_url"].startswith("http://127.0.0.1:"))

    def test_concurrent_agent_starts_share_one_worker(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(lambda _: BrowserManager(self.temp.name).start(port=0), range(4)))
        self.assertEqual(len({result["pid"] for result in results}), 1)
        self.assertEqual(len({result["browser_url"] for result in results}), 1)
        self.assertEqual(sum(not result["reused"] for result in results), 1)

    def test_explicit_endpoint_and_changed_device_never_reuse_the_wrong_worker(self):
        calls = []

        def wda_stub(label):
            class Handler(BaseHTTPRequestHandler):
                def do_POST(self):
                    self.rfile.read(int(self.headers.get("Content-Length", "0")))
                    calls.append((label, self.path))
                    body = b'{"value":null}'
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)

                def log_message(self, *args):
                    pass

            server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            worker = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
            worker.start()
            self.addCleanup(server.server_close)
            self.addCleanup(server.shutdown)
            return server

        configured, override = wda_stub("configured"), wda_stub("override")
        config_path = Path(self.temp.name) / "config.json"
        config_path.write_text(json.dumps({"udid": "TEST-DEVICE-ONE", "local_port": configured.server_port}))
        manager = BrowserManager(self.temp.name, "http://127.0.0.1:" + str(override.server_port))
        first = manager.start(port=0)
        target = urlsplit(first["browser_url"])
        connection = http.client.HTTPConnection(target.hostname, target.port, timeout=3)
        try:
            connection.request("POST", target.path + "api", body=json.dumps({"name": "pua_screen_action", "arguments": {"action": "home"}}),
                headers={"Origin": "http://" + target.netloc, "Content-Type": "application/json",
                         "Authorization": "Bearer " + manager._status()["token"]})
            response = connection.getresponse()
            self.assertFalse(json.loads(response.read())["isError"])
        finally:
            connection.close()
        self.assertEqual(calls, [("override", "/wda/homescreen")])
        self.assertEqual(manager.start(port=0)["pid"], first["pid"])
        config_path.write_text(json.dumps({"udid": "TEST-DEVICE-TWO", "local_port": configured.server_port}))
        second = manager.start(port=0)
        self.assertNotEqual(second["pid"], first["pid"])
        third = self.manager.start(port=0)
        self.assertNotEqual(third["pid"], second["pid"])
        self.assertTrue(self.manager.start(port=0)["reused"])

    def test_unverified_process_and_nonlocal_metadata_are_never_signalled(self):
        with patch.object(self.manager, "_status", return_value={"running": True, "pid": 1}), \
                patch.object(self.manager, "_owned", return_value=False), patch("wda_browser.os.kill") as kill:
            with self.assertRaises(RuntimeError):
                self.manager.stop()
            kill.assert_not_called()
        self.manager.path.write_text(json.dumps({"browser_url": "http://example.com/private/", "token": "private"}))
        with patch("wda_browser.request_json") as request:
            self.assertFalse(self.manager.status()["running"])
            request.assert_not_called()


class BrowserIntegrationTests(unittest.TestCase):
    def test_browser_gesture_obeys_the_same_filesystem_lock_as_an_agent(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"IPHONE_USE_BROWSER": "0", "IPHONE_USE_ANALYTICS": "0"}):
            runtime = Runtime(directory)
            self.addCleanup(runtime.close)
            server = make_server(runtime, "shared-lock", 0)
            worker = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
            worker.start()
            try:
                with (Path(directory) / "operation.lock").open("a") as lock, patch.object(runtime.client, "request") as request:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=2)
                    try:
                        connection.request("POST", "/api", body=json.dumps({"name": "pua_screen_action", "arguments": {"action": "tap", "x": 20, "y": 30, "width": 390, "height": 844}}), headers={"Origin": "http://127.0.0.1:" + str(server.server_port), "Authorization": "Bearer shared-lock", "Content-Type": "application/json"})
                        response = connection.getresponse()
                        result = json.loads(response.read())
                        self.assertEqual(result["structuredContent"]["error"]["code"], "device_busy")
                    finally:
                        connection.close()
                    request.assert_not_called()
            finally:
                server.shutdown()
                server.server_close()
                worker.join(2)

    def test_ready_recovers_expired_session_by_querying_once_without_restarting_wda(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Runtime(directory, browser_enabled=False)
            self.addCleanup(runtime.close)
            with patch.object(runtime.setup_manager, "pending_recovery", return_value=None), \
                    patch.object(runtime.setup_manager, "recover") as restart, \
                    patch.object(runtime, "ready_once", side_effect=[WDAError("invalid session id", "Session does not exist"), {"ready": True}]) as ready:
                result = runtime.ready(screenshot=False)
            self.assertTrue(result["ready"])
            self.assertTrue(result["recovery"]["session_recreated"])
            self.assertEqual(ready.call_count, 2)
            restart.assert_not_called()

    def test_ready_start_and_open_return_link_without_launching_external_browser(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"IPHONE_USE_BROWSER": "1", "IPHONE_USE_ANALYTICS": "0"}):
            (Path(directory) / "config.json").write_text(json.dumps({"udid": "TEST-DEVICE"}))
            runtime = Runtime(directory)
            self.addCleanup(runtime.close)
            for name, args, result in (
                ("pua_ready", {}, {"ready": True}),
                ("pua_setup", {"action": "start"}, {"ok": True, "service": {"ready": True}}),
                ("pua_screen", {}, {"frame": None}),
            ):
                with self.subTest(name=name), patch.object(runtime, "_dispatch", return_value=result), \
                        patch("wda_browser.BrowserManager.start", return_value={"browser_url": "http://127.0.0.1:18101/"}) as start:
                    self.assertIn("browser_url", runtime.call(name, args))
                    start.assert_called_once_with()

    def test_browser_failure_does_not_invalidate_ready_and_waiting_does_not_start_browser(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"IPHONE_USE_BROWSER": "1", "IPHONE_USE_ANALYTICS": "0"}):
            (Path(directory) / "config.json").write_text(json.dumps({"udid": "TEST-DEVICE"}))
            runtime = Runtime(directory)
            self.addCleanup(runtime.close)
            for error in (RuntimeError("cannot bind"), KeyError("browser_url"), ImportError("missing optional transport")):
                with self.subTest(error=type(error).__name__), patch.object(runtime, "_dispatch", return_value={"ready": True}), \
                        patch("wda_browser.BrowserManager.start", side_effect=error):
                    result = runtime.call("pua_ready", {})
                    self.assertTrue(result["ready"])
                    self.assertEqual(result["browser_error"], str(error))
            with patch.object(runtime, "_dispatch", return_value={"ready": False, "state": "recovering"}), patch("wda_browser.BrowserManager.start") as start:
                self.assertFalse(runtime.call("pua_ready", {})["ready"])
                start.assert_not_called()

    def test_browser_disabled_keeps_the_original_ready_response(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"IPHONE_USE_ANALYTICS": "0"}):
            runtime = Runtime(directory, browser_enabled=False)
            self.addCleanup(runtime.close)
            with patch.object(runtime, "_dispatch", return_value={"ready": True}), \
                    patch("wda_browser.BrowserManager.start") as start:
                result = runtime.call("pua_ready", {})
            self.assertEqual(result, {"ready": True})
            start.assert_not_called()

    def test_existing_actions_and_pause_resume_do_not_start_the_browser_service(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"IPHONE_USE_BROWSER": "1", "IPHONE_USE_ANALYTICS": "0"}):
            (Path(directory) / "config.json").write_text(json.dumps({"udid": "TEST-DEVICE"}))
            runtime = Runtime(directory)
            self.addCleanup(runtime.close)
            for name, args in (("pua_tap", {"x": 1, "y": 2}), ("pua_type_text", {"text": "test"}),
                               ("pua_apps", {"query": "Calculator"}), ("pua_doctor", {}),
                               ("pua_screen_frame", {}), ("pua_screen_action", {"action": "home"}),
                               ("pua_screen", {"action": "pause"}), ("pua_screen", {"action": "resume"})):
                with self.subTest(name=name, args=args), patch.object(runtime, "_dispatch", return_value={"ok": True}), \
                        patch("wda_browser.BrowserManager.start") as start:
                    self.assertEqual(runtime.call(name, args), {"ok": True})
                    start.assert_not_called()

    def test_gui_path_discovers_nvm_under_current_home_and_paths_with_spaces(self):
        with tempfile.TemporaryDirectory(prefix="another user ") as directory:
            node = Path(directory) / ".nvm/versions/node/v24.14.0/bin/node"
            node.parent.mkdir(parents=True)
            node.write_text("#!/bin/sh\nexit 0\n")
            node.chmod(0o700)
            with patch("wda_environment.Path.home", return_value=Path(directory)), \
                    patch.dict(os.environ, {"PATH": "/usr/bin:/bin", "NVM_DIR": str(Path(directory) / ".nvm")}):
                self.assertTrue(prepare_environment().startswith("/usr/bin:/bin:"))
                self.assertEqual(shutil.which("node"), str(node))

    def test_environment_discovery_preserves_host_tool_precedence_and_runtime_is_side_effect_free(self):
        with tempfile.TemporaryDirectory(prefix="host selected tools ") as directory:
            root = Path(directory)
            for name in ("node", "git"):
                selected = root / "bin" / name
                selected.parent.mkdir(exist_ok=True)
                selected.write_text("#!/bin/sh\nexit 0\n")
                selected.chmod(0o700)
            given = str(root / "bin") + ":/usr/bin:/bin"
            with patch.dict(os.environ, {"PATH": given, "IPHONE_USE_ANALYTICS": "0"}):
                runtime = Runtime(root / "state", browser_enabled=False)
                try:
                    self.assertEqual(os.environ["PATH"], given)
                    prepare_environment()
                    self.assertTrue(os.environ["PATH"].startswith(given))
                    self.assertEqual(shutil.which("node"), str(root / "bin/node"))
                    self.assertEqual(shutil.which("git"), str(root / "bin/git"))
                finally:
                    runtime.close()


if __name__ == "__main__":
    unittest.main()
