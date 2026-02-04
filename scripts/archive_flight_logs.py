#!/usr/bin/env python3
"""
Compatibility wrapper for the flight log archiver.

Canonical implementation lives at:
  architecture/1-ground-truth/scripts/archive_flight_logs.py

Some docs reference `python3 scripts/archive_flight_logs.py`, so keep this thin
wrapper to avoid drift.
"""

from __future__ import annotations

import runpy
from pathlib import Path


def main() -> int:
    script = (
        Path(__file__).resolve().parents[1]
        / "architecture/1-ground-truth/scripts/archive_flight_logs.py"
    )
    runpy.run_path(str(script), run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

