#!/usr/bin/env python
"""Nightly scoring (design doc §4, Phase 2): compute & store forecast errors.

Run by the `dewdrop-score` timer after actuals have been ingested. Scores every
forecast whose target_date now has an actuals row and isn't scored yet.
"""
import logging

from dewdrop.db import connect
from dewdrop.scoring import score_pending

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("dewdrop.score")


def main() -> None:
    with connect() as conn:
        written = score_pending(conn)
    log.info("Scored %d newly-verifiable forecast(s)", written)


if __name__ == "__main__":
    main()
