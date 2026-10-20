"""Loopback-only browser transport for the existing iPhone screen runtime.

The worker owns its HTTP listener and ScreenHub only. It never owns or stops WDA.
Private state records make starts idempotent across independent agent processes.
"""
from __future__ import annotations

import argparse
import contextlib
import errno
import fcntl
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit
import webbrowser

from wda_environment import prepare_environment
from wda_setup import state_directory, _read_json, _write_json

DEFAULT_PORT = 18101
MAX_REQUEST_BYTES = 16384
ROOT = Path(__file__).resolve().parents[1]
APP_NAME = "iphone-use-browser"


def revision():
    digest = hashlib.sha256()
    # A backend-only update must replace the worker too, even when its HTML and
    # HTTP entry point have not changed. Hash shipped sources, never user state.
    sources = sorted((ROOT / "server").glob("*.py"))
    sources += [ROOT / "assets/phone-screen.html", ROOT / "tooling/screen-stream.mjs"]
    for path in sources:
        digest.update(str(path.relative_to(ROOT)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


def request_json(url, timeout=0.5):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url, timeout=timeout) as response:
        return json.loads(response.read(4096))


class BrowserManager:
    def __init__(self, state_dir=None, base_url=None):
        self.state_dir = Path(state_directory(state_dir)).expanduser().resolve()
        self.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.state_dir / "browser.json"
        self.base_url = base_url

    def _binding(self):
        """Reuse a worker only for the same configured phone and WDA endpoint."""
        config = _read_json(self.state_dir / "config.json", {})
        if not isinstance(config, dict):
            raise ValueError("Invalid local device configuration")
        base_url = self.base_url or os.environ.get("WDA_URL") or "http://127.0.0.1:" + str(config.get("local_port", 18100))
        binding = {"base_url": base_url, "udid": config.get("udid"),
                   "mjpeg_device_port": config.get("mjpeg_device_port", 9100)}
        return base_url, hashlib.sha256(json.dumps(binding, sort_keys=True).encode()).hexdigest()[:16]

    def _status(self):
        record = _read_json(self.path, {})
        try:
            parsed = urlsplit(record["browser_url"])
            # Recognize the old token URL too, so an upgrade can verify and stop
            # its own old worker before replacing it with the stable root URL.
            if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or parsed.username \
                    or parsed.query or parsed.fragment or parsed.path not in ("/", "/" + record["token"] + "/"):
                raise ValueError("Invalid local browser record")
            health = request_json(record["browser_url"] + "health")
            if health.get("app") != APP_NAME or health.get("pid") != record["pid"] \
                    or health.get("instance") != record["instance"]:
                raise ValueError("Browser ownership does not match")
            return {"ok": True, "running": True, **record}
        except (KeyError, TypeError, ValueError, AttributeError, OSError, urllib.error.URLError):
            return {"ok": True, "running": False}

    def status(self):
        status = self._status()
        return {key: value for key, value in status.items() if key not in ("token", "instance", "server_file")}

    def _owned(self, record):
        try:
            command = subprocess.check_output(["ps", "-p", str(record["pid"]), "-o", "command="], text=True)
            path = Path(record["server_file"])
            return path.name == "wda_browser.py" and path.parent.name == "server" \
                and str(path) in command and "--serve" in command \
                and str(self.state_dir) in command
        except (KeyError, OSError, subprocess.CalledProcessError):
            return False

    def _stop(self, record):
        if not self._owned(record):
            raise RuntimeError("Browser process ownership could not be verified; no process was stopped.")
        os.kill(record["pid"], signal.SIGTERM)
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline and self._status().get("running"):
            time.sleep(0.05)
        if self._status().get("running"):
            raise RuntimeError("Browser service is still stopping; no other process was stopped.")

    @contextlib.contextmanager
    def _lock(self):
        with (self.state_dir / "browser.lock").open("a") as stream:
            os.fchmod(stream.fileno(), 0o600)
            fcntl.flock(stream, fcntl.LOCK_EX)
            yield

    def stop(self):
        with self._lock():
            record = self._status()
            if record.get("running"):
                self._stop(record)
            return {"ok": True, "running": False, "stopped": bool(record.get("running"))}

    def start(self, open_browser=False, port=DEFAULT_PORT):
        if isinstance(port, bool) or not isinstance(port, int) or not 0 <= port <= 65535:
            raise ValueError("Browser port must be between 0 and 65535.")
        with self._lock():
            record = self._status()
            base_url, binding = self._binding()
            reused = record.get("running") and record.get("revision") == revision() and record.get("binding") == binding
            if record.get("running") and not reused:
                self._stop(record)
            if not reused:
                log_path = self.state_dir / "browser.log"
                fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
                with os.fdopen(fd, "ab") as log:
                    child = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--serve",
                        "--state-dir", str(self.state_dir), "--port", str(port), "--url", base_url],
                        stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
                threading.Thread(target=child.wait, name="browser-worker-reaper", daemon=True).start()
                deadline = time.monotonic() + 8
                while time.monotonic() < deadline:
                    record = self._status()
                    if record.get("running") and record.get("pid") == child.pid:
                        break
                    if child.poll() is not None:
                        raise RuntimeError("Browser service did not start; inspect " + str(log_path))
                    time.sleep(0.05)
                else:
                    # This is our newly created child, never a process found by port.
                    child.terminate()
                    raise RuntimeError("Browser startup timed out; inspect " + str(log_path))
            result = self.status()
            result["reused"] = bool(reused)
        if open_browser:
            try:
                result["browser_opened"] = bool(webbrowser.open(result["browser_url"]))
            except (OSError, webbrowser.Error):
                result["browser_opened"] = False
        return result


def make_server(runtime, token, port=DEFAULT_PORT):
    """Return an HTTP server that delegates only the two existing panel operations."""
    from iphone_use import PUAError, validate, validate_semantics, SCHEMAS

    html = (ROOT / "assets/phone-screen.html").read_text()
    marker = '<html lang="zh-CN">'
    if html.count(marker) != 1:
        raise ValueError("Packaged phone screen is missing its HTML marker.")
    page = html.replace(marker, '<html lang="zh-CN" data-transport="browser">', 1).encode()
    gate = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass  # Never log the access token, phone frame or submitted arguments.

        def reply(self, status, body, mime="application/json"):
            if not isinstance(body, bytes):
                body = json.dumps(body, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
            self.send_response(status)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(body)))
            if self.close_connection:
                self.send_header("Connection", "close")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'")
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass  # A timed-out client must never cause an action to be replayed.

        def local(self):
            return self.headers.get("Host") == "127.0.0.1:" + str(self.server.server_port)

        def do_GET(self):
            if not self.local():
                self.reply(403, {"error": "Invalid host"})
            elif self.path == "/":
                self.reply(200, page, "text/html; charset=utf-8")
            elif self.path == "/session":
                # A same-origin fetch bootstraps the per-worker credential without
                # putting it in bookmarks, links or browser history. Cross-origin
                # pages cannot supply this header without a CORS preflight; we
                # never allow CORS. Also reject explicit foreign origins/sites.
                origin = "http://127.0.0.1:" + str(self.server.server_port)
                if self.headers.get("X-iPhone-Use") != "browser" \
                        or self.headers.get("Origin") not in (None, origin) \
                        or self.headers.get("Sec-Fetch-Site") not in (None, "same-origin"):
                    self.reply(403, {"error": "Invalid browser access"})
                else:
                    self.reply(200, {"app": APP_NAME, "token": token})
            elif self.path == "/health":
                preview = runtime.screen.start() if hasattr(runtime, "screen") else {}
                self.reply(200, {"app": APP_NAME, "pid": os.getpid(), "instance": self.server.instance,
                    "preview": {key: preview.get(key) for key in ("frame_available", "frame_age_ms", "paused", "busy")}})
            else:
                self.reply(404, {"error": "Not found"})

        def do_POST(self):
            origin = "http://127.0.0.1:" + str(self.server.server_port)
            if not self.local() or self.headers.get("Origin") != origin \
                    or not hmac.compare_digest(self.headers.get("Authorization", "").encode(), ("Bearer " + token).encode()):
                self.close_connection = True
                self.reply(403, {"error": "Invalid browser access"})
                return
            if self.path != "/api":
                self.close_connection = True
                self.reply(404, {"error": "Not found"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= MAX_REQUEST_BYTES or self.headers.get("Transfer-Encoding") \
                        or self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                    self.close_connection = True
                    self.reply(413 if length > MAX_REQUEST_BYTES else 400, {"error": "Invalid request body"})
                    return
                request = json.loads(self.rfile.read(length), parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
                if not isinstance(request, dict) or set(request) - {"name", "arguments"}:
                    raise ValueError("Invalid request")
                name, args = request.get("name"), request.get("arguments", {})
                if name not in ("pua_screen_frame", "pua_screen_action"):
                    self.reply(403, {"error": "Only panel operations are available"})
                    return
                validate(args, SCHEMAS[name[4:]])
                validate_semantics(name[4:], args)
                acquired = name == "pua_screen_frame" or gate.acquire(blocking=False)
                if not acquired:
                    raise PUAError("device_busy", "A screen action is already running.", details={"action_executed": False})
                try:
                    data = runtime.call(name, args)
                    result = {"content": [], "structuredContent": data, "isError": False}
                finally:
                    if name != "pua_screen_frame":
                        gate.release()
                self.reply(200, result)
            except PUAError as error:
                self.reply(200, {"content": [], "structuredContent": {"error": error.as_dict()}, "isError": True})
            except (ValueError, TypeError, UnicodeError):
                self.close_connection = True
                self.reply(400, {"error": "Invalid request"})
            except Exception:
                self.reply(500, {"error": "Panel request failed; inspect local service state"})

        def setup(self):
            super().setup()
            self.connection.settimeout(15)

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    server.action_gate = gate
    server.instance = secrets.token_hex(16)
    return server


def serve(state_dir, port=DEFAULT_PORT, base_url=None):
    prepare_environment()
    from iphone_use import Runtime
    runtime = Runtime(state_dir, base_url, browser_enabled=False)
    token = secrets.token_urlsafe(32)
    manager = BrowserManager(state_dir, runtime.base_url)
    server = None
    try:
        try:
            server = make_server(runtime, token, port)
        except OSError as error:
            if port == 0 or error.errno != errno.EADDRINUSE:
                raise
            server = make_server(runtime, token, 0)
        record = {"pid": os.getpid(), "token": token, "instance": server.instance,
            "revision": revision(), "binding": manager._binding()[1], "server_file": str(Path(__file__).resolve()),
            "browser_url": "http://127.0.0.1:" + str(server.server_port) + "/"}
        _write_json(manager.path, record)
        def stop(signum, frame):
            threading.Thread(target=server.shutdown, daemon=True).start()
        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        server.serve_forever(poll_interval=0.1)
    finally:
        if server:
            server.server_close()
        if server:
            with server.action_gate:
                runtime.close()
        else:
            runtime.close()
        current = _read_json(manager.path, {})
        if current.get("pid") == os.getpid():
            with contextlib.suppress(FileNotFoundError):
                manager.path.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", nargs="?", choices=("start", "status", "stop"), default="start")
    parser.add_argument("--state-dir")
    parser.add_argument("--url", help="use the same local WDA endpoint as the controlling agent")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--open", action="store_true", dest="open_browser")
    parser.add_argument("--serve", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.serve:
        serve(args.state_dir, args.port, args.url)
        return 0
    manager = BrowserManager(args.state_dir, args.url)
    try:
        result = manager.start(args.open_browser, args.port) if args.action == "start" else getattr(manager, args.action)()
    except (OSError, ValueError, RuntimeError) as error:
        result = {"ok": False, "error": str(error)}
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
