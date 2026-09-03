"""CLI: setup | sample | backfill | stream | verify | dashboards | agent | incident."""
from __future__ import annotations

import argparse
import json
import time
from datetime import timedelta

import requests

from src.config import (
    DS_APM_INTERNAL,
    DS_CHECKOUT,
    DS_INVENTORY,
    DS_NOTIFICATION,
    DS_K8S_EVENT,
    DS_K8S_POD,
    DS_K8S_NODE,
    DS_HOST,
    DS_ORCHESTRATOR,
    DS_TRACES,
    ELASTIC_URL,
    ES_HEADERS,
    KBN_HEADERS,
    KIBANA_DIR,
    KIBANA_URL,
)
from src.generators import select
from src.generators.apm import ensure_apm_mappings
from src.setup_cmd import run_setup
from src.sink.elastic import BulkSink, es_search
from src.world.model import load_world, utcnow


def _docs_from_gen(gen, world, t0, t1, anchor):
    """Normalize generator output to (index, doc) pairs."""
    for item in gen.emit(world, t0, t1, anchor):
        if isinstance(item, tuple) and len(item) == 2:
            yield item
        else:
            yield gen.DATA_STREAM, item


def cmd_setup(_: argparse.Namespace):
    run_setup(include_alerts=True)


def cmd_sample(args: argparse.Namespace):
    world = load_world()
    anchor = utcnow()
    t1 = anchor
    t0 = anchor - timedelta(hours=2)
    ok = True
    for gen in select(args.scope):
        docs = list(_docs_from_gen(gen, world, t0, t1, anchor))
        if not docs:
            print(f"[skip] {getattr(gen, 'DATA_STREAM', gen.__name__)}: no docs")
            continue
        index, doc = docs[0]
        # Prefer pipeline simulate for orchestrator
        if index == DS_ORCHESTRATOR:
            r = requests.post(
                f"{ELASTIC_URL}/_ingest/pipeline/logs-elasticco.orchestrator/_simulate",
                headers=ES_HEADERS,
                timeout=60,
                json={"docs": [{"_source": doc}]},
            )
            if r.status_code >= 300:
                print(f"[fail] simulate: {r.status_code} {r.text[:200]}")
                ok = False
                continue
            src = r.json()["docs"][0].get("doc", {}).get("_source", {})
            need = ["tenant.id", "trace.id", "orchestrator.dag_id", "orchestrator.task_id"]
            missing = [f for f in need if _get(src, f) is None]
            if missing:
                print(f"[fail] {index}: missing after pipeline {missing}")
                ok = False
            else:
                print(
                    f"[ok] {index}: tenant={_get(src,'tenant.id')} "
                    f"trace={_get(src,'trace.id')} dag={_get(src,'orchestrator.dag_id')}"
                )
        else:
            r = requests.post(
                f"{ELASTIC_URL}/{index}/_doc?refresh=wait_for",
                headers=ES_HEADERS,
                json=doc,
                timeout=60,
            )
            if r.status_code >= 300:
                print(f"[fail] {index}: {r.status_code} {r.text[:200]}")
                ok = False
            else:
                print(f"[ok] {index}: live-write accepted")
    if not ok:
        raise SystemExit(1)


def _get(d: dict, dotted: str):
    cur = d
    for p in dotted.split("."):
        if not isinstance(cur, dict) or p not in cur:
            return None
        cur = cur[p]
    return cur


def cmd_backfill(args: argparse.Namespace):
    world = load_world()
    gens = select(args.scope)
    anchor = utcnow()
    start = anchor - timedelta(hours=args.hours)
    sink = BulkSink()
    print(
        f"backfilling {args.scope} {args.hours}h: "
        f"{start:%Y-%m-%d %H:%M} -> {anchor:%Y-%m-%d %H:%M} UTC ({len(gens)} generators)"
    )
    ensure_apm_mappings()
    t0 = start
    began = time.time()
    while t0 < anchor:
        t1 = min(t0 + timedelta(hours=1), anchor)
        for gen in gens:
            for index, doc in _docs_from_gen(gen, world, t0, t1, anchor):
                sink.add(index, doc)
        print(f"  hour {t0:%H:%M}-{t1:%H:%M} buffered")
        t0 = t1
    indexed, failed, errors = sink.close()
    print(f"done in {time.time()-began:.1f}s")
    for idx, n in sorted(indexed.items()):
        print(f"  indexed {n:5d} -> {idx}")
    for idx, n in sorted(failed.items()):
        print(f"  FAILED  {n:5d} -> {idx}: {errors.get(idx)}")
    if failed:
        raise SystemExit(1)
    from src.setup_cmd import refresh_data_views

    print("== refresh data views ==")
    refresh_data_views(force=True)


def cmd_stream(args: argparse.Namespace):
    world = load_world()
    live_incident = getattr(args, "live_incident", True)
    if live_incident:
        # Keep the tick inside the planted window so a long session does not
        # emit healthy recovery traffic that ages 60-minute alerts out.
        duration = max(int(world.cfg["incident"].get("duration_minutes", 60)), 15)
        world.cfg["incident"]["start_offset_minutes"] = duration
        world.cfg["incident"]["duration_minutes"] = duration
        print(
            "  [live-incident] pinning incident window through now "
            "so 60-minute alerts stay firing"
        )
        lr = world.cfg.get("log_rate")
        if lr:
            d = max(int(lr.get("duration_minutes", 35)), 15)
            lr["start_offset_minutes"] = d
            lr["duration_minutes"] = d
            print("  [live-incident] pinning U7 log-rate DEBUG flood through now")
        gap = world.cfg.get("telemetry_gap")
        if gap:
            d = max(int(gap.get("duration_minutes", 20)), 15)
            gap["start_offset_minutes"] = d
            gap["duration_minutes"] = d
            print("  [live-incident] pinning U8 notification log silence through now")
    else:
        print(
            "  [warn] --no-live-incident: ticks are healthy recovery; "
            "60-minute alerts will age out"
        )
    gens = select(args.scope)
    ensure_apm_mappings()
    print(f"streaming scope={args.scope} tick={args.tick}s (Ctrl+C to stop)")
    while True:
        anchor = utcnow()
        t0 = anchor - timedelta(seconds=args.tick)
        sink = BulkSink(batch_docs=200)
        for gen in gens:
            for index, doc in _docs_from_gen(gen, world, t0, anchor, anchor):
                sink.add(index, doc)
        indexed, failed, errors = sink.close()
        total = sum(indexed.values())
        print(f"  tick {anchor:%H:%M:%S} indexed={total} failed={sum(failed.values())}")
        if failed:
            for idx, err in errors.items():
                print(f"    {idx}: {err}")
        time.sleep(args.tick)


def _last_60m_correlation_hits() -> int:
    """Hits that should keep the 60-minute correlation / error-rate rules firing."""
    gte = {"range": {"@timestamp": {"gte": "now-60m"}}}
    demo = {"term": {"labels.demo": "elastic-co"}}

    def n(index: str, extra: dict) -> int:
        try:
            r = es_search(
                index,
                {
                    "size": 0,
                    "track_total_hits": True,
                    "query": {"bool": {"filter": [gte, demo, extra]}},
                },
            )
            return int(r["hits"]["total"]["value"])
        except Exception:
            return 0

    oom = n(DS_K8S_EVENT, {"term": {"kubernetes.event.reason": "OOMKilled"}})
    logs = n(DS_CHECKOUT, {"query_string": {"query": "*OutOfMemory*", "fields": ["message"]}})
    slow = n(
        DS_TRACES,
        {
            "bool": {
                "must": [
                    {"term": {"span.type": "db"}},
                    {"term": {"tenant.id": "acme-retail"}},
                    {"range": {"span.duration.us": {"gte": 2_000_000}}},
                ]
            }
        },
    )
    return oom + logs + slow


def verify_alert_rules() -> bool:
    """Assert demo alert rules exist, are enabled, have Cases where claimed, and are firing."""
    rules_file = KIBANA_DIR / "alert-rules.json"
    if not rules_file.exists():
        print("[fail] kibana/alert-rules.json missing")
        return False

    expected = json.loads(rules_file.read_text())
    rules_with_cases = {
        "elasticco-checkout-correlated-rca",
        "elasticco-eks-pod-restarts",
        "elasticco-log-telemetry-gap",
    }
    rules_with_workflow = {"elasticco-checkout-correlated-rca", "elasticco-eks-pod-restarts"}
    ok = True

    try:
        r = requests.get(
            f"{KIBANA_URL}/api/alerting/rules/_find",
            headers=KBN_HEADERS,
            params={"per_page": 100, "search": "elasticco", "search_fields": "name"},
            timeout=60,
        )
    except Exception as exc:
        print(f"[fail] alert rules API: {exc}")
        return False

    if r.status_code >= 300:
        print(f"[fail] alert rules API: {r.status_code} {r.text[:200]}")
        return False

    by_name = {x["name"]: x for x in r.json().get("data", []) if x.get("name")}

    for rule in expected:
        name = rule["name"]
        remote = by_name.get(name)
        if not remote:
            print(f"[fail] alert rule missing: {name}")
            ok = False
            continue

        if not remote.get("enabled", True):
            print(f"[fail] alert rule disabled: {name}")
            ok = False
        else:
            print(f"[ok] alert rule active: {name}")

        if name != "elasticco-noisy-node-cpu" and rule.get("rule_type_id") == ".es-query":
            params = remote.get("params") or {}
            esql = ((params.get("esqlQuery") or {}).get("esql") or "")
            grouped = params.get("groupBy") == "row"
            has_svc = "BY service.name" in esql or "`service.name`" in esql
            if grouped and has_svc:
                print(f"[ok] {name}: service.name on alert (APM inventory / map)")
            else:
                print(
                    f"[fail] {name}: missing per-row service.name "
                    "— APM inventory/map will not badge checkout-api (re-run setup)"
                )
                ok = False

        if name in rules_with_cases:
            actions = remote.get("actions") or []
            has_cases = any(
                a.get("id") == "system-connector-.cases" or a.get("actionTypeId") == ".cases"
                for a in actions
            )
            if has_cases:
                print(f"[ok] {name}: Cases connector attached")
            else:
                print(
                    f"[fail] {name}: missing Cases connector "
                    "(re-run setup or attach system-connector-.cases in Kibana)"
                )
                ok = False

        if name in rules_with_workflow:
            actions = remote.get("actions") or []
            has_wf = any(
                a.get("id") == "system-connector-.workflows"
                or a.get("actionTypeId") == ".workflows"
                for a in actions
            )
            if has_wf:
                print(f"[ok] {name}: Workflows connector attached")
            else:
                print(
                    f"[fail] {name}: missing Run Workflow action "
                    "(re-run setup after elasticco-detect-remediate exists)"
                )
                ok = False

        status = (remote.get("execution_status") or {}).get("status", "")
        if status == "error":
            print(f"[fail] {name}: execution_status=error")
            ok = False
        elif status == "active":
            print(f"[ok] {name}: firing (execution_status=active)")
        elif name in rules_with_cases or name == "elasticco-app-checkout-error-rate":
            print(
                f"[fail] {name}: not firing (execution_status={status or 'unknown'}) "
                "— wait 1–2 min after backfill or start stream (live-incident default)"
            )
            ok = False
        else:
            print(f"[info] {name}: execution_status={status or 'unknown'}")

    hits = _last_60m_correlation_hits()
    if hits > 0:
        print(f"[ok] last-60m correlation evidence: {hits} hits")
    else:
        print(
            "[fail] last-60m correlation evidence: 0 hits "
            "(incident window is not through now — re-run backfill or start stream)"
        )
        ok = False

    return ok


def cmd_verify(args: argparse.Namespace):
    world = load_world()
    anchor = utcnow()
    heroes = world.hero_traces(anchor)
    hero_ids = [h.trace_id for h in heroes]
    ok = True

    def count(index: str, query: dict) -> int:
        try:
            r = es_search(index, {"size": 0, "track_total_hits": True, "query": query})
            return int(r["hits"]["total"]["value"])
        except Exception as exc:
            print(f"[fail] search {index}: {exc}")
            return -1

    checks = [
        (
            "orchestrator acme-retail ERROR retry storm",
            DS_ORCHESTRATOR,
            {
                "bool": {
                    "must": [
                        {"term": {"tenant.id": world.blast_tenant["id"]}},
                        {"term": {"log.level": "error"}},
                    ]
                }
            },
        ),
        (
            "orchestrator structured tenant+trace",
            DS_ORCHESTRATOR,
            {
                "bool": {
                    "must": [
                        {"term": {"tenant.id": world.blast_tenant["id"]}},
                        {"exists": {"field": "trace.id"}},
                        {"exists": {"field": "orchestrator.dag_id"}},
                    ]
                }
            },
        ),
        (
            "hero traces in APM",
            DS_TRACES,
            {"terms": {"trace.id": hero_ids[:3]}},
        ),
        (
            "slow db spans",
            DS_TRACES,
            {
                "bool": {
                    "must": [
                        {"term": {"span.type": "db"}},
                        {"term": {"span.subtype": "postgresql"}},
                        {"term": {"tenant.id": world.blast_tenant["id"]}},
                    ]
                }
            },
        ),
        (
            "OOMKilled events",
            DS_K8S_EVENT,
            {"term": {"kubernetes.event.reason": "OOMKilled"}},
        ),
        (
            "pod memory metrics",
            DS_K8S_POD,
            {"exists": {"field": "kubernetes.pod.memory.usage.bytes"}},
        ),
        (
            "checkout OOM logs",
            DS_CHECKOUT,
            {"query_string": {"query": "*OutOfMemory*", "fields": ["message"]}},
        ),
        (
            "inventory SkuCache DEBUG flood",
            DS_INVENTORY,
            {
                "bool": {
                    "must": [
                        {"term": {"log.level": "debug"}},
                        {"term": {"log.logger": "com.elasticco.inventory.SkuCache"}},
                    ]
                }
            },
        ),
        (
            "notification-service log baseline (U8)",
            DS_NOTIFICATION,
            {"term": {"service.name": "notification-service"}},
        ),
        (
            "host CPU metrics",
            DS_HOST,
            {"exists": {"field": "system.cpu.total.norm.pct"}},
        ),
        (
            "k8s node metrics",
            DS_K8S_NODE,
            {"exists": {"field": "kubernetes.node.cpu.usage.nanocores"}},
        ),
        (
            "APM runtime metrics by service",
            DS_APM_INTERNAL,
            {"term": {"service.name": "checkout-api"}},
        ),
        (
            "APM JVM heap pool metrics (checkout-api)",
            DS_APM_INTERNAL,
            {
                "bool": {
                    "must": [
                        {"term": {"service.name": "checkout-api"}},
                        {"exists": {"field": "jvm.memory.heap.pool.used"}},
                    ]
                }
            },
        ),
    ]

    for label, index, query in checks:
        n = count(index, query)
        if n < 0:
            ok = False
        elif n == 0:
            print(f"[fail] {label}: 0 hits on {index}")
            ok = False
        else:
            print(f"[ok] {label}: {n} hits")

    # U8 — logs silent last 15m, APM still transacting
    ntfy_15m = count(
        DS_NOTIFICATION,
        {
            "bool": {
                "must": [
                    {"range": {"@timestamp": {"gte": "now-15m"}}},
                    {"term": {"labels.demo": "elastic-co"}},
                ]
            }
        },
    )
    if ntfy_15m < 0:
        ok = False
    elif ntfy_15m == 0:
        print("[ok] notification-service logs last 15m: 0 (telemetry gap planted)")
    else:
        print(
            f"[fail] notification-service logs last 15m: {ntfy_15m} "
            "(gap not through now — re-run backfill --scope app_logs or start stream)"
        )
        ok = False

    ntfy_apm_15m = count(
        DS_TRACES,
        {
            "bool": {
                "must": [
                    {"range": {"@timestamp": {"gte": "now-15m"}}},
                    {"term": {"labels.demo": "elastic-co"}},
                    {"term": {"processor.event": "transaction"}},
                    {"term": {"service.name": "notification-service"}},
                ]
            }
        },
    )
    if ntfy_apm_15m < 0:
        ok = False
    elif ntfy_apm_15m == 0:
        print(
            "[fail] notification-service APM last 15m: 0 "
            "(app looks down too — re-run backfill --scope apm or start stream)"
        )
        ok = False
    else:
        print(f"[ok] notification-service APM last 15m: {ntfy_apm_15m} txns (app alive)")

    # Correlation: same trace.id in orchestrator + traces
    if heroes:
        tid = heroes[0].trace_id
        n_log = count(DS_ORCHESTRATOR, {"term": {"trace.id": tid}})
        n_tr = count(DS_TRACES, {"term": {"trace.id": tid}})
        if n_log > 0 and n_tr > 0:
            print(f"[ok] correlation hero trace {tid[:12]}… logs={n_log} traces={n_tr}")
        else:
            print(f"[fail] correlation hero trace {tid[:12]}… logs={n_log} traces={n_tr}")
            ok = False

    print("== data views ==")
    from src.setup_cmd import verify_data_views

    if not verify_data_views():
        ok = False

    if getattr(args, "alerts", False):
        print("== alert rules ==")
        if not verify_alert_rules():
            ok = False
        print("== native SLO ==")
        try:
            from src.slos import SLO_ID, SLO_API, _kbn as slo_kbn

            r = slo_kbn("GET", f"{SLO_API}/{SLO_ID}")
            if r.status_code == 200:
                summary = r.json().get("summary") or {}
                status = (summary.get("status") or "unknown").upper()
                sli = summary.get("sliValue")
                if status == "NO_DATA":
                    print(
                        f"[fail] SLO {SLO_ID}: status=NO_DATA "
                        "(indicator is not seeing traces — re-run setup)"
                    )
                    ok = False
                else:
                    print(f"[ok] SLO {SLO_ID}: status={status} sli={sli}")
            elif r.status_code in (403, 404):
                print(f"[fail] SLO {SLO_ID}: {r.status_code}")
                ok = False
            else:
                print(f"[fail] SLO {SLO_ID}: {r.status_code}")
                ok = False
        except Exception as exc:
            print(f"[fail] SLO check: {exc}")
            ok = False
        print("== Agent Builder ==")
        try:
            from src.agent_builder import verify_agent

            if not verify_agent():
                ok = False
        except Exception as exc:
            print(f"[fail] Agent Builder check: {exc}")
            ok = False
        print("== Kibana Workflow ==")
        try:
            from src.workflows import verify_workflow

            if not verify_workflow():
                ok = False
        except Exception as exc:
            print(f"[fail] Workflow check: {exc}")
            ok = False

    print(f"Kibana: {KIBANA_URL}")
    if not ok:
        raise SystemExit(1)


def cmd_agent(args: argparse.Namespace):
    """Provision or re-print the Agent Builder RCA agent (customer-facing U5 close)."""
    from src.agent_builder import ensure_agent, verify_agent

    if getattr(args, "verify_only", False):
        if not verify_agent():
            raise SystemExit(1)
        return
    ensure_agent(fail_loud=getattr(args, "fail_loud", False))


def cmd_workflow(args: argparse.Namespace):
    """Provision the Kibana Workflow that stitches detect → RCA → case."""
    from src.workflows import ensure_workflow, verify_workflow

    if getattr(args, "verify_only", False):
        if not verify_workflow():
            raise SystemExit(1)
        return
    ensure_workflow(fail_loud=getattr(args, "fail_loud", False))


def cmd_incident(args: argparse.Namespace):
    """Facilitator backup: CLI RCA — investigate, approve, remediate, email summary."""
    from src.rca_agent import run_incident_workflow

    run_incident_workflow(
        auto=args.auto,
        email=args.email,
        dry_run=args.dry_run,
        skip_email=args.no_email,
        skip_case=args.no_case,
    )


def cmd_dashboards(_: argparse.Namespace):
    """Re-import Kibana saved objects + publish ES|QL incident dashboard."""
    from src.setup_cmd import ensure_alert_rules, import_saved_objects, publish_dashboard, refresh_data_views

    import_saved_objects()
    print("== data views ==")
    refresh_data_views(force=True)
    publish_dashboard()
    ensure_alert_rules()
    print("Deep links:")
    print(f"  Discover orchestrator: {KIBANA_URL}/app/discover#/?_a=(dataSource:(dataViewId:elasticco-orchestrator))")
    print(f"  Discover logs (all):   {KIBANA_URL}/app/discover#/?_a=(dataSource:(dataViewId:elasticco-logs))")
    print(f"  APM services:          {KIBANA_URL}/app/apm/services")
    print(f"  Alerts:                {KIBANA_URL}/app/observability/alerts")
    print(f"  Cases:                 {KIBANA_URL}/app/observability/cases")
    print(f"  AI Assistant:          {KIBANA_URL}/app/observabilityAIAssistant")
    print(f"  Agent Builder:         {KIBANA_URL}/app/agent_builder/chat")
    print(f"  Workflows:             {KIBANA_URL}/app/workflows")
    print(f"  SLOs:                  {KIBANA_URL}/app/observability/slos")
    print(f"  Dashboard (incident):  {KIBANA_URL}/app/dashboards#/view/elasticco-incident-overview")
    print(f"  Dashboard (eks):       {KIBANA_URL}/app/dashboards#/view/elasticco-eks-restarts")
    print(f"  Dashboard (traces):    {KIBANA_URL}/app/dashboards#/view/elasticco-distributed-traces")
    print(f"  Dashboard (e2e):       {KIBANA_URL}/app/dashboards#/view/elasticco-e2e-tracing")
    print(f"  Dashboard (log rate):  {KIBANA_URL}/app/dashboards#/view/elasticco-log-rate")
    print(f"  Dashboard (telemetry): {KIBANA_URL}/app/dashboards#/view/elasticco-telemetry-gap")
    print(f"  AIOps log rate:        {KIBANA_URL}/app/ml/aiops/log_rate_analysis")
    print(f"  Incidents (audit):     {KIBANA_URL}/app/discover#/?_a=(dataSource:(dataViewId:elasticco-incidents))")


SCOPE_CHOICES = [
    "all",
    "orchestrator",
    "apm",
    "apm_deps",
    "traces",
    "k8s",
    "infra",
    "app_logs",
]


def main():
    p = argparse.ArgumentParser(description="Elastic Co. observability demo")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser(
        "setup",
        help="pipelines, templates, native SLO, Agent Builder, Workflow, alerts",
    ).set_defaults(func=cmd_setup)

    s = sub.add_parser("sample", help="simulate/pipeline-check one doc per generator")
    s.add_argument(
        "--scope",
        default="all",
        choices=SCOPE_CHOICES,
    )
    s.set_defaults(func=cmd_sample)

    b = sub.add_parser("backfill", help="plant incident history")
    b.add_argument("--hours", type=int, default=6)
    b.add_argument(
        "--scope",
        default="all",
        choices=SCOPE_CHOICES,
    )
    b.set_defaults(func=cmd_backfill)

    st = sub.add_parser("stream", help="live tick for demos")
    st.add_argument("--tick", type=int, default=60)
    st.add_argument(
        "--scope",
        default="all",
        choices=SCOPE_CHOICES,
    )
    st.add_argument(
        "--live-incident",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="keep the planted incident window through now so 60-minute alerts stay firing "
        "(default: on; --no-live-incident for healthy recovery ticks)",
    )
    st.set_defaults(func=cmd_stream)

    v = sub.add_parser("verify", help="assert correlation + field presence")
    v.add_argument(
        "--alerts",
        action="store_true",
        help="verify alert rules (exist, enabled, Cases, Workflows, firing) plus SLO, agent, workflow",
    )
    v.set_defaults(func=cmd_verify)
    sub.add_parser("dashboards", help="import Kibana assets + print links").set_defaults(
        func=cmd_dashboards
    )

    ag = sub.add_parser("agent", help="provision Agent Builder RCA agent (U5 close)")
    ag.add_argument(
        "--verify-only",
        action="store_true",
        help="check tools + agent exist; do not upsert",
    )
    ag.add_argument(
        "--fail-loud",
        action="store_true",
        help="exit non-zero if Agent Builder APIs reject the upsert",
    )
    ag.set_defaults(func=cmd_agent)

    wf = sub.add_parser("workflow", help="provision Kibana Workflow detect-to-remediate")
    wf.add_argument(
        "--verify-only",
        action="store_true",
        help="check workflow exists and is enabled; do not upsert",
    )
    wf.add_argument(
        "--fail-loud",
        action="store_true",
        help="exit non-zero if Workflows APIs reject the upsert",
    )
    wf.set_defaults(func=cmd_workflow)

    inc = sub.add_parser(
        "incident",
        help="facilitator backup: CLI RCA investigate / approve / email (not the customer close)",
    )
    inc.add_argument(
        "--auto",
        action="store_true",
        help="skip human approval (automatic remediation)",
    )
    inc.add_argument(
        "--email",
        default="oncall@elastic.co",
        help="incident summary recipient",
    )
    inc.add_argument(
        "--dry-run",
        action="store_true",
        help="investigate only — no approval, remediation, or email",
    )
    inc.add_argument(
        "--no-email",
        action="store_true",
        help="remediate but skip email notification",
    )
    inc.add_argument(
        "--no-case",
        action="store_true",
        help="skip opening/updating the Kibana Observability case",
    )
    inc.set_defaults(func=cmd_incident)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
