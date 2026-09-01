"""Shared helpers for generators."""
import math
from datetime import datetime, timedelta, timezone

AGENT_ID = "6f0b45cf-9a3e-4c1d-8b2a-7e5d4c3b2a10"


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def isos(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def poisson_count(rng, lam: float) -> int:
    """Cheap poisson-ish integer draw."""
    n = int(lam)
    if rng.random() < lam - n:
        n += 1
    return n


def spread(rng, t0: datetime, t1: datetime) -> datetime:
    secs = (t1 - t0).total_seconds()
    return t0 + timedelta(seconds=rng.random() * secs)


def aligned(t0: datetime, t1: datetime, minutes: int):
    """Timestamps aligned to `minutes` boundaries within [t0, t1)."""
    step = minutes * 60
    t = math.ceil(t0.timestamp() / step) * step
    out = []
    while t < t1.timestamp():
        out.append(datetime.fromtimestamp(t, tz=timezone.utc))
        t += step
    return out


def log_doc(dataset: str, ts: datetime, message: str) -> dict:
    return {
        "@timestamp": iso(ts),
        "data_stream": {"type": "logs", "dataset": dataset, "namespace": "default"},
        "message": message,
        "tags": ["preserve_original_event", "synthetic"],
    }


def metric_doc(dataset: str, ts: datetime, metricset: str, period_ms: int) -> dict:
    module = dataset.split(".")[0]
    return {
        "@timestamp": iso(ts),
        "data_stream": {"type": "metrics", "dataset": dataset, "namespace": "default"},
        "agent": {"type": "metricbeat", "version": "9.2.0",
                  "name": "synthetic-poller", "id": AGENT_ID},
        "event": {"dataset": dataset, "module": module, "duration": 115000000},
        "metricset": {"name": metricset, "period": period_ms},
        "service": {"type": module},
        "ecs": {"version": "8.0.0"},
    }
