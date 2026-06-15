#!/usr/bin/env python3
"""One-off cleanup of forecast_errors rows that no longer get written.

Removes:
  1. Rows scored against any actuals source other than the primary ground
     truth (scoring is now anchored on a single authority — asos_mci by
     default). The secondary station data still drives the microclimate
     offset; it just doesn't belong in the bias/error history.
  2. Rows with a negative horizon (forecast snapshots mistakenly taken after
     the target day, an artifact of the old UTC-rollover bug).

The underlying forecasts/actuals rows are untouched, so this is recoverable:
re-scoring with the old code would regenerate the rows.

Usage: python scripts/prune_errors.py [--dry-run]
"""
import sys

from dewdrop import config
from dewdrop.db import connect


def main() -> None:
    dry_run = "--dry-run" in sys.argv
    primary = config.ENABLED_ACTUALS[0]
    with connect() as conn:
        non_primary = conn.execute(
            "SELECT COUNT(*) AS n FROM forecast_errors WHERE actuals_source != ?",
            (primary,),
        ).fetchone()["n"]
        negative = conn.execute(
            "SELECT COUNT(*) AS n FROM forecast_errors "
            "WHERE actuals_source = ? AND horizon_days < 0",
            (primary,),
        ).fetchone()["n"]
        print(f"forecast_errors rows not against '{primary}': {non_primary}")
        print(f"forecast_errors rows with negative horizon:   {negative}")
        if dry_run:
            print("Dry run — nothing deleted.")
            return
        conn.execute(
            "DELETE FROM forecast_errors WHERE actuals_source != ? "
            "OR horizon_days < 0",
            (primary,),
        )
    print(f"Deleted {non_primary + negative} row(s).")


if __name__ == "__main__":
    main()
