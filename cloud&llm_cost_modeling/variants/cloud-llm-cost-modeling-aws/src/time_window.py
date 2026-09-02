"""Shared demo time window aligned with relative backfill/stream anchors."""
from datetime import timedelta

from src.world.scenarios import utcnow

# Default matches CLI backfill --days 120 (~4 months)
DEMO_DAYS = 120


def demo_window(days: int = DEMO_DAYS, to_pad_days: int = 0) -> dict:
    """Return Kibana time_range {from, to} covering [utcnow()-days, utcnow()+pad].

    Absolute timestamps are computed at publish/setup time so stored dashboards
    match a fresh backfill. Republish after backfill to refresh the window.
    """
    anchor = utcnow()
    start = anchor - timedelta(days=days)
    end = anchor + timedelta(days=to_pad_days)
    return {
        "from": start.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "to": end.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
    }


def window_label(days: int = DEMO_DAYS, to_pad_days: int = 0) -> str:
    w = demo_window(days=days, to_pad_days=to_pad_days)
    return f"{w['from'][:10]} – {w['to'][:10]} (computed at publish)"
