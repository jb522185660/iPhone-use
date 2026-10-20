#!/bin/sh
set -eu
task_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
for task_python in /Library/Frameworks/Python.framework/Versions/Current/bin/python3 /opt/homebrew/bin/python3 /usr/local/bin/python3 python3; do
    if command -v "$task_python" >/dev/null 2>&1; then
        exec "$task_python" "$task_root/server/iphone_use.py" "$@"
    fi
done
printf '%s\n' 'Python 3.9 or newer is required.' >&2
exit 1
