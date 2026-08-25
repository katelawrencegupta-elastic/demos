#!/usr/bin/env python3
"""Apply ARCH-02 templates, pipelines, and retention-class data streams."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from elasticsearch import NotFoundError

from client import (  # noqa: E402
    COMPONENT_TEMPLATES,
    CONFIGS,
    INDEX_TEMPLATES,
    PIPELINES,
    RETENTION,
    STREAMS,
    get_client,
)


def load(path: Path) -> dict:
    return json.loads(path.read_text())


def main() -> None:
    es = get_client()

    for pipeline_id in PIPELINES:
        pipeline = load(CONFIGS / "ingest-pipelines" / f"{pipeline_id}.json")
        es.ingest.put_pipeline(id=pipeline_id, **pipeline)
        print(f"pipeline: {pipeline_id}")

    for name in COMPONENT_TEMPLATES:
        body = load(CONFIGS / "component-templates" / f"{name}.json")
        es.cluster.put_component_template(name=name, **body)
        print(f"component_template: {name}")

    for name in INDEX_TEMPLATES:
        template = load(CONFIGS / "index-templates" / f"{name}.json")
        es.indices.put_index_template(name=name, **template)
        print(f"index_template: {name}")

    for stream in STREAMS.values():
        try:
            es.indices.get_data_stream(name=stream)
            print(f"data_stream exists: {stream}")
        except NotFoundError:
            es.indices.create_data_stream(name=stream)
            print(f"data_stream created: {stream}")
        expected = RETENTION[stream]
        es.indices.put_data_lifecycle(name=stream, data_retention=expected)
        got = es.indices.get_data_lifecycle(name=stream)
        life = got.get("data_streams", [{}])[0].get("lifecycle", {})
        print(f"  lifecycle: {life.get('data_retention')} (want {expected})")


if __name__ == "__main__":
    main()
