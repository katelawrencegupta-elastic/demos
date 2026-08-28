"""Kibana Observability Cases — create, comment, and update status."""
from __future__ import annotations

import requests

from src.config import KBN_HEADERS, KIBANA_URL

CASE_OWNER = "observability"
CASE_TITLE = "EKS restart loop — checkout-api (eks-elastic-prod-usc1)"
CASE_TAGS = ["elastic-co", "eks", "checkout-api", "oom", "demo"]
CASES_ACTION_ID = "system-connector-.cases"


def cases_system_action() -> dict:
    """Attach the Cases system connector so firing alerts open/update a case.

    Serverless rejects ``actionTypeId`` on rule updates; the connector id is enough.
    """
    return {
        "group": "query matched",
        "id": CASES_ACTION_ID,
        "params": {
            "subAction": "run",
            "subActionParams": {
                "groupingBy": [],
                "reopenClosedCases": True,
                "timeWindow": "7d",
            },
        },
        "frequency": {
            "notify_when": "onActiveAlert",
            "summary": False,
        },
    }


def _req(method: str, path: str, **kwargs) -> requests.Response:
    return requests.request(
        method,
        f"{KIBANA_URL}{path}",
        headers=KBN_HEADERS,
        timeout=60,
        **kwargs,
    )


def find_case(*, title: str = CASE_TITLE, tags: list[str] | None = None) -> dict | None:
    params: dict = {
        "owner": CASE_OWNER,
        "perPage": 50,
        "sortField": "createdAt",
        "sortOrder": "desc",
    }
    if tags:
        params["tags"] = tags
    r = _req("GET", "/api/cases/_find", params=params)
    if r.status_code >= 300:
        print(f"  [warn] find cases: {r.status_code} {r.text[:200]}")
        return None
    cases = r.json().get("cases", [])
    for c in cases:
        if c.get("title") == title:
            return c
    tagged = [t for t in (tags or []) if t]
    if tagged:
        for c in cases:
            ct = set(c.get("tags") or [])
            if set(tagged).issubset(ct):
                return c
    return None


def create_case(
    *,
    title: str = CASE_TITLE,
    description: str,
    severity: str = "high",
    tags: list[str] | None = None,
) -> dict | None:
    body = {
        "title": title,
        "description": description,
        "tags": tags or CASE_TAGS,
        "severity": severity if severity in ("low", "medium", "high", "critical") else "high",
        "owner": CASE_OWNER,
        "connector": {"id": "none", "name": "none", "type": ".none", "fields": None},
        "settings": {"syncAlerts": True},
    }
    r = _req("POST", "/api/cases", json=body)
    if r.status_code >= 300:
        print(f"  [warn] create case: {r.status_code} {r.text[:300]}")
        return None
    case = r.json()
    print(f"  [ok] case created: {case.get('title')} ({case_url(case)})")
    return case


def ensure_case(
    *,
    title: str = CASE_TITLE,
    description: str,
    severity: str = "high",
    tags: list[str] | None = None,
) -> dict | None:
    existing = find_case(title=title, tags=tags or CASE_TAGS)
    if existing:
        print(f"  [ok] case exists: {existing.get('title')} ({case_url(existing)})")
        return existing
    return create_case(title=title, description=description, severity=severity, tags=tags)


def add_comment(case_id: str, comment: str) -> dict | None:
    r = _req(
        "POST",
        f"/api/cases/{case_id}/comments",
        json={"comment": comment, "type": "user", "owner": CASE_OWNER},
    )
    if r.status_code >= 300:
        print(f"  [warn] case comment: {r.status_code} {r.text[:240]}")
        return None
    return r.json()


def set_status(case: dict, status: str) -> dict | None:
    """status: open | in-progress | closed."""
    cid = case.get("id")
    version = case.get("version")
    if not cid or not version:
        return None
    r = _req(
        "PATCH",
        "/api/cases",
        json={"cases": [{"id": cid, "version": version, "status": status}]},
    )
    if r.status_code >= 300:
        print(f"  [warn] case status {status}: {r.status_code} {r.text[:240]}")
        return None
    updated = r.json()
    if isinstance(updated, list) and updated:
        return updated[0]
    if isinstance(updated, dict) and updated.get("cases"):
        return updated["cases"][0]
    return updated if isinstance(updated, dict) else case


def case_url(case: dict) -> str:
    cid = case.get("id", "")
    return f"{KIBANA_URL}/app/observability/cases/{cid}"
