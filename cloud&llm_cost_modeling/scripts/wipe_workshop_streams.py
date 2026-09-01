"""Wipe all workshop data streams (generators.ALL) via async delete_by_query."""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests

from src.config import ELASTIC_URL, ES_HEADERS
from src.generators import ALL

POLL_SEC = 5
TASK_TIMEOUT_SEC = 7200


def _count_docs(ds: str) -> int | None:
    r = requests.post(
        f"{ELASTIC_URL}/{ds}/_count",
        headers=ES_HEADERS,
        json={"query": {"match_all": {}}},
        timeout=120,
    )
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return int(r.json().get("count") or 0)


def _poll_task(task_id: str, ds: str) -> tuple[int, str | None]:
    deadline = time.time() + TASK_TIMEOUT_SEC
    last_deleted = 0
    while time.time() < deadline:
        r = requests.get(
            f"{ELASTIC_URL}/_tasks/{task_id}",
            headers=ES_HEADERS,
            timeout=120,
        )
        r.raise_for_status()
        body = r.json()
        if body.get("completed"):
            resp = body.get("response") or {}
            deleted = int(resp.get("deleted") or 0)
            failures = resp.get("failures") or []
            err = None
            if failures:
                err = str(failures[0])[:300]
            return deleted, err
        status = body.get("task", {}).get("status") or {}
        last_deleted = int(status.get("deleted") or last_deleted)
        if last_deleted:
            print(f"    ... {ds}: {last_deleted:,} deleted so far", flush=True)
        time.sleep(POLL_SEC)
    raise TimeoutError(f"task {task_id} for {ds} did not complete in {TASK_TIMEOUT_SEC}s")


def _run_delete(ds: str) -> int:
    params = {
        "wait_for_completion": "false",
        "conflicts": "proceed",
        "slices": "auto",
    }
    r = requests.post(
        f"{ELASTIC_URL}/{ds}/_delete_by_query",
        headers=ES_HEADERS,
        params=params,
        json={"query": {"match_all": {}}},
        timeout=120,
    )
    if r.status_code == 404:
        return -1
    if r.status_code >= 300:
        raise RuntimeError(f"{ds}: {r.status_code} {r.text[:400]}")
    data = r.json()
    task_id = data.get("task")
    if not task_id:
        return int(data.get("deleted") or 0)
    deleted, _err = _poll_task(task_id, ds)
    requests.post(
        f"{ELASTIC_URL}/{ds}/_refresh",
        headers=ES_HEADERS,
        timeout=120,
    )
    return deleted


def wipe_stream(ds: str) -> str:
    before = _count_docs(ds)
    if before is None:
        return "skip_not_found"
    if before == 0:
        return "ok_0"

    total_deleted = 0
    for attempt in range(1, 6):
        n = _run_delete(ds)
        if n < 0:
            return "skip_not_found"
        total_deleted += max(n, 0)
        after = _count_docs(ds) or 0
        if after == 0:
            return f"ok_{total_deleted}"
        print(
            f"    retry {attempt}/5 {ds}: {after:,} docs remain",
            flush=True,
        )
        time.sleep(10)
    after = _count_docs(ds) or 0
    raise RuntimeError(f"{ds}: {after:,} docs remain after delete retries")


def main() -> int:
    streams = sorted({g.DATA_STREAM for g in ALL})
    print(f"== Wipe {len(streams)} workshop data streams (async delete_by_query) ==", flush=True)
    summary: dict[str, str] = {}
    errors: list[str] = []
    for ds in streams:
        print(f"  {ds} ...", flush=True)
        try:
            result = wipe_stream(ds)
            summary[ds] = result
            print(f"  [{result.split('_')[0]}] {ds}: {result}", flush=True)
        except Exception as e:
            summary[ds] = f"fail:{e}"
            errors.append(f"{ds}: {e}")
            print(f"  [fail] {ds}: {e}", flush=True)

    print("\n== wipe summary ==", flush=True)
    for ds in streams:
        print(f"  {ds}: {summary.get(ds, '?')}", flush=True)
    if errors:
        print(f"\n{len(errors)} error(s)", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
