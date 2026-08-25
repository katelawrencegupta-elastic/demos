#!/usr/bin/env python3
"""Backfill workshop streams with N days of synthetic telemetry.

    .venv/bin/python scripts/backfill.py --days 7
"""

from __future__ import annotations

import argparse
import random
import secrets
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "edot"))
sys.path.insert(0, str(ROOT / "agents"))

from elasticsearch.helpers import bulk

from client import get_client  # noqa: E402
from ingest import HOSTS, PUBLIC_HOST_IPS, SERVICES, events, index_docs  # noqa: E402
from syslog_events import next_event  # noqa: E402
from syslog_factory import backfill as syslog_file_backfill  # noqa: E402

OTEL_LOGS = "logs-workshop.otel.otel-default"
OTEL_SYSLOG = "logs-system.auth.otel-default"
OTEL_TRACES = "traces-workshop.otel.otel-default"
OTEL_METRICS = "metrics-workshop.otel.otel-default"
# Serverless OTel metrics are TSDS with ~2h look-back; older docs land in the failure store.
METRICS_LOOKBACK_HOURS = 2.0

ROUTES = {
    "well-data-api": ("/v2/wells/{well}/surveys", "/v2/wells/{well}/logs"),
    "telemetry-gateway": ("/v1/ingest", "/health"),
    "identity-service": ("/v1/auth/token", "/v1/auth/jwks"),
    "rig-scheduler": ("/v1/jobs/schedule", "/v1/jobs/{job}"),
}
SERVICE_TEAMS = {
    "well-data-api": "drilling-apps",
    "telemetry-gateway": "platform",
    "identity-service": "identity",
    "rig-scheduler": "platform",
}


def resource_attrs(host: str, service: str, rng: random.Random, extra: dict | None = None) -> dict:
    attrs = {
        "deployment.environment": "workshop",
        "host.name": host,
        "host.ip": rng.choice(PUBLIC_HOST_IPS),
        "service.name": service,
        "service.version": "8.2312.0" if service == "rsyslog" else "1.8.2",
        "team": SERVICE_TEAMS.get(service, "platform"),
        "telemetry.sdk.language": "python",
        "telemetry.sdk.name": "opentelemetry",
        "telemetry.sdk.version": "1.44.0",
    }
    if extra:
        attrs.update(extra)
    return attrs


def iso(ts: datetime) -> str:
    return ts.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def walk(days: float, every: float) -> list[datetime]:
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days)
    n = max(1, int((now - start).total_seconds() / every))
    return [start + timedelta(seconds=i * every) for i in range(n)]


def load_keep(ts: datetime, rng: random.Random) -> bool:
    hour = ts.hour
    if hour < 6:
        return rng.random() < 0.22
    if hour < 8 or hour >= 21:
        return rng.random() < 0.50
    return True


def http_status(ts: datetime, rng: random.Random) -> int:
    error_p = 0.14 if 8 <= ts.hour < 18 else 0.05
    roll = rng.random()
    if roll < error_p:
        return 500
    if roll < error_p + 0.08:
        return 404
    if roll < error_p + 0.18:
        return 201
    return 200


def otel_http_log(ts: datetime, rng: random.Random) -> dict:
    service = rng.choice(SERVICES)
    host = rng.choice(HOSTS)
    status = http_status(ts, rng)
    route = rng.choice(ROUTES[service])
    path = route.format(well=8000 + rng.randint(0, 200), job=rng.randint(100, 999))
    if status >= 500:
        body, sev_text, sev_num = (
            f"survey lookup failed: upstream timeout path={path} status={status}",
            "ERROR",
            17,
        )
    elif status >= 400:
        body, sev_text, sev_num = f"well not found path={path} status={status}", "WARN", 13
    else:
        body, sev_text, sev_num = f"request completed path={path} status={status}", "INFO", 9
    stamp = iso(ts)
    return {
        "@timestamp": stamp,
        "observed_timestamp": stamp,
        "body": {"text": body},
        "severity_text": sev_text,
        "severity_number": sev_num,
        "span_id": secrets.token_hex(8),
        "trace_id": secrets.token_hex(16),
        "data_stream": {
            "type": "logs",
            "dataset": "workshop.otel.otel",
            "namespace": "default",
        },
        "resource": {
            "attributes": resource_attrs(host, service, rng)
        },
        "scope": {"name": f"workshop.{service}"},
        "attributes": {
            "http.request.method": "POST" if status == 201 else "GET",
            "url.path": path,
            "http.response.status_code": status,
        },
    }


def otel_syslog_log(ts: datetime, rng: random.Random) -> dict:
    host = rng.choice(HOSTS)
    body, attrs, severity = next_event(host, rng, ts)
    stamp = iso(ts)
    return {
        "@timestamp": stamp,
        "observed_timestamp": stamp,
        "body": {"text": body},
        "severity_text": severity.name,
        "severity_number": int(severity.value),
        "data_stream": {
            "type": "logs",
            "dataset": "system.auth.otel",
            "namespace": "default",
        },
        "resource": {
            "attributes": resource_attrs(host, "rsyslog", rng)
        },
        "scope": {"name": "sre-01-syslog"},
        "attributes": attrs,
    }


def otel_metric(ts: datetime, rng: random.Random) -> dict:
    service = rng.choice(SERVICES)
    host = rng.choice(HOSTS)
    status = http_status(ts, rng)
    stamp = iso(ts)
    return {
        "@timestamp": stamp,
        "start_timestamp": stamp,
        "unit": "{request}",
        "temporality": "cumulative",
        "data_stream": {
            "type": "metrics",
            "dataset": "workshop.otel.otel",
            "namespace": "default",
        },
        "resource": {
            "attributes": resource_attrs(host, service, rng)
        },
        "scope": {"name": "sre-01-factory"},
        "attributes": {
            "http.request.method": "POST" if status == 201 else "GET",
            "http.response.status_code": status,
        },
        "metrics": {"http.server.request.total": 1.0},
    }


def otel_trace(ts: datetime, rng: random.Random) -> dict:
    service = rng.choice(SERVICES)
    host = rng.choice(HOSTS)
    status = http_status(ts, rng)
    route = rng.choice(ROUTES[service])
    path = route.format(well=8000 + rng.randint(0, 200), job=rng.randint(100, 999))
    method = "POST" if status == 201 else "GET"
    duration_us = max(80, int(rng.gauss(120 if status < 500 else 1400, 40)))
    span_id = secrets.token_hex(8)
    stamp = iso(ts)
    outcome = "failure" if status >= 500 else "success"
    family = f"HTTP {status // 100}xx"
    return {
        "@timestamp": stamp,
        "duration": duration_us * 1000,
        "kind": "Server",
        "links": [],
        "name": f"{method} {route}",
        "span_id": span_id,
        "trace_id": secrets.token_hex(16),
        "data_stream": {
            "type": "traces",
            "dataset": "workshop.otel.otel",
            "namespace": "default",
        },
        "resource": {
            "attributes": resource_attrs(
                host,
                service,
                rng,
                extra={
                    "agent.name": "opentelemetry/python",
                    "agent.version": "1.44.0",
                },
            )
        },
        "scope": {
            "name": "sre-01-factory",
            "attributes": {
                "service.framework.name": "sre-01-factory",
                "service.framework.version": "",
            },
        },
        "attributes": {
            "event.outcome": outcome,
            "event.success_count": 0 if status >= 500 else 1,
            "http.request.method": method,
            "http.response.status_code": status,
            "http.route": route,
            "processor.event": "transaction",
            "server.address": service,
            "timestamp.us": int(ts.timestamp() * 1_000_000),
            "transaction.duration.us": duration_us,
            "transaction.id": span_id,
            "transaction.name": f"{method} {route}",
            "transaction.representative_count": 1.0,
            "transaction.result": family,
            "transaction.root": True,
            "transaction.sampled": True,
            "transaction.type": "request",
            "url.path": path,
        },
    }


def bulk_index(stream: str, docs: list[dict]) -> None:
    if not docs:
        print(f"indexed=0 errors=0 stream={stream}")
        return
    es = get_client()
    actions = ({"_op_type": "create", "_index": stream, "_source": doc} for doc in docs)
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
        raise SystemExit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=float, default=7.0)
    parser.add_argument("--every", type=float, default=60.0, help="seconds between platform/OTel HTTP events")
    parser.add_argument("--syslog-every", type=float, default=180.0, help="seconds between syslog events")
    parser.add_argument("--skip-files", action="store_true", help="do not append Fleet agent log files")
    parser.add_argument(
        "--metrics-hours",
        type=float,
        default=METRICS_LOOKBACK_HOURS,
        help="hours of OTel metrics to index (TSDS look-back; older docs are rejected)",
    )
    parser.add_argument(
        "--only",
        choices=("all", "metrics"),
        default="all",
        help="index every stream, or only OTel metrics",
    )
    args = parser.parse_args()
    rng = random.Random(7)

    metric_docs = [
        otel_metric(ts, rng)
        for ts in walk(args.metrics_hours / 24.0, args.every)
        if load_keep(ts, rng)
    ]
    bulk_index(OTEL_METRICS, metric_docs)

    if args.only == "metrics":
        print(f"backfill complete metrics={len(metric_docs)} hours={args.metrics_hours}")
        return

    platform = events(days=args.days, every=args.every, rng=random.Random(11))
    _, nerr = index_docs(platform)
    if nerr:
        raise SystemExit(1)

    http_logs = [
        otel_http_log(ts, rng) for ts in walk(args.days, args.every) if load_keep(ts, rng)
    ]
    bulk_index(OTEL_LOGS, http_logs)

    syslog_logs = [
        otel_syslog_log(ts, rng)
        for ts in walk(args.days, args.syslog_every)
        if load_keep(ts, rng)
    ]
    bulk_index(OTEL_SYSLOG, syslog_logs)

    traces = [
        otel_trace(ts, rng) for ts in walk(args.days, args.every) if load_keep(ts, rng)
    ]
    bulk_index(OTEL_TRACES, traces)

    if not args.skip_files:
        syslog_file_backfill(args.days, args.syslog_every)

    print(
        f"backfill complete days={args.days} "
        f"platform={len(platform)} otel_logs={len(http_logs)} "
        f"otel_syslog={len(syslog_logs)} traces={len(traces)} "
        f"metrics={len(metric_docs)}"
    )


if __name__ == "__main__":
    main()
