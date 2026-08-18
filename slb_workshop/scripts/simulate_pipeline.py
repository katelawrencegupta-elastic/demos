#!/usr/bin/env python3
"""Simulate the workshop ingest pipeline without writing data."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from client import FIXTURES, PIPELINE_ID, get_client  # noqa: E402


def main() -> None:
    es = get_client()
    body = json.loads((FIXTURES / "pipeline-simulate.json").read_text())
    result = es.ingest.simulate(id=PIPELINE_ID, **body)
    for i, doc in enumerate(result["docs"], start=1):
        src = doc.get("doc", {}).get("_source", {})
        err = doc.get("error") or src.get("error")
        print(f"--- doc {i} ---")
        print(
            json.dumps(
                {
                    "@timestamp": src.get("@timestamp"),
                    "message": src.get("message"),
                    "service.name": (src.get("service") or {}).get("name"),
                    "log.level": (src.get("log") or {}).get("level"),
                    "data_stream": src.get("data_stream"),
                    "event.dataset": (src.get("event") or {}).get("dataset"),
                    "http.response.status_code": (
                        (src.get("http") or {}).get("response") or {}
                    ).get("status_code"),
                    "error": err,
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
