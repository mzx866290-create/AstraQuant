#!/usr/bin/env python
"""Legacy compatibility wrapper. Use scripts/start_local.py for local dev."""
from scripts.legacy.compat import main


if __name__ == "__main__":
    raise SystemExit(main("run_simple_api.py"))
