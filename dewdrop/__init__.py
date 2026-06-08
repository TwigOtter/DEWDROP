"""DEWDROP — Demonic Environmental Weather Detection, Reporting, and Observation Project.

Polls forecasts from multiple weather services, stores them in SQLite, compares
against actual readings from an EcoWitt GW2000 station, scores per-service error,
and produces bias-corrected forecasts.
"""

__version__ = "0.1.0"
