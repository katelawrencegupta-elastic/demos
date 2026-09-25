"""Keep ESS Billing OOTB dashboards working against synthetic + Fleet data.

History: an ELK Co index template (priority 210) shadowed Fleet's
`metrics-ess_billing.billing@package` mapping. `deployment_name` /
`deployment_type` then landed as non-aggregatable text (or were absent),
so OOTB Lens/controls reported "Could not locate field" / ES|QL
verification_exception. Heal by removing the shadowing template and
confirming package keyword mappings + docs with those fields.

A second failure mode: Kibana data views (`metrics-*`, package-specific)
cache field lists. After a stream recreate/backfill they can still report
0 `ess.billing.*` fields even when ES mappings + docs are healthy — Lens
then shows "Could not locate field". Refresh those data views as part of
health.
"""
from __future__ import annotations

import requests

from src.config import ELASTIC_URL, ES_HEADERS, KBN_HEADERS, KIBANA_ROOT, KIBANA_URL

DATA_STREAM = "metrics-ess_billing.billing-default"
# Current + prior company-name shadow templates (delete either if present).
SHADOW_TEMPLATES = ("elk-ess-billing", "meridian-ess-billing")
SHADOW_TEMPLATE = SHADOW_TEMPLATES[0]
REQUIRED_KEYWORD = (
    "ess.billing.deployment_name",
    "ess.billing.deployment_type",
    "ess.billing.deployment_id",
)
# Fields the OOTB Billing dashboard / Lens panels need visible on data views.
DASHBOARD_FIELDS = REQUIRED_KEYWORD + (
    "ess.billing.sku",
    "ess.billing.total_ecu",
    "ess.billing.type",
    "ess.billing.quantity.value",
    "ess.billing.cloud.service.type",
    "ess.billing.cloud.machine.type",
)


def _field_types() -> dict[str, list[str]]:
    r = requests.post(
        f"{ELASTIC_URL}/metrics-ess_billing.billing-*/_field_caps",
        headers=ES_HEADERS,
        json={"fields": list(REQUIRED_KEYWORD)},
        timeout=30,
    )
    if r.status_code != 200:
        return {}
    out = {}
    for name, types in (r.json().get("fields") or {}).items():
        if name in REQUIRED_KEYWORD:
            out[name] = list(types.keys())
    return out


def remove_shadowing_template() -> bool:
    removed_any = False
    for name in SHADOW_TEMPLATES:
        r = requests.get(
            f"{ELASTIC_URL}/_index_template/{name}",
            headers=ES_HEADERS,
            timeout=30,
        )
        if r.status_code == 404:
            continue
        requests.delete(
            f"{ELASTIC_URL}/_index_template/{name}",
            headers=ES_HEADERS,
            timeout=30,
        )
        print(f"  [ok] removed shadowing index template {name}")
        removed_any = True
    return removed_any


def _list_ess_data_views(base: str) -> list[tuple[str, str]]:
    """Return [(id, title)] for metrics-* and ESS billing data views in a space."""
    r = requests.get(f"{base}/api/data_views", headers=KBN_HEADERS, timeout=30)
    if r.status_code != 200:
        return []
    views = r.json().get("data_view") or r.json().get("data_views") or []
    if isinstance(views, dict):
        views = views.get("items") or list(views.values())
    out = []
    for v in views:
        title = v.get("title") or ""
        vid = v.get("id")
        if not vid:
            continue
        if title == "metrics-*" or "ess_billing.billing" in title:
            out.append((vid, title))
    return out


def _data_view_has_ess_fields(base: str, vid: str) -> tuple[bool, int]:
    r = requests.get(
        f"{base}/api/data_views/data_view/{vid}",
        headers=KBN_HEADERS,
        timeout=30,
    )
    if r.status_code != 200:
        return False, 0
    fields = (r.json().get("data_view") or {}).get("fields") or {}
    if isinstance(fields, list):
        names = {f.get("name") for f in fields if isinstance(f, dict)}
    else:
        names = set(fields.keys())
    present = sum(1 for f in DASHBOARD_FIELDS if f in names)
    return present >= len(REQUIRED_KEYWORD), present


def refresh_ess_billing_data_views(*, fail_loud: bool = False) -> bool:
    """Force Kibana data views to re-read ess.billing.* from Elasticsearch."""
    bases = []
    for b in (KIBANA_URL, KIBANA_ROOT):
        if b and b not in bases:
            bases.append(b)
    ok = True
    for base in bases:
        space = "finops" if base == KIBANA_URL and KIBANA_URL != KIBANA_ROOT else "default"
        if "/s/" in (base or ""):
            space = base.rstrip("/").split("/")[-1]
        views = _list_ess_data_views(base)
        if not views:
            views = [("metrics-*", "metrics-*")]
        for vid, title in views:
            healthy, n = _data_view_has_ess_fields(base, vid)
            if healthy:
                print(f"  [ok] data view {space}/{title}: {n} ess.billing fields")
                continue
            body = {"refresh_fields": True, "data_view": {"title": title}}
            r = requests.post(
                f"{base}/api/data_views/data_view/{vid}",
                headers=KBN_HEADERS,
                json=body,
                timeout=60,
            )
            if r.status_code >= 300:
                msg = (
                    f"data view refresh {space}/{vid}: "
                    f"{r.status_code} {r.text[:200]}"
                )
                if fail_loud:
                    raise SystemExit(f"  [fail] {msg}")
                print(f"  [warn] {msg}")
                ok = False
                continue
            healthy, n = _data_view_has_ess_fields(base, vid)
            if healthy:
                print(
                    f"  [ok] refreshed data view {space}/{title}: "
                    f"{n} ess.billing fields"
                )
            else:
                msg = (
                    f"data view {space}/{title} still missing "
                    f"ess.billing fields ({n})"
                )
                if fail_loud:
                    raise SystemExit(f"  [fail] {msg}")
                print(f"  [warn] {msg}")
                ok = False
    return ok


def ensure_ess_billing_field_health(*, fail_loud: bool = False) -> bool:
    """Ensure deployment_* fields are aggregatable keywords for OOTB Lens."""
    print("== ESS billing field health ==")
    removed = remove_shadowing_template()
    types = _field_types()
    bad = []
    for field in REQUIRED_KEYWORD:
        got = types.get(field) or []
        if "keyword" not in got:
            bad.append(f"{field}={got or 'MISSING'}")
    if bad:
        msg = (
            "ESS billing mappings are not OOTB-compatible "
            f"({', '.join(bad)}). Delete {DATA_STREAM} and re-backfill "
            "`--scope ess-billing` so Fleet package keyword mappings apply."
        )
        if fail_loud:
            raise SystemExit(f"  [fail] {msg}")
        print(f"  [warn] {msg}")
        return False

    # Confirm docs actually carry the fields (mapping alone is not enough).
    # Partial backfills without a wipe leave stale lines missing
    # ess.billing.cloud.* — require full coverage, not just >0.
    r = requests.post(
        f"{ELASTIC_URL}/_query",
        headers=ES_HEADERS,
        json={
            "query": (
                "FROM metrics-ess_billing.billing-*\n"
                "| STATS n = COUNT(*), "
                "named = COUNT(ess.billing.deployment_name), "
                "svc = COUNT(`ess.billing.cloud.service.type`)\n"
            )
        },
        timeout=60,
    )
    if r.status_code != 200:
        msg = f"ESS billing probe failed: {r.status_code} {r.text[:200]}"
        if fail_loud:
            raise SystemExit(f"  [fail] {msg}")
        print(f"  [warn] {msg}")
        return False
    rows = r.json().get("values") or [[0, 0, 0]]
    n, named, svc = rows[0][0], rows[0][1], rows[0][2]
    if n == 0:
        msg = "ESS billing stream is empty — run backfill --scope ess-billing"
        if fail_loud:
            raise SystemExit(f"  [fail] {msg}")
        print(f"  [warn] {msg}")
        return False
    if named == 0 or named < n:
        msg = (
            f"ESS billing docs lack deployment_name ({named}/{n}) — wipe "
            f"{DATA_STREAM} and re-backfill `--scope ess-billing`"
        )
        if fail_loud:
            raise SystemExit(f"  [fail] {msg}")
        print(f"  [warn] {msg}")
        return False
    if svc < n:
        msg = (
            f"ESS billing docs lack cloud.service.type ({svc}/{n}) — wipe "
            f"{DATA_STREAM} and re-backfill `--scope ess-billing` "
            "(create-only backfill will not update stale docs)"
        )
        if fail_loud:
            raise SystemExit(f"  [fail] {msg}")
        print(f"  [warn] {msg}")
        return False
    note = " (removed shadowing template)" if removed else ""
    print(
        f"  [ok] deployment_* keyword; {named}/{n} named; "
        f"{svc}/{n} cloud.service.type{note}"
    )

    print("== ESS billing data views (field cache) ==")
    return refresh_ess_billing_data_views(fail_loud=fail_loud)


def pin_ess_billing_dashboards_all_spaces() -> None:
    """Pin OOTB ESS Billing dashboards in default + finops spaces.

    Fleet installs stable ids (`ess_billing-billingdashboard`) in the default
    space; installing into a Kibana space remaps them to new UUIDs with
    originId set. Pin both.
    """
    from src.setup_cmd import _backfill_time_range

    win = _backfill_time_range()
    targets = [
        (KIBANA_ROOT, "ess_billing-billingdashboard"),
        (KIBANA_ROOT, "ess_billing-creditsdashboard"),
    ]
    for origin in (
        "ess_billing-billingdashboard",
        "ess_billing-creditsdashboard",
    ):
        r = requests.get(
            f"{KIBANA_URL}/api/dashboards/{origin}",
            headers=KBN_HEADERS,
            timeout=30,
        )
        if r.status_code == 200:
            targets.append((KIBANA_URL, origin))

    for base in (KIBANA_URL,):
        for did in (
            "94e01542-b7d9-51c6-85ca-e5d1d87f8dde",
            "a993ca71-5d10-5438-b5e3-6af50291ba28",
        ):
            targets.append((base, did))

    seen = set()
    for base, did in targets:
        key = (base, did)
        if key in seen:
            continue
        seen.add(key)
        r = requests.get(
            f"{base}/api/dashboards/{did}", headers=KBN_HEADERS, timeout=30
        )
        if r.status_code != 200:
            continue
        body = r.json()["data"]
        body["time_range"] = win
        rr = requests.put(
            f"{base}/api/dashboards/{did}",
            headers=KBN_HEADERS,
            json=body,
            timeout=60,
        )
        space = "finops" if base == KIBANA_URL and KIBANA_URL != KIBANA_ROOT else "default"
        if "/s/" in (base or ""):
            space = base.rstrip("/").split("/")[-1]
        if rr.status_code >= 300:
            print(
                f"  [warn] pin {space}/{did}: {rr.status_code} {rr.text[:200]}"
            )
        else:
            print(f"  [ok] pinned {space}: {body.get('title')}")
