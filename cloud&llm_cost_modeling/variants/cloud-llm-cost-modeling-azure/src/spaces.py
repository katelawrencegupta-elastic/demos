"""Ensure the configured Kibana space exists (spaces API is not space-scoped)."""
from __future__ import annotations

import requests

from src.config import KBN_HEADERS, KIBANA_ROOT, KIBANA_SPACE

SPACE_API = f"{KIBANA_ROOT}/api/spaces/space"


def _kbn(method: str, url: str, **kwargs):
    kwargs.setdefault("headers", KBN_HEADERS)
    kwargs.setdefault("timeout", 60)
    return requests.request(method, url, **kwargs)


def ensure_space(fail_loud: bool = False) -> bool:
    space = (KIBANA_SPACE or "").strip()
    if not space or space.lower() == "default":
        return True
    print(f"== Kibana space {space} ==")
    body = {
        "id": space,
        "name": "FinOps" if space == "finops" else space,
        "description": "ELK Co FinOps",
        "color": "#0B6E4F",
        "initials": "FO",
        "disabledFeatures": [],
    }
    r = _kbn("GET", f"{SPACE_API}/{space}")
    if r.status_code == 200:
        r = _kbn("PUT", f"{SPACE_API}/{space}", json=body)
        if r.status_code >= 300:
            print(f"  [ok] space exists: {space}")
        else:
            print(f"  [ok] space updated: {space}")
        return True
    r = _kbn("POST", SPACE_API, json=body)
    if r.status_code >= 300:
        msg = f"  [fail] create space {space}: {r.status_code} {r.text[:400]}"
        if fail_loud:
            raise SystemExit(msg)
        print(msg.replace("[fail]", "[warn]"))
        return False
    print(f"  [ok] space created: {space}")
    return True
