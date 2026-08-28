"""CLI: setup | sample | backfill | stream | verify | dashboards."""
from __future__ import annotations

import argparse
import json
import time
from datetime import timedelta

import requests

from src.config import (
    DS_APM_INTERNAL,
    DS_CHECKOUT,
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


def cmd_stream(args: argparse.Namespace):
    world = load_world()
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


def verify_alert_rules() -> bool:
    """Assert demo alert rules exist, are enabled, and quality rules have Cases actions."""
    rules_file = KIBANA_DIR / "alert-rules.json"
    if not rules_file.exists():
        print("[fail] kibana/alert-rules.json missing")
        return False

    expected = json.loads(rules_file.read_text())
    rules_with_cases = {"elasticco-checkout-slo-burn", "elasticco-eks-pod-restarts"}
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

    if getattr(args, "alerts", False):
        print("== alert rules ==")
        if not verify_alert_rules():
            ok = False

    print(f"Kibana: {KIBANA_URL}")
    if not ok:
        raise SystemExit(1)


def cmd_incident(args: argparse.Namespace):
    """U5: RCA agent — investigate, approve, remediate, email summary."""
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
    from src.setup_cmd import ensure_alert_rules, ensure_data_views, import_saved_objects, publish_dashboard

    ensure_data_views()
    import_saved_objects()
    publish_dashboard()
    ensure_alert_rules()
    print("Deep links:")
    print(f"  Discover orchestrator: {KIBANA_URL}/app/discover#/?_a=(dataSource:(dataViewId:elasticco-orchestrator))")
    print(f"  APM services:          {KIBANA_URL}/app/apm/services")
    print(f"  Alerts:                {KIBANA_URL}/app/observability/alerts")
    print(f"  Cases:                 {KIBANA_URL}/app/observability/cases")
    print(f"  AI Assistant:          {KIBANA_URL}/app/observabilityAIAssistant")
    print(f"  Dashboard (incident):  {KIBANA_URL}/app/dashboards#/view/elasticco-incident-overview")
    print(f"  Dashboard (eks):       {KIBANA_URL}/app/dashboards#/view/elasticco-eks-restarts")
    print(f"  Dashboard (traces):    {KIBANA_URL}/app/dashboards#/view/elasticco-distributed-traces")
    print(f"  Dashboard (e2e):       {KIBANA_URL}/app/dashboards#/view/elasticco-e2e-tracing")
    print(f"  Incidents (audit):     {KIBANA_URL}/app/discover#/?_a=(dataSource:(dataViewId:elasticco-incidents))")


def main():
    p = argparse.ArgumentParser(description="Elastic Co. observability demo")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("setup", help="pipelines, templates, data views, alerts").set_defaults(
        func=cmd_setup
    )

    s = sub.add_parser("sample", help="simulate/pipeline-check one doc per generator")
    s.add_argument(
        "--scope",
        default="all",
        choices=["all", "orchestrator", "apm", "apm_deps", "traces", "k8s", "infra"],
    )
    s.set_defaults(func=cmd_sample)

    b = sub.add_parser("backfill", help="plant incident history")
    b.add_argument("--hours", type=int, default=6)
    b.add_argument(
        "--scope",
        default="all",
        choices=["all", "orchestrator", "apm", "apm_deps", "traces", "k8s", "infra"],
    )
    b.set_defaults(func=cmd_backfill)

    st = sub.add_parser("stream", help="live tick for demos")
    st.add_argument("--tick", type=int, default=60)
    st.add_argument(
        "--scope",
        default="all",
        choices=["all", "orchestrator", "apm", "apm_deps", "traces", "k8s", "infra"],
    )
    st.set_defaults(func=cmd_stream)

    v = sub.add_parser("verify", help="assert correlation + field presence")
    v.add_argument(
        "--alerts",
        action="store_true",
        help="also verify Kibana alert rules exist and Cases actions are attached",
    )
    v.set_defaults(func=cmd_verify)
    sub.add_parser("dashboards", help="import Kibana assets + print links").set_defaults(
        func=cmd_dashboards
    )

    inc = sub.add_parser(
        "incident",
        help="U5 RCA agent: investigate, approve remediation, email summary",
    )
    inc.add_argument(
        "--auto",
        action="store_true",
        help="skip human approval (automatic remediation)",
    )
    inc.add_argument(
        "--email",
        default="kate.lawrencegupta@elastic.co",
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
