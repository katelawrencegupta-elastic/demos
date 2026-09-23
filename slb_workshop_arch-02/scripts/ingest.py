#!/usr/bin/env python3
"""Index sample telemetry into each ARCH-02 retention class / schema stream.

Lab-critical seed docs (canonical trace, @custom well_id, rogue stream) stay
intact. The rest is volume so Discover, retention classes, and schema miss
look like a real platform rather than 18 fixture rows.
"""

from __future__ import annotations

import hashlib
import random
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

WELLS = ("8321", "4402", "9107", "1188", "7750", "6033")
SERVICES = (
    ("well-data-api", "1.8.2", "drilling-apps"),
    ("mud-weight-svc", "2.3.1", "drilling-apps"),
    ("survey-ingestor", "0.9.4", "subsurface"),
    ("witsml-gateway", "4.1.0", "subsurface"),
    ("identity-service", "3.2.0", "platform"),
)
PATHS = (
    "/v2/wells/{well}/surveys",
    "/v2/wells/{well}/trajectory",
    "/v2/wells/{well}/mud",
    "/v2/witsml/ingest",
    "/health",
)
METHODS = ("GET", "GET", "GET", "POST", "POST")
SITES = ("gulf-of-mexico", "north-sea", "us-central")
HOSTS = ("aks-arch-01", "aks-arch-02", "aks-arch-03", "aks-edge-01")
SEVERITY = {"INFO": 9, "WARN": 13, "ERROR": 17, "DEBUG": 5}

RNG = random.Random(20260923)


def now_iso(offset_minutes: float = 0) -> str:
    ts = datetime.now(timezone.utc) - timedelta(minutes=offset_minutes)
    return ts.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def hex_id(n: int, seed: str) -> str:
    digest = hashlib.sha256(seed.encode()).hexdigest()
    return digest[:n]


def pick_level(error_rate: float = 0.10) -> str:
    roll = RNG.random()
    if roll < error_rate:
        return "ERROR"
    if roll < error_rate + 0.12:
        return "WARN"
    if roll < error_rate + 0.18:
        return "DEBUG"
    return "INFO"


def status_for(level: str, method: str) -> int:
    if level == "ERROR":
        return RNG.choice((500, 502, 504, 503))
    if level == "WARN":
        return RNG.choice((404, 409, 429))
    if method == "POST":
        return 201
    return 200


def message_for(level: str, path: str) -> str:
    if level == "ERROR":
        if "survey" in path:
            return "survey lookup failed: upstream timeout"
        if "mud" in path:
            return "mud-weight-svc unavailable: connection reset"
        if "witsml" in path:
            return "witsml ingest failed: schema validation"
        return "request failed: upstream timeout"
    if level == "WARN":
        if "trajectory" in path:
            return "witsml parse warning: missing md"
        if "429" in path:
            return "rate limit approaching on mud-weight-svc"
        return "cache miss on trajectory; served from origin"
    if path == "/health":
        return "health check ok"
    return "request completed"


def seed_ecs_incident() -> list[tuple[str, dict]]:
    """Canonical lab-2 incident. Do not change field names."""
    docs: list[tuple[str, dict]] = []
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
                    "labels": {"team": "drilling-apps", "site": "gulf-of-mexico"},
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
                "labels": {"team": "drilling-apps", "site": "us-central"},
            },
        )
    )
    return docs


def seed_otel_incident() -> list[tuple[str, dict]]:
    docs: list[tuple[str, dict]] = []
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
                    "severity_number": SEVERITY[severity],
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
                    "labels": {"team": "drilling-apps", "site": "gulf-of-mexico"},
                },
            )
        )
    return docs


def ecs_app_docs(count: int, hours: float, environment: str) -> list[tuple[str, dict]]:
    stream = STREAMS["app_ecs"] if environment == "prod" else STREAMS["app_nonprod"]
    docs: list[tuple[str, dict]] = []
    span_minutes = hours * 60
    for i in range(count):
        service, version, team = SERVICES[i % len(SERVICES)]
        well = WELLS[i % len(WELLS)]
        method = METHODS[i % len(METHODS)]
        path = PATHS[i % len(PATHS)].format(well=well)
        level = pick_level(0.11 if environment == "prod" else 0.18)
        if i % 37 == 0 and environment == "prod":
            # Extra volume on the lab incident so Discover is not five rows.
            well, path, level = WELL_ID, "/v2/wells/8321/surveys", "ERROR"
            trace = TRACE_ID
            span = SPAN_ID
        else:
            trace = hex_id(32, f"ecs-{environment}-{i}")
            span = hex_id(16, f"ecs-span-{environment}-{i}")
        docs.append(
            (
                stream,
                {
                    "@timestamp": now_iso(RNG.uniform(0, span_minutes)),
                    "message": message_for(level, path),
                    "log": {"level": level},
                    "service": {
                        "name": service,
                        "environment": environment,
                        "version": version,
                    },
                    "trace": {"id": trace},
                    "span": {"id": span},
                    "http": {
                        "request": {"method": method},
                        "response": {"status_code": status_for(level, method)},
                    },
                    "url": {"path": path},
                    "slb": {"well_id": well},
                    "host": {"name": HOSTS[i % len(HOSTS)]},
                    "labels": {"team": team, "site": SITES[i % len(SITES)]},
                },
            )
        )
    return docs


def otel_app_docs(count: int, hours: float) -> list[tuple[str, dict]]:
    docs: list[tuple[str, dict]] = []
    span_minutes = hours * 60
    for i in range(count):
        service, version, team = SERVICES[i % len(SERVICES)]
        well = WELLS[i % len(WELLS)]
        method = METHODS[i % len(METHODS)]
        path = PATHS[i % len(PATHS)].format(well=well)
        level = pick_level(0.11)
        if i % 37 == 0:
            well, path, level = WELL_ID, "/v2/wells/8321/surveys", "ERROR"
            trace = TRACE_ID
            span = SPAN_ID
        else:
            trace = hex_id(32, f"otel-prod-{i}")
            span = hex_id(16, f"otel-span-{i}")
        docs.append(
            (
                STREAMS["app_otel"],
                {
                    "@timestamp": now_iso(RNG.uniform(0, span_minutes)),
                    "body": {"text": message_for(level, path)},
                    "severity_text": level,
                    "severity_number": SEVERITY[level],
                    "trace_id": trace,
                    "span_id": span,
                    "resource": {
                        "attributes": {
                            "service.name": service,
                            "service.version": version,
                            "deployment.environment": "prod",
                        }
                    },
                    "attributes": {
                        "http.request.method": method,
                        "http.response.status_code": status_for(level, method),
                        "url.path": path,
                    },
                    "labels": {"team": team, "site": SITES[i % len(SITES)]},
                },
            )
        )
    return docs


def audit_docs(count: int, hours: float) -> list[tuple[str, dict]]:
    actions = (
        ("iam.role.update", "success", "role change: {team} granted {perm}"),
        ("iam.role.update", "failure", "role change denied: {team} requested {perm}"),
        ("security.api_key.create", "success", "API key created for {service}"),
        ("security.api_key.invalidate", "success", "API key invalidated for {service}"),
        ("dataset.create", "failure", "unsanctioned dataset create blocked: logs-{team}.custom-prod"),
        ("dataset.create", "success", "exception approved: logs-workshop.{team}-prod"),
        ("template.change", "success", "component template logs-workshop.app@custom updated"),
        ("exception.request", "success", "retention exception: audit class +30d for well {well}"),
    )
    users = ("platform-admin", "arch-02-workshop", "site-sre-gulf", "drilling-lead")
    docs: list[tuple[str, dict]] = []
    span_minutes = hours * 60
    for i in range(count):
        action, outcome, tmpl = actions[i % len(actions)]
        service, _, team = SERVICES[i % len(SERVICES)]
        well = WELLS[i % len(WELLS)]
        docs.append(
            (
                STREAMS["audit"],
                {
                    "@timestamp": now_iso(RNG.uniform(0, span_minutes)),
                    "message": tmpl.format(
                        team=team, perm="dataset.create", service=service, well=well
                    ),
                    "event": {"action": action, "outcome": outcome},
                    "user": {"name": users[i % len(users)]},
                    "log": {"level": "WARN" if outcome == "failure" else "INFO"},
                    "service": {"name": "identity-service", "environment": "prod"},
                    "labels": {"team": "platform", "site": SITES[i % len(SITES)]},
                },
            )
        )
    return docs


def metrics_docs(count: int, hours: float) -> list[tuple[str, dict]]:
    docs: list[tuple[str, dict]] = []
    span_minutes = hours * 60
    for i in range(count):
        host = HOSTS[i % len(HOSTS)]
        kind = ("cpu", "memory", "disk")[i % 3]
        base = 0.18 + (i % len(HOSTS)) * 0.07
        spike = 0.35 if i % 23 == 0 else 0.0
        value = min(0.97, base + spike + RNG.uniform(-0.04, 0.08))
        if kind == "cpu":
            metric = {"system": {"cpu": {"total": {"norm": {"pct": round(value, 4)}}}}}
        elif kind == "memory":
            metric = {"system": {"memory": {"used": {"pct": round(value, 4)}}}}
        else:
            metric = {"system": {"filesystem": {"used": {"pct": round(0.42 + value * 0.2, 4)}}}}
        docs.append(
            (
                STREAMS["metrics"],
                {
                    "@timestamp": now_iso(RNG.uniform(0, span_minutes)),
                    "metricset": {"name": kind},
                    "host": {"name": host},
                    "service": {"name": "node-exporter"},
                    "labels": {"team": "platform", "site": SITES[i % len(SITES)]},
                    **metric,
                },
            )
        )
    return docs


def trace_docs(count: int, hours: float) -> list[tuple[str, dict]]:
    docs: list[tuple[str, dict]] = [
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
    span_minutes = hours * 60
    for i in range(count):
        service, _, team = SERVICES[i % 4]
        well = WELLS[i % len(WELLS)]
        method = METHODS[i % len(METHODS)]
        path = PATHS[i % len(PATHS)].format(well=well)
        failed = i % 11 == 0
        docs.append(
            (
                STREAMS["traces"],
                {
                    "@timestamp": now_iso(RNG.uniform(0, min(span_minutes, 3 * 24 * 60 - 30))),
                    "trace": {"id": hex_id(32, f"trace-{i}")},
                    "span": {
                        "id": hex_id(16, f"tspan-{i}"),
                        "name": f"{method} {path}",
                        "duration": {"us": 12000 + RNG.randint(0, 900000) + (800000 if failed else 0)},
                    },
                    "service": {"name": service},
                    "event": {"outcome": "failure" if failed else "success"},
                    "http": {"response": {"status_code": 500 if failed else status_for("INFO", method)}},
                    "labels": {"team": team, "site": SITES[i % len(SITES)]},
                },
            )
        )
    return docs


def rogue_docs(count: int) -> list[tuple[str, dict]]:
    """Unsanctioned dataset — no central template, non-contract field names."""
    docs: list[tuple[str, dict]] = [
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
    for i in range(count):
        docs.append(
            (
                ROGUE_STREAM,
                {
                    "@timestamp": now_iso(RNG.uniform(0, 180)),
                    "message": RNG.choice(
                        (
                            "pit gain alarm ignored — local logger only",
                            "hookload spike; not on workshop.app",
                            "alice-test namespace leak into drilling-prod",
                        )
                    ),
                    "service_name": RNG.choice(("mud-logger", "hookload-edge", "alice-laptop")),
                    "lvl": RNG.choice(("err", "warn", "info")),
                    "wellId": WELLS[i % len(WELLS)],
                    "siteName": SITES[i % len(SITES)],
                },
            )
        )
    return docs


def index_pairs(pairs: list[tuple[str, dict]]) -> tuple[int, int]:
    es = get_client()
    actions = (
        {"_op_type": "create", "_index": stream, "_source": doc} for stream, doc in pairs
    )
    ok, errors = bulk(
        es,
        actions,
        chunk_size=400,
        refresh="wait_for",
        raise_on_error=False,
    )
    nerr = len(errors) if errors else 0
    print(f"indexed={ok} errors={nerr} attempted={len(pairs)}")
    if errors:
        print(errors[:3])
    return ok, nerr


def main() -> None:
    pairs = (
        seed_ecs_incident()
        + seed_otel_incident()
        + ecs_app_docs(420, hours=36, environment="prod")
        + ecs_app_docs(90, hours=24, environment="nonprod")
        + otel_app_docs(420, hours=36)
        + audit_docs(48, hours=72)
        + metrics_docs(240, hours=36)
        + trace_docs(90, hours=36)
        + rogue_docs(18)
    )
    _, nerr = index_pairs(pairs)
    if nerr:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
