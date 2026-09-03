"""Provision Elastic Co. detect-to-remediate Kibana Workflow.

API refs:
  POST /api/workflows/workflow          create (optional custom id)
  GET  /api/workflows/workflow/{id}     read
  PUT  /api/workflows/workflow/{id}     update yaml / enabled
  GET  /api/workflows                   list (query=)
"""
from __future__ import annotations

import json

import requests

from src.config import KBN_HEADERS, KIBANA_DIR, KIBANA_URL

WORKFLOW_ID = "elasticco-detect-remediate"
WORKFLOW_FILE = KIBANA_DIR / "workflow-detect-remediate.yaml"
WORKFLOWS_API = f"{KIBANA_URL}/api/workflows"
WORKFLOW_APP_URL = f"{KIBANA_URL}/app/workflows"


def _kbn(method: str, url: str, **kwargs):
    kwargs.setdefault("headers", KBN_HEADERS)
    kwargs.setdefault("timeout", 60)
    return requests.request(method, url, **kwargs)


def load_yaml() -> str:
    if not WORKFLOW_FILE.exists():
        raise SystemExit(f"missing {WORKFLOW_FILE}")
    return WORKFLOW_FILE.read_text()


def _find_existing() -> dict | None:
    r = _kbn("GET", f"{WORKFLOWS_API}/workflow/{WORKFLOW_ID}")
    if r.status_code == 200:
        return r.json()
    if r.status_code not in (404, 400):
        # 400/404 on GET-by-id: fall through to list search
        pass

    r = _kbn(
        "GET",
        WORKFLOWS_API,
        params={"query": WORKFLOW_ID, "size": 50, "page": 1},
    )
    if r.status_code != 200:
        return None
    for item in r.json().get("results") or []:
        if item.get("id") == WORKFLOW_ID:
            return item
        if item.get("name") in (
            "Elastic Co. detect-to-remediate",
            WORKFLOW_ID,
        ):
            return item
    return None


def ensure_workflow(fail_loud: bool = False) -> bool:
    """Upsert the detect-to-remediate workflow. Must be enabled for the rule picker."""
    try:
        return _ensure_inner(fail_loud)
    except requests.RequestException as exc:
        msg = f"  [fail] Workflows HTTP: {exc}"
        if fail_loud:
            raise SystemExit(msg)
        print(msg.replace("[fail]", "[warn]"))
        return False


def _ensure_inner(fail_loud: bool) -> bool:
    yaml_text = load_yaml()
    print("== Elastic Co. detect-to-remediate workflow ==")
    existing = _find_existing()
    if existing:
        wid = existing.get("id") or WORKFLOW_ID
        r = _kbn(
            "PUT",
            f"{WORKFLOWS_API}/workflow/{wid}",
            json={"yaml": yaml_text, "enabled": True},
        )
        action = "updated"
    else:
        r = _kbn(
            "POST",
            f"{WORKFLOWS_API}/workflow",
            json={"id": WORKFLOW_ID, "yaml": yaml_text},
        )
        action = "created"

    if r.status_code >= 300:
        msg = f"  [fail] workflow {action} {WORKFLOW_ID}: {r.status_code} {r.text[:500]}"
        if r.status_code in (403, 404) and not fail_loud:
            print(msg.replace("[fail]", "[warn]"))
            print("         Workflows may be unavailable on this project; skip")
            return False
        if fail_loud:
            raise SystemExit(msg)
        print(msg.replace("[fail]", "[warn]"))
        return False

    body = r.json() if r.text else {}
    valid = body.get("valid", True)
    errs = body.get("validationErrors") or []
    if valid is False or errs:
        snippet = json.dumps(errs or {"valid": valid}, default=str)[:800]
        msg = f"  [fail] workflow invalid: {snippet}"
        if fail_loud:
            raise SystemExit(msg)
        print(msg.replace("[fail]", "[warn]"))
        return False

    print(f"  [ok] workflow {action}: {WORKFLOW_ID} (enabled={body.get('enabled', True)})")
    print(f"  UI:       {WORKFLOW_APP_URL}")
    return True


def verify_workflow() -> bool:
    print("== Elastic Co. detect-to-remediate workflow ==")
    existing = _find_existing()
    if not existing:
        print(f"  [fail] workflow missing: {WORKFLOW_ID}")
        print(f"         run: python -m src.cli workflow")
        print(f"  UI:       {WORKFLOW_APP_URL}")
        return False
    enabled = existing.get("enabled", True)
    valid = existing.get("valid", True)
    if not enabled:
        print(f"  [fail] workflow disabled: {WORKFLOW_ID} (must be enabled for Run Workflow)")
        return False
    if valid is False:
        print(f"  [fail] workflow invalid: {WORKFLOW_ID}")
        return False
    print(f"  [ok] workflow {WORKFLOW_ID} (enabled, name={existing.get('name')})")
    print(f"  UI:       {WORKFLOW_APP_URL}")
    return True
