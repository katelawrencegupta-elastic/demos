from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from functools import lru_cache
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from elasticsearch import Elasticsearch

ROOT = Path(__file__).resolve().parents[1]
CONFIGS = ROOT / "configs"
FIXTURES = ROOT / "fixtures"

DATA_STREAM = "logs-workshop.platform-default"
PIPELINE_ID = "logs-workshop.platform"
GEOIP_PIPELINE_ID = "logs-workshop.host-geoip"
LOGS_CUSTOM_PIPELINE_ID = "logs@custom"
INDEX_TEMPLATE = "logs-workshop.platform"
COMPONENT_TEMPLATES = (
    "logs-workshop.platform-mappings",
    "logs-workshop.platform-settings",
)
OTEL_CUSTOM_COMPONENT_TEMPLATES = (
    "logs-otel@custom",
    "metrics-otel@custom",
    "traces-otel@custom",
)
DATA_VIEW_NAME = "Workshop platform logs"
DATA_VIEW_ID = "workshop-platform-logs"
DATA_VIEW_TITLE = "logs-workshop.platform-*"
DASHBOARD_ID = "bb3f65fa-c3d7-4b09-8295-b9645c789de9"
DASHBOARD_TITLE = "SRE-01 Workshop — Platform logs"
COMPARE_DASHBOARD_ID = "c8f4e1a2-9b3d-4e6f-a7c0-1d2e3f4a5b6c"
COMPARE_DASHBOARD_TITLE = "SRE-01 Workshop — Agents vs EDOT"
METRICS_DASHBOARD_ID = "f1a8c3d2-4e6b-4a90-9c17-2d5e8b0a4f63"
METRICS_DASHBOARD_TITLE = "SRE-01 Workshop — Metrics"
TRACES_DASHBOARD_ID = "a9c4e7b1-5f8d-4b21-8e36-1c7a0d9f5e24"
TRACES_DASHBOARD_TITLE = "SRE-01 Workshop — Traces"
COMPARE_DATA_VIEWS = (
    ("workshop-agent-logs", "logs-system.auth-*,logs-system.syslog-*", "Workshop agent logs"),
    ("workshop-agent-metrics", "metrics-system.*", "Workshop agent metrics"),
    ("workshop-edot-logs", "logs-*.otel-*", "Workshop EDOT logs"),
    ("workshop-edot-metrics", "metrics-*.otel-*", "Workshop EDOT metrics"),
    ("workshop-edot-traces", "traces-*.otel-*", "Workshop EDOT traces"),
)

load_dotenv(ROOT / ".env")


def env(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if value is None or value == "":
        raise RuntimeError(f"Missing required env var: {name}")
    return value


@lru_cache(maxsize=1)
def get_client() -> Elasticsearch:
    return Elasticsearch(
        env("ELASTIC_URL"),
        api_key=env("ELASTIC_API_KEY"),
        request_timeout=180,
    )


def kibana_request(
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    api_version: str | None = None,
) -> dict[str, Any]:
    url = env("KIBANA_URL").rstrip("/") + path
    headers = {
        "Authorization": f"ApiKey {env('ELASTIC_API_KEY')}",
        "kbn-xsrf": "true",
        "Content-Type": "application/json",
    }
    if api_version:
        headers["elastic-api-version"] = api_version
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise RuntimeError(f"Kibana {method} {path} -> {exc.code}: {detail[:2000]}") from exc
    return json.loads(raw) if raw else {}


def kibana_url(app_path: str) -> str:
    return env("KIBANA_URL").rstrip("/") + app_path

