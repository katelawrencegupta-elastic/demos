"""Provision live Verdian Dynamics FinOps Kibana Workflows.

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
WORKFLOWS_API = f"{KIBANA_URL}/api/workflows"
WORKFLOW_APP_URL = f"{KIBANA_URL}/app/workflows"

WORKFLOW_IDS = (
    "gev-finops-spend-spike-case",
    "gev-finops-spend-spike-auto-approve",
    "gev-finops-rightsize-case",
    "gev-finops-rightsize-auto-approve",
)


def _kbn(method: str, url: str, **kwargs):
    kwargs.setdefault("headers", KBN_HEADERS)
    kwargs.setdefault("timeout", 60)
    return requests.request(method, url, **kwargs)


def _find_existing(workflow_id: str) -> dict | None:
    r = _kbn("GET", f"{WORKFLOWS_API}/workflow/{workflow_id}")
    if r.status_code == 200:
        return r.json()
    r = _kbn(
        "GET",
        WORKFLOWS_API,
        params={"query": workflow_id, "size": 50, "page": 1},
    )
    if r.status_code != 200:
        return None
    for item in r.json().get("results") or []:
        if item.get("id") == workflow_id:
            return item
    return None


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
            json={"id": workflow_id, "yaml": yaml_text},
        )
        action = "created"

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
    print(f"  [ok] workflow {action}: {workflow_id} (enabled={body.get('enabled', True)})")
    return True


def ensure_workflows(fail_loud: bool = False) -> bool:
    print("== FinOps workflows ==")
    ok = True
    for wid in WORKFLOW_IDS:
        if not _upsert_one(wid, fail_loud):
            ok = False
    print(f"  UI:       {WORKFLOW_APP_URL}")
    return ok


def verify_workflows() -> bool:
    print("== FinOps workflows ==")
    ok = True
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
    print(f"  UI:       {WORKFLOW_APP_URL}")
    return ok
