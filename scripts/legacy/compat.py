"""Compatibility helpers for historical root startup scripts."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OFFICIAL_LOCAL_START = ROOT / "scripts" / "start_local.py"


def main(script_name: str) -> int:
    print(f"{script_name} is a legacy compatibility wrapper.")
    print("Official local startup: python scripts/start_local.py")
    print("Official container startup: docker compose up -d")
    print()
    print("Delegating to scripts/start_local.py...")
    return subprocess.call([sys.executable, str(OFFICIAL_LOCAL_START)], cwd=str(ROOT))
