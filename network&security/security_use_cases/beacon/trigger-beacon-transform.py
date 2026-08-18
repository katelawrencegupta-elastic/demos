#!/usr/bin/env python3
"""Restart the Network Beaconing ML transform and check for results.

Usage:
  cp .env.example .env   # set ELASTIC_HOSTS and ELASTIC_API_KEY
  python3 trigger-beacon-transform.py

Reads Elastic credentials from .env in this directory (see elastic_env.py).
"""

from __future__ import annotations

import base64
import json
import sys
import time
from pathlib import Path
from urllib import error, request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from elastic_env import load_elastic_env

TRANSFORM_ID = "logs-beaconing.pivot_transform-default-1.6.0"


def load_env() -> tuple[str, str]:
    return load_elastic_env(__file__)


def call(method: str, hosts: str, api_key: str, path: str, body: dict | None = None) -> dict:
    headers = {
        "Authorization": f"ApiKey {base64.b64encode(api_key.encode()).decode()}",
        "Content-Type": "application/json",
    }
    data = json.dumps(body).encode() if body is not None else None
    req = request.Request(f"{hosts}{path}", data=data, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=120) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except error.HTTPError as exc:
        detail = exc.read().decode()
        raise RuntimeError(f"{method} {path} -> {exc.code}: {detail}") from exc


def main() -> None:
    hosts, api_key = load_env()
    print(f"Restarting transform {TRANSFORM_ID} ...")
    try:
        call("POST", hosts, api_key, f"/_transform/{TRANSFORM_ID}/_stop?wait_for_completion=true")
    except RuntimeError as exc:
        if "409" not in str(exc):
            raise
    call("POST", hosts, api_key, f"/_transform/{TRANSFORM_ID}/_start")

    for _ in range(24):
        time.sleep(5)
        stats = call("GET", hosts, api_key, f"/_transform/{TRANSFORM_ID}/_stats")
        transform = stats["transforms"][0]
        state = transform.get("state")
        indexed = transform.get("stats", {}).get("documents_indexed", 0)
        processed = transform.get("stats", {}).get("documents_processed", 0)
        print(f"  state={state} processed={processed} indexed={indexed}")
        if processed > 0 and state == "started":
            break

    count = call(
        "POST",
        hosts,
        api_key,
        "/ml_beaconing.all/_count",
        {"query": {"term": {"beacon_stats.is_beaconing": True}}},
    ).get("count", 0)
    print(f"ml_beaconing.all documents with is_beaconing=true: {count}")


if __name__ == "__main__":
    main()
