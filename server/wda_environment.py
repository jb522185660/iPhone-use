"""Find already installed command-line dependencies in desktop app environments."""
import os
from pathlib import Path
import shutil


def prepare_environment():
    """Fill a GUI's sparse PATH without overriding the host's selected tools."""
    current_path = os.environ.get("PATH", os.defpath)
    current = current_path.split(os.pathsep)
    candidates = []
    nvm = Path(os.environ.get("NVM_DIR", str(Path.home() / ".nvm")))
    for directory in (nvm / "versions/node").glob("v*/bin"):
        try:
            version = tuple(int(part) for part in directory.parent.name[1:].split("."))
        except ValueError:
            continue
        if len(version) == 3 and ((version[0] == 20 and version[1] >= 19)
                or (version[0] == 22 and version[1] >= 12) or version[0] >= 24):
            if (directory / "node").is_file() and os.access(directory / "node", os.X_OK):
                candidates.append((version, directory))
    additions = []
    if not shutil.which("node") and candidates:
        additions.append(str(max(candidates)[1]))
    additions.extend(path for path in ("/opt/homebrew/bin", "/usr/local/bin") if Path(path).is_dir())
    additions = [path for path in additions if path not in current]
    os.environ["PATH"] = current_path + (os.pathsep + os.pathsep.join(additions) if additions else "")
    return os.environ["PATH"]
