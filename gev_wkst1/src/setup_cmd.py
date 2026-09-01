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

RETIRED_ALERT_NAMES = ("elasticco-checkout-slo-burn",)

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
        "id": "metrics-elasticco.host-*",
        "title": "metrics-elasticco.host-*",
        "name": "Elastic Co. Host Metrics",
        "timeFieldName": "@timestamp",
    },
    {
        "id": "elasticco-incidents",
        "title": "logs-elasticco.incident-*",
        "name": "Elastic Co. Incident Audit",
        "timeFieldName": "@timestamp",
    },
    {
        "id": "elasticco-logs",
        "title": "logs-elasticco.*",
        "name": "Elastic Co. Logs",
        "timeFieldName": "@timestamp",
    },
    {
        "id": "elasticco-all",
        "title": "logs-elasticco.*,metrics-elasticco.*,metrics-apm*,traces-apm*",
        "name": "Elastic Co. All",
        "timeFieldName": "@timestamp",
    },
]

# Fields Discover needs after backfill — used by verify + refresh guardrails.
DATA_VIEW_REQUIRED_FIELDS: dict[str, list[str]] = {
    "elasticco-orchestrator": ["tenant.id", "trace.id", "orchestrator.dag_id", "log.level"],
    "elasticco-checkout": ["service.name", "service.version", "message"],
    "elasticco-k8s": ["kubernetes.event.reason", "kubernetes.pod.name", "service.name"],
    "metrics-elasticco.host-*": ["system.cpu.total.norm.pct", "host.name"],
    "elasticco-incidents": ["incident.id", "incident.phase", "message"],
    "elasticco-logs": ["tenant.id", "trace.id", "service.name", "kubernetes.event.reason"],
}


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


def _disable_retired_rules(names: tuple[str, ...] = RETIRED_ALERT_NAMES):
    """Disable rules renamed out of the demo (e.g. fake SLO-burn)."""
    for name in names:
        r = requests.get(
            f"{KIBANA_URL}/api/alerting/rules/_find",
            headers=KBN_HEADERS,
            params={"search": name, "search_fields": "name", "per_page": 20},
            timeout=60,
        )
        if r.status_code != 200:
            continue
        for rule in r.json().get("data") or []:
            if rule.get("name") != name:
                continue
            rid = rule.get("id")
            if not rid or not rule.get("enabled", True):
                print(f"  [ok] retired alert already off: {name}")
                continue
            r2 = requests.post(
                f"{KIBANA_URL}/api/alerting/rule/{rid}/_disable",
                headers=KBN_HEADERS,
                timeout=60,
            )
            if r2.status_code >= 300:
                print(f"  [warn] disable retired rule {name}: {r2.status_code} {r2.text[:160]}")
            else:
                print(f"  [ok] disabled retired alert: {name}")


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
    cleanup_probe_stream()
    print("  [ok] API key can create indices and write documents")


def cleanup_probe_stream():
    """Remove write-probe data stream if a prior setup left it behind."""
    for target in ("logs-elasticco-probe",):
        r = requests.delete(f"{ELASTIC_URL}/_data_stream/{target}", headers=ES_HEADERS, timeout=30)
        if r.status_code < 300:
            print(f"  [ok] removed probe data stream {target}")


def _create_data_view(dv: dict) -> bool:
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
        fields = r.json().get("data_view", {}).get("fields", {})
        print(f"  [ok] data view {dv['id']} ({len(fields)} fields)")
        return True
    if (
        r.status_code == 409
        or "already exists" in r.text.lower()
        or "duplicate data view" in r.text.lower()
    ):
        return _update_data_view(dv)
    print(f"  [warn] data view {dv['id']}: {r.status_code} {r.text[:200]}")
    return False


def _update_data_view(dv: dict) -> bool:
    body = {
        "data_view": {
            "title": dv["title"],
            "name": dv["name"],
            "timeFieldName": dv["timeFieldName"],
        }
    }
    for method, path in (
        ("POST", f"/api/data_views/data_view/{dv['id']}"),
        ("PUT", f"/api/data_views/data_view/{dv['id']}"),
    ):
        r = requests.request(method, f"{KIBANA_URL}{path}", headers=KBN_HEADERS, json=body, timeout=60)
        if r.status_code < 300:
            fields = r.json().get("data_view", {}).get("fields", {})
            print(f"  [ok] data view {dv['id']} updated ({len(fields)} fields)")
            return True
    print(f"  [warn] update data view {dv['id']}: {r.status_code} {r.text[:200]}")
    return False


def ensure_data_views():
    for dv in DATA_VIEWS:
        _create_data_view(dv)


def refresh_data_views(*, force: bool = True):
    """Recreate data views so Kibana reloads field caps from indexed documents.

    Serverless has no fields/_refresh API; delete+create after backfill is required
    when views were first created against empty indices or overwritten by ndjson import.
    """
    cleanup_probe_stream()
    for dv in DATA_VIEWS:
        if force:
            requests.delete(
                f"{KIBANA_URL}/api/data_views/data_view/{dv['id']}",
                headers=KBN_HEADERS,
                timeout=30,
            )
        _create_data_view(dv)


def verify_data_views() -> bool:
    """Assert demo data views expose structured fields (not the managed logs-* view)."""
    ok = True
    for dv_id, required in DATA_VIEW_REQUIRED_FIELDS.items():
        r = requests.get(
            f"{KIBANA_URL}/api/data_views/data_view/{dv_id}",
            headers=KBN_HEADERS,
            timeout=60,
        )
        if r.status_code >= 300:
            print(f"[fail] data view {dv_id}: {r.status_code}")
            ok = False
            continue
        fields = r.json().get("data_view", {}).get("fields", {})
        missing = [f for f in required if f not in fields]
        if missing:
            print(f"[fail] data view {dv_id} missing fields: {', '.join(missing)}")
            print("       run: python -m src.cli dashboards   (after backfill)")
            ok = False
        else:
            print(f"[ok] data view {dv_id}: {len(fields)} fields incl. {', '.join(required[:3])}")
    return ok


def _delete_rule(rid: str, name: str) -> bool:
    r = requests.delete(
        f"{KIBANA_URL}/api/alerting/rule/{rid}",
        headers=KBN_HEADERS,
        timeout=60,
    )
    if r.status_code >= 300 and r.status_code != 404:
        print(f"  [warn] delete rule {name}: {r.status_code} {r.text[:160]}")
        return False
    print(f"  [ok] deleted rule {name} (will recreate)")
    return True


def _create_rule(rule: dict) -> bool:
    """POST a rule; consumer cannot be changed on update. Retry alerts if infrastructure 400s."""
    consumers = [rule.get("consumer") or "alerts"]
    for extra in ("alerts", "observability"):
        if extra not in consumers:
            consumers.append(extra)
    last = None
    bodies = [rule]
    if rule.get("actions"):
        bodies.append({**rule, "actions": []})
    for consumer in consumers:
        for body in bodies:
            payload = {**body, "consumer": consumer}
            r = requests.post(
                f"{KIBANA_URL}/api/alerting/rule",
                headers=KBN_HEADERS,
                json=payload,
                timeout=60,
            )
            last = r
            if r.status_code < 300:
                extra = f" (consumer={consumer})" if consumer != rule.get("consumer") else ""
                print(f"  [ok] alert rule created: {rule['name']}{extra}")
                return True
            if r.status_code != 400:
                break
    print(f"  [warn] create rule {rule['name']}: {last.status_code} {last.text[:300]}")
    return False


def ensure_alert_rules():
    """Create noisy vs quality ES query rules via Kibana alerting API."""
    rules_file = KIBANA_DIR / "alert-rules.json"
    if not rules_file.exists():
        print("  [warn] kibana/alert-rules.json missing; skip alerts")
        return
    rules = json.loads(rules_file.read_text())
    _disable_retired_rules()
    for rule in rules:
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
            remote = existing[0]
            rid = remote["id"]
            # consumer / rule_type_id are immutable — recreate so noisy CPU
            # can leave consumer=logs (execution_status=error on host metrics).
            if remote.get("consumer") != rule.get("consumer") or remote.get("rule_type_id") != rule.get(
                "rule_type_id"
            ):
                if _delete_rule(rid, rule["name"]):
                    _create_rule(rule)
                continue
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
        _create_rule(rule)


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
    print("== kibana saved objects ==")
    import_saved_objects()
    print("== data views ==")
    refresh_data_views(force=True)
    print("== incident dashboard (ES|QL) ==")
    try:
        publish_dashboard()
    except SystemExit:
        print("  [warn] dashboard publish failed; run: python -m src.cli dashboards")
    if include_alerts:
        print("== alert rules ==")
        ensure_alert_rules()
    print("== native SLOs ==")
    try:
        from src.slos import ensure_slos
        ensure_slos(fail_loud=False)
    except Exception as exc:
        print(f"  [warn] SLO provision: {exc}")
    print("== Agent Builder RCA agent ==")
    try:
        from src.agent_builder import ensure_agent
        ensure_agent(fail_loud=False)
    except Exception as exc:
        print(f"  [warn] Agent Builder: {exc}")
    kb = KIBANA_DIR / "knowledge-base-checkout-oom.md"
    if kb.exists():
        print(f"  [info] U4 knowledge base export: {kb}")
    print("setup complete")
