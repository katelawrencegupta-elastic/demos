"""Reusable FinOps / FinOps smoke tests with pass/fail report.

Usage:
  # Live ELK Co FinOps suite (default with --profile live)
  .venv/bin/python -m src.cli --profile live smoke
  .venv/bin/python -m src.cli --profile live smoke --fix --deep

  # One workshop variant (from config/variants.yaml)
  .venv/bin/python -m src.cli smoke --variant aws

  # Matrix across all variants (+ live suite when profile=live)
  .venv/bin/python -m src.cli --profile live smoke --all-variants --json-out /tmp/matrix.json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Callable

import requests

from src.config import (
    ELASTIC_URL,
    ES_HEADERS,
    KBN_HEADERS,
    KIBANA_ROOT,
    KIBANA_URL,
)


@dataclass
class CheckResult:
    id: str
    name: str
    ok: bool
    detail: str = ""
    fixed: bool = False
    duration_ms: int = 0


@dataclass
class SmokeReport:
    started_at: str
    finished_at: str = ""
    profile: str = "live"
    suite: str = "live-finops"
    variant: str = ""
    kibana: str = ""
    elastic: str = ""
    passed: int = 0
    failed: int = 0
    fixed: int = 0
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.failed == 0


def _es_query(query: str, timeout: int = 60) -> tuple[int, dict]:
    r = requests.post(
        f"{ELASTIC_URL}/_query",
        headers=ES_HEADERS,
        json={"query": query},
        timeout=timeout,
    )
    try:
        body = r.json()
    except Exception:
        body = {"raw": r.text[:500]}
    return r.status_code, body


def _kbn_get(
    path: str,
    base: str | None = None,
    params: dict | None = None,
) -> requests.Response:
    root = base or KIBANA_URL
    return requests.get(
        f"{root}{path}",
        headers=KBN_HEADERS,
        params=params,
        timeout=60,
    )


def _check(
    results: list[CheckResult],
    check_id: str,
    name: str,
    fn: Callable[[], tuple[bool, str]],
    fix: Callable[[], tuple[bool, str]] | None = None,
    *,
    do_fix: bool = False,
) -> None:
    t0 = time.time()
    try:
        ok, detail = fn()
    except Exception as e:
        ok, detail = False, f"exception: {e}"
    fixed = False
    if not ok and do_fix and fix is not None:
        try:
            fixed_ok, fix_detail = fix()
            if fixed_ok:
                ok2, detail2 = fn()
                if ok2:
                    ok, detail, fixed = True, f"{detail2} (fixed: {fix_detail})", True
                else:
                    detail = f"{detail}; fix attempted ({fix_detail}) but still failing: {detail2}"
            else:
                detail = f"{detail}; fix failed: {fix_detail}"
        except Exception as e:
            detail = f"{detail}; fix exception: {e}"
    results.append(
        CheckResult(
            id=check_id,
            name=name,
            ok=ok,
            detail=detail,
            fixed=fixed,
            duration_ms=int((time.time() - t0) * 1000),
        )
    )


# --- individual checks -----------------------------------------------------


def check_es_connectivity() -> tuple[bool, str]:
    r = requests.get(ELASTIC_URL, headers=ES_HEADERS, timeout=30)
    if r.status_code != 200:
        return False, f"status {r.status_code}"
    info = r.json()
    return True, f"{info.get('version', {}).get('number')} ({info.get('version', {}).get('build_flavor')})"


def check_kibana_connectivity() -> tuple[bool, str]:
    r = _kbn_get("/api/status", base=KIBANA_URL)
    if r.status_code != 200:
        # Some serverless builds 404 /api/status — fall back to dashboards list
        r2 = _kbn_get("/api/dashboards", params={"size": 1})
        if r2.status_code == 200:
            return True, "dashboards API reachable"
        return False, f"status={r.status_code} dashboards={r2.status_code}"
    return True, "ok"


def check_stream_docs(stream: str, min_docs: int = 1) -> tuple[bool, str]:
    status, body = _es_query(
        f"FROM {stream}\n| STATS n = COUNT(*)\n"
    )
    if status != 200:
        return False, f"query {status}: {str(body)[:200]}"
    rows = body.get("values") or [[0]]
    n = int(rows[0][0] or 0)
    if n < min_docs:
        return False, f"{n} docs (want >= {min_docs})"
    return True, f"{n} docs"


def check_ess_billing_fields() -> tuple[bool, str]:
    from src.config import KIBANA_URL
    from src.ess_billing_health import (
        _data_view_has_ess_fields,
        _field_types,
        _list_ess_data_views,
    )

    types = _field_types()
    bad = []
    for field in (
        "ess.billing.deployment_name",
        "ess.billing.deployment_type",
        "ess.billing.deployment_id",
    ):
        got = types.get(field) or []
        if "keyword" not in got:
            bad.append(f"{field}={got or 'MISSING'}")
    if bad:
        return False, ", ".join(bad)
    status, body = _es_query(
        "FROM metrics-ess_billing.billing-*\n"
        "| STATS n = COUNT(*), named = COUNT(ess.billing.deployment_name), "
        "svc = COUNT(`ess.billing.cloud.service.type`)\n"
    )
    if status != 200:
        return False, f"probe {status}"
    n, named, svc = (body.get("values") or [[0, 0, 0]])[0]
    if not n or not named:
        return False, f"docs n={n} named={named}"
    if svc < n:
        return False, f"cloud.service.type {svc}/{n} (stale docs — wipe+rebackfill)"
    # OOTB Lens fails when the data view field cache is stale (0 ess.billing.*).
    stale = []
    for vid, title in _list_ess_data_views(KIBANA_URL) or [("metrics-*", "metrics-*")]:
        ok, count = _data_view_has_ess_fields(KIBANA_URL, vid)
        if not ok:
            stale.append(f"{title}({count})")
    if stale:
        return False, f"stale data views: {', '.join(stale)}"
    return True, f"keyword; {named}/{n} named; {svc}/{n} svc; data views ok"


def fix_ess_billing_fields() -> tuple[bool, str]:
    from src.ess_billing_health import ensure_ess_billing_field_health

    ok = ensure_ess_billing_field_health(fail_loud=False)
    return ok, "ensure_ess_billing_field_health"


def check_dashboard(did: str) -> tuple[bool, str]:
    r = _kbn_get(f"/api/dashboards/{did}")
    if r.status_code != 200:
        return False, f"GET {r.status_code}"
    title = (r.json().get("data") or {}).get("title") or did
    return True, title


def check_hub_links() -> tuple[bool, str]:
    """ESS Billing / Credits / Inference hub tabs must resolve in this space."""
    from src.live_dashboards import (
        DASHBOARD_IDS, HUB_LINK_LABELS, OOTB_HUB_DASHBOARDS, _resolve_hub_ids,
    )

    mapping = _resolve_hub_ids()
    hub_local = tuple(dict.fromkeys(
        mapping[fid] for fid in OOTB_HUB_DASHBOARDS if fid in mapping))
    broken = []
    checked = 0
    for did in DASHBOARD_IDS + hub_local:
        r = _kbn_get(f"/api/dashboards/{did}")
        if r.status_code != 200:
            continue
        for p in (r.json().get("data") or {}).get("panels") or []:
            links = (p.get("config") or {}).get("links") or []
            for link in links:
                label = link.get("label") or ""
                if label not in HUB_LINK_LABELS:
                    continue
                checked += 1
                dest = link.get("destination") or ""
                rr = _kbn_get(f"/api/dashboards/{dest}")
                if rr.status_code != 200:
                    broken.append(f"{did}:{label}->{dest}({rr.status_code})")
    if checked == 0:
        return False, "no hub OOTB links found on FinOps dashboards"
    if broken:
        return False, "; ".join(broken[:6])
    return True, f"{checked} hub links ok"


def fix_hub_links() -> tuple[bool, str]:
    from src.live_dashboards import _retarget_hub_links

    _retarget_hub_links()
    return True, "retargeted hub links"


def check_heatmap_panel(did: str, panel_id: str, expect: dict) -> tuple[bool, str]:
    r = _kbn_get(f"/api/dashboards/{did}")
    if r.status_code != 200:
        return False, f"dashboard {r.status_code}"
    panel = next(
        (p for p in (r.json().get("data") or {}).get("panels") or [] if p.get("id") == panel_id),
        None,
    )
    if not panel:
        return False, f"panel {panel_id} missing"
    cfg = panel.get("config") or {}
    ds = cfg.get("data_source") or {}
    query = ds.get("query") or ""
    axis = ((cfg.get("axis") or {}).get("x") or {})
    scale = axis.get("scale")
    x_col = ((cfg.get("x") or {}).get("column"))
    problems = []
    if expect.get("scale") and scale != expect["scale"]:
        problems.append(f"scale={scale} want {expect['scale']}")
    if expect.get("x_column") and x_col != expect["x_column"]:
        problems.append(f"x={x_col} want {expect['x_column']}")
    if expect.get("query_contains"):
        for needle in expect["query_contains"]:
            if needle not in query:
                problems.append(f"query missing {needle!r}")
    if problems:
        return False, "; ".join(problems)
    return True, f"scale={scale} x={x_col}"


def fix_heatmaps() -> tuple[bool, str]:
    """Re-apply live dashboard ES|QL rewrites (includes heatmap tunes)."""
    from src.live_dashboards import _rewrite_billing_esql

    _rewrite_billing_esql()
    return True, "rewrote billing/rightsizing dashboard ES|QL"


def check_workflows() -> tuple[bool, str]:
    from src.workflows import WORKFLOW_IDS, _find_existing

    missing = []
    disabled = []
    for wid in WORKFLOW_IDS:
        existing = _find_existing(wid)
        if not existing:
            missing.append(wid)
        elif existing.get("enabled") is False:
            disabled.append(wid)
    if missing or disabled:
        parts = []
        if missing:
            parts.append(f"missing={missing}")
        if disabled:
            parts.append(f"disabled={disabled}")
        return False, "; ".join(parts)
    return True, f"{len(WORKFLOW_IDS)} workflows enabled"


def fix_workflows() -> tuple[bool, str]:
    from src.workflows import ensure_workflows

    ok = ensure_workflows(fail_loud=False)
    return ok, "ensure_workflows"


def check_case_custom_fields() -> tuple[bool, str]:
    from src.workflows import _CASE_CUSTOM_FIELDS

    r = _kbn_get("/api/cases/configure", params={"owner": "observability"})
    if r.status_code != 200:
        return False, f"configure GET {r.status_code}"
    configs = r.json() if isinstance(r.json(), list) else []
    cfg = next((c for c in configs if c.get("owner") == "observability"), None)
    have = {f.get("key") for f in (cfg or {}).get("customFields") or []}
    missing = {f["key"] for f in _CASE_CUSTOM_FIELDS} - have
    if missing:
        return False, f"missing {sorted(missing)}"
    return True, f"{len(have)} custom fields"


def fix_case_custom_fields() -> tuple[bool, str]:
    from src.workflows import ensure_case_configuration

    ok = ensure_case_configuration(fail_loud=False)
    return ok, "ensure_case_configuration"


def check_slos_have_data() -> tuple[bool, str]:
    from src.budgets import load_budgets

    cfg = load_budgets()
    bad = []
    statuses = []
    for spec in cfg.get("slos") or []:
        r = _kbn_get(f"/api/observability/slos/{spec['id']}")
        if r.status_code != 200:
            bad.append(f"{spec['id']}:GET:{r.status_code}")
            continue
        status = (r.json().get("summary") or {}).get("status")
        if status in (None, "NO_DATA"):
            bad.append(f"{spec['id']}:{status or 'NO_DATA'}")
        else:
            statuses.append(f"{spec['id']}={status}")
    if bad:
        return False, f"{len(statuses)} ok; bad={bad}"
    return True, f"{len(statuses)} SLOs with data"


def fix_slos_no_data() -> tuple[bool, str]:
    from src.budgets import load_budgets, recover_slos

    cfg = load_budgets()
    stale = []
    for spec in cfg.get("slos") or []:
        r = _kbn_get(f"/api/observability/slos/{spec['id']}")
        if r.status_code != 200:
            stale.append(spec["id"])
            continue
        if (r.json().get("summary") or {}).get("status") in (None, "NO_DATA"):
            stale.append(spec["id"])
    if not stale:
        return True, "nothing to reset"
    recover_slos(fail_loud=False, slo_ids=stale)
    # wait briefly for transforms
    time.sleep(20)
    return True, f"reset {stale}"


def check_agent() -> tuple[bool, str]:
    from src.agent_builder import load_agent_config, AGENTS_API, TOOLS_API, _kbn

    cfg = load_agent_config()
    aid = cfg["agent"]["id"]
    missing_tools = []
    for spec in cfg.get("tools") or []:
        r = _kbn("GET", f"{TOOLS_API}/{spec['id']}")
        if r.status_code != 200:
            missing_tools.append(spec["id"])
    r = _kbn("GET", f"{AGENTS_API}/{aid}")
    if r.status_code != 200:
        return False, f"agent {aid}: {r.status_code}"
    if missing_tools:
        return False, f"missing tools {missing_tools[:5]}"
    return True, f"agent {aid} + {len(cfg.get('tools') or [])} tools"


def check_genai_tracking() -> tuple[bool, str]:
    from src.genai_settings import _read_token_usage_enabled

    enabled = _read_token_usage_enabled()
    if enabled is True:
        return True, "enabled"
    return False, f"enabled={enabled!r}"


def check_ess_package() -> tuple[bool, str]:
    r = requests.get(
        f"{KIBANA_ROOT}/api/fleet/epm/packages/ess_billing",
        headers=KBN_HEADERS,
        timeout=60,
    )
    if r.status_code != 200:
        return False, f"lookup {r.status_code}"
    item = r.json().get("item") or {}
    if item.get("status") != "installed":
        return False, f"status={item.get('status')}"
    return True, f"v{item.get('version')}"


def check_svs_ess_panels() -> tuple[bool, str]:
    """Spend-vs-savings Elastic Cloud panels must use bare dataset KQL (not .keyword)."""
    r = _kbn_get("/api/dashboards/finops-spend-vs-savings")
    if r.status_code != 200:
        return False, f"dashboard GET {r.status_code}"
    panels = (r.json().get("data") or {}).get("panels") or []
    by_id = {p.get("id"): p for p in panels if isinstance(p, dict)}
    missing = [pid for pid in ("svs-ess-kpi", "svs-ess") if pid not in by_id]
    if missing:
        return False, f"missing panels {missing}"
    for pid in ("svs-ess-kpi", "svs-ess"):
        cfg = by_id[pid].get("config") or {}
        blob = json.dumps(cfg)
        if "data_stream.dataset.keyword" in blob:
            return False, f"{pid} still filters on dataset.keyword"
        if not cfg.get("ignore_global_filters"):
            return False, f"{pid} should ignore AWS account control"
    # Confirm the (fixed) KQL actually hits docs in the demo window
    from src.time_window import demo_window

    win = demo_window(to_pad_days=1)
    status, body = _es_query(
        "FROM metrics-ess_billing.billing-*\n"
        f'| WHERE @timestamp >= "{win["from"]}" AND @timestamp <= "{win["to"]}"\n'
        "| STATS n = COUNT(*), ecu = SUM(ess.billing.total_ecu)\n"
    )
    if status != 200:
        return False, f"ess probe {status}"
    n, ecu = (body.get("values") or [[0, 0]])[0]
    if not n or not ecu:
        return False, f"ess empty in window n={n} ecu={ecu}"
    return True, f"panels ok; {n} docs / {round(float(ecu), 2)} ECU"


def fix_svs_ess_panels() -> tuple[bool, str]:
    from src.live_dashboards import _fix_billing_dashboard_filters, _fix_svs_ess_panels

    _fix_billing_dashboard_filters()
    _fix_svs_ess_panels()
    return True, "fix_svs_ess_panels"


def check_esql_panel_queries() -> tuple[bool, str]:
    """Run representative ES|QL from live dashboards."""
    probes = [
        (
            "aws_linked",
            'FROM metrics-aws.billing-*\n'
            '| WHERE @timestamp > NOW() - 30 days AND aws.billing.group_definition.key == "LINKED_ACCOUNT"\n'
            "| STATS spend = SUM(aws.billing.UnblendedCost.amount)\n",
        ),
        (
            "ess_deploy",
            "FROM metrics-ess_billing.billing-*\n"
            "| STATS total = SUM(ess.billing.total_ecu::DOUBLE) "
            "BY ess.billing.deployment_type, ess.billing.deployment_name\n"
            "| LIMIT 5\n",
        ),
        (
            "svs_heat_month",
            "FROM metrics-aws.billing-*\n"
            "| WHERE @timestamp > NOW() - 120 days "
            'AND aws.billing.group_definition.key == "LINKED_ACCOUNT"\n'
            "| EVAL month = CONCAT(\n"
            '    TO_STRING(DATE_EXTRACT("year", @timestamp)), "-",\n'
            '    CASE(DATE_EXTRACT("month_of_year", @timestamp) < 10, "0", ""),\n'
            '    TO_STRING(DATE_EXTRACT("month_of_year", @timestamp))\n'
            "  )\n"
            "| STATS spend = ROUND(SUM(aws.billing.UnblendedCost.amount), 2) "
            "BY month, account = cloud.account.id\n"
            "| LIMIT 5\n",
        ),
        (
            "cpu_heat_week",
            "FROM metrics-aws.ec2_metrics-*\n"
            "| WHERE @timestamp > NOW() - 30 days AND cloud.instance.name IS NOT NULL\n"
            "| STATS cpu = ROUND(AVG(host.cpu.usage) * 100, 1) "
            "BY t = DATE_TRUNC(1 week, @timestamp), instance = cloud.instance.name\n"
            "| EVAL week = SUBSTRING(TO_STRING(t), 0, 10)\n"
            "| KEEP week, instance, cpu\n"
            "| LIMIT 5\n",
        ),
    ]
    failed = []
    for name, q in probes:
        status, body = _es_query(q)
        if status != 200:
            failed.append(f"{name}:{status}:{str(body)[:120]}")
            continue
        if not (body.get("values") or body.get("columns")):
            failed.append(f"{name}:empty")
    if failed:
        return False, "; ".join(failed[:4])
    return True, f"{len(probes)} ES|QL probes ok"



def check_workflow_run_auto(*, deep: bool) -> tuple[bool, str]:
    if not deep:
        return True, "skipped (pass --deep)"
    wid = "gev-finops-spend-spike-auto-approve"
    r = requests.post(
        f"{KIBANA_URL}/api/workflows/workflow/{wid}/run",
        headers=KBN_HEADERS,
        json={"inputs": {"account": "*", "service": "*", "lookback": "7 days"}},
        timeout=60,
    )
    if r.status_code >= 300:
        return False, f"run {r.status_code}: {r.text[:200]}"
    eid = r.json().get("workflowExecutionId")
    if not eid:
        return False, f"no execution id: {r.text[:200]}"
    deadline = time.time() + 300
    last = None
    while time.time() < deadline:
        rr = requests.get(
            f"{KIBANA_URL}/api/workflows/executions/{eid}",
            headers=KBN_HEADERS,
            timeout=30,
        )
        body = rr.json() if rr.status_code == 200 else {}
        last = body.get("status")
        if last in ("completed", "failed", "cancelled", "waiting_for_input"):
            if last == "completed":
                return True, f"execution {eid[:8]}… completed"
            return False, f"execution {eid[:8]}… {last} err={body.get('error')}"
        time.sleep(3)
    return False, f"timeout last={last}"


def check_rightsizing() -> tuple[bool, str]:
    from src.rightsizing import DATA_STREAM, TRANSFORM_ID

    r = requests.get(
        f"{ELASTIC_URL}/_data_stream/{DATA_STREAM}",
        headers=ES_HEADERS,
        timeout=30,
    )
    if r.status_code != 200:
        return False, f"stream {r.status_code}"
    r = requests.get(
        f"{ELASTIC_URL}/_transform/{TRANSFORM_ID}",
        headers=ES_HEADERS,
        timeout=30,
    )
    if r.status_code != 200:
        return False, f"transform {r.status_code}"
    status, body = _es_query(f"FROM {DATA_STREAM.replace('-default', '-*')}\n| STATS n=COUNT(*)\n")
    # latest index pattern used by dashboards
    status2, body2 = _es_query(
        "FROM finops-rightsizing-latest*\n| STATS n=COUNT(*)\n"
    )
    n = (body2.get("values") or [[0]])[0][0] if status2 == 200 else 0
    if status2 != 200 or not n:
        return False, f"latest index docs={n} query={status2}"
    return True, f"transform ok; latest={n} docs"


# --- runner ----------------------------------------------------------------


def run_smoke(*, fix: bool = False, deep: bool = False) -> SmokeReport:
    from src.profile import finops_profile
    from src.live_dashboards import DASHBOARD_IDS

    report = SmokeReport(
        started_at=datetime.now(timezone.utc).isoformat(),
        profile=finops_profile(),
        suite="live-finops",
        variant="",
        kibana=KIBANA_URL,
        elastic=ELASTIC_URL.split("@")[-1] if "@" in ELASTIC_URL else ELASTIC_URL,
    )
    results: list[CheckResult] = []

    _check(results, "es", "Elasticsearch connectivity", check_es_connectivity, do_fix=fix)
    _check(results, "kibana", "Kibana connectivity (finops space)", check_kibana_connectivity, do_fix=fix)
    _check(results, "ess_pkg", "Fleet ess_billing package", check_ess_package, do_fix=fix)
    _check(results, "genai", "GenAI token usage tracking", check_genai_tracking, do_fix=fix)

    for stream, mid, min_docs in (
        ("metrics-aws.billing-*", "data_aws_billing", 10),
        ("metrics-aws.ec2_metrics-*", "data_ec2", 10),
        ("logs-finops.rightsizing-*", "data_rightsizing", 1),
        ("finops-rightsizing-latest*", "data_rightsizing_latest", 1),
        ("metrics-ess_billing.billing-*", "data_ess_billing", 10),
        ("logs-elastic.inference_token_usage-default", "data_inference", 1),
    ):
        _check(
            results,
            mid,
            f"Data: {stream}",
            lambda s=stream, m=min_docs: check_stream_docs(s, m),
            do_fix=fix,
        )

    _check(
        results,
        "ess_fields",
        "ESS billing deployment_* keyword fields",
        check_ess_billing_fields,
        fix=fix_ess_billing_fields,
        do_fix=fix,
    )
    _check(
        results,
        "rightsizing",
        "Rightsizing stream + transform + latest",
        check_rightsizing,
        do_fix=fix,
    )

    for did in DASHBOARD_IDS:
        _check(
            results,
            f"dash_{did}",
            f"Dashboard {did}",
            lambda d=did: check_dashboard(d),
            do_fix=fix,
        )

    _check(
        results,
        "hub_links",
        "Hub tabs ESS Billing / Credits / Inference",
        check_hub_links,
        fix=fix_hub_links,
        do_fix=fix,
    )
    _check(
        results,
        "svs_heat",
        "Spend heatmap panel (ordinal month)",
        lambda: check_heatmap_panel(
            "finops-spend-vs-savings",
            "svs-heat",
            {
                "scale": "ordinal",
                "x_column": "month",
                "query_contains": ["BY month, account", "DATE_EXTRACT"],
            },
        ),
        fix=fix_heatmaps,
        do_fix=fix,
    )
    _check(
        results,
        "rs_heat",
        "EC2 CPU heatmap panel (ordinal week)",
        lambda: check_heatmap_panel(
            "finops-rightsizing-overview",
            "rs-v-heat",
            {
                "scale": "ordinal",
                "x_column": "week",
                "query_contains": ["SUBSTRING(TO_STRING(t)", "host.cpu.usage"],
            },
        ),
        fix=fix_heatmaps,
        do_fix=fix,
    )
    _check(
        results,
        "svs_ess",
        "Spend vs savings Elastic Cloud panels",
        check_svs_ess_panels,
        fix=fix_svs_ess_panels,
        do_fix=fix,
    )
    _check(
        results,
        "esql_probes",
        "Representative ES|QL probes",
        check_esql_panel_queries,
        do_fix=fix,
    )
    _check(
        results,
        "case_fields",
        "Observability Cases FinOps custom fields",
        check_case_custom_fields,
        fix=fix_case_custom_fields,
        do_fix=fix,
    )
    _check(
        results,
        "workflows",
        "FinOps workflows provisioned",
        check_workflows,
        fix=fix_workflows,
        do_fix=fix,
    )
    _check(
        results,
        "workflow_run",
        "Workflow auto-approve execution",
        lambda: check_workflow_run_auto(deep=deep),
        do_fix=fix,
    )
    _check(
        results,
        "slos",
        "Spend SLOs have SLI data (not NO_DATA)",
        check_slos_have_data,
        fix=fix_slos_no_data,
        do_fix=fix,
    )
    _check(
        results,
        "agent",
        "FinOps AI Assistant + tools",
        check_agent,
        do_fix=fix,
    )

    report.checks = results
    report.passed = sum(1 for c in results if c.ok)
    report.failed = sum(1 for c in results if not c.ok)
    report.fixed = sum(1 for c in results if c.fixed)
    report.finished_at = datetime.now(timezone.utc).isoformat()
    return report


def print_report(report: SmokeReport) -> None:
    print()
    print("=" * 72)
    print("LIVE FINOPS SMOKE REPORT" if report.suite == "live-finops" else "VARIANT SMOKE REPORT")
    print("=" * 72)
    print(f"suite:    {report.suite}")
    if report.variant:
        print(f"variant:  {report.variant}")
    print(f"profile:  {report.profile}")
    print(f"kibana:   {report.kibana}")
    print(f"started:  {report.started_at}")
    print(f"finished: {report.finished_at}")
    print("-" * 72)
    width = max(len(c.name) for c in report.checks) if report.checks else 20
    for c in report.checks:
        mark = "PASS" if c.ok else "FAIL"
        fix = " FIXED" if c.fixed else ""
        detail = (c.detail or "").replace("\n", " ")
        if len(detail) > 90:
            detail = detail[:87] + "..."
        print(f"[{mark}]{fix:6}  {c.name:<{width}}  {detail}  ({c.duration_ms}ms)")
    print("-" * 72)
    print(
        f"RESULT: {'SUCCESS' if report.ok else 'FAILURE'}  "
        f"passed={report.passed} failed={report.failed} fixed={report.fixed} "
        f"total={len(report.checks)}"
    )
    print("=" * 72)


def write_report_json(report: SmokeReport, path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(asdict(report), f, indent=2)
    print(f"wrote {path}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Live FinOps smoke test")
    p.add_argument("--fix", action="store_true", help="attempt known remediations")
    p.add_argument("--deep", action="store_true", help="run mutating workflow execution")
    p.add_argument("--json-out", help="write machine-readable report JSON")
    args = p.parse_args(argv)

    report = run_smoke(fix=args.fix, deep=args.deep)
    print_report(report)
    if args.json_out:
        write_report_json(report, args.json_out)
    return 0 if report.ok else 1


if __name__ == "__main__":
    # Ensure live profile when invoked as module without cli wrapper
    import os

    os.environ.setdefault("FINOPS_PROFILE", "live")
    raise SystemExit(main())
