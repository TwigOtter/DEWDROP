#!/usr/bin/env python
"""Create the SQLite schema. Idempotent."""
from dewdrop import config
from dewdrop.db import init_db

if __name__ == "__main__":
    init_db()
    print(f"Initialized DEWDROP database at {config.DB_PATH}")
