#!/usr/bin/env python3
"""Show workshop pipeline, templates, data stream, lifecycle, and a sample hit."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from client import DATA_STREAM, INDEX_TEMPLATE, PIPELINE_ID, get_client  # noqa: E402


def main() -> None:
    es = get_client()
    info = es.info()
    stream = es.indices.get_data_stream(name=DATA_STREAM)
    lifecycle = es.indices.get_data_lifecycle(name=DATA_STREAM)
    count = es.count(index=DATA_STREAM)
    sample = es.search(
        index=DATA_STREAM,
        size=1,
        sort=[{"@timestamp": {"order": "desc"}}],
        query={"term": {"labels.workshop": "sre-01"}},
    )
    hits = sample.get("hits", {}).get("hits", [])
    print(
        json.dumps(
            {
                "build_flavor": info.get("version", {}).get("build_flavor"),
                "version": info.get("version", {}).get("number"),
                "pipeline": PIPELINE_ID,
                "index_template": INDEX_TEMPLATE,
                "data_stream": stream["data_streams"][0]["name"],
                "generation": stream["data_streams"][0].get("generation"),
                "backing_indices": [
                    idx["index_name"]
                    for idx in stream["data_streams"][0].get("indices", [])
                ],
                "lifecycle": lifecycle.get("data_streams", [{}])[0].get("lifecycle"),
                "doc_count": count.get("count"),
                "latest_hit": hits[0]["_source"] if hits else None,
            },
            indent=2,
            default=str,
        )
    )


if __name__ == "__main__":
    main()
