#!/bin/sh
set -eu
task_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
python3 "$task_root/scripts/package.py" --stage-only
codex plugin marketplace add "$task_root" --json
task_installation=$(python3 "$task_root/scripts/install_plugin.py")
printf '%s\n' "$task_installation" | python3 "$task_root/scripts/register_mcp.py"
task_installed_root=$(printf '%s\n' "$task_installation" | python3 -c 'import json,sys; print(json.load(sys.stdin)["installedPath"])')
python3 "$task_installed_root/scripts/launch_screen.py" --install-desktop
printf '%s\n' 'Reconnect the Codex chat to load iPhone Use tools and skills.'
