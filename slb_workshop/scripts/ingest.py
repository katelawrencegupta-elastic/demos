#!/usr/bin/env python3
"""Index sample platform logs into the workshop data stream.

    .venv/bin/python scripts/ingest.py
    .venv/bin/python scripts/ingest.py --days 7 --every 60
"""

from __future__ import annotations

import argparse
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from elasticsearch.helpers import bulk

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from client import DATA_STREAM, get_client  # noqa: E402

SERVICES = (
    "well-data-api",
    "telemetry-gateway",
    "identity-service",
    "rig-scheduler",
)
HOSTS = ("aks-sre-01", "aks-sre-02", "aks-sre-03")
# Public DNS / RIR addresses so GeoIP on host.ip plots on the workshop maps.
PUBLIC_HOST_IPS = (
    "8.8.8.8",
    "8.8.4.4",
    "208.67.222.222",
    "94.140.14.14",
    "77.88.8.8",
    "168.95.1.1",
    "200.160.0.8",
    "196.216.2.1",
    "101.101.101.101",
    "80.67.169.12",
    "202.12.27.33",
    "139.130.4.5",
    "84.200.69.80",
    "4.2.2.1",
    "193.19.64.8",
    "41.204.63.58",
)
TEAMS = ("platform", "drilling-apps", "identity")
PATHS = (
    "/v2/wells/8321/surveys",
    "/v2/wells/1044/logs",
    "/health",
    "/v1/auth/token",
    "/v1/jobs/schedule",
)

JSON_TEMPLATES = (
    '{{"service":{{"name":"{service}","environment":"prod","version":"1.8.2"}},'
    '"host":{{"name":"{host}","ip":"{ip}"}},"log":{{"level":"{level}"}},'
    '"http":{{"request":{{"method":"{method}"}},"response":{{"status_code":{status}}}}},'
    '"url":{{"path":"{path}"}},"labels":{{"team":"{team}"}},'
    '"message":"{msg}"}}'
)

GROK_LINES = (
    "{ts} WARN [telemetry-gateway] retrying kafka produce topic=rig.metrics partition={part}",
    "{ts} INFO [rig-scheduler] assigned job well_id={well} crew=night",
    "{ts} ERROR [identity-service] token exchange failed client_id=sre-workshop",
)


def schedule(
    *,
    count: int | None = None,
    days: float | None = None,
    every: float = 60.0,
) -> list[datetime]:
    now = datetime.now(timezone.utc)
    if days:
        start = now - timedelta(days=days)
        n = max(1, int((now - start).total_seconds() / every))
        return [start + timedelta(seconds=i * every) for i in range(n)]
    total = count if count is not None else 40
    return [now - timedelta(minutes=total - i) for i in range(total)]


def _status_for(i: int, ts: datetime, rng: random.Random, patterned: bool) -> int:
    if not patterned:
        return 500 if i % 11 == 0 else 200 if i % 3 else 201 if i % 7 else 404
    hour = ts.hour
    error_p = 0.14 if 8 <= hour < 18 else 0.05
    miss_p = 0.08
    roll = rng.random()
    if roll < error_p:
        return 500
    if roll < error_p + miss_p:
        return 404
    if roll < error_p + miss_p + 0.10:
        return 201
    return 200


def events(
    count: int | None = None,
    days: float | None = None,
    every: float = 60.0,
    rng: random.Random | None = None,
) -> list[dict]:
    rng = rng or random.Random()
    patterned = days is not None
    docs: list[dict] = []
    for i, ts in enumerate(schedule(count=count, days=days, every=every)):
        if patterned and not _in_load_window(ts, rng):
            continue
        ts_iso = ts.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        service = SERVICES[i % len(SERVICES)]
        grok = (i % 5 == 0) if not patterned else rng.random() < 0.18
        if grok:
            line = GROK_LINES[i % len(GROK_LINES)].format(
                ts=ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
                part=i % 8,
                well=8000 + i,
            )
            docs.append({"@timestamp": ts_iso, "message": line})
            continue
        status = _status_for(i, ts, rng, patterned)
        level = "ERROR" if status >= 500 else "WARN" if status >= 400 else "INFO"
        msg = {
            200: "request completed",
            201: "job accepted",
            404: "well not found",
            500: "survey lookup failed: upstream timeout",
        }[status]
        payload = JSON_TEMPLATES.format(
            service=service,
            host=rng.choice(HOSTS),
            ip=rng.choice(PUBLIC_HOST_IPS),
            level=level,
            method="GET" if status != 201 else "POST",
            status=status,
            path=rng.choice(PATHS),
            team=rng.choice(TEAMS),
            msg=msg,
        )
        docs.append({"@timestamp": ts_iso, "message": payload})
    return docs


def _in_load_window(ts: datetime, rng: random.Random) -> bool:
    hour = ts.hour
    if 0 <= hour < 6:
        return rng.random() < 0.22
    if hour < 8 or hour >= 21:
        return rng.random() < 0.50
    return True


def index_docs(docs: list[dict], stream: str = DATA_STREAM) -> tuple[int, int]:
    es = get_client()
    actions = (
        {"_op_type": "create", "_index": stream, "_source": doc} for doc in docs
    )
    ok, errors = bulk(
        es,
        actions,
        chunk_size=500,
        refresh="wait_for",
        raise_on_error=False,
    )
    nerr = len(errors) if errors else 0
    print(f"indexed={ok} errors={nerr} stream={stream}")
    if errors:
        print(errors[:3])
    return ok, nerr


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=40, help="recent events when --days is omitted")
    parser.add_argument("--days", type=float, default=None, help="spread events over N days")
    parser.add_argument(
        "--every",
        type=float,
        default=60.0,
        help="seconds between candidate events when --days is set",
    )
    args = parser.parse_args()
    docs = events(count=args.count, days=args.days, every=args.every)
    _, nerr = index_docs(docs)
    if nerr:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
