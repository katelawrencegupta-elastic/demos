#!/usr/bin/env python3
"""Show that ECS and OTel field names do not query each other without translation."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from client import STREAMS, get_client  # noqa: E402

TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"


def count(es, index: str, field: str, value: str) -> int:
    return es.count(index=index, query={"term": {field: value}}).get("count", 0)


def main() -> None:
    es = get_client()
    pairs = (
        ("ECS `trace.id`", STREAMS["app_ecs"], "trace.id", TRACE_ID),
        ("OTel `trace_id` on ECS stream", STREAMS["app_ecs"], "trace_id", TRACE_ID),
        ("OTel `trace_id`", STREAMS["app_otel"], "trace_id", TRACE_ID),
        ("ECS `trace.id` on OTel stream", STREAMS["app_otel"], "trace.id", TRACE_ID),
        ("ECS `log.level:ERROR`", STREAMS["app_ecs"], "log.level", "ERROR"),
        ("OTel `severity_text:ERROR` on ECS", STREAMS["app_ecs"], "severity_text", "ERROR"),
        ("OTel `severity_text:ERROR`", STREAMS["app_otel"], "severity_text", "ERROR"),
        ("ECS `log.level` on OTel stream", STREAMS["app_otel"], "log.level", "ERROR"),
    )
    rows = [
        {"query": label, "index": index, "hits": count(es, index, field, value)}
        for label, index, field, value in pairs
    ]
    print(json.dumps({"incident_trace_id": TRACE_ID, "results": rows}, indent=2))
    crossed = [r for r in rows if "on " in r["query"] and r["hits"]]
    if crossed:
        raise SystemExit("unexpected cross-schema hits — mixed authoring leaked")
    print("ok: mixed queries miss. translation is required; aliasing is not enough for metrics.")


if __name__ == "__main__":
    main()
