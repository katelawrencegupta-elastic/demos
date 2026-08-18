#!/usr/bin/env python3
"""Remove workshop data stream, templates, and ingest pipeline."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from elasticsearch import NotFoundError

from client import (  # noqa: E402
    COMPONENT_TEMPLATES,
    DATA_STREAM,
    INDEX_TEMPLATE,
    PIPELINE_ID,
    get_client,
)


def ignore_404(fn, *args, **kwargs) -> None:
    try:
        fn(*args, **kwargs)
    except NotFoundError:
        pass


def main() -> None:
    es = get_client()
    ignore_404(es.indices.delete_data_stream, name=DATA_STREAM)
    print(f"deleted data_stream: {DATA_STREAM}")
    ignore_404(es.indices.delete_index_template, name=INDEX_TEMPLATE)
    print(f"deleted index_template: {INDEX_TEMPLATE}")
    for name in COMPONENT_TEMPLATES:
        ignore_404(es.cluster.delete_component_template, name=name)
        print(f"deleted component_template: {name}")
    ignore_404(es.ingest.delete_pipeline, id=PIPELINE_ID)
    print(f"deleted pipeline: {PIPELINE_ID}")


if __name__ == "__main__":
    main()
