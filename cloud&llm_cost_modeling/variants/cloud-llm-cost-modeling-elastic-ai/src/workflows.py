"""Provision live ELK Co FinOps Kibana Workflows.

API refs:
  POST /api/workflows/workflow
  GET  /api/workflows/workflow/{id}
  PUT  /api/workflows/workflow/{id}
  GET  /api/workflows
"""
from __future__ import annotations

import json

import requests

from src.config import KBN_HEADERS, KIBANA_URL, ROOT

WORKFLOWS_DIR = ROOT / "kibana" / "live" / "workflows"


def _workflows_api() -> str:
    from src.config import KIBANA_URL
    return f"{KIBANA_URL}/api/workflows"


def _workflow_app_url() -> str:
    from src.config import KIBANA_URL
    return f"{KIBANA_URL}/app/workflows"


WORKFLOW_IDS = (
    "elk-finops-spend-spike-hitl",
    "elk-finops-spend-spike-auto-approve",
    "elk-finops-rightsize-case",
    "elk-finops-rightsize-auto-approve",
)

# Observability Cases custom fields required by the FinOps workflow YAML.
# createCase fails with "No custom fields configured" when this is empty.
_CASE_CUSTOM_FIELDS = (
    {"key": "resource-arn", "label": "Resource ARN", "type": "text", "required": False},
    {"key": "recommended-action", "label": "Recommended action", "type": "text", "required": False},
    {"key": "cloud-account-id", "label": "Cloud account ID", "type": "text", "required": False},
    {"key": "billing-service", "label": "Billing service", "type": "text", "required": False},
    {"key": "approval-status", "label": "Approval status", "type": "text", "required": False},
    {"key": "rca-class", "label": "RCA class", "type": "text", "required": False},
    {"key": "proposed-fix", "label": "Proposed fix", "type": "text", "required": False},
    {"key": "infeasible", "label": "Infeasible", "type": "text", "required": False},
)


def _kbn(method: str, url: str, **kwargs):
    kwargs.setdefault("headers", KBN_HEADERS)
    kwargs.setdefault("timeout", 60)
    return requests.request(method, url, **kwargs)


def ensure_case_configuration(fail_loud: bool = False) -> bool:
    """Ensure Observability Cases has FinOps custom fields (finops space)."""
    print("== Observability Cases config (FinOps custom fields) ==")
    r = _kbn("GET", f"{KIBANA_URL}/api/cases/configure", params={"owner": "observability"})
    if r.status_code >= 300:
        msg = f"  [fail] cases configure GET: {r.status_code} {r.text[:300]}"
        if fail_loud:
            raise SystemExit(msg)
        print(msg.replace("[fail]", "[warn]"))
        return False

    configs = r.json() if isinstance(r.json(), list) else []
    existing = next((c for c in configs if c.get("owner") == "observability"), None)
    wanted_keys = {f["key"] for f in _CASE_CUSTOM_FIELDS}

    if existing:
        have = {f.get("key") for f in (existing.get("customFields") or [])}
        missing = wanted_keys - have
        if not missing:
            print(f"  [ok] cases configure already has {len(have)} custom fields")
            return True
        # Merge: keep existing fields, append missing FinOps keys.
        merged = list(existing.get("customFields") or [])
        by_key = {f.get("key"): f for f in merged}
        for field in _CASE_CUSTOM_FIELDS:
            if field["key"] not in by_key:
                merged.append(dict(field))
        body = {
            "version": existing.get("version"),
            "customFields": merged,
        }
        cid = existing.get("id")
        r = _kbn("PATCH", f"{KIBANA_URL}/api/cases/configure/{cid}", json=body)
        action = "updated"
    else:
        body = {
            "owner": "observability",
            "connector": {
                "id": "none",
                "name": "none",
                "type": ".none",
                "fields": None,
            },
            "closure_type": "close-by-user",
            "customFields": [dict(f) for f in _CASE_CUSTOM_FIELDS],
        }
        r = _kbn("POST", f"{KIBANA_URL}/api/cases/configure", json=body)
        action = "created"

    if r.status_code >= 300:
        msg = f"  [fail] cases configure {action}: {r.status_code} {r.text[:400]}"
        if fail_loud:
            raise SystemExit(msg)
        print(msg.replace("[fail]", "[warn]"))
        return False
    fields = (r.json() or {}).get("customFields") or []
    print(f"  [ok] cases configure {action} ({len(fields)} custom fields)")
    return True


def _find_existing(workflow_id: str) -> dict | None:
    api = _workflows_api()
    r = _kbn("GET", f"{api}/workflow/{workflow_id}")
    if r.status_code == 200:
        return r.json()
    r = _kbn(
        "GET",
        api,
        params={"query": workflow_id, "size": 50, "page": 1},
    )
    if r.status_code != 200:
        return None
    for item in r.json().get("results") or []:
        if item.get("id") == workflow_id:
            return item
    return None


def _put_workflow(wid: str, yaml_text: str) -> requests.Response:
    return _kbn(
        "PUT",
        f"{_workflows_api()}/workflow/{wid}",
        json={"yaml": yaml_text, "enabled": True},
    )


def _post_workflow(workflow_id: str, yaml_text: str) -> requests.Response:
    return _kbn(
        "POST",
        f"{_workflows_api()}/workflow",
        json={"id": workflow_id, "yaml": yaml_text},
    )


def _delete_workflow(wid: str) -> None:
    _kbn("DELETE", f"{_workflows_api()}/workflow/{wid}")


def _upsert_one(workflow_id: str, fail_loud: bool) -> bool:
    path = WORKFLOWS_DIR / f"{workflow_id}.yaml"
    if not path.is_file():
        msg = f"  [fail] missing {path}"
        if fail_loud:
            raise SystemExit(msg)
        print(msg.replace("[fail]", "[warn]"))
        return False
    yaml_text = path.read_text(encoding="utf-8")
    existing = _find_existing(workflow_id)
    if existing:
        wid = existing.get("id") or workflow_id
        r = _put_workflow(wid, yaml_text)
        action = "updated"
    else:
        r = _post_workflow(workflow_id, yaml_text)
        action = "created"
        # After space delete, POST can 409 while GET-by-id still 404.
        if r.status_code == 409:
            recovered = _find_existing(workflow_id)
            if recovered:
                wid = recovered.get("id") or workflow_id
                print(f"  [warn] workflow {workflow_id} POST 409 — PUT via list id={wid}")
                r = _put_workflow(wid, yaml_text)
                action = "updated"
            else:
                print(f"  [warn] workflow {workflow_id} POST 409 — DELETE+POST retry")
                _delete_workflow(workflow_id)
                r = _post_workflow(workflow_id, yaml_text)
                action = "recreated"

    if r.status_code >= 300:
        msg = f"  [fail] workflow {action} {workflow_id}: {r.status_code} {r.text[:500]}"
        if r.status_code in (403, 404) and not fail_loud:
            print(msg.replace("[fail]", "[warn]"))
            return False
        if fail_loud:
            raise SystemExit(msg)
        print(msg.replace("[fail]", "[warn]"))
        return False

    body = r.json() if r.text else {}
    errs = body.get("validationErrors") or []
    if body.get("valid") is False or errs:
        snippet = json.dumps(errs or {"valid": body.get("valid")}, default=str)[:800]
        msg = f"  [fail] workflow invalid {workflow_id}: {snippet}"
        if fail_loud:
            raise SystemExit(msg)
        print(msg.replace("[fail]", "[warn]"))
        return False
    # Confirm readable (GET may 404 briefly after create; list fallback).
    if not _find_existing(workflow_id):
        msg = f"  [fail] workflow {workflow_id} upserted but not findable via GET/list"
        if fail_loud:
            raise SystemExit(msg)
        print(msg.replace("[fail]", "[warn]"))
        return False
    print(f"  [ok] workflow {action}: {workflow_id} (enabled={body.get('enabled', True)})")
    return True


def ensure_workflows(fail_loud: bool = False) -> bool:
    ok = ensure_case_configuration(fail_loud=fail_loud)
    print("== FinOps workflows ==")
    for wid in WORKFLOW_IDS:
        if not _upsert_one(wid, fail_loud):
            ok = False
    print(f"  UI:       {_workflow_app_url()}")
    return ok


def verify_workflows() -> bool:
    print("== FinOps workflows ==")
    ok = True
    r = _kbn("GET", f"{KIBANA_URL}/api/cases/configure", params={"owner": "observability"})
    configs = r.json() if r.status_code == 200 and isinstance(r.json(), list) else []
    cfg = next((c for c in configs if c.get("owner") == "observability"), None)
    have = {f.get("key") for f in (cfg or {}).get("customFields") or []}
    missing = {f["key"] for f in _CASE_CUSTOM_FIELDS} - have
    if missing:
        print(f"  [fail] cases custom fields missing: {sorted(missing)}")
        ok = False
    else:
        print(f"  [ok] cases configure ({len(have)} custom fields)")
    for wid in WORKFLOW_IDS:
        existing = _find_existing(wid)
        if not existing:
            print(f"  [fail] workflow missing: {wid}")
            ok = False
            continue
        if existing.get("enabled") is False:
            print(f"  [fail] workflow disabled: {wid}")
            ok = False
            continue
        print(f"  [ok] workflow {wid} ({existing.get('name')})")
    print(f"  UI:       {_workflow_app_url()}")
    return ok
