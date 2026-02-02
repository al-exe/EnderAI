#!/usr/bin/env python3

from __future__ import annotations

import argparse
import datetime as dt
import shutil
import sys
from pathlib import Path


DEFAULT_ACTIVE_DIR = Path("architecture/3-task-context/flight-logs")
DEFAULT_ARCHIVE_DIR = Path("architecture/1-ground-truth/flight-logs/archive")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Archive daily flight logs older than N days (UTC) from Layer 3 into Layer 1."
        )
    )
    parser.add_argument(
        "--active-dir",
        type=Path,
        default=DEFAULT_ACTIVE_DIR,
        help=f"Directory containing active daily logs (default: {DEFAULT_ACTIVE_DIR})",
    )
    parser.add_argument(
        "--archive-dir",
        type=Path,
        default=DEFAULT_ARCHIVE_DIR,
        help=f"Directory to move archived logs into (default: {DEFAULT_ARCHIVE_DIR})",
    )
    parser.add_argument(
        "--keep-days",
        type=int,
        default=7,
        help="Keep logs whose age in days is <= keep-days (default: 7)",
    )
    parser.add_argument(
        "--now-utc-date",
        type=str,
        default=None,
        help="Override today's UTC date (YYYY-MM-DD) for testing",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would move without modifying the filesystem",
    )
    return parser.parse_args()


def utc_today(override: str | None) -> dt.date:
    if override is None:
        return dt.datetime.now(dt.timezone.utc).date()
    return dt.date.fromisoformat(override)


def parse_log_date(path: Path) -> dt.date | None:
    # Expected: YYYY-MM-DD.mdc
    if path.suffix != ".mdc":
        return None
    try:
        return dt.date.fromisoformat(path.stem)
    except ValueError:
        return None


def unique_destination_path(destination: Path) -> Path:
    if not destination.exists():
        return destination

    stem = destination.stem
    suffix = destination.suffix
    parent = destination.parent

    for i in range(1, 1000):
        candidate = parent / f"{stem}.dup{i}{suffix}"
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Could not find a free destination name for {destination}")


def main() -> int:
    args = parse_args()

    if args.keep_days < 0:
        print("--keep-days must be >= 0", file=sys.stderr)
        return 2

    today = utc_today(args.now_utc_date)
    active_dir: Path = args.active_dir
    archive_dir: Path = args.archive_dir

    if not active_dir.exists():
        print(f"No active dir found at {active_dir}; nothing to archive.")
        return 0

    candidates = sorted(active_dir.iterdir())
    to_archive: list[tuple[Path, dt.date, int]] = []
    skipped = 0

    for path in candidates:
        if not path.is_file():
            continue
        log_date = parse_log_date(path)
        if log_date is None:
            skipped += 1
            continue

        age_days = (today - log_date).days
        if age_days > args.keep_days:
            to_archive.append((path, log_date, age_days))

    moved = 0
    for src, log_date, age_days in to_archive:
        bucket = log_date.strftime("%Y-%m")
        dest_dir = archive_dir / bucket
        dest_dir.mkdir(parents=True, exist_ok=True)

        dest = unique_destination_path(dest_dir / src.name)

        action = "WOULD MOVE" if args.dry_run else "MOVE"
        print(f"{action}: {src} -> {dest}  (age={age_days}d, today={today})")

        if not args.dry_run:
            shutil.move(str(src), str(dest))
            moved += 1

    print(
        f"Done. moved={moved} eligible={len(to_archive)} skipped={skipped} keep_days={args.keep_days}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
