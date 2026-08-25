#!/usr/bin/env python3
"""Index sample telemetry into each ARCH-02 retention class / schema stream."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from elasticsearch.helpers import bulk

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from client import ROGUE_STREAM, STREAMS, get_client  # noqa: E402

TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
SPAN_ID = "00f067aa0ba902b7"
WELL_ID = "8321"


def now_iso(offset_minutes: int = 0) -> str:
    ts = datetime.now(timezone.utc) - timedelta(minutes=offset_minutes)
    return ts.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def ecs_app_docs() -> list[tuple[str, dict]]:
    docs = []
    for i, level in enumerate(("INFO", "WARN", "ERROR", "INFO", "ERROR")):
        status = 500 if level == "ERROR" else 200 if level == "INFO" else 404
        docs.append(
            (
                STREAMS["app_ecs"],
                {
                    "@timestamp": now_iso(i),
                    "message": "survey lookup failed: upstream timeout"
                    if level == "ERROR"
                    else "request completed",
                    "log": {"level": level},
                    "service": {"name": "well-data-api", "environment": "prod", "version": "1.8.2"},
                    "trace": {"id": TRACE_ID},
                    "span": {"id": SPAN_ID},
                    "http": {
                        "request": {"method": "GET"},
                        "response": {"status_code": status},
                    },
                    "url": {"path": "/v2/wells/8321/surveys"},
                    "slb": {"well_id": WELL_ID},
                    "labels": {"team": "drilling-apps"},
                },
            )
        )
    docs.append(
        (
            STREAMS["app_nonprod"],
            {
                "@timestamp": now_iso(1),
                "message": "nonprod survey lookup",
                "log": {"level": "INFO"},
                "service": {"name": "well-data-api", "environment": "nonprod"},
                "trace": {"id": TRACE_ID},
                "labels": {"team": "drilling-apps"},
            },
        )
    )
    return docs


def otel_app_docs() -> list[tuple[str, dict]]:
    docs = []
    for i, severity in enumerate(("INFO", "WARN", "ERROR", "INFO", "ERROR")):
        docs.append(
            (
                STREAMS["app_otel"],
                {
                    "@timestamp": now_iso(i),
                    "body": {
                        "text": "survey lookup failed: upstream timeout"
                        if severity == "ERROR"
                        else "request completed"
                    },
                    "severity_text": severity,
                    "severity_number": {"INFO": 9, "WARN": 13, "ERROR": 17}[severity],
                    "trace_id": TRACE_ID,
                    "span_id": SPAN_ID,
                    "resource": {
                        "attributes": {
                            "service.name": "well-data-api",
                            "service.version": "1.8.2",
                            "deployment.environment": "prod",
                        }
                    },
                    "attributes": {
                        "http.request.method": "GET",
                        "http.response.status_code": 500 if severity == "ERROR" else 200,
                        "url.path": "/v2/wells/8321/surveys",
                    },
                    "labels": {"team": "drilling-apps"},
                },
            )
        )
    return docs


def audit_docs() -> list[tuple[str, dict]]:
    return [
        (
            STREAMS["audit"],
            {
                "@timestamp": now_iso(3),
                "message": "role change: drilling-apps granted dataset.create",
                "event": {"action": "iam.role.update", "outcome": "success"},
                "user": {"name": "platform-admin"},
                "log": {"level": "INFO"},
                "service": {"name": "identity-service"},
            },
        ),
        (
            STREAMS["audit"],
            {
                "@timestamp": now_iso(2),
                "message": "API key created for well-data-api",
                "event": {"action": "security.api_key.create", "outcome": "success"},
                "user": {"name": "arch-02-workshop"},
                "log": {"level": "INFO"},
                "service": {"name": "identity-service"},
            },
        ),
    ]


def metrics_docs() -> list[tuple[str, dict]]:
    docs = []
    for i, host in enumerate(("aks-arch-01", "aks-arch-02", "aks-arch-03")):
        docs.append(
            (
                STREAMS["metrics"],
                {
                    "@timestamp": now_iso(i),
                    "metricset": {"name": "cpu"},
                    "host": {"name": host},
                    "system": {"cpu": {"total": {"norm": {"pct": 0.12 + i * 0.07}}}},
                    "service": {"name": "node-exporter"},
                },
            )
        )
    return docs


def trace_docs() -> list[tuple[str, dict]]:
    return [
        (
            STREAMS["traces"],
            {
                "@timestamp": now_iso(0),
                "trace": {"id": TRACE_ID},
                "span": {"id": SPAN_ID, "name": "GET /v2/wells/8321/surveys", "duration": {"us": 842000}},
                "service": {"name": "well-data-api"},
                "event": {"outcome": "failure"},
                "http": {"response": {"status_code": 500}},
            },
        )
    ]


def rogue_docs() -> list[tuple[str, dict]]:
    return [
        (
            ROGUE_STREAM,
            {
                "@timestamp": now_iso(0),
                "message": "unsanctioned dataset — no central template",
                "service_name": "mud-logger",
                "lvl": "err",
            },
        )
    ]


def index_pairs(pairs: list[tuple[str, dict]]) -> tuple[int, int]:
    es = get_client()
    actions = (
        {"_op_type": "create", "_index": stream, "_source": doc} for stream, doc in pairs
    )
    ok, errors = bulk(
        es,
        actions,
        chunk_size=200,
        refresh="wait_for",
        raise_on_error=False,
    )
    nerr = len(errors) if errors else 0
    print(f"indexed={ok} errors={nerr}")
    if errors:
        print(errors[:3])
    return ok, nerr


def main() -> None:
    pairs = (
        ecs_app_docs()
        + otel_app_docs()
        + audit_docs()
        + metrics_docs()
        + trace_docs()
        + rogue_docs()
    )
    _, nerr = index_pairs(pairs)
    if nerr:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
