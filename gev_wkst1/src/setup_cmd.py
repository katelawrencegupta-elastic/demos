"""Install pipelines, templates, data views, and alert rule definitions."""
import json
from pathlib import Path

import requests

from src.config import (
    COMPONENTS_DIR,
    ELASTIC_URL,
    ES_HEADERS,
    KBN_HEADERS,
    KIBANA_DIR,
    KIBANA_URL,
    PIPELINES_DIR,
    TEMPLATES_DIR,
)

COMPONENT_ORDER = [
    "logs-elasticco.orchestrator",
    "logs-elasticco.checkout",
    "logs-elasticco.k8s.event",
    "logs-elasticco.incident",
    "metrics-elasticco.k8s.pod",
    "metrics-elasticco.k8s.node",
    "metrics-elasticco.host",
]

INDEX_TEMPLATES = [
    "logs-elasticco.orchestrator",
    "logs-elasticco.checkout",
    "logs-elasticco.k8s.event",
    "logs-elasticco.incident",
    "metrics-elasticco.k8s.pod",
    "metrics-elasticco.k8s.node",
    "metrics-elasticco.host",
]

PIPELINES = ["logs-elasticco.orchestrator"]

DATA_VIEWS = [
    {
        "id": "elasticco-orchestrator",
        "title": "logs-elasticco.orchestrator-*",
        "name": "Elastic Co. Orchestrator Logs",
        "timeFieldName": "@timestamp",
    },
    {
        "id": "elasticco-checkout",
        "title": "logs-elasticco.checkout-*",
        "name": "Elastic Co. Checkout Logs",
        "timeFieldName": "@timestamp",
    },
    {
        "id": "elasticco-k8s",
        "title": "logs-elasticco.k8s.event-*,metrics-elasticco.k8s.*,metrics-elasticco.host-*",
        "name": "Elastic Co. Kubernetes",
        "timeFieldName": "@timestamp",
    },
    {
        "id": "elasticco-incidents",
        "title": "logs-elasticco.incident-*",
        "name": "Elastic Co. Incident Audit",
        "timeFieldName": "@timestamp",
    },
    {
        "id": "elasticco-all",
        "title": "logs-elasticco.*,metrics-elasticco.*,metrics-apm*,traces-apm*",
        "name": "Elastic Co. All",
        "timeFieldName": "@timestamp",
    },
]


def _put_json(path: str, body: dict):
    r = requests.put(f"{ELASTIC_URL}{path}", headers=ES_HEADERS, json=body, timeout=60)
    return r


def ensure_pipelines():
    for name in PIPELINES:
        body = json.loads((PIPELINES_DIR / f"{name}.json").read_text())
        r = _put_json(f"/_ingest/pipeline/{name}", body)
        if r.status_code >= 300:
            raise SystemExit(f"pipeline {name}: {r.status_code} {r.text[:300]}")
        print(f"  [ok] pipeline {name}")


def ensure_templates():
    for name in COMPONENT_ORDER:
        body = json.loads((COMPONENTS_DIR / f"{name}.json").read_text())
        r = _put_json(f"/_component_template/{name}", body)
        if r.status_code >= 300:
            raise SystemExit(f"component {name}: {r.status_code} {r.text[:300]}")
        print(f"  [ok] component template {name}")
    for name in INDEX_TEMPLATES:
        body = json.loads((TEMPLATES_DIR / f"{name}.json").read_text())
        r = _put_json(f"/_index_template/{name}", body)
        if r.status_code >= 300:
            raise SystemExit(f"index template {name}: {r.status_code} {r.text[:300]}")
        print(f"  [ok] index template {name}")


def check_write_access():
    probe = "logs-elasticco-probe"
    r = requests.post(
        f"{ELASTIC_URL}/{probe}/_doc",
        headers=ES_HEADERS,
        json={"@timestamp": "2026-01-01T00:00:00Z", "message": "probe"},
        timeout=30,
    )
    if r.status_code >= 300:
        raise SystemExit(f"cannot write: {r.status_code} {r.text[:300]}")
    requests.delete(f"{ELASTIC_URL}/{probe}", headers=ES_HEADERS)
    print("  [ok] API key can create indices and write documents")


def ensure_data_views():
    for dv in DATA_VIEWS:
        # Try create; if exists, update attributes
        body = {
            "data_view": {
                "id": dv["id"],
                "title": dv["title"],
                "name": dv["name"],
                "timeFieldName": dv["timeFieldName"],
            }
        }
        r = requests.post(
            f"{KIBANA_URL}/api/data_views/data_view",
            headers=KBN_HEADERS,
            json=body,
            timeout=60,
        )
        if r.status_code in (200, 201):
            print(f"  [ok] data view {dv['id']}")
            continue
        if (
            r.status_code == 409
            or "already exists" in r.text.lower()
            or "duplicate data view" in r.text.lower()
        ):
            r2 = requests.post(
                f"{KIBANA_URL}/api/data_views/data_view/{dv['id']}",
                headers=KBN_HEADERS,
                json={
                    "data_view": {
                        "title": dv["title"],
                        "name": dv["name"],
                        "timeFieldName": dv["timeFieldName"],
                    }
                },
                timeout=60,
            )
            if r2.status_code >= 300:
                r2 = requests.put(
                    f"{KIBANA_URL}/api/data_views/data_view/{dv['id']}",
                    headers=KBN_HEADERS,
                    json={
                        "data_view": {
                            "title": dv["title"],
                            "name": dv["name"],
                            "timeFieldName": dv["timeFieldName"],
                        }
                    },
                    timeout=60,
                )
            if r2.status_code >= 300:
                print(f"  [warn] update data view {dv['id']}: {r2.status_code} {r2.text[:200]}")
            else:
                print(f"  [ok] data view {dv['id']} updated")
            continue
        print(f"  [warn] data view {dv['id']}: {r.status_code} {r.text[:200]}")


def ensure_alert_rules():
    """Create noisy vs quality ES query rules via Kibana alerting API."""
    rules_file = KIBANA_DIR / "alert-rules.json"
    if not rules_file.exists():
        print("  [warn] kibana/alert-rules.json missing; skip alerts")
        return
    rules = json.loads(rules_file.read_text())
    for rule in rules:
        # List existing by name
        r = requests.get(
            f"{KIBANA_URL}/api/alerting/rules/_find",
            headers=KBN_HEADERS,
            params={"search": rule["name"], "search_fields": "name", "per_page": 20},
            timeout=60,
        )
        existing = []
        if r.status_code == 200:
            existing = [x for x in r.json().get("data", []) if x.get("name") == rule["name"]]
        if existing:
            rid = existing[0]["id"]
            update_body = {
                k: v
                for k, v in rule.items()
                if k not in ("id", "rule_type_id", "consumer", "enabled")
            }
            r2 = requests.put(
                f"{KIBANA_URL}/api/alerting/rule/{rid}",
                headers=KBN_HEADERS,
                json=update_body,
                timeout=60,
            )
            if r2.status_code >= 300 and update_body.get("actions"):
                print(
                    f"  [warn] update rule {rule['name']} with Cases action: "
                    f"{r2.status_code} {r2.text[:240]}"
                )
                update_body["actions"] = []
                r2 = requests.put(
                    f"{KIBANA_URL}/api/alerting/rule/{rid}",
                    headers=KBN_HEADERS,
                    json=update_body,
                    timeout=60,
                )
            if r2.status_code >= 300:
                print(f"  [warn] update rule {rule['name']}: {r2.status_code} {r2.text[:240]}")
            else:
                print(f"  [ok] alert rule updated: {rule['name']}")
            continue
        r = requests.post(
            f"{KIBANA_URL}/api/alerting/rule",
            headers=KBN_HEADERS,
            json=rule,
            timeout=60,
        )
        if r.status_code >= 300 and rule.get("actions"):
            print(
                f"  [warn] create rule {rule['name']} with Cases action: "
                f"{r.status_code} {r.text[:300]}"
            )
            stripped = {**rule, "actions": []}
            r = requests.post(
                f"{KIBANA_URL}/api/alerting/rule",
                headers=KBN_HEADERS,
                json=stripped,
                timeout=60,
            )
        if r.status_code >= 300:
            print(f"  [warn] create rule {rule['name']}: {r.status_code} {r.text[:300]}")
        else:
            print(f"  [ok] alert rule created: {rule['name']}")


def import_saved_objects():
    ndjson = KIBANA_DIR / "saved-objects.ndjson"
    if not ndjson.exists():
        print("  [warn] kibana/saved-objects.ndjson missing; skip import")
        return
    headers = {
        "Authorization": KBN_HEADERS["Authorization"],
        "kbn-xsrf": "true",
    }
    with open(ndjson, "rb") as f:
        r = requests.post(
            f"{KIBANA_URL}/api/saved_objects/_import?overwrite=true",
            headers=headers,
            files={"file": ("saved-objects.ndjson", f, "application/ndjson")},
            timeout=120,
        )
    if r.status_code >= 300:
        print(f"  [warn] saved objects import: {r.status_code} {r.text[:300]}")
    else:
        summary = r.json() if r.text else {}
        print(
            f"  [ok] saved objects import: success={summary.get('success')} "
            f"count={summary.get('successCount')}"
        )


def publish_dashboard():
    from src.dashboards import publish_all

    return publish_all()

def run_setup(include_alerts: bool = True):
    print("== write access ==")
    check_write_access()
    print("== pipelines ==")
    ensure_pipelines()
    print("== templates ==")
    ensure_templates()
    # Ensure APM custom fields exist even before first apm emit
    from src.generators.apm import ensure_apm_mappings

    print("== apm mappings ==")
    ensure_apm_mappings()
    print("== data views ==")
    ensure_data_views()
    print("== kibana saved objects ==")
    import_saved_objects()
    print("== incident dashboard (ES|QL) ==")
    try:
        publish_dashboard()
    except SystemExit:
        print("  [warn] dashboard publish failed; run: python -m src.cli dashboards")
    if include_alerts:
        print("== alert rules ==")
        ensure_alert_rules()
    kb = KIBANA_DIR / "knowledge-base-checkout-oom.md"
    if kb.exists():
        print(f"  [info] U4 knowledge base export: {kb}")
    print("setup complete")
