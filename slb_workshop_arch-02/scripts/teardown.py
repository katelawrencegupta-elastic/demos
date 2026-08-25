#!/usr/bin/env python3
"""Remove ARCH-02 workshop streams, templates, and pipelines."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from elasticsearch import NotFoundError

from client import (  # noqa: E402
    COMPONENT_TEMPLATES,
    INDEX_TEMPLATES,
    PIPELINES,
    ROGUE_STREAM,
    STREAMS,
    get_client,
)


def ignore_404(fn, *args, **kwargs) -> None:
    try:
        fn(*args, **kwargs)
    except NotFoundError:
        pass


def main() -> None:
    es = get_client()
    for stream in (*STREAMS.values(), ROGUE_STREAM):
        ignore_404(es.indices.delete_data_stream, name=stream)
        print(f"deleted data_stream: {stream}")
    for name in INDEX_TEMPLATES:
        ignore_404(es.indices.delete_index_template, name=name)
        print(f"deleted index_template: {name}")
    for name in COMPONENT_TEMPLATES:
        ignore_404(es.cluster.delete_component_template, name=name)
        print(f"deleted component_template: {name}")
    for pipeline_id in PIPELINES:
        ignore_404(es.ingest.delete_pipeline, id=pipeline_id)
        print(f"deleted pipeline: {pipeline_id}")


if __name__ == "__main__":
    main()
