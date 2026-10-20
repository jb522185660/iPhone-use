#!/usr/bin/env python3
"""Launch an existing configured iPhone and its standalone browser panel."""
import json
import argparse
from pathlib import Path
import shutil
import shlex
import socket
import subprocess
import sys
import time


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "server"))
from wda_browser import BrowserManager
from wda_environment import prepare_environment as prepare_runtime_environment
from iphone_use import Runtime, PUAError
ACTIVE_STATES = {"queued", "running"}


class LauncherError(Exception):
    pass


def prepare_environment():
    prepare_runtime_environment()
    if not (PROJECT_ROOT / "scripts/wda.sh").is_file():
        raise LauncherError(f"找不到 iPhone Use 项目：{PROJECT_ROOT}")
    missing = [name for name in ("node", "npm", "xcrun", "xcodebuild") if not shutil.which(name)]
    if missing:
        raise LauncherError("缺少依赖：" + "、".join(missing))


def wda(action, **arguments):
    command = ["/bin/sh", str(PROJECT_ROOT / "scripts/wda.sh"), action]
    for name, value in arguments.items():
        command.extend(["--" + name.replace("_", "-"), str(value)])
    result = subprocess.run(command, capture_output=True, text=True, cwd=PROJECT_ROOT)
    try:
        response = json.loads(result.stdout)
    except ValueError as error:
        raise LauncherError(result.stderr.strip() or result.stdout.strip() or "启动脚本没有返回有效结果。") from error
    if not isinstance(response, dict):
        raise LauncherError("启动脚本返回了无法识别的结果。")
    return response


def require_success(response):
    if not response.get("ok"):
        raise LauncherError(str(response.get("error") or "操作失败，请检查 USB、设备解锁和 Xcode 签名。"))
    return response


def connected_devices(discovery):
    return [device for device in discovery.get("devices", [])
            if str(device.get("transport", "")).lower() in {"wired", "usb"}
            and str(device.get("connection_state", "")).lower() in {"connected", "available"}
            and device.get("udid")]


def choose_device(devices, read_input=input):
    if not devices:
        raise LauncherError("未发现 USB 连接的 iPhone/iPad。请连接数据线、解锁设备并信任这台 Mac，再次双击启动。")
    if len(devices) == 1:
        device = devices[0]
        print(f"已自动选择：{device.get('name', 'iPhone')}（{device.get('model') or 'iOS 设备'}）", flush=True)
        return device
    print("发现多台 USB 设备，请选择：")
    for number, device in enumerate(devices, 1):
        print(f"  {number}. {device.get('name', 'iPhone')} · {device.get('model') or 'iOS 设备'} · {device['udid'][-8:]}")
    while True:
        answer = read_input("输入设备编号，或输入 q 取消：").strip()
        if answer.lower() == "q":
            return None
        if answer.isascii() and answer.isdecimal() and 1 <= int(answer) <= len(devices):
            return devices[int(answer) - 1]
        print(f"请输入 1 到 {len(devices)} 之间的编号。")


def port_is_open(port):
    with socket.socket() as connection:
        connection.settimeout(0.5)
        return connection.connect_ex(("127.0.0.1", port)) == 0


def wait_for_job(job_id, starting=False):
    deadline = time.monotonic() + (120 if starting else 600)
    while True:
        status = require_success(wda("status", job_id=job_id))
        job = next((entry for entry in status.get("jobs", []) if entry.get("id") == job_id), None)
        if job is None:
            raise LauncherError("无法查询后台任务，请重新双击并检查状态。")
        serving = job.get("action") != "recover" or job.get("recovery_phase") == "serving"
        if starting and job.get("state") in ACTIVE_STATES and status.get("service", {}).get("ready") and serving:
            return status
        if job.get("state") not in ACTIVE_STATES:
            if not starting and job.get("state") == "succeeded":
                return status
            raise LauncherError(f"后台任务未完成：{job.get('error') or job.get('state')}\n日志：{job.get('log_path', '')}")
        if time.monotonic() >= deadline:
            raise LauncherError(f"任务仍在进行，请稍后再次双击以继续等待。\n日志：{job.get('log_path', '')}")
        time.sleep(2)


def select_configuration(device, status):
    config = status.get("config") or {}
    if not all(config.get(key) for key in ("udid", "team_id", "bundle_id", "source_dir")):
        raise LauncherError("尚未完成首次签名配置，请先在 Codex 中使用 iphone-use-setup 配置设备。")
    if config["udid"] == device["udid"]:
        return status
    active_jobs = [job for job in status.get("jobs", []) if job.get("state") in ACTIVE_STATES]
    if any(job.get("action") not in {"start", "recover"} for job in active_jobs):
        raise LauncherError("已有下载或构建正在进行，请等它完成后再切换设备。")
    print(f"正在切换到：{device.get('name', 'iPhone')}……", flush=True)
    for job in active_jobs:
        require_success(wda("stop", job_id=job["id"]))
    deadline = time.monotonic() + 12
    while True:
        current = require_success(wda("status"))
        active = any(job.get("state") in ACTIVE_STATES for job in current.get("jobs", []))
        if not active and not port_is_open(config.get("local_port", 18100)):
            break
        if time.monotonic() >= deadline:
            raise LauncherError("原设备服务尚未释放连接，或端口由其他服务占用。请结束原连接后重试。")
        time.sleep(0.3)
    settings = {key: value for key, value in config.items()
                if key in {"udid", "team_id", "bundle_id", "source_dir", "local_port", "device_port"}}
    settings["udid"] = device["udid"]
    require_success(wda("configure", **settings))
    return require_success(wda("status"))


def start_service(status):
    for job in status.get("jobs", []):
        if job.get("state") in ACTIVE_STATES and job.get("action") == "recover":
            print("正在等待已有的恢复任务……", flush=True)
            wait_for_job(job["id"], starting=True)
            return
    if status.get("service", {}).get("ready"):
        print("现有 WDA 连接正常，直接复用。", flush=True)
        return
    for job in status.get("jobs", []):
        if job.get("state") in ACTIVE_STATES:
            print("正在等待已有的后台任务……", flush=True)
            starting = job.get("action") in {"start", "recover"}
            wait_for_job(job["id"], starting=starting)
            if starting:
                return
    print("正在启动 WDA 和 USB 连接，请保持手机解锁……", flush=True)
    result = wda("start")
    if not result.get("ok") and "Run build successfully for this configuration" in str(result.get("error", "")):
        print("所选设备需要构建 WDA，正在使用已有团队和签名配置构建……", flush=True)
        build = require_success(wda("build"))
        wait_for_job(build["job_id"])
        result = wda("start")
    require_success(result)
    if not result.get("service", {}).get("ready"):
        job_id = result.get("job_id") or result.get("job", {}).get("id")
        if not job_id:
            raise LauncherError("尚未取得启动任务，请检查设备连接后重试。")
        wait_for_job(job_id, starting=True)


def install_desktop_launcher():
    launcher = PROJECT_ROOT / "启动iPhone屏幕.command"
    if not launcher.is_file():
        raise LauncherError("找不到项目启动入口：" + str(launcher))
    try:
        portable = '"$HOME"/' + shlex.quote(launcher.relative_to(Path.home()).as_posix())
    except ValueError:
        portable = shlex.quote(str(launcher))
    desktop = Path.home() / "Desktop"
    desktop.mkdir(exist_ok=True)
    target = desktop / "启动iPhone屏幕.command"
    content = '''#!/bin/sh
# iPhone Use desktop launcher
task_launcher=''' + portable + '''
if [ ! -f "$task_launcher" ]; then
    printf '%s\\n' '找不到 iPhone Use 启动入口，请从当前安装目录重新生成桌面快捷方式。' >&2
    if [ -t 0 ]; then printf '\\n按回车关闭窗口……'; read -r task_response; fi
    exit 1
fi
exec /bin/sh "$task_launcher" "$@"
'''
    if target.exists():
        old = target.read_text()
        if "iPhone Use" not in old and "desktop_launcher.py" not in old:
            raise LauncherError("桌面已有同名脚本且归属不明，未覆盖：" + str(target))
        if old != content:
            backup = target.with_name(target.name + ".bak-" + time.strftime("%Y%m%d-%H%M%S"))
            shutil.copy2(target, backup)
    if not target.exists() or old != content:
        target.write_text(content)
    target.chmod(0o700)
    print("桌面启动入口：" + str(target), flush=True)
    return target


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-open", action="store_true", help="start the panel and print its URL without opening a browser")
    parser.add_argument("--install-desktop", action="store_true", help="install the desktop shortcut without starting the phone")
    options = parser.parse_args(argv)
    if options.install_desktop:
        install_desktop_launcher()
        return
    print("iPhone 屏幕启动器\n", flush=True)
    prepare_environment()
    status = require_success(wda("status"))
    discovery = require_success(wda("discover"))
    device = choose_device(connected_devices(discovery))
    if device is None:
        print("已取消。")
        return
    status = select_configuration(device, status)
    start_service(status)
    runtime = Runtime(browser_enabled=False)
    try:
        for attempt in range(3):
            try:
                ready = runtime.call("pua_ready", {"recover": True, "screenshot": False})
                if ready.get("state") == "recovering" and attempt < 2:
                    wait_for_job(ready["recovery"]["job_id"], starting=True)
                    continue
                break
            except PUAError as error:
                if error.code == "invalid session id" and attempt == 0:
                    continue
                raise LauncherError(str(error)) from error
        if ready.get("ready") is not True:
            raise LauncherError("控制通道仍未就绪，请检查返回状态：" + json.dumps(ready, ensure_ascii=False))
    finally:
        runtime.close()
    browser = BrowserManager().start(open_browser=not options.no_open)
    print("\n手机屏幕：" + browser["browser_url"], flush=True)
    if not options.no_open and not browser.get("browser_opened"):
        print("网页服务已启动，请在浏览器中打开上面的链接。", flush=True)


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print("\n已取消。")
        sys.exit(1)
    except (LauncherError, OSError, RuntimeError) as error:
        print(f"\n启动失败：{error}", file=sys.stderr, flush=True)
        sys.exit(1)
