#!/usr/bin/env python3
"""Install the Codex plugin without removing files used by existing chats."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


PLUGIN_ID = "iphone-use@iphone-use-local"
VERSION = re.compile(r"\d+\.\d+\.\d+")


def cache_directory():
    home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser().resolve()
    path = home
    for part in ("plugins", "cache", "iphone-use-local", "iphone-use"):
        path = path / part
        if path.is_symlink():
            raise RuntimeError(f"Refusing a symlink in the plugin cache path: {path}")
    return path


def snapshot_versions(cache, backup):
    versions = []
    if not cache.exists():
        return versions
    for source in sorted(cache.iterdir()):
        manifest = source / "plugin.json"
        if (not VERSION.fullmatch(source.name) or source.is_symlink() or not source.is_dir()
                or manifest.is_symlink() or not manifest.is_file()):
            continue
        try:
            owned = json.loads(manifest.read_text()).get("name") == "iphone-use"
        except (ValueError, AttributeError, UnicodeError):
            owned = False
        if owned:
            # Preserve links as links; never copy their external targets.
            shutil.copytree(source, backup / source.name, symlinks=True)
            versions.append(source.name)
    return versions


def restore_versions(cache, backup, versions):
    for version in versions:
        target = cache / version
        # The installer owns new and replaced versions, including same-version updates.
        if os.path.lexists(target):
            continue
        cache.mkdir(parents=True, exist_ok=True)
        shutil.copytree(backup / version, target, symlinks=True)


def install_plugin():
    cache = cache_directory()
    backup = Path(tempfile.mkdtemp(prefix="iphone-use-plugin-cache-"))
    try:
        versions = snapshot_versions(cache, backup)
    except BaseException:
        shutil.rmtree(backup)
        raise
    try:
        # Inherit stdout/stderr so install.sh receives the original JSON result.
        return subprocess.run(["codex", "plugin", "add", PLUGIN_ID, "--json"], check=False).returncode
    finally:
        try:
            if cache_directory() != cache:
                raise RuntimeError("The plugin cache location changed during installation.")
            restore_versions(cache, backup, versions)
        except BaseException:
            print(f"Plugin cache recovery is incomplete; the backup is retained at {backup}", file=sys.stderr)
            raise
        else:
            shutil.rmtree(backup)


if __name__ == "__main__":
    sys.exit(install_plugin())
