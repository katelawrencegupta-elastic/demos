"""Bulk indexer for Elastic data streams."""
import json
import time
from collections import Counter

import requests

from src.config import ELASTIC_URL, ES_HEADERS

NDJSON_HEADERS = {**ES_HEADERS, "Content-Type": "application/x-ndjson"}
RETRYABLE = {429, 502, 503, 504}


class BulkSink:
    def __init__(self, batch_docs: int = 500):
        self.batch_docs = batch_docs
        self.buf = []
        self.indexed = Counter()
        self.failed = Counter()
        self.error_samples = {}

    def add(self, index: str, doc: dict):
        self.buf.append((index, doc))
        if len(self.buf) >= self.batch_docs:
            self.flush()

    def flush(self):
        if not self.buf:
            return
        lines = []
        for idx, doc in self.buf:
            lines.append(json.dumps({"create": {"_index": idx}}))
            lines.append(json.dumps(doc, separators=(",", ":")))
        body = ("\n".join(lines) + "\n").encode()

        resp = None
        r = None
        for attempt in range(6):
            r = requests.post(
                f"{ELASTIC_URL}/_bulk", headers=NDJSON_HEADERS, data=body, timeout=120
            )
            if r.status_code in RETRYABLE:
                time.sleep(min(2**attempt, 20))
                continue
            r.raise_for_status()
            resp = r.json()
            break
        if resp is None:
            raise RuntimeError(f"bulk kept failing: {r.status_code} {r.text[:300]}")

        for (idx, _), item in zip(self.buf, resp["items"]):
            res = item.get("create") or item.get("index") or {}
            if res.get("status", 500) < 300:
                self.indexed[idx] += 1
            else:
                self.failed[idx] += 1
                self.error_samples.setdefault(idx, json.dumps(res.get("error"))[:400])
        self.buf = []

    def close(self):
        self.flush()
        return self.indexed, self.failed, self.error_samples


def es_search(index: str, body: dict) -> dict:
    r = requests.post(
        f"{ELASTIC_URL}/{index}/_search", headers=ES_HEADERS, json=body, timeout=60
    )
    r.raise_for_status()
    return r.json()


def es_request(method: str, path: str, body: dict | None = None, timeout: int = 60):
    r = requests.request(
        method,
        f"{ELASTIC_URL}{path}",
        headers=ES_HEADERS,
        json=body,
        timeout=timeout,
    )
    return r
