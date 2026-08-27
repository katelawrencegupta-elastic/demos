"""Shared generator helpers."""
from datetime import datetime, timedelta, timezone

from src.world.model import iso


def hour_slices(t0: datetime, t1: datetime):
    cur = t0.replace(minute=0, second=0, microsecond=0)
    if cur < t0:
        cur += timedelta(hours=1)
    while cur < t1:
        nxt = min(cur + timedelta(hours=1), t1)
        if cur < nxt:
            yield cur, nxt
        cur = nxt


def in_incident(ts: datetime, start: datetime, end: datetime) -> bool:
    return start <= ts <= end


def ds_meta(type_: str, dataset: str, namespace: str = "default") -> dict:
    return {"type": type_, "dataset": dataset, "namespace": namespace}


def base_labels() -> dict:
    return {"demo": "elastic-co"}


def ensure_utc(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


__all__ = ["hour_slices", "in_incident", "ds_meta", "base_labels", "ensure_utc", "iso"]
