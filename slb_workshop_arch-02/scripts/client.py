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
ARTIFACTS = ROOT / "artifacts"

WORKSHOP = "arch-02"

# Retention classes (namespace = environment).
STREAMS = {
    "metrics": "metrics-workshop.platform-prod",
    "app_ecs": "logs-workshop.app-prod",
    "app_otel": "logs-workshop.app.otel-prod",
    "app_nonprod": "logs-workshop.app-nonprod",
    "audit": "logs-workshop.audit-prod",
    "traces": "traces-workshop.app-prod",
}

ROGUE_STREAM = "logs-rogue.drilling-prod"

RETENTION = {
    STREAMS["metrics"]: "7d",
    STREAMS["app_ecs"]: "30d",
    STREAMS["app_otel"]: "30d",
    STREAMS["app_nonprod"]: "14d",
    STREAMS["audit"]: "90d",
    STREAMS["traces"]: "3d",
}

INDEX_TEMPLATES = (
    "metrics-workshop.platform",
    "logs-workshop.app",
    "logs-workshop.app.otel",
    "logs-workshop.audit",
    "traces-workshop.app",
)

COMPONENT_TEMPLATES = (
    "arch02-ecs-mappings",
    "arch02-otel-mappings",
    "arch02-metrics-mappings",
    "arch02-traces-mappings",
    "arch02-common-settings",
    "logs-workshop.app@custom",
)

PIPELINES = (
    "logs-workshop.app",
    "logs-workshop.app.otel",
    "logs-workshop.audit",
    "metrics-workshop.platform",
    "traces-workshop.app",
)

DATA_VIEWS = (
    ("arch02-retention-classes", "metrics-workshop.platform-*,logs-workshop.app-*,logs-workshop.audit-*,traces-workshop.app-*", "ARCH-02 retention classes"),
    ("arch02-ecs-app", "logs-workshop.app-prod", "ARCH-02 ECS app logs"),
    ("arch02-otel-app", "logs-workshop.app.otel-prod", "ARCH-02 OTel app logs"),
    ("arch02-audit", "logs-workshop.audit-*", "ARCH-02 audit"),
)

DASHBOARD_ID = "a02c1e11-7b4d-4f8a-9e21-5c6d8a0b1f42"
DASHBOARD_TITLE = "ARCH-02 Workshop — Governance evidence"
DASHBOARD_FILE = "dashboard-governance.json"

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
