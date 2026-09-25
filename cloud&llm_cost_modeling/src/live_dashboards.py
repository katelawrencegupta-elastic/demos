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
    # Prior finops-space Fleet installs (ids rotate on each space install)
    "94e01542-b7d9-51c6-85ca-e5d1d87f8dde": "ess_billing-billingdashboard",
    "a993ca71-5d10-5438-b5e3-6af50291ba28": "ess_billing-creditsdashboard",
    "170c8161-d5f6-4f3b-b459-4bbfdef379e0": "ess_billing-billingdashboard",
    "8eb7824a-1c91-4dcc-ada9-3ee361aef8e7": "ess_billing-creditsdashboard",
}
HUB_DASHBOARD_IDS = dict(HUB_BACKUP_IDS)
OOTB_HUB_DASHBOARDS = tuple(OOTB_HUB_TITLES.keys())

# Hub tab labels → Fleet/OOTB id (used when destination UUID is stale/unknown).
# FinOps Meridian tabs use "ESS Billing" / "ESS Credits"; the OOTB ESS package
# dashboards themselves label the same tabs "Billing" / "Credits".
HUB_LINK_LABELS = {
    "Inference tokens": "kibana-inference-token-usage",
    "ESS Billing": "ess_billing-billingdashboard",
    "ESS Credits": "ess_billing-creditsdashboard",
    "Billing": "ess_billing-billingdashboard",
    "Credits": "ess_billing-creditsdashboard",
}
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
    _fix_billing_dashboard_filters()
    _fix_svs_ess_panels()
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


# Text fields that dynamic-mapping left non-aggregatable on metrics-aws.billing-*.
# Dashboard KQL / options-list controls must hit the .keyword multi-field.
# Do NOT include data_stream.* — Fleet data streams map those as plain keyword
# (no .keyword multi-field). Rewriting them blanks ESS Cloud panels.
_BILLING_TEXT_FIELDS = (
    "aws.billing.group_definition.key",
    "aws.billing.group_definition.type",
    "cloud.account.id",
    "cloud.account.name",
)

# Accidental .keyword suffixes that must be stripped from KQL on ESS / DS fields.
_BARE_KEYWORD_FIELDS = (
    "data_stream.dataset",
    "data_stream.namespace",
    "data_stream.type",
)


def _rewrite_billing_kql(expr: str) -> str:
    """Point KQL exact-match filters at .keyword multi-fields."""
    if not isinstance(expr, str) or not expr.strip():
        return expr
    out = expr
    for field in sorted(_BILLING_TEXT_FIELDS, key=len, reverse=True):
        kw = f"{field}.keyword"
        # Replace bare field refs that are not already `.keyword`.
        parts = out.split(kw)
        parts = [p.replace(field, kw) for p in parts]
        out = kw.join(parts)
    return out


def _is_esql(text: str) -> bool:
    """True for ES|QL (must keep bare field names — .keyword multi-fields vary by index)."""
    if not isinstance(text, str):
        return False
    head = text.lstrip()[:80].upper()
    return head.startswith("FROM ") or "\n| " in text or text.lstrip().startswith("|")


def _revert_esql_keyword_fields(q: str) -> str:
    """Undo accidental .keyword suffixes inside ES|QL (breaks rightsizing / mixed maps)."""
    if not isinstance(q, str):
        return q
    out = q
    for field in sorted(_BILLING_TEXT_FIELDS + _BARE_KEYWORD_FIELDS, key=len, reverse=True):
        out = out.replace(f"{field}.keyword", field)
    return out


def _revert_bare_keyword_kql(expr: str) -> str:
    """Strip .keyword from fields that are already keyword (ESS / data_stream.*)."""
    if not isinstance(expr, str) or not expr.strip():
        return expr
    out = expr
    for field in sorted(_BARE_KEYWORD_FIELDS, key=len, reverse=True):
        out = out.replace(f"{field}.keyword", field)
    return out


def _fix_billing_panel_filters(obj):
    """Rewrite Lens/KQL filters to .keyword; leave ES|QL on bare field names."""
    if isinstance(obj, dict):
        # ES|QL data_source: restore bare fields, do not keyword-ize
        if obj.get("type") == "esql" and isinstance(obj.get("query"), str):
            return {
                **{k: _fix_billing_panel_filters(v) for k, v in obj.items()
                   if k != "query"},
                "query": _revert_esql_keyword_fields(obj["query"]),
            }
        out = {}
        for k, v in obj.items():
            if k in ("expression", "query") and isinstance(v, str):
                if _is_esql(v):
                    out[k] = _revert_esql_keyword_fields(v)
                elif (
                    "group_definition.key" in v
                    or "data_stream.dataset" in v
                    or "cloud.account.id" in v
                ):
                    # Keyword-ize AWS text fields, then undo data_stream.* damage.
                    rewritten = _rewrite_billing_kql(v)
                    out[k] = _revert_bare_keyword_kql(rewritten)
                else:
                    out[k] = v
            elif k == "field_name" and v in _BILLING_TEXT_FIELDS:
                out[k] = f"{v}.keyword"
            elif k == "field" and v in _BILLING_TEXT_FIELDS:
                out[k] = f"{v}.keyword"
            elif k == "fields" and isinstance(v, list):
                out[k] = [
                    f"{f}.keyword" if f in _BILLING_TEXT_FIELDS else f
                    for f in v
                ]
            else:
                out[k] = _fix_billing_panel_filters(v)
        return out
    if isinstance(obj, list):
        return [_fix_billing_panel_filters(v) for v in obj]
    if isinstance(obj, str) and _is_esql(obj):
        return _revert_esql_keyword_fields(obj)
    if isinstance(obj, str) and (
            "group_definition.key :" in obj or 'group_definition.key:"' in obj
            or "data_stream.dataset :" in obj
            or "data_stream.dataset.keyword" in obj):
        return _revert_bare_keyword_kql(_rewrite_billing_kql(obj))
    return obj


def _fix_billing_dashboard_filters() -> None:
    """Patch live Cost Explorer dashboards after import (Serverless text maps)."""
    for did in (
        "finops-aws-billing-overview-unblended",
        "finops-spend-vs-savings",
        "meridian-finops-llm-observability-dynamic-aws",
    ):
        r = requests.get(
            f"{KIBANA_URL}/api/dashboards/{did}",
            headers=KBN_HEADERS,
            timeout=30,
        )
        if r.status_code != 200:
            print(f"  [warn] billing filter fix GET {did}: {r.status_code}")
            continue
        body = r.json().get("data") or r.json()
        fixed = _fix_billing_panel_filters(body)
        if fixed == body:
            print(f"  [ok] billing filters already keyword-safe on {did}")
            continue
        r = requests.put(
            f"{KIBANA_URL}/api/dashboards/{did}",
            headers=KBN_HEADERS,
            json=fixed,
            timeout=60,
        )
        if r.status_code >= 300:
            print(f"  [warn] billing filter fix {did}: {r.status_code} {r.text[:200]}")
        else:
            print(f"  [ok] rewrote text-field KQL filters on {did}")


def _fix_svs_ess_panels() -> None:
    """Repair spend-vs-savings Elastic Cloud panels after the .keyword KQL bug.

    Also ignore the AWS Account ID control (ESS uses Elastic org id) and prefer
    deployment_name in the table (package 1.9 shape).
    """
    did = "finops-spend-vs-savings"
    r = requests.get(f"{KIBANA_URL}/api/dashboards/{did}", headers=KBN_HEADERS, timeout=30)
    if r.status_code != 200:
        print(f"  [warn] svs ESS fix GET: {r.status_code}")
        return
    body = r.json().get("data") or r.json()
    panels = list(body.get("panels") or [])
    changed = False
    for i, p in enumerate(panels):
        if not isinstance(p, dict) or p.get("id") not in ("svs-ess", "svs-ess-kpi"):
            continue
        cfg = dict(p.get("config") or {})
        cfg["ignore_global_filters"] = True
        # Ensure dataset filter does not use the non-existent .keyword multi-field.
        if p.get("id") == "svs-ess-kpi":
            metrics = list(cfg.get("metrics") or [])
            for j, m in enumerate(metrics):
                m = dict(m)
                filt = dict(m.get("filter") or {})
                expr = filt.get("expression") or ""
                if "data_stream.dataset" in expr:
                    filt["expression"] = _revert_bare_keyword_kql(expr)
                    filt["language"] = filt.get("language") or "kql"
                    m["filter"] = filt
                    metrics[j] = m
                    changed = True
            cfg["metrics"] = metrics
        if p.get("id") == "svs-ess":
            q = dict(cfg.get("query") or {})
            if "data_stream.dataset" in (q.get("expression") or ""):
                q["expression"] = _revert_bare_keyword_kql(q.get("expression") or "")
                cfg["query"] = q
            # Prefer deployment_name (OOTB package grain) then line item name.
            cfg["title"] = "Elastic Cloud by deployment (ECU)"
            cfg["rows"] = [
                {
                    "operation": "terms",
                    "label": "Deployment",
                    "fields": ["ess.billing.deployment_name"],
                    "limit": 12,
                    "rank_by": {"type": "metric", "metric_index": 0, "direction": "desc"},
                    "visible": True,
                    "alignment": "left",
                    "color": {"type": "auto"},
                    "click_filter": False,
                },
                {
                    "operation": "terms",
                    "label": "Type",
                    "fields": ["ess.billing.deployment_type"],
                    "limit": 8,
                    "rank_by": {"type": "metric", "metric_index": 0, "direction": "desc"},
                    "visible": True,
                    "alignment": "left",
                    "color": {"type": "auto"},
                    "click_filter": False,
                },
                {
                    "operation": "terms",
                    "label": "Line item",
                    "fields": ["ess.billing.name"],
                    "limit": 8,
                    "rank_by": {"type": "metric", "metric_index": 0, "direction": "desc"},
                    "visible": True,
                    "alignment": "left",
                    "color": {"type": "auto"},
                    "click_filter": False,
                },
            ]
            changed = True
        panels[i] = {**p, "config": cfg}
        changed = True
    if not changed:
        print("  [warn] svs ESS panels not found on dashboard")
        return
    body["panels"] = panels
    r = requests.put(
        f"{KIBANA_URL}/api/dashboards/{did}",
        headers=KBN_HEADERS,
        json=body,
        timeout=60,
    )
    if r.status_code >= 300:
        print(f"  [warn] svs ESS fix PUT: {r.status_code} {r.text[:300]}")
    else:
        print("  [ok] spend-vs-savings Elastic Cloud panels repaired (bare dataset KQL + ignore account)")


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
| EVAL week = SUBSTRING(TO_STRING(t), 0, 10)
| INLINE STATS avg_cpu = AVG(cpu) BY instance
| INLINE STATS cutoff_lo = PERCENTILE(avg_cpu, 10), cutoff_hi = PERCENTILE(avg_cpu, 90)
| WHERE avg_cpu <= cutoff_lo OR avg_cpu >= cutoff_hi
| SORT avg_cpu ASC, instance ASC, week ASC
| KEEP week, instance, cpu
"""


def _tune_rightsizing_heatmap(obj):
    """Keep ~18 short-named instance rows (idle vs busy tails) on a weekly grain.

    The vendored heatmap plotted every instance id across 24 buckets, hit the
    ES|QL 1000-row cap, and packed ~90 long labels into a short panel.

    Use string week labels + ordinal X — temporal DATE_TRUNC weeks render as
    near-zero-width bands on Serverless heatmaps (same blank-panel bug as
    spend-vs-savings monthly).
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
        cfg["x"] = {"column": "week", "label": "Week"}
        cfg["y"] = {"column": "instance", "label": "Instance"}
        cfg["metric"] = {
            "column": "cpu",
            "label": "CPU %",
            "color": {"type": "auto"},
        }
        cfg["styling"] = {"cells": {"labels": {"visible": False}}}
        cfg["legend"] = {
            "visibility": "visible",
            "position": "right",
            "truncate_after_lines": 1,
        }
        cfg["axis"] = {
            "x": {
                "title": {"text": "", "visible": False},
                "labels": {"visible": True, "orientation": "angled"},
                "scale": "ordinal",
            },
            "y": {
                "title": {"text": "", "visible": False},
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


_SVS_HEAT_QUERY = """\
FROM metrics-aws.billing-*
| WHERE @timestamp >= ?_tstart AND @timestamp <= ?_tend
  AND aws.billing.group_definition.key == "LINKED_ACCOUNT"
| EVAL account = CASE(
    COALESCE(aws.billing.group_by.LINKED_ACCOUNT, cloud.account.id) == "985408759551", "apm-stage",
    COALESCE(aws.billing.group_by.LINKED_ACCOUNT, cloud.account.id) == "041298796264", "monitoring",
    COALESCE(aws.billing.group_by.LINKED_ACCOUNT, cloud.account.id) == "439106060789", "ESF-4391",
    COALESCE(aws.billing.group_by.LINKED_ACCOUNT, cloud.account.id) == "119672459156", "ESF-1196",
    COALESCE(aws.billing.group_by.LINKED_ACCOUNT, cloud.account.id)
  ),
  month = CONCAT(
    TO_STRING(DATE_EXTRACT("year", @timestamp)), "-",
    CASE(DATE_EXTRACT("month_of_year", @timestamp) < 10, "0", ""),
    TO_STRING(DATE_EXTRACT("month_of_year", @timestamp))
  )
| STATS spend = ROUND(SUM(aws.billing.UnblendedCost.amount), 2)
    BY month, account
| WHERE spend IS NOT NULL
| SORT account ASC, month ASC
"""

# Spend heatmap: monthly string labels + ordinal X (temporal DATE_TRUNC
# months render as near-zero-width bands → blank panel). Tall slot avoids
# overflow into the next row on Serverless.
_SVS_HEAT_H = 28
_SVS_ACT_HEAT_H = 18


def _tune_spend_vs_savings_heatmap(obj):
    """Keep heatmaps from overflowing onto panels below."""
    if not isinstance(obj, dict):
        if isinstance(obj, list):
            return [_tune_spend_vs_savings_heatmap(v) for v in obj]
        return obj
    panels = obj.get("panels")
    if isinstance(panels, list) and any(
            p.get("id") == "svs-heat" for p in panels if isinstance(p, dict)):
        return {**obj, "panels": _shift_svs_heatmap_panels(panels)}
    if obj.get("id") == "svs-heat" and obj.get("type") == "vis":
        cfg = dict(obj.get("config") or {})
        cfg["title"] = "Spend heatmap: account × month (LINKED_ACCOUNT unblended)"
        cfg["ignore_global_filters"] = False
        cfg["data_source"] = {"type": "esql", "query": _SVS_HEAT_QUERY}
        cfg["x"] = {"column": "month", "label": "Month"}
        cfg["y"] = {"column": "account", "label": "Account"}
        cfg["metric"] = {
            "column": "spend",
            "label": "Unblended USD",
            "color": {"type": "auto"},
        }
        cfg["legend"] = {
            "visibility": "visible",
            "position": "right",
            "truncate_after_lines": 1,
        }
        cfg["styling"] = {"cells": {"labels": {"visible": False}}}
        cfg["axis"] = {
            "x": {
                "title": {"text": "", "visible": False},
                "labels": {"visible": True, "orientation": "horizontal"},
                "scale": "ordinal",
            },
            "y": {
                "title": {"text": "", "visible": False},
                "labels": {"visible": True},
            },
        }
        grid = dict(obj.get("grid") or {})
        grid["h"] = max(int(grid.get("h") or 0), _SVS_HEAT_H)
        return {**obj, "config": cfg, "grid": grid}
    if obj.get("id") == "svs-act-heat" and obj.get("type") == "vis":
        # Cell value labels collide on small cells; hide them + legend.
        cfg = dict(obj.get("config") or {})
        styling = dict(cfg.get("styling") or {})
        cells = dict(styling.get("cells") or {})
        labels = dict(cells.get("labels") or {})
        labels["visible"] = False
        cells["labels"] = labels
        styling["cells"] = cells
        cfg["styling"] = styling
        cfg["legend"] = {
            "visibility": "hidden",
            "position": "right",
            "truncate_after_lines": 1,
        }
        cfg["axis"] = {
            "x": {
                "title": {"text": "", "visible": False},
                "labels": {"visible": True, "orientation": "angled"},
                "scale": "ordinal",
            },
            "y": {
                "title": {"text": "", "visible": False},
                "labels": {"visible": True},
            },
        }
        grid = dict(obj.get("grid") or {})
        grid["h"] = max(int(grid.get("h") or 0), _SVS_ACT_HEAT_H)
        return {**obj, "config": cfg, "grid": grid}
    return {k: _tune_spend_vs_savings_heatmap(v) for k, v in obj.items()}


def _shift_svs_heatmap_panels(panels: list) -> list:
    """Retune heatmaps and assign non-overlapping grid rows (idempotent)."""
    by_id = {}
    order = []
    for p in panels:
        pid = p.get("id")
        order.append(pid)
        if pid in ("svs-heat", "svs-act-heat"):
            by_id[pid] = _tune_spend_vs_savings_heatmap(p)
        else:
            by_id[pid] = p

    heat = by_id.get("svs-heat")
    if not heat:
        return panels
    heat_g = dict(heat.get("grid") or {})
    heat_g.update({"x": 0, "y": 36, "w": 48, "h": _SVS_HEAT_H})
    heat = {**heat, "grid": heat_g}
    by_id["svs-heat"] = heat
    y = 36 + _SVS_HEAT_H  # 64

    # Row: spend / identified by account
    for pid, x in (("svs-spend-acct", 0), ("svs-id-acct", 24)):
        if pid in by_id:
            g = dict(by_id[pid].get("grid") or {})
            g.update({"x": x, "y": y, "w": 24, "h": 14})
            by_id[pid] = {**by_id[pid], "grid": g}
    y += 14  # 78

    # Row: services / actions
    for pid, x in (("svs-svc", 0), ("svs-act", 24)):
        if pid in by_id:
            g = dict(by_id[pid].get("grid") or {})
            g.update({"x": x, "y": y, "w": 24, "h": 14})
            by_id[pid] = {**by_id[pid], "grid": g}
    y += 14  # 92

    # Bubble alone full width (side-by-side with act-heat looked stacked)
    if "svs-scatter" in by_id:
        g = dict(by_id["svs-scatter"].get("grid") or {})
        g.update({"x": 0, "y": y, "w": 48, "h": 16})
        by_id["svs-scatter"] = {**by_id["svs-scatter"], "grid": g}
    y += 16  # 108

    # Action heatmap alone full width
    if "svs-act-heat" in by_id:
        g = dict(by_id["svs-act-heat"].get("grid") or {})
        g.update({"x": 0, "y": y, "w": 48, "h": _SVS_ACT_HEAT_H})
        by_id["svs-act-heat"] = {**by_id["svs-act-heat"], "grid": g}
    y += _SVS_ACT_HEAT_H  # 126

    # Row: ESS
    if "svs-ess-kpi" in by_id:
        g = dict(by_id["svs-ess-kpi"].get("grid") or {})
        g.update({"x": 0, "y": y, "w": 12, "h": 6})
        by_id["svs-ess-kpi"] = {**by_id["svs-ess-kpi"], "grid": g}
    if "svs-ess" in by_id:
        g = dict(by_id["svs-ess"].get("grid") or {})
        g.update({"x": 12, "y": y, "w": 36, "h": 12})
        by_id["svs-ess"] = {**by_id["svs-ess"], "grid": g}

    return [by_id[pid] for pid in order if pid in by_id]


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
        rewritten = _tune_spend_vs_savings_heatmap(
            _tune_rightsizing_heatmap(_rewrite_obj(body)))
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
    # Meridian FinOps dashboards + the space-local ESS Billing/Credits copies.
    # OOTB package assets ship Fleet ids (ess_billing-*) which 404 in non-default
    # spaces; rewrite those self-tabs to the UUIDs that exist here.
    hub_local = tuple(dict.fromkeys(
        mapping[fid] for fid in OOTB_HUB_DASHBOARDS if fid in mapping))
    for did in DASHBOARD_IDS + hub_local:
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
        # Links panel entries: prefer label→current space id so rotating Fleet
        # UUIDs (each space install) never leave dead hub tabs.
        if obj.get("type") == "dashboardLink":
            out = {k: _retarget_hub_obj(v, mapping) for k, v in obj.items()}
            label = out.get("label")
            fleet_id = HUB_LINK_LABELS.get(label) if isinstance(label, str) else None
            if fleet_id and fleet_id in mapping:
                out["destination"] = mapping[fleet_id]
            elif isinstance(out.get("destination"), str) and out["destination"] in mapping:
                out["destination"] = mapping[out["destination"]]
            return out
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
