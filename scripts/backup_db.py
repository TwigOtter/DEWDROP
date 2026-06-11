#!/usr/bin/env python3
"""Nightly SQLite backup with simple retention.

Uses sqlite3's online backup API (safe against concurrent writers under WAL)
to copy the live DB to DEWDROP_BACKUP_DIR, then prunes everything but the
newest DEWDROP_BACKUP_KEEP copies. Run by dewdrop-backup.timer.

The accumulated forecast/error history is the whole value of this project —
point DEWDROP_BACKUP_DIR at a different disk or synced folder if you can.
"""
import sqlite3
import sys

from dewdrop import config


def main() -> None:
    src_path = config.DB_PATH
    if not src_path.exists():
        print(f"No database at {src_path} — nothing to back up.", file=sys.stderr)
        sys.exit(1)

    config.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = config.local_today().isoformat()
    dest_path = config.BACKUP_DIR / f"dewdrop-{stamp}.sqlite3"

    src = sqlite3.connect(src_path)
    dest = sqlite3.connect(dest_path)
    try:
        with dest:
            src.backup(dest)
    finally:
        dest.close()
        src.close()
    size_mb = dest_path.stat().st_size / 1e6
    print(f"Backed up {src_path} -> {dest_path} ({size_mb:.1f} MB)")

    backups = sorted(config.BACKUP_DIR.glob("dewdrop-*.sqlite3"))
    for old in backups[:-config.BACKUP_KEEP]:
        old.unlink()
        print(f"Pruned {old.name}")


if __name__ == "__main__":
    main()
