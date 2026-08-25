#!/usr/bin/env python3
"""Verify Elasticsearch connectivity and print cluster info."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from client import env, get_client  # noqa: E402


def main() -> None:
    es = get_client()
    info = es.info()
    indices = es.cat.indices(format="json")
    print(
        json.dumps(
            {
                "elasticsearch": env("ELASTIC_URL"),
                "kibana": env("KIBANA_URL"),
                "name": info.get("name"),
                "cluster_name": info.get("cluster_name"),
                "version": info.get("version", {}).get("number"),
                "build_flavor": info.get("version", {}).get("build_flavor"),
                "index_count": len(indices) if isinstance(indices, list) else None,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
