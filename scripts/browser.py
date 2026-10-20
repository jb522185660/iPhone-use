#!/usr/bin/env python3
"""Start, inspect or stop the local iPhone browser panel."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
from wda_browser import main

if __name__ == "__main__":
    sys.exit(main())
