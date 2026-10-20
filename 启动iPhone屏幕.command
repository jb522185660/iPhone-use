#!/bin/sh
# iPhone Use manual launcher; run after installation and initial device setup.
task_root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd) || exit 1

task_launch() {
    if [ ! -f "$task_root/scripts/launch_screen.py" ]; then
        printf '%s\n' '找不到 iPhone Use 启动程序，请保留完整项目目录，或重新生成桌面快捷方式。' >&2
        return 1
    fi
    for task_python in /Library/Frameworks/Python.framework/Versions/Current/bin/python3 /opt/homebrew/bin/python3 /usr/local/bin/python3 python3; do
        if command -v "$task_python" >/dev/null 2>&1; then
            "$task_python" "$task_root/scripts/launch_screen.py" "$@"
            return $?
        fi
    done
    printf '%s\n' '找不到 Python，请检查 iPhone Use 安装。' >&2
    return 1
}

task_launch "$@"
task_result=$?
if [ -t 0 ]; then printf '\n按回车关闭窗口……'; read -r task_response; fi
exit "$task_result"
