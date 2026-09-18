"""Import live Verdian Dynamics FinOps dashboards (Lens/Vega saved objects)."""
from __future__ import annotations

import re

import requests

from src.config import KBN_HEADERS, KIBANA_ROOT, KIBANA_SPACE, KIBANA_URL, ROOT

NDJSON = ROOT / "kibana" / "live" / "dashboards.ndjson"

DASHBOARD_IDS = (
    "meridian-finops-llm-observability-dynamic-aws",
    "finops-aws-billing-overview-unblended",
    "finops-spend-vs-savings",
    "finops-rightsizing-overview",
)

# Vendored hub tabs still name the original-cluster dashboard UUIDs. Fleet
# installs the OOTB objects in the default space under these ids. Serverless
# cannot share the same id into another space, so finops gets title-matched copies.
OOTB_HUB_TITLES = {
    "kibana-inference-token-usage": "[Elastic] Inference Token Usage",
    "ess_billing-billingdashboard": "[Metrics ESS Billing] Billing dashboard",
    "ess_billing-creditsdashboard": "[Metrics ESS Billing] Credits dashboard",
}
HUB_BACKUP_IDS = {
    "ffd600e5-2862-4bf4-8556-2ef8872c5ba5": "kibana-inference-token-usage",
    "4e3d2263-42f4-43ce-bd12-dd7863f18804": "ess_billing-billingdashboard",
    "952b4e0a-1a55-4794-8c57-d26b8c6d9086": "ess_billing-creditsdashboard",
}
HUB_DASHBOARD_IDS = dict(HUB_BACKUP_IDS)
OOTB_HUB_DASHBOARDS = tuple(OOTB_HUB_TITLES.keys())
_KIBANA_HOST_RE = re.compile(r"https://[^/\s)]+\.kb\.[^/\s)]+elastic\.cloud")


def publish() -> list[str]:
    print("== live FinOps dashboards (saved-object import) ==")
    if not NDJSON.is_file():
        raise SystemExit(f"missing {NDJSON}")
    headers = {
        "Authorization": KBN_HEADERS["Authorization"],
        "kbn-xsrf": "true",
    }
    with open(NDJSON, "rb") as f:
        r = requests.post(
            f"{KIBANA_URL}/api/saved_objects/_import?overwrite=true",
            headers=headers,
            files={"file": ("dashboards.ndjson", f, "application/ndjson")},
            timeout=120,
        )
    if r.status_code >= 300:
        raise SystemExit(
            f"  [fail] dashboard import: {r.status_code} {r.text[:500]}")
    summary = r.json() if r.text else {}
    errors = summary.get("errors") or []
    print(
        f"  [ok] import success={summary.get('success')} "
        f"count={summary.get('successCount')} errors={len(errors)}"
    )
    for err in errors[:8]:
        print(f"  [warn] {err.get('type')}/{err.get('id')}: {err.get('error')}")
    urls = []
    for did in DASHBOARD_IDS:
        url = f"{KIBANA_URL}/app/dashboards#/view/{did}"
        print(f"  {url}")
        urls.append(url)
    _pin_time_ranges()
    _rewrite_billing_esql()
    ensure_hub_ootb()
    _refresh_billing_data_view()
    return urls


def _pin_time_ranges() -> None:
    """Store an absolute backfill window so the picker is not Last 15 minutes.

    Billing docs are daily at midnight; a relative 15-minute (or even 30-day
    window while 120d backfill is still catching up) looks empty.
    """
    from src.time_window import demo_window
    win = demo_window(to_pad_days=1)
    for did in DASHBOARD_IDS:
        r = requests.get(
            f"{KIBANA_URL}/api/dashboards/{did}",
            headers=KBN_HEADERS,
            timeout=30,
        )
        if r.status_code != 200:
            print(f"  [warn] dashboard GET {did}: {r.status_code}")
            continue
        body = r.json().get("data") or r.json()
        body["time_range"] = win
        r = requests.put(
            f"{KIBANA_URL}/api/dashboards/{did}",
            headers=KBN_HEADERS,
            json=body,
            timeout=60,
        )
        if r.status_code >= 300:
            print(f"  [warn] pin time range {did}: {r.status_code} {r.text[:200]}")
        else:
            print(f"  [ok] pinned {did} {win['from'][:10]} → {win['to'][:10]}")


_BILLING_ESQL_FIELDS = (
    "aws.billing.group_by.INSTANCE_TYPE",
    "aws.billing.group_by.AZ",
)


def _rewrite_esql_query(q: str) -> str:
    """Bind CE queries to the saved data view and quote sparse group_by grains.

    Kibana's dashboard ES|QL validator builds an ad-hoc data view from
    `FROM metrics-aws.billing-default`. That snapshot often omits dynamically
    mapped Cost Explorer dimensions (INSTANCE_TYPE, AZ), so the panel errors
    with "Field aws.billing.group_by.INSTANCE_TYPE was not found" even when
    Elasticsearch has the field. Point at `metrics-aws.billing-*` (the saved
    data view) and backtick the grain fields.
    """
    out = q.replace("FROM metrics-aws.billing-default", "FROM metrics-aws.billing-*")
    out = out.replace(
        "metrics-aws.billing-default-@timestamp",
        "metrics-aws.billing-*-@timestamp",
    )
    for field in _BILLING_ESQL_FIELDS:
        quoted = f"`{field}`"
        out = out.replace(quoted, field)
        out = out.replace(field, quoted)
    return _rewrite_ec2_cpu_query(out)


def _rewrite_ec2_cpu_query(q: str) -> str:
    """Fleet's aws.ec2_metrics pipeline renames CPUUtilization.avg -> host.cpu.usage.

    It also does `avg / 100` in Painless. Integer CPU (42) becomes 0 before the
    rename, so scatter/heatmap `WHERE cpu_avg IS NOT NULL` returns nothing.
    Query the ECS field (0-1) and scale back to percent.
    """
    if "aws.ec2.metrics.CPUUtilization.avg" not in q and "host.cpu.usage" not in q:
        return q
    out = q.replace("`aws.ec2.metrics.CPUUtilization.avg`", "aws.ec2.metrics.CPUUtilization.avg")
    out = out.replace(
        "PERCENTILE(aws.ec2.metrics.CPUUtilization.avg, 95)",
        "(PERCENTILE(host.cpu.usage, 95) * 100)",
    )
    out = out.replace(
        "AVG(aws.ec2.metrics.CPUUtilization.avg)",
        "(AVG(host.cpu.usage) * 100)",
    )
    out = out.replace("aws.ec2.metrics.CPUUtilization.avg", "host.cpu.usage")
    return out


def _rewrite_obj(obj):
    if isinstance(obj, dict):
        return {k: _rewrite_obj(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_rewrite_obj(v) for v in obj]
    if isinstance(obj, str) and "FROM metrics-aws.billing" in obj:
        return _rewrite_esql_query(obj)
    if isinstance(obj, str) and "aws.ec2.metrics.CPUUtilization" in obj:
        return _rewrite_ec2_cpu_query(obj)
    if isinstance(obj, str) and obj.startswith("metrics-aws.billing-default"):
        return obj.replace("metrics-aws.billing-default", "metrics-aws.billing-*")
    return obj


_RIGHTSIZING_HEATMAP_QUERY = """\
FROM metrics-aws.ec2_metrics-*
| WHERE @timestamp >= ?_tstart AND @timestamp < ?_tend
    AND cloud.instance.name IS NOT NULL
| STATS cpu = ROUND(AVG(host.cpu.usage) * 100, 1)
    BY t = DATE_TRUNC(1 week, @timestamp), instance = cloud.instance.name
| INLINE STATS avg_cpu = AVG(cpu) BY instance
| INLINE STATS cutoff_lo = PERCENTILE(avg_cpu, 10), cutoff_hi = PERCENTILE(avg_cpu, 90)
| WHERE avg_cpu <= cutoff_lo OR avg_cpu >= cutoff_hi
| SORT avg_cpu ASC, instance ASC, t ASC
| KEEP t, instance, cpu
"""


def _tune_rightsizing_heatmap(obj):
    """Keep ~18 short-named instance rows (idle vs busy tails) on a weekly grain.

    The vendored heatmap plotted every instance id across 24 buckets, hit the
    ES|QL 1000-row cap, and packed ~90 long labels into a short panel.
    """
    if not isinstance(obj, dict):
        if isinstance(obj, list):
            return [_tune_rightsizing_heatmap(v) for v in obj]
        return obj
    panels = obj.get("panels")
    if isinstance(panels, list) and any(
            p.get("id") in ("rs-vega-heat", "rs-v-heat") for p in panels if isinstance(p, dict)):
        return {**obj, "panels": _shift_rightsizing_heatmap_panels(panels)}
    if obj.get("id") in ("rs-vega-heat", "rs-v-heat") and obj.get("type") == "vis":
        cfg = dict(obj.get("config") or {})
        cfg["title"] = (
            "EC2 CPU heatmap — lowest vs highest 10% (weekly; "
            "persistent low color = idle)"
        )
        cfg["ignore_global_filters"] = True
        cfg["data_source"] = {"type": "esql", "query": _RIGHTSIZING_HEATMAP_QUERY}
        cfg["x"] = {"column": "t", "label": "Week"}
        cfg["y"] = {"column": "instance", "label": "Instance"}
        cfg["metric"] = {
            "column": "cpu",
            "label": "CPU %",
            "color": {"type": "auto"},
        }
        cfg["axis"] = {
            "x": {
                "title": {"text": "", "visible": False},
                "labels": {"visible": True, "orientation": "angled"},
                "scale": "temporal",
            },
            "y": {
                "title": {"visible": False},
                "labels": {"visible": True},
            },
        }
        grid = dict(obj.get("grid") or {})
        grid["h"] = max(int(grid.get("h") or 0), 26)
        return {**obj, "config": cfg, "grid": grid}
    return {k: _tune_rightsizing_heatmap(v) for k, v in obj.items()}


def _shift_rightsizing_heatmap_panels(panels: list) -> list:
    heat_ids = {"rs-vega-heat", "rs-v-heat"}
    heat_h = 26
    heat_y = None
    out = []
    for p in panels:
        if p.get("id") in heat_ids:
            tuned = _tune_rightsizing_heatmap(p)
            heat_y = int((tuned.get("grid") or {}).get("y") or 47)
            heat_h = int((tuned.get("grid") or {}).get("h") or heat_h)
            out.append(tuned)
        else:
            out.append(p)
    if heat_y is None:
        return out
    # Panels that used to sit under the old short heatmap (y>=61 table row)
    floor = 61
    new_below = heat_y + heat_h
    shifted = []
    for p in out:
        grid = dict(p.get("grid") or {})
        y = int(grid.get("y") or 0)
        if p.get("id") not in heat_ids and y >= floor:
            grid["y"] = y + (new_below - floor)
            shifted.append({**p, "grid": grid})
        else:
            shifted.append(p)
    return shifted


def _rewrite_billing_esql() -> None:
    for did in DASHBOARD_IDS:
        r = requests.get(
            f"{KIBANA_URL}/api/dashboards/{did}",
            headers=KBN_HEADERS,
            timeout=30,
        )
        if r.status_code != 200:
            print(f"  [warn] dashboard GET {did}: {r.status_code}")
            continue
        body = r.json().get("data") or r.json()
        rewritten = _tune_rightsizing_heatmap(_rewrite_obj(body))
        r = requests.put(
            f"{KIBANA_URL}/api/dashboards/{did}",
            headers=KBN_HEADERS,
            json=rewritten,
            timeout=60,
        )
        if r.status_code >= 300:
            print(f"  [warn] rewrite ES|QL {did}: {r.status_code} {r.text[:200]}")
        else:
            print(f"  [ok] rewrote billing ES|QL on {did}")


def _refresh_billing_data_view() -> None:
    r = requests.get(
        f"{KIBANA_URL}/api/data_views",
        headers=KBN_HEADERS,
        timeout=30,
    )
    if r.status_code != 200:
        return
    views = r.json().get("data_view") or r.json().get("data_views") or []
    if isinstance(views, dict):
        views = views.get("items") or []
    for v in views:
        title = v.get("title") or ""
        vid = v.get("id")
        if not vid or not any(
            key in title for key in (
                "aws.billing",
                "aws.ec2_metrics",
                "inference_token_usage",
                ".kibana-inference-token-usage",
                "finops-rightsizing-latest",
                "aws.rds",
            )
        ):
            continue
        new_title = title
        if title == ".kibana-inference-token-usage":
            new_title = "logs-elastic.inference_token_usage-default"
        r = requests.post(
            f"{KIBANA_URL}/api/data_views/data_view/{vid}",
            headers=KBN_HEADERS,
            timeout=30,
            json={"refresh_fields": True, "data_view": {"title": new_title}},
        )
        print(f"  [ok] refreshed data view {new_title}" if r.status_code < 300
              else f"  [warn] data view refresh {new_title}: {r.status_code}")


def ensure_hub_ootb() -> None:
    """Install/share OOTB inference + ESS dashboards and retarget hub tabs."""
    print("== FinOps hub OOTB dashboards ==")
    _install_ess_billing_package()
    from src.setup_cmd import patch_tsds_templates
    patch_tsds_templates()
    _share_hub_dashboards()
    _retarget_hub_links()
    _pin_hub_ootb_time_ranges()
    from src.setup_cmd import patch_inference_token_usage_dashboard
    patch_inference_token_usage_dashboard()


def _install_ess_billing_package() -> None:
    r = requests.get(
        f"{KIBANA_ROOT}/api/fleet/epm/packages/ess_billing",
        headers=KBN_HEADERS, timeout=60)
    if r.status_code >= 300:
        print(f"  [warn] ess_billing package lookup: {r.status_code} {r.text[:200]}")
        return
    item = r.json().get("item") or {}
    if item.get("status") == "installed":
        print(f"  [ok] package ess_billing {item.get('version')} already installed")
        return
    print("  installing package ess_billing ...")
    r = requests.post(
        f"{KIBANA_ROOT}/api/fleet/epm/packages/ess_billing",
        headers=KBN_HEADERS, json={}, timeout=600)
    if r.status_code >= 300:
        print(f"  [warn] ess_billing install: {r.status_code} {r.text[:300]}")
        return
    print("  [ok] package ess_billing installed")


def _list_space_dashboards(base: str) -> dict[str, str]:
    """Return {title: id} for dashboards visible in a space."""
    r = requests.get(f"{base}/api/dashboards", headers=KBN_HEADERS, timeout=60)
    if r.status_code != 200:
        print(f"  [warn] list dashboards {base}: {r.status_code} {r.text[:200]}")
        return {}
    out = {}
    for item in r.json().get("data") or []:
        data = item.get("data") or item
        title = data.get("title")
        did = item.get("id") or data.get("id")
        if title and did and title not in out:
            out[title] = did
    return out


def _resolve_hub_ids() -> dict[str, str]:
    """Map backup UUIDs + Fleet ids to the dashboard id that exists in this space."""
    space = (KIBANA_SPACE or "").strip()
    base = KIBANA_URL if space and space.lower() != "default" else KIBANA_ROOT
    by_title = _list_space_dashboards(base)
    mapping = {}
    for fleet_id, title in OOTB_HUB_TITLES.items():
        sid = by_title.get(title)
        if not sid:
            print(f"  [warn] {title} not in space {space or 'default'}")
            continue
        mapping[fleet_id] = sid
        print(f"  [ok] hub {title} -> {sid}")
    for backup_id, fleet_id in HUB_BACKUP_IDS.items():
        if fleet_id in mapping:
            mapping[backup_id] = mapping[fleet_id]
    HUB_DASHBOARD_IDS.clear()
    HUB_DASHBOARD_IDS.update(mapping)
    return mapping


def _share_hub_dashboards() -> None:
    import time
    space = (KIBANA_SPACE or "").strip()
    missing = []
    for did in OOTB_HUB_DASHBOARDS:
        r = None
        for _attempt in range(6):
            r = requests.get(
                f"{KIBANA_ROOT}/api/dashboards/{did}",
                headers=KBN_HEADERS, timeout=30)
            if r.status_code == 200:
                break
            time.sleep(2)
        if r is None or r.status_code != 200:
            missing.append(did)
            print(f"  [warn] OOTB dashboard missing in default space: {did}")
            continue
        title = (r.json().get("data") or r.json()).get("title") or did
        print(f"  [ok] default space has {did} ({title})")
    if not space or space.lower() == "default":
        _resolve_hub_ids()
        return
    present = _list_space_dashboards(KIBANA_URL)
    needed = [title for title in OOTB_HUB_TITLES.values() if title not in present]
    if not needed:
        print(f"  [ok] hub OOTB dashboards already in space {space}")
        _resolve_hub_ids()
        return
    objects = [{"type": "dashboard", "id": did}
               for did in OOTB_HUB_DASHBOARDS if did not in missing]
    if not objects:
        return
    r = requests.post(
        f"{KIBANA_ROOT}/api/spaces/_update_objects_spaces",
        headers=KBN_HEADERS, timeout=60,
        json={
            "objects": objects,
            "spacesToAdd": [space],
            "spacesToRemove": [],
            "includeReferences": True,
        },
    )
    if r.status_code < 300:
        print(f"  [ok] shared OOTB dashboards into space {space}")
        _resolve_hub_ids()
        return
    print(f"  [warn] share into {space}: {r.status_code} {r.text[:300]}")
    r = requests.post(
        f"{KIBANA_ROOT}/api/spaces/_copy_saved_objects",
        headers=KBN_HEADERS, timeout=120,
        json={
            "objects": objects,
            "spaces": [space],
            "includeReferences": True,
            "overwrite": True,
            "createNewCopies": False,
        },
    )
    if r.status_code < 300:
        print(f"  [ok] copied OOTB dashboards into space {space}")
        _resolve_hub_ids()
        return
    print(f"  [warn] copy into {space}: {r.status_code} {r.text[:300]}")
    _import_hub_dashboards(objects)
    _resolve_hub_ids()


def _import_hub_dashboards(objects: list[dict]) -> None:
    """Serverless spaces cannot share/copy; export from default and import."""
    r = requests.post(
        f"{KIBANA_ROOT}/api/saved_objects/_export",
        headers=KBN_HEADERS, timeout=120,
        json={
            "objects": objects,
            "includeReferencesDeep": True,
            "excludeExportDetails": False,
        },
    )
    if r.status_code >= 300:
        print(f"  [warn] export OOTB dashboards: {r.status_code} {r.text[:300]}")
        _put_hub_dashboards()
        return
    headers = {
        "Authorization": KBN_HEADERS["Authorization"],
        "kbn-xsrf": "true",
    }
    r = requests.post(
        f"{KIBANA_URL}/api/saved_objects/_import?overwrite=true",
        headers=headers, timeout=120,
        files={"file": ("hub-ootb.ndjson", r.content, "application/ndjson")},
    )
    if r.status_code >= 300:
        print(f"  [warn] import OOTB into {KIBANA_SPACE}: {r.status_code} {r.text[:300]}")
        _put_hub_dashboards()
        return
    summary = r.json() if r.text else {}
    errors = summary.get("errors") or []
    print(
        f"  [ok] imported OOTB into {KIBANA_SPACE} "
        f"success={summary.get('success')} count={summary.get('successCount')} "
        f"errors={len(errors)}"
    )
    for err in errors[:8]:
        print(f"  [warn] {err.get('type')}/{err.get('id')}: {err.get('error')}")
    if errors:
        _put_hub_dashboards()


def _put_hub_dashboards() -> None:
    """Last-resort copy via Dashboards API GET default / PUT space."""
    for did in OOTB_HUB_DASHBOARDS:
        r = requests.get(
            f"{KIBANA_ROOT}/api/dashboards/{did}",
            headers=KBN_HEADERS, timeout=30)
        if r.status_code != 200:
            print(f"  [warn] default GET {did}: {r.status_code}")
            continue
        body = r.json().get("data") or r.json()
        r = requests.put(
            f"{KIBANA_URL}/api/dashboards/{did}",
            headers=KBN_HEADERS, json=body, timeout=60)
        if r.status_code >= 300:
            print(f"  [warn] space PUT {did}: {r.status_code} {r.text[:200]}")
        else:
            print(f"  [ok] PUT {did} into space {KIBANA_SPACE}")


def _retarget_hub_links() -> None:
    mapping = _resolve_hub_ids()
    if not mapping:
        print("  [warn] no hub targets resolved; skip retarget")
        return
    for did in DASHBOARD_IDS:
        r = requests.get(
            f"{KIBANA_URL}/api/dashboards/{did}",
            headers=KBN_HEADERS, timeout=30)
        if r.status_code != 200:
            print(f"  [warn] dashboard GET {did}: {r.status_code}")
            continue
        body = r.json().get("data") or r.json()
        rewritten = _retarget_hub_obj(body, mapping)
        r = requests.put(
            f"{KIBANA_URL}/api/dashboards/{did}",
            headers=KBN_HEADERS, json=rewritten, timeout=60)
        if r.status_code >= 300:
            print(f"  [warn] retarget hub {did}: {r.status_code} {r.text[:200]}")
        else:
            print(f"  [ok] retargeted hub links on {did}")


def _retarget_hub_obj(obj, mapping=None):
    mapping = mapping or HUB_DASHBOARD_IDS
    if isinstance(obj, dict):
        out = {}
        is_dash_ref = obj.get("type") == "dashboard"
        for k, v in obj.items():
            if (k in ("destination", "destinationId")
                    and isinstance(v, str) and v in mapping):
                out[k] = mapping[v]
            elif (k == "id" and is_dash_ref
                    and isinstance(v, str) and v in mapping):
                out[k] = mapping[v]
            else:
                out[k] = _retarget_hub_obj(v, mapping)
        return out
    if isinstance(obj, list):
        return [_retarget_hub_obj(v, mapping) for v in obj]
    if isinstance(obj, str):
        out = obj
        for old, new in mapping.items():
            out = out.replace(f"#/view/{old}", f"#/view/{new}")
        out = _KIBANA_HOST_RE.sub(KIBANA_ROOT, out)
        return out
    return obj


def _pin_hub_ootb_time_ranges() -> None:
    from src.time_window import demo_window
    win = demo_window(to_pad_days=1)
    mapping = _resolve_hub_ids()
    ids = tuple(dict.fromkeys(mapping[fid] for fid in OOTB_HUB_DASHBOARDS if fid in mapping))
    for did in ids:
        r = requests.get(
            f"{KIBANA_URL}/api/dashboards/{did}",
            headers=KBN_HEADERS, timeout=30)
        if r.status_code != 200:
            print(f"  [warn] hub target GET {did}: {r.status_code}")
            continue
        body = r.json().get("data") or r.json()
        body["time_range"] = win
        r = requests.put(
            f"{KIBANA_URL}/api/dashboards/{did}",
            headers=KBN_HEADERS, json=body, timeout=60)
        if r.status_code >= 300:
            print(f"  [warn] pin hub target {did}: {r.status_code} {r.text[:200]}")
        else:
            print(f"  [ok] pinned {did} {win['from'][:10]} → {win['to'][:10]}")


def verify_dashboards() -> bool:
    print("== live FinOps dashboards ==")
    ok = True
    mapping = _resolve_hub_ids()
    hub_ids = tuple(dict.fromkeys(
        mapping[fid] for fid in OOTB_HUB_DASHBOARDS if fid in mapping))
    for did in DASHBOARD_IDS + hub_ids:
        r = requests.get(
            f"{KIBANA_URL}/api/dashboards/{did}",
            headers=KBN_HEADERS,
            timeout=30,
        )
        if r.status_code == 200:
            body = r.json()
            title = (
                (body.get("data") or {}).get("title")
                or (body.get("attributes") or {}).get("title")
                or body.get("title")
                or did
            )
            print(f"  [ok] {did} ({title})")
        else:
            print(f"  [fail] dashboard {did}: {r.status_code}")
            ok = False
    missing_titles = [
        title for fid, title in OOTB_HUB_TITLES.items() if fid not in mapping]
    for title in missing_titles:
        print(f"  [fail] hub dashboard missing: {title}")
        ok = False
    return ok
