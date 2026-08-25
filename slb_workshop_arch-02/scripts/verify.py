#!/usr/bin/env python3
"""Print retention classes, schema split, and template ownership evidence."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from elasticsearch import NotFoundError

from client import RETENTION, ROGUE_STREAM, STREAMS, get_client  # noqa: E402

TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"


def lifecycle_row(es, name: str) -> dict:
    try:
        stream = es.indices.get_data_stream(name=name)
        ds = stream["data_streams"][0]
        life = es.indices.get_data_lifecycle(name=name)
        lc = life.get("data_streams", [{}])[0].get("lifecycle", {})
        count = es.count(index=name).get("count")
        return {
            "stream": name,
            "generation": ds.get("generation"),
            "template": ds.get("template") or ds.get("index_template"),
            "data_retention": lc.get("data_retention"),
            "expected_retention": RETENTION.get(name),
            "doc_count": count,
            "backing": [idx["index_name"] for idx in ds.get("indices", [])],
        }
    except NotFoundError:
        return {"stream": name, "missing": True}


def schema_counts(es) -> dict:
    ecs = es.count(
        index=STREAMS["app_ecs"],
        query={"term": {"trace.id": TRACE_ID}},
    ).get("count")
    otel = es.count(
        index=STREAMS["app_otel"],
        query={"term": {"trace_id": TRACE_ID}},
    ).get("count")
    ecs_miss = es.count(
        index=STREAMS["app_ecs"],
        query={"term": {"trace_id": TRACE_ID}},
    ).get("count")
    otel_miss = es.count(
        index=STREAMS["app_otel"],
        query={"term": {"trace.id": TRACE_ID}},
    ).get("count")
    return {
        "trace.id on ECS stream": ecs,
        "trace_id on OTel stream": otel,
        "trace_id on ECS stream (should be 0)": ecs_miss,
        "trace.id on OTel stream (should be 0)": otel_miss,
    }


def main() -> None:
    es = get_client()
    info = es.info()
    rows = [lifecycle_row(es, name) for name in (*STREAMS.values(), ROGUE_STREAM)]
    print(
        json.dumps(
            {
                "build_flavor": info.get("version", {}).get("build_flavor"),
                "version": info.get("version", {}).get("number"),
                "retention_classes": rows,
                "schema_split": schema_counts(es),
            },
            indent=2,
            default=str,
        )
    )


if __name__ == "__main__":
    main()
