#!/usr/bin/env python3
"""Index sample platform logs into the workshop data stream."""

from __future__ import annotations

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
    '"host":{{"name":"{host}"}},"log":{{"level":"{level}"}},'
    '"http":{{"request":{{"method":"{method}"}},"response":{{"status_code":{status}}}}},'
    '"url":{{"path":"{path}"}},"labels":{{"team":"{team}"}},'
    '"message":"{msg}"}}'
)

GROK_LINES = (
    "{ts} WARN [telemetry-gateway] retrying kafka produce topic=rig.metrics partition={part}",
    "{ts} INFO [rig-scheduler] assigned job well_id={well} crew=night",
    "{ts} ERROR [identity-service] token exchange failed client_id=sre-workshop",
)


def events(count: int = 40) -> list[dict]:
    now = datetime.now(timezone.utc)
    docs: list[dict] = []
    for i in range(count):
        ts = now - timedelta(minutes=count - i)
        ts_iso = ts.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        service = SERVICES[i % len(SERVICES)]
        if i % 5 == 0:
            line = GROK_LINES[i % len(GROK_LINES)].format(
                ts=ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
                part=i % 8,
                well=8000 + i,
            )
            docs.append({"@timestamp": ts_iso, "message": line})
            continue
        status = 500 if i % 11 == 0 else 200 if i % 3 else 201 if i % 7 else 404
        level = "ERROR" if status >= 500 else "WARN" if status >= 400 else "INFO"
        msg = {
            200: "request completed",
            201: "job accepted",
            404: "well not found",
            500: "survey lookup failed: upstream timeout",
        }[status]
        payload = JSON_TEMPLATES.format(
            service=service,
            host=random.choice(HOSTS),
            level=level,
            method="GET" if status != 201 else "POST",
            status=status,
            path=random.choice(PATHS),
            team=random.choice(TEAMS),
            msg=msg,
        )
        docs.append({"@timestamp": ts_iso, "message": payload})
    return docs


def main() -> None:
    es = get_client()
    docs = events()
    actions = (
        {"_op_type": "create", "_index": DATA_STREAM, "_source": doc} for doc in docs
    )
    ok, errors = bulk(es, actions, refresh="wait_for", raise_on_error=False)
    print(f"indexed={ok} errors={len(errors) if errors else 0} stream={DATA_STREAM}")
    if errors:
        print(errors[:3])
        raise SystemExit(1)


if __name__ == "__main__":
    main()
