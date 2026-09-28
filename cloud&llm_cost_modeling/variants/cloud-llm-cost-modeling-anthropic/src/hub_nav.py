"""Bidirectional FinOps hub tab navigation.

Injects / upserts the same horizontal \"FinOps dashboards\" links bar onto every
hub destination so OOTB boards (GCP Billing, ESS, Inference, …) always link
back to Overview in the same browser tab.
"""
from __future__ import annotations

import copy

import requests

from src.config import KBN_HEADERS, KIBANA_URL

HUB_PANEL_ID = "finops-hub-tabs"
HUB_PANEL_TITLE = "FinOps dashboards"
HUB_SHIFT_Y = 7  # panel h=5 + 2 gap


def _hub_links_config(items: list) -> dict:
    """Links embeddable config — always same-tab."""
    links = []
    for item in items:
        if len(item) >= 3 and item[2] == "externalLink":
            label, dest = item[0], item[1]
            links.append({
                "label": label,
                "type": "externalLink",
                "destination": dest,
                "options": {"open_in_new_tab": False},
            })
        else:
            label, dest = item[0], item[1]
            links.append({
                "label": label,
                "type": "dashboardLink",
                "destination": dest,
                "options": {
                    "use_filters": True,
                    "use_time_range": True,
                    "open_in_new_tab": False,
                },
            })
    return {
        "title": HUB_PANEL_TITLE,
        "hide_title": False,
        "layout": "horizontal",
        "links": links,
    }


def hub_tabs_embeddable(items: list, *, y: int = 0) -> dict:
    """Flat links panel suitable for Dashboard API ``panels`` lists."""
    return {
        "grid": {"x": 0, "y": y, "w": 48, "h": 5},
        "type": "links",
        "config": _hub_links_config(items),
    }


def _is_hub_panel(panel: dict) -> bool:
    if not isinstance(panel, dict) or panel.get("type") != "links":
        return False
    # Live NDJSON may carry panelIndex; Dashboard API PUT rejects writing it.
    if panel.get("panelIndex") == HUB_PANEL_ID or panel.get("id") == HUB_PANEL_ID:
        return True
    title = (panel.get("config") or {}).get("title") or ""
    return title == HUB_PANEL_TITLE


def _shift_y(panel: dict, dy: int) -> None:
    grid = panel.get("grid")
    if isinstance(grid, dict) and "y" in grid:
        grid["y"] = int(grid["y"]) + dy
    for child in panel.get("panels") or []:
        _shift_y(child, dy)


def _find_hub_in_panels(panels: list) -> dict | None:
    for p in panels or []:
        if _is_hub_panel(p):
            return p
        found = _find_hub_in_panels(p.get("panels") or [])
        if found is not None:
            return found
    return None


def apply_hub_tabs_to_body(body: dict, items: list) -> dict:
    """Return a copy of dashboard body with hub tabs upserted at the top."""
    out = copy.deepcopy(body)
    panels = list(out.get("panels") or [])
    existing = _find_hub_in_panels(panels)
    cfg = _hub_links_config(items)
    if existing is not None:
        existing["config"] = cfg
        existing["type"] = "links"
        # Do not set panelIndex — Kibana Dashboard API rejects it on PUT.
        grid = existing.setdefault("grid", {"x": 0, "y": 0, "w": 48, "h": 5})
        grid.setdefault("x", 0)
        grid.setdefault("w", 48)
        grid.setdefault("h", 5)
    else:
        for p in panels:
            _shift_y(p, HUB_SHIFT_Y)
        panels.insert(0, hub_tabs_embeddable(items, y=0))
        out["panels"] = panels
    return out


def _strip_panel_index(obj):
    """Dashboard API PUT rejects ``panelIndex`` even when GET returns it."""
    if isinstance(obj, dict):
        out = {k: _strip_panel_index(v) for k, v in obj.items() if k != "panelIndex"}
        return out
    if isinstance(obj, list):
        return [_strip_panel_index(v) for v in obj]
    return obj


def upsert_hub_tabs(dashboard_id: str, items: list | None = None) -> bool:
    """GET → upsert FinOps hub bar → PUT. Returns False if missing / failed."""
    from src.dashboards import hub_tabs_items

    items = items if items is not None else hub_tabs_items()
    r = requests.get(
        f"{KIBANA_URL}/api/dashboards/{dashboard_id}",
        headers=KBN_HEADERS,
        timeout=60,
    )
    if r.status_code == 404:
        print(f"  [skip] hub tabs {dashboard_id}: not found")
        return False
    if r.status_code != 200:
        print(f"  [warn] hub tabs GET {dashboard_id}: {r.status_code}")
        return False
    body = r.json().get("data") or r.json()
    rewritten = _strip_panel_index(apply_hub_tabs_to_body(body, items))
    r = requests.put(
        f"{KIBANA_URL}/api/dashboards/{dashboard_id}",
        headers=KBN_HEADERS,
        json=rewritten,
        timeout=60,
    )
    if r.status_code >= 300:
        print(f"  [warn] hub tabs PUT {dashboard_id}: {r.status_code} {r.text[:200]}")
        return False
    print(f"  [ok] hub tabs on {dashboard_id}")
    return True


def hub_destination_ids(items: list | None = None) -> list[str]:
    """Unique dashboard ids referenced by hub tab items (including Overview)."""
    from src.dashboards import hub_tabs_items

    items = items if items is not None else hub_tabs_items()
    ids: list[str] = []
    for item in items:
        dest = item[1]
        if isinstance(dest, str) and not dest.startswith("/") and dest not in ids:
            ids.append(dest)
    return ids


def ensure_hub_tabs_on_destinations(items: list | None = None) -> int:
    """Upsert hub bar onto every destination in ``items``. Returns success count."""
    from src.dashboards import hub_tabs_items

    items = items if items is not None else hub_tabs_items()
    print("== FinOps hub tabs on destinations ==")
    ok = 0
    for did in hub_destination_ids(items):
        if upsert_hub_tabs(did, items):
            ok += 1
    return ok


def live_hub_tabs_items() -> list:
    """Hub destinations for the live AWS Cost Explorer FinOps space."""
    from src.live_dashboards import DASHBOARD_IDS, _resolve_hub_ids

    mapping = _resolve_hub_ids()
    overview, billing, spend, rightsizing = DASHBOARD_IDS
    items = [
        ("Overview", overview),
        ("AWS Billing", billing),
        ("Spend vs savings", spend),
        ("Rightsizing", rightsizing),
    ]
    if "kibana-inference-token-usage" in mapping:
        items.append(("Inference tokens", mapping["kibana-inference-token-usage"]))
    if "ess_billing-billingdashboard" in mapping:
        items.append(("ESS Billing", mapping["ess_billing-billingdashboard"]))
    if "ess_billing-creditsdashboard" in mapping:
        items.append(("ESS Credits", mapping["ess_billing-creditsdashboard"]))
    return items


def verify_hub_tabs(dashboard_id: str, *, overview_id: str) -> tuple[bool, str]:
    """Assert hub panel has Overview → overview_id and no new-tab links."""
    r = requests.get(
        f"{KIBANA_URL}/api/dashboards/{dashboard_id}",
        headers=KBN_HEADERS,
        timeout=60,
    )
    if r.status_code == 404:
        return False, "dashboard missing"
    if r.status_code != 200:
        return False, f"GET {r.status_code}"
    body = r.json().get("data") or r.json()
    hub = _find_hub_in_panels(body.get("panels") or [])
    if hub is None:
        return False, "no FinOps hub tabs panel"
    links = (hub.get("config") or {}).get("links") or []
    if not links:
        return False, "hub panel has no links"
    overview = next((L for L in links if L.get("label") == "Overview"), None)
    if overview is None:
        return False, "Overview tab missing"
    if overview.get("destination") != overview_id:
        return False, f"Overview→{overview.get('destination')!r} want {overview_id!r}"
    bad_new = [
        L.get("label")
        for L in links
        if (L.get("options") or {}).get("open_in_new_tab") is True
    ]
    if bad_new:
        return False, f"open_in_new_tab on {bad_new}"
    return True, f"{len(links)} tabs"
