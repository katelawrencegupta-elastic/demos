"""Provision Meridian FinOps spend SLOs and ES|QL budget alert rules.

Calibration probes (run against live cluster before tightening YAML)::

    FROM metrics-aws_billing.cur-default
    | WHERE @timestamp >= NOW() - 30 days
    | STATS daily = SUM(aws_billing.cur.line_item.unblended_cost) BY day = BUCKET(@timestamp, 1d)
    | STATS avg_30d = AVG(daily), total_30d = SUM(daily)

    FROM metrics-aws_billing.cur-default
    | WHERE @timestamp >= NOW() - 14 days
      AND aws_billing.cur.line_item.usage_account_name == "meridian-staging"
    | STATS daily = SUM(aws_billing.cur.line_item.unblended_cost) BY day = BUCKET(@timestamp, 1d)
    | STATS avg = AVG(daily)

    FROM traces-apm-default
    | WHERE @timestamp >= NOW() - 7 days
      AND span.subtype == "gen_ai" AND service.name == "checkout-assistant"
    | STATS cost_7d = SUM(TO_DOUBLE(labels.llm_cost_usd))

    FROM metrics-gcp.billing-default
    | WHERE @timestamp >= NOW() - 7 days
      AND gcp.billing.project_name == "meridian-ml-prod"
    | STATS cost_7d = SUM(gcp.billing.total)
"""
from __future__ import annotations

import uuid
from functools import lru_cache

import requests
import yaml

from src.config import KBN_HEADERS, KIBANA_URL, ROOT

BUDGETS_CONFIG = ROOT / "config" / "budgets.yaml"
TAGS = ["meridian", "finops", "workshop"]
WORKFLOWS_CONNECTOR = "system-connector-.workflows"

SLO_API = f"{KIBANA_URL}/api/observability/slos"
RULE_API = f"{KIBANA_URL}/api/alerting/rule"


def load_budgets() -> dict:
    from src.profile import LIVE_DIR, is_live
    path = LIVE_DIR / "budgets.yaml" if is_live() else BUDGETS_CONFIG
    with open(path) as f:
        return yaml.safe_load(f)


def budget_numbers(cfg: dict | None = None) -> dict:
    """Flat dict of named USD thresholds for dashboards / callers."""
    cfg = cfg or load_budgets()
    return dict(cfg["budgets"])


def substitutions(cfg: dict | None = None) -> dict:
    """Numbers + live account ids + kibana_url for YAML `.format()`."""
    from src.profile import is_live, live_accounts
    cfg = cfg or load_budgets()
    mapping = dict(cfg["budgets"])
    if is_live():
        mapping.update(live_accounts())
    mapping["kibana_url"] = KIBANA_URL
    return mapping


def _rule_tags(cfg: dict | None = None) -> list:
    cfg = cfg or load_budgets()
    return list(cfg.get("tags") or TAGS)


def _kbn(method: str, url: str, **kwargs):
    kwargs.setdefault("headers", KBN_HEADERS)
    kwargs.setdefault("timeout", 60)
    return requests.request(method, url, **kwargs)


def _timeslice_slo_body(spec: dict, ceiling: float) -> dict:
    params = {
        "index": spec["index"],
        "timestampField": "@timestamp",
        "metric": {
            "metrics": [
                {
                    "name": "A",
                    "aggregation": "sum",
                    "field": spec["field"],
                }
            ],
            "equation": "A",
            "comparator": "LTE",
            "threshold": ceiling,
        },
    }
    filt = (spec.get("filter") or "").strip()
    if filt:
        params["filter"] = filt.format(**substitutions())
    return {
        "name": spec["name"],
        "description": (spec.get("description") or "").strip(),
        "indicator": {
            "type": "sli.metric.timeslice",
            "params": params,
        },
        "budgetingMethod": "timeslices",
        "timeWindow": {"duration": "30d", "type": "rolling"},
        "objective": {
            "target": 0.95,
            "timesliceTarget": 0.95,
            "timesliceWindow": "24h",
        },
        "tags": _rule_tags(),
    }


def _upsert_slo(slo_id: str, body: dict, fail_loud: bool) -> bool:
    r = _kbn("GET", f"{SLO_API}/{slo_id}")
    if r.status_code == 200:
        r = _kbn("PUT", f"{SLO_API}/{slo_id}", json=body)
        action = "updated"
    elif r.status_code == 404:
        payload = {**body, "id": slo_id}
        r = _kbn("POST", SLO_API, json=payload)
        action = "created"
    else:
        msg = f"  [fail] SLO GET {slo_id}: {r.status_code} {r.text[:240]}"
        if fail_loud:
            raise SystemExit(msg)
        print(msg.replace("[fail]", "[warn]"))
        return False

    if r.status_code >= 300:
        msg = f"  [fail] SLO {action} {slo_id}: {r.status_code} {r.text[:400]}"
        # Missing Observability SLO privilege / feature — soft-fail by default.
        if r.status_code in (403, 404) and not fail_loud:
            print(msg.replace("[fail]", "[warn]"))
            return False
        if fail_loud:
            raise SystemExit(msg)
        print(msg.replace("[fail]", "[warn]"))
        return False
    print(f"  [ok] SLO {action}: {slo_id}")
    return True


def _esql_for_alert(spec: dict, mapping: dict) -> str:
    if spec.get("esql"):
        return spec["esql"].format(**mapping).strip()
    kind = spec["kind"]
    nums = mapping
    if kind == "aws_mtd":
        return (
            "FROM metrics-aws_billing.cur-default\n"
            "| STATS spend = SUM(aws_billing.cur.line_item.unblended_cost)\n"
            f"| WHERE spend > {nums['aws_monthly_usd']}"
        )
    if kind == "staging_daily":
        return (
            "FROM metrics-aws_billing.cur-default\n"
            '| WHERE aws_billing.cur.line_item.usage_account_name == "meridian-staging"\n'
            "| STATS spend = SUM(aws_billing.cur.line_item.unblended_cost)\n"
            f"| WHERE spend > {nums['staging_daily_alert_usd']}"
        )
    if kind == "checkout_7d":
        return (
            "FROM traces-apm-default\n"
            '| WHERE span.subtype == "gen_ai" AND service.name == "checkout-assistant"\n'
            "| STATS spend = SUM(TO_DOUBLE(labels.llm_cost_usd))\n"
            f"| WHERE spend > {nums['checkout_7d_alert_usd']}"
        )
    if kind == "gcp_ml_7d":
        return (
            "FROM metrics-gcp.billing-default\n"
            '| WHERE gcp.billing.project_name == "meridian-ml-prod"\n'
            "| STATS spend = SUM(gcp.billing.total)\n"
            f"| WHERE spend > {nums['gcp_ml_7d_alert_usd']}"
        )
    raise ValueError(f"unknown alert kind: {kind}")


@lru_cache(maxsize=1)
def _server_log_connector_id() -> str | None:
    try:
        r = _kbn("GET", f"{KIBANA_URL}/api/actions/connectors")
    except requests.RequestException:
        return None
    if r.status_code != 200:
        return None
    body = r.json()
    items = body if isinstance(body, list) else body.get("data") or body.get("connectors") or []
    named = None
    generic = None
    for c in items:
        if c.get("connector_type_id") != ".server-log" and c.get("actionTypeId") != ".server-log":
            continue
        cid = c.get("id")
        if not cid:
            continue
        if (c.get("name") or "") == "FinOps demo server log":
            named = cid
        elif generic is None:
            generic = cid
    return named or generic


def _with_action_uuids(actions: list, existing: list | None) -> list:
    """Kibana rejects multi-action PUTs that cannot correlate rows; keep ids stable."""
    by_id: dict[str, str] = {}
    for a in existing or []:
        cid, uid = a.get("id"), a.get("uuid")
        if cid and uid and cid not in by_id:
            by_id[cid] = uid
    out = []
    for a in actions:
        item = dict(a)
        item["uuid"] = item.get("uuid") or by_id.get(item.get("id")) or str(uuid.uuid4())
        out.append(item)
    return out


def _alert_actions(spec: dict, mapping: dict) -> list:
    actions = []
    log_id = _server_log_connector_id()
    if log_id:
        raw = spec.get("message") or spec["name"]
        try:
            msg = raw.format(**mapping)
        except (KeyError, ValueError):
            msg = raw
        actions.append({
            "group": "query matched",
            "id": log_id,
            "params": {"message": msg, "level": "info"},
            "frequency": {
                "summary": False,
                "notify_when": "onActionGroupChange",
                "throttle": None,
            },
        })
    if spec.get("workflow_id"):
        # PUT rejects connector_type_id (GET returns it). System connector has no group.
        actions.append({
            "id": WORKFLOWS_CONNECTOR,
            "params": {
                "subAction": "run",
                "subActionParams": {
                    "workflowId": spec["workflow_id"],
                    "summaryMode": False,
                    "alertStates": {
                        "new": True,
                        "ongoing": False,
                        "recovered": True,
                    },
                },
            },
        })
    return actions


def _esql_rule_body(spec: dict, mapping: dict) -> dict:
    return {
        "name": spec["name"],
        "tags": _rule_tags(),
        "rule_type_id": ".es-query",
        "consumer": "stackAlerts",
        "enabled": True,
        "schedule": {"interval": spec.get("schedule", "1h")},
        "actions": _alert_actions(spec, mapping),
        "params": {
            "searchType": "esqlQuery",
            "timeWindowSize": spec["time_window_size"],
            "timeWindowUnit": spec["time_window_unit"],
            "threshold": [0],
            "thresholdComparator": ">",
            "size": 10,
            "esqlQuery": {"esql": _esql_for_alert(spec, mapping)},
            "aggType": "count",
            "groupBy": "all",
            "termSize": 5,
            "sourceFields": [],
            "timeField": "@timestamp",
            "excludeHitsFromPreviousRun": True,
        },
    }


def _burn_rate_rule_body(slo_id: str, name: str) -> dict:
    from src.profile import is_live
    windows = [
        {
            "id": str(uuid.uuid4()),
            "burnRateThreshold": 1.0,
            "maxBurnRateThreshold": 10,
            "longWindow": {"value": 72, "unit": "h"},
            "shortWindow": {"value": 360, "unit": "m"},
            "actionGroup": "slo.burnRate.low",
        },
        {
            "id": str(uuid.uuid4()),
            "burnRateThreshold": 3.0,
            "maxBurnRateThreshold": 30,
            "longWindow": {"value": 24, "unit": "h"},
            "shortWindow": {"value": 120, "unit": "m"},
            "actionGroup": "slo.burnRate.medium",
        },
    ]
    if is_live():
        windows.append({
            "id": str(uuid.uuid4()),
            "burnRateThreshold": 10.0,
            "maxBurnRateThreshold": 30,
            "longWindow": {"value": 1, "unit": "h"},
            "shortWindow": {"value": 5, "unit": "m"},
            "actionGroup": "slo.burnRate.high",
        })
    return {
        "name": name,
        "tags": _rule_tags(),
        "rule_type_id": "slo.rules.burnRate",
        "consumer": "slo",
        "enabled": True,
        "schedule": {"interval": "1m"},
        "actions": [],
        "params": {
            "sloId": slo_id,
            "windows": windows,
            "dependencies": [],
        },
    }


def _upsert_rule(rule_id: str, body: dict, fail_loud: bool) -> bool:
    r = _kbn("GET", f"{RULE_API}/{rule_id}")
    existing_actions = (r.json().get("actions") or []) if r.status_code == 200 else []
    if "actions" in body:
        body = {**body, "actions": _with_action_uuids(body["actions"], existing_actions)}
    if r.status_code == 200:
        # Update payload omits rule_type_id / consumer; some rule types reject `enabled` on PUT.
        update = {
            k: body[k]
            for k in ("name", "tags", "schedule", "params", "actions")
            if k in body
        }
        r = _kbn("PUT", f"{RULE_API}/{rule_id}", json=update)
        action = "updated"
    elif r.status_code == 404:
        r = _kbn("POST", f"{RULE_API}/{rule_id}", json=body)
        action = "created"
    else:
        msg = f"  [fail] rule GET {rule_id}: {r.status_code} {r.text[:240]}"
        if fail_loud:
            raise SystemExit(msg)
        print(msg.replace("[fail]", "[warn]"))
        return False

    if r.status_code >= 300:
        err = r.text[:400]
        if body.get("actions") and any(
            a.get("id") == WORKFLOWS_CONNECTOR for a in body["actions"]
        ):
            print(f"  [warn] {rule_id} with workflow action: {r.status_code} {err}")
            stripped = {
                **body,
                "actions": [a for a in body["actions"] if a.get("id") != WORKFLOWS_CONNECTOR],
            }
            print(f"  [warn] retrying {rule_id} without workflow action")
            if action == "updated":
                update = {
                    k: stripped[k]
                    for k in ("name", "tags", "schedule", "params", "actions")
                    if k in stripped
                }
                r = _kbn("PUT", f"{RULE_API}/{rule_id}", json=update)
            else:
                r = _kbn("POST", f"{RULE_API}/{rule_id}", json=stripped)
        if r.status_code >= 300:
            msg = f"  [fail] rule {action} {rule_id}: {r.status_code} {r.text[:400]}"
            if fail_loud:
                raise SystemExit(msg)
            print(msg.replace("[fail]", "[warn]"))
            return False
    print(f"  [ok] rule {action}: {rule_id}")
    return True


def ensure_budgets(fail_loud: bool = False) -> None:
    """Upsert spend SLOs + burn-rate rules + ES|QL budget alerts."""
    cfg = load_budgets()
    mapping = substitutions(cfg)
    print("== FinOps spend SLOs ==")
    for spec in cfg.get("slos") or []:
        ceiling = float(mapping[spec["ceiling_key"]])
        ok = _upsert_slo(spec["id"], _timeslice_slo_body(spec, ceiling), fail_loud)
        if ok and spec.get("burn_rate_alert"):
            burn_id = f"{spec['id']}-burn"
            _upsert_rule(
                burn_id,
                _burn_rate_rule_body(spec["id"], f"{spec['name']} — burn rate"),
                fail_loud,
            )

    print("== FinOps budget ES|QL alerts ==")
    for spec in cfg.get("alerts") or []:
        _upsert_rule(spec["id"], _esql_rule_body(spec, mapping), fail_loud)

    # SLOs created before backfill (or with empty transforms) stay NO_DATA / N/A
    # until reset. Auto-recover any that still have no SLI summary.
    stale = []
    r = _kbn("GET", SLO_API, params={"perPage": 100})
    if r.status_code == 200:
        known = {s["id"] for s in cfg.get("slos") or []}
        for s in r.json().get("results") or []:
            sid = s.get("id")
            if sid not in known:
                continue
            status = (s.get("summary") or {}).get("status")
            if status in (None, "NO_DATA"):
                stale.append(sid)
    if stale:
        print(f"== Recover {len(stale)} SLO(s) with NO_DATA ==")
        recover_slos(fail_loud=fail_loud, slo_ids=stale)


def recover_slos(fail_loud: bool = False, slo_ids: list[str] | None = None) -> None:
    """Reset Meridian spend SLOs (recreate transforms + reprocess SLI data).

    Uses POST /api/observability/slos/{id}/_reset. When *slo_ids* is omitted,
    resets all Meridian SLOs from config plus any flagged outdated in definitions.
    """
    cfg = load_budgets()
    ids = set(slo_ids or [])
    if not ids:
        ids = {s["id"] for s in cfg.get("slos") or []}
        r = _kbn("GET", f"{SLO_API}/_definitions", params={"includeOutdatedOnly": 1})
        if r.status_code == 200:
            for spec in r.json().get("results") or []:
                if spec.get("id"):
                    ids.add(spec["id"])

    print("== Recover Meridian SLOs (reset) ==")
    for slo_id in sorted(ids):
        r = _kbn("POST", f"{SLO_API}/{slo_id}/_reset")
        if r.status_code >= 300:
            msg = f"  [fail] SLO reset {slo_id}: {r.status_code} {r.text[:400]}"
            if fail_loud:
                raise SystemExit(msg)
            print(msg.replace("[fail]", "[warn]"))
            continue
        summ = (r.json().get("summary") or {})
        eb = summ.get("errorBudget") or {}
        status = summ.get("status") or "pending"
        print(f"  [ok] reset {slo_id} — status={status} eb_remaining={eb.get('remaining')}")


def verify_budgets() -> bool:
    """Return True if all Meridian budget SLOs/rules exist and rules are enabled."""
    cfg = load_budgets()
    ok = True
    print("== FinOps budgets / SLOs ==")
    for spec in cfg.get("slos") or []:
        r = _kbn("GET", f"{SLO_API}/{spec['id']}")
        if r.status_code == 200:
            print(f"  [ok] SLO {spec['id']}")
        else:
            print(f"  [fail] SLO {spec['id']}: {r.status_code}")
            ok = False
        if spec.get("burn_rate_alert"):
            burn_id = f"{spec['id']}-burn"
            r = _kbn("GET", f"{RULE_API}/{burn_id}")
            if r.status_code == 200 and r.json().get("enabled"):
                print(f"  [ok] burn-rate rule {burn_id}")
            else:
                print(f"  [fail] burn-rate rule {burn_id}: {r.status_code}")
                ok = False

    for spec in cfg.get("alerts") or []:
        r = _kbn("GET", f"{RULE_API}/{spec['id']}")
        if r.status_code != 200 or not r.json().get("enabled"):
            print(f"  [fail] alert {spec['id']}: {r.status_code}")
            ok = False
            continue
        wf = spec.get("workflow_id")
        if wf:
            found = any(
                ((a.get("params") or {}).get("subActionParams") or {}).get("workflowId") == wf
                or a.get("id") == WORKFLOWS_CONNECTOR
                for a in (r.json().get("actions") or [])
            )
            if found:
                print(f"  [ok] alert {spec['id']} (enabled, workflow={wf})")
            else:
                print(f"  [fail] alert {spec['id']} missing workflow action {wf}")
                ok = False
        else:
            print(f"  [ok] alert {spec['id']} (enabled)")

    print(f"  SLOs:     {KIBANA_URL}/app/observability/slos")
    print(f"  Alerts:   {KIBANA_URL}/app/observability/alerts")
    print(f"  Rules:    {KIBANA_URL}/app/management/insightsAndAlerting/triggersActions/rules")
    return ok


def slo_and_alert_ids() -> tuple[list[str], list[str]]:
    cfg = load_budgets()
    slo_ids = [s["id"] for s in cfg.get("slos") or []]
    alert_ids = [a["id"] for a in cfg.get("alerts") or []]
    for s in cfg.get("slos") or []:
        if s.get("burn_rate_alert"):
            alert_ids.append(f"{s['id']}-burn")
    return slo_ids, alert_ids
