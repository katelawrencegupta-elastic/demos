#!/usr/bin/env python3
"""Apply workshop ingest pipeline, component templates, and index template."""

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
    DATA_STREAM,
    GEOIP_PIPELINE_ID,
    INDEX_TEMPLATE,
    LOGS_CUSTOM_PIPELINE_ID,
    OTEL_CUSTOM_COMPONENT_TEMPLATES,
    PIPELINE_ID,
    get_client,
)


def load(path: Path) -> dict:
    return json.loads(path.read_text())


def main() -> None:
    es = get_client()

    for pipeline_id in (PIPELINE_ID, GEOIP_PIPELINE_ID, LOGS_CUSTOM_PIPELINE_ID):
        pipeline = load(CONFIGS / "ingest-pipelines" / f"{pipeline_id}.json")
        es.ingest.put_pipeline(id=pipeline_id, **pipeline)
        print(f"pipeline: {pipeline_id}")

    for name in (*COMPONENT_TEMPLATES, *OTEL_CUSTOM_COMPONENT_TEMPLATES):
        body = load(CONFIGS / "component-templates" / f"{name}.json")
        es.cluster.put_component_template(name=name, **body)
        print(f"component_template: {name}")

    template = load(CONFIGS / "index-templates" / f"{INDEX_TEMPLATE}.json")
    es.indices.put_index_template(name=INDEX_TEMPLATE, **template)
    print(f"index_template: {INDEX_TEMPLATE}")

    try:
        es.indices.get_data_stream(name=DATA_STREAM)
        print(f"data_stream exists: {DATA_STREAM}")
    except NotFoundError:
        es.indices.create_data_stream(name=DATA_STREAM)
        print(f"data_stream created: {DATA_STREAM}")

    lifecycle = es.indices.get_data_lifecycle(name=DATA_STREAM)
    print(json.dumps(lifecycle.body, indent=2))


if __name__ == "__main__":
    main()
