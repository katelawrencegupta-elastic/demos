"""CLI: setup | sample | backfill | stream | verify."""
import argparse
import json
import time
from datetime import timedelta

import requests

from src.config import ELASTIC_URL, ES_HEADERS, KBN_HEADERS, KIBANA_URL
from src.generators import select
from src.sink.elastic import BulkSink, es_search
from src.variant import active_variant, list_variants
from src.world.model import load_world
from src.world.scenarios import utcnow

# Fields that must exist after native integration pipeline parsing
PARSE_CHECKS = {
    "aws.cloudtrail": ["event.action", "cloud.account.id", "user.name"],
    "aws.guardduty": ["aws.guardduty.severity.value", "cloud.account.id"],
    "aws.s3access": ["aws.s3access.bucket", "http.response.status_code"],
    "gcp.audit": ["event.action", "cloud.project.id"],
    "azure.activitylogs": ["azure.activitylogs.operation_name", "azure.subscription_id"],
    "openai.completions": ["openai.base.model", "openai.completions.input_tokens"],
    "openai.embeddings": ["openai.base.model", "openai.embeddings.input_tokens"],
    "openai.images": ["openai.base.model", "openai.images.images", "openai.images.size"],
    "openai.audio_transcriptions": ["openai.base.model", "openai.audio_transcriptions.seconds"],
    "openai.audio_speeches": ["openai.base.model", "openai.audio_speeches.characters"],
    "openai.moderations": ["openai.base.model", "openai.moderations.input_tokens"],
    "openai.rate_limits": ["openai.rate_limits.model",
                           "openai.rate_limits.max_requests_per_1_minute"],
    "aws_bedrock.invocation": ["aws_bedrock.invocation.model_id",
                               "gen_ai.usage.prompt_tokens"],
    "azure_openai.logs": ["azure.open_ai.category", "azure.resource.id"],
    "gcp_vertexai.auditlogs": [
        "event.action",
        "gcp.vertexai.audit.service_name",
        "gcp.vertexai.audit.resource_name",
        "client.user.email",
    ],
}


def _scope_default():
    return active_variant().default_scope


def _print_variant():
    v = active_variant()
    print(f"== variant: {v.id} — {v.title} ==")


def _resolve_scope(args) -> str:
    return getattr(args, "scope", None) or _scope_default()


def _flatten(d, prefix=""):
    out = {}
    for k, v in d.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(_flatten(v, key + "."))
        else:
            out[key] = v
    return out


def _one_doc(gen, world, anchor):
    back = 1
    while back < 72:
        docs = list(gen.emit(world, anchor - timedelta(hours=back),
                             anchor - timedelta(hours=back - 1), anchor))
        if docs:
            return docs[0]
        back += 1
    return None


def cmd_sample(scope: str):
    world = load_world()
    anchor = utcnow()
    ok = True
    gens = [g for g in select(scope)
            if getattr(g, "DATA_STREAM", "").startswith("logs-")]
    for gen in gens:
        doc = _one_doc(gen, world, anchor)
        ds = gen.DATA_STREAM
        if doc is None:
            print(f"[skip] {ds}: no sample in window (ok if traffic is sparse)")
            continue
        dataset = ds.split("-")[1]  # logs-<dataset>-default

        if dataset in PARSE_CHECKS:
            r = requests.post(
                f"{ELASTIC_URL}/_ingest/_simulate",
                headers=ES_HEADERS, timeout=60,
                json={"docs": [{"_index": ds, "_id": "sample-1", "_source": doc}]})
            if r.status_code >= 300:
                print(f"[fail] {ds}: simulate {r.status_code} {r.text[:200]}")
                ok = False
                continue
            result = r.json()["docs"][0]["doc"]
            if "error" in result:
                print(f"[fail] {ds}: pipeline error {json.dumps(result['error'])[:300]}")
                ok = False
                continue
            flat = _flatten(result["_source"])
            missing = [f for f in PARSE_CHECKS[dataset] if f not in flat]
            if missing:
                print(f"[fail] {ds}: missing {missing}")
                # show related keys for debugging
                roots = {m.split(".")[0] for m in missing}
                print("       related:", sorted(k for k in flat if k.split(".")[0] in roots)[:20])
                ok = False
            else:
                shown = {f: flat[f] for f in PARSE_CHECKS[dataset]}
                print(f"[ok] {ds}: {shown}")
        else:
            r = requests.post(f"{ELASTIC_URL}/{ds}/_doc?refresh=wait_for",
                              headers=ES_HEADERS, json=doc, timeout=60)
            if r.status_code >= 300:
                print(f"[fail] {ds}: write {r.status_code} {r.text[:200]}")
                ok = False
            else:
                print(f"[ok] {ds}: live-write accepted")
    if not ok:
        raise SystemExit(1)


def cmd_backfill(days: int, scope: str):
    world = load_world()
    gens = select(scope)
    anchor = utcnow()
    start = anchor - timedelta(days=days)
    sink = BulkSink()
    print(f"backfilling {scope} {days} days: "
          f"{start:%Y-%m-%d %H:%M} -> {anchor:%Y-%m-%d %H:%M} UTC "
          f"({len(gens)} generators)")
    t0 = start
    n_hours = 0
    began = time.time()
    while t0 < anchor:
        t1 = min(t0 + timedelta(hours=1), anchor)
        for gen in gens:
            for doc in gen.emit(world, t0, t1, anchor):
                sink.add(gen.DATA_STREAM, doc)
        n_hours += 1
        if n_hours % 24 == 0:
            done = sum(sink.indexed.values())
            print(f"  day {n_hours // 24}/{days}: {done:,} docs indexed "
                  f"({time.time() - began:.0f}s elapsed)")
        t0 = t1
    indexed, failed, errors = sink.close()
    print("\n== backfill done ==")
    for idx in sorted(set(indexed) | set(failed)):
        line = f"  {idx}: {indexed.get(idx, 0):,} indexed"
        if failed.get(idx):
            line += f", {failed[idx]:,} FAILED  e.g. {errors.get(idx, '')}"
        print(line)
    if failed:
        raise SystemExit(1)


def cmd_stream(tick: int, scope: str):
    world = load_world()
    gens = select(scope)
    anchor = utcnow()
    last = anchor
    sink = BulkSink(batch_docs=500)
    print(f"streaming {scope} every {tick}s (ctrl-c to stop) ...")
    try:
        while True:
            time.sleep(tick)
            now = utcnow()
            n = 0
            for gen in gens:
                for doc in gen.emit(world, last, now, anchor):
                    sink.add(gen.DATA_STREAM, doc)
                    n += 1
            sink.flush()
            print(f"  {now:%H:%M:%S} +{n} docs "
                  f"(total {sum(sink.indexed.values()):,}, "
                  f"failed {sum(sink.failed.values()):,})")
            last = now
    except KeyboardInterrupt:
        sink.close()
        print("stopped.")


def cmd_verify(scope: str):
    from src.setup_cmd import CUR_ALIAS, INFERENCE_TOKEN_USAGE_DATA_VIEW_ID, INFERENCE_TOKEN_USAGE_INDEX
    from src.time_window import demo_window

    gens = select(scope)
    failed = False
    print("== per data stream: doc count, time range ==")
    total = 0
    for gen in gens:
        ds = gen.DATA_STREAM
        body = {
            "size": 0,
            "track_total_hits": True,
            "aggs": {"min_ts": {"min": {"field": "@timestamp"}},
                     "max_ts": {"max": {"field": "@timestamp"}}},
        }
        try:
            res = es_search(ds, body)
        except requests.HTTPError as e:
            print(f"  [fail] {ds}: {e}")
            failed = True
            continue
        count = res["hits"]["total"]["value"]
        total += count
        aggs = res["aggregations"]
        rng = (f"{aggs['min_ts'].get('value_as_string', '?')[:16]} .. "
               f"{aggs['max_ts'].get('value_as_string', '?')[:16]}")
        print(f"  {ds}: {count:,} docs  [{rng}]")
    print(f"  TOTAL: {total:,} docs")

    print("\n== scenario / integration spot-checks ==")
    win = demo_window()
    v = active_variant()
    if scope in ("all", "cloud"):
        if v.has_generator("aws_cloudtrail"):
            try:
                r = es_search("logs-aws.cloudtrail-default", {
                    "size": 0, "track_total_hits": True})
                n = r["hits"]["total"]["value"]
                print(f"  CloudTrail events: {n:,}")
                if n < 1:
                    print("  [fail] CloudTrail stream empty")
                    failed = True
            except requests.HTTPError as e:
                print(f"  CloudTrail: FAIL {e}")
                failed = True

        if v.has_generator("aws_billing_cur"):
            r = requests.get(f"{ELASTIC_URL}/_alias/{CUR_ALIAS}",
                             headers=ES_HEADERS, timeout=30)
            if r.status_code == 200:
                print(f"  CUR alias {CUR_ALIAS}: ok")
            else:
                print(f"  [fail] CUR alias {CUR_ALIAS}: {r.status_code}")
                failed = True

        if v.has_generator("ess_billing_credits"):
            try:
                r = requests.post(f"{ELASTIC_URL}/_query", headers=ES_HEADERS, timeout=30, json={
                    "query": (
                        "FROM metrics-ess_billing.credits-*\n"
                        "| WHERE ess.billing.active == true\n"
                        "| INLINE STATS latest = MAX(@timestamp)\n"
                        "| WHERE @timestamp == latest\n"
                        "| STATS current_balance = SUM(ess.billing.ecu_balance)"
                    ),
                })
                r.raise_for_status()
                rows = r.json().get("values") or []
                balance = rows[0][0] if rows and rows[0] else None
                print(f"  ESS billing credits balance: {balance}")
                if balance is None or balance <= 0:
                    print("  [fail] credits dashboard needs active ECU balance docs "
                          "(run: python -m src.cli backfill --scope ess-billing)")
                    failed = True
            except requests.HTTPError as e:
                print(f"  ESS billing credits: FAIL {e}")
                failed = True

        if v.has_generator("aws_guardduty"):
            try:
                r = es_search("logs-aws.guardduty-default", {
                    "size": 0, "track_total_hits": True,
                    "query": {"prefix": {"rule.name": "CryptoCurrency"}}})
                n = r["hits"]["total"]["value"]
                print(f"  GuardDuty crypto findings: {n}")
                if n < 1:
                    print("  [fail] expected crypto findings")
                    failed = True
            except requests.HTTPError as e:
                print(f"  GuardDuty crypto: FAIL {e}")
                failed = True

            try:
                r = es_search("logs-aws.guardduty-default", {
                    "size": 0, "track_total_hits": True,
                    "query": {"prefix": {"rule.name": "Policy:S3"}}})
                n = r["hits"]["total"]["value"]
                print(f"  GuardDuty S3 policy findings: {n}")
                if n < 1:
                    print("  [fail] expected S3 exposure findings")
                    failed = True
            except requests.HTTPError as e:
                print(f"  GuardDuty S3: FAIL {e}")
                failed = True

    if scope in ("all", "llm", "openai-extra"):
        allowed = {g.DATA_STREAM for g in select(scope)}
        checks = [
            ("logs-openai.completions-default", "OpenAI completions"),
            ("logs-openai.embeddings-default", "OpenAI embeddings"),
            ("logs-openai.images-default", "OpenAI images"),
            ("logs-openai.audio_transcriptions-default", "OpenAI transcriptions"),
            ("logs-openai.audio_speeches-default", "OpenAI speeches"),
            ("logs-openai.moderations-default", "OpenAI moderations"),
            ("logs-openai.rate_limits-default", "OpenAI rate limits"),
            ("metrics-anthropic_metrics.usage-default", "Anthropic usage"),
            ("metrics-anthropic_metrics.cost-default", "Anthropic cost"),
            ("metrics-anthropic_metrics.rate_limit-default", "Anthropic rate limits"),
            ("logs-aws_bedrock.invocation-default", "Bedrock invocations"),
            ("metrics-aws_bedrock.runtime-default", "Bedrock runtime"),
            ("metrics-aws_bedrock.guardrails-default", "Bedrock guardrails"),
            ("logs-azure_openai.logs-default", "Azure OpenAI logs"),
            ("metrics-azure.open_ai-default", "Azure OpenAI metrics"),
            ("metrics-azure.billing-default", "Azure billing (incl. OpenAI)"),
            ("logs-gcp_vertexai.prompt_response_logs-default", "Vertex prompt logs"),
            ("metrics-gcp_vertexai.metrics-default", "Vertex metrics"),
            ("logs-gcp_vertexai.auditlogs-default", "Vertex audit logs"),
            ("traces-apm-default", "APM traces"),
        ]
        for ds, label in checks:
            if ds not in allowed:
                continue
            try:
                r = es_search(ds, {"size": 0, "track_total_hits": True})
                print(f"  {label}: {r['hits']['total']['value']:,}")
            except requests.HTTPError as e:
                print(f"  {label}: FAIL {e}")
                failed = True

        # APM ES|QL columns required by FinOps LLM cost panels
        print("\n== APM gen_ai ES|QL columns ==")
        need = ("span.subtype", "gen_ai.usage.total_tokens", "labels.llm_cost_usd")
        r = requests.post(
            f"{ELASTIC_URL}/traces-apm-default/_field_caps",
            headers=ES_HEADERS, timeout=60,
            json={"fields": list(need)},
        )
        if r.status_code >= 300:
            print(f"  [fail] field_caps: {r.status_code} {r.text[:200]}")
            failed = True
        else:
            fields = r.json().get("fields") or {}
            for f in need:
                if f in fields:
                    print(f"  [ok] {f}")
                else:
                    print(f"  [fail] missing column {f}")
                    failed = True

        q = (
            f'FROM traces-apm-default\n'
            f'| WHERE @timestamp >= "{win["from"]}" AND @timestamp <= "{win["to"]}" '
            f'AND span.subtype == "gen_ai"\n'
            f'| STATS calls = COUNT(*)'
        )
        r = requests.post(f"{ELASTIC_URL}/_query", headers=ES_HEADERS,
                          timeout=60, json={"query": q})
        if r.status_code >= 300:
            print(f"  [fail] ES|QL gen_ai probe: {r.status_code} {r.text[:300]}")
            failed = True
        else:
            vals = (r.json().get("values") or [[None]])[0]
            calls = vals[0] if vals else None
            print(f"  gen_ai spans in demo window: {calls}")
            if not calls:
                print("  [fail] no gen_ai spans in demo window")
                failed = True

        try:
            r = es_search("logs-openai.completions-default", {
                "size": 0, "track_total_hits": True,
                "aggs": {"models": {"terms": {"field": "openai.base.model", "size": 8}}}})
            models = {b["key"]: b["doc_count"]
                      for b in r["aggregations"]["models"]["buckets"]}
            print(f"  OpenAI models: {models}")
        except requests.HTTPError:
            pass

        try:
            r = es_search("metrics-anthropic_metrics.cost-default", {
                "size": 0, "track_total_hits": True,
                "aggs": {"spend_cents": {"sum": {"field": "anthropic.cost.amount"}}}})
            print(f"  Anthropic spend (cents): {r['aggregations']['spend_cents']['value']:.0f}")
        except requests.HTTPError:
            pass

        try:
            r = es_search("metrics-azure.billing-default", {
                "size": 0, "track_total_hits": True,
                "query": {"term": {"azure.resource.type": "Microsoft.CognitiveServices"}},
                "aggs": {
                    "cost": {"sum": {"field": "azure.billing.pretax_cost"}},
                    "products": {"terms": {"field": "azure.billing.product", "size": 8}},
                }})
            products = {b["key"]: b["doc_count"]
                        for b in r["aggregations"]["products"]["buckets"]}
            print(f"  Azure OpenAI billing docs: {r['hits']['total']['value']:,}  "
                  f"cost=${r['aggregations']['cost']['value']:.2f}  products={products}")
        except requests.HTTPError:
            pass

        try:
            r = es_search("metrics-azure.open_ai-default", {
                "size": 0, "track_total_hits": True,
                "query": {"exists": {
                    "field": "azure.open_ai.provisioned_managed_utilization_v2.avg"}},
                "aggs": {"models": {"terms": {
                    "field": "azure.dimensions.model_name", "size": 8}}}})
            models = {b["key"]: b["doc_count"]
                      for b in r["aggregations"]["models"]["buckets"]}
            print(f"  Azure OpenAI PTU docs: {r['hits']['total']['value']:,}  "
                  f"models={models}")
        except requests.HTTPError:
            pass

        try:
            r = es_search("logs-azure_openai.logs-default", {
                "size": 0, "track_total_hits": True,
                "query": {"bool": {"should": [
                    {"term": {"azure.open_ai.properties.backend_response_body.choices.finish_reason":
                              "content_filter"}},
                    {"term": {"azure.open_ai.properties.backend_response_body.error.code":
                              "content_filter"}},
                ], "minimum_should_match": 1}},
                "aggs": {
                    "resp": {"terms": {"field": "azure.open_ai.properties.backend_response_body.content_filtered_categories.category_name", "size": 8}},
                    "prompt": {"terms": {"field": "azure.open_ai.properties.backend_response_body.error.innererror.content_filtered_categories.category_name", "size": 8}},
                }})
            print(f"  Azure OpenAI content-filter logs: {r['hits']['total']['value']:,}  "
                  f"response={ {b['key']: b['doc_count'] for b in r['aggregations']['resp']['buckets']} }  "
                  f"prompt={ {b['key']: b['doc_count'] for b in r['aggregations']['prompt']['buckets']} }")
        except requests.HTTPError:
            pass

    if scope in ("all", "elastic-ai") and v.has_generator("agent_builder_traces"):
        try:
            r = es_search("traces-agent_builder.otel-default", {
                "size": 0, "track_total_hits": True,
                "aggs": {
                    "kinds": {"terms": {"field": "attributes.elastic.inference.span.kind", "size": 8}},
                    "agents": {"terms": {"field": "attributes.gen_ai.agent.id", "size": 8}},
                }})
            kinds = {b["key"]: b["doc_count"]
                     for b in r["aggregations"]["kinds"]["buckets"]}
            agents = {b["key"]: b["doc_count"]
                      for b in r["aggregations"]["agents"]["buckets"]}
            total = r["hits"]["total"]["value"]
            print(f"  Agent Builder traces: {total:,}  "
                  f"kinds={kinds}  agents={agents}")
            from src.elastic_ai_reindex import verify_finops_agent_traces
            if not verify_finops_agent_traces(agents, total):
                failed = True
        except requests.HTTPError as e:
            print(f"  Agent Builder traces: FAIL {e}")
            failed = True
        try:
            r = es_search("logs-elastic.inference_token_usage-default", {
                "size": 0, "track_total_hits": True,
                "aggs": {
                    "features": {"terms": {"field": "inference.feature_name", "size": 8}},
                    "cost": {"sum": {"field": "labels.cost_usd"}},
                }})
            features = {b["key"]: b["doc_count"]
                        for b in r["aggregations"]["features"]["buckets"]}
            print(f"  Inference token usage: {r['hits']['total']['value']:,}  "
                  f"cost=${r['aggregations']['cost']['value']:.2f}  features={features}")
        except requests.HTTPError as e:
            print(f"  Inference token usage: FAIL {e}")
            failed = True

        r = requests.get(
            f"{KIBANA_URL}/api/data_views/data_view/{INFERENCE_TOKEN_USAGE_DATA_VIEW_ID}",
            headers=KBN_HEADERS, timeout=30)
        if r.status_code != 200:
            print(f"  [fail] inference data view: {r.status_code}")
            failed = True
        else:
            title = r.json()["data_view"].get("title")
            if title == INFERENCE_TOKEN_USAGE_INDEX:
                print(f"  [ok] inference data view -> {title}")
            else:
                print(f"  [fail] inference data view title={title!r} "
                      f"(expected {INFERENCE_TOKEN_USAGE_INDEX})")
                failed = True

    print()
    from src.budgets import verify_budgets
    if v.setup_enabled("budgets"):
        if not verify_budgets():
            failed = True
    else:
        print("  [skip] budgets (not enabled for this variant)")

    print()
    from src.agent_builder import verify_agent
    if v.setup_enabled("agent"):
        if not verify_agent():
            failed = True
    else:
        print("  [skip] agent (not enabled for this variant)")

    print("\n== kibana ==")
    print(f"  Discover:   {KIBANA_URL}/app/discover")
    print(f"  Dashboards: {KIBANA_URL}/app/dashboards")
    print("  Search: OpenAI, Anthropic, Bedrock, Azure OpenAI, Vertex AI, APM")
    print("  Note: log PARSE_CHECKS live in `sample`; metrics/APM use verify probes above.")
    if failed:
        raise SystemExit(1)


def main():
    p = argparse.ArgumentParser(
        prog="synthcloud",
        description="Multi-cloud + LLM synthetic data factory for Elastic")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("setup", help="install integrations, APM mappings, patch TSDS, check access")
    s_sample = sub.add_parser("sample", help="validate one doc per log generator")
    s_sample.add_argument(
        "--scope",
        choices=["all", "cloud", "llm", "openai-extra", "elastic-ai", "ess-billing"],
        default=None,
        help="generator scope (default: active variant)",
    )
    b = sub.add_parser("backfill", help="bulk-index historical data")
    b.add_argument("--days", type=int, default=120)
    b.add_argument(
        "--scope",
        choices=["all", "cloud", "llm", "openai-extra", "elastic-ai", "ess-billing"],
        default=None,
        help="generator scope (default: active variant)",
    )
    s = sub.add_parser("stream", help="continuously emit live events")
    s.add_argument("--tick", type=int, default=60)
    s.add_argument(
        "--scope",
        choices=["all", "cloud", "llm", "openai-extra", "elastic-ai", "ess-billing"],
        default=None,
        help="generator scope (default: active variant)",
    )
    v = sub.add_parser("verify", help="doc counts and scenario spot checks")
    v.add_argument(
        "--scope",
        choices=["all", "cloud", "llm", "openai-extra", "elastic-ai", "ess-billing"],
        default=None,
        help="generator scope (default: active variant)",
    )
    d = sub.add_parser("dashboards", help="publish FinOps + LLM Kibana dashboards")
    d.add_argument(
        "--variant",
        choices=["baseline", "dynamic", "classic", "original", "ai-assistant", "all"],
        default="baseline",
        help="baseline=primary FinOps (default); dynamic=alias of baseline; "
             "classic/original=legacy layout; all=baseline+classic+AI",
    )
    sub.add_parser(
        "budgets",
        help="provision FinOps spend SLOs + ES|QL budget alert rules",
    )
    sub.add_parser(
        "recover-slos",
        help="reset all Meridian spend SLOs (recreate transforms + reprocess SLI)",
    )
    sub.add_parser(
        "agent",
        help="provision Meridian FinOps AI Assistant (Agent Builder + ES|QL tools)",
    )
    ri = sub.add_parser(
        "reindex-elastic-ai",
        help="wipe synthetic Agent Builder + inference usage docs, re-backfill elastic-ai",
    )
    ri.add_argument("--days", type=int, default=120)
    ri.add_argument(
        "--all",
        action="store_true",
        help="delete all docs in elastic-ai streams (default: synthetic / non-custom traces)",
    )
    sub.add_parser("backup", help="snapshot Kibana/Fleet/ES objects into ./elastic")
    sub.add_parser("variants", help="list workshop fork profiles")
    args = p.parse_args()

    if args.cmd == "setup":
        from src import setup_cmd
        setup_cmd.run()
    elif args.cmd == "sample":
        _print_variant()
        cmd_sample(_resolve_scope(args))
    elif args.cmd == "backfill":
        _print_variant()
        cmd_backfill(args.days, _resolve_scope(args))
    elif args.cmd == "stream":
        _print_variant()
        cmd_stream(args.tick, _resolve_scope(args))
    elif args.cmd == "verify":
        _print_variant()
        cmd_verify(_resolve_scope(args))
    elif args.cmd == "dashboards":
        from src.dashboards import publish
        _print_variant()
        layout = args.variant
        publish(
            include_baseline=layout in ("baseline", "dynamic", "all"),
            include_classic=layout in ("classic", "original", "all"),
            include_dynamic_alias=layout in ("baseline", "dynamic", "all"),
            include_ai=layout in ("ai-assistant", "baseline", "dynamic", "all"),
        )
    elif args.cmd == "budgets":
        from src.budgets import ensure_budgets
        ensure_budgets(fail_loud=True)
    elif args.cmd == "recover-slos":
        from src.budgets import recover_slos
        recover_slos(fail_loud=True)
    elif args.cmd == "agent":
        from src.agent_builder import ensure_agent
        ensure_agent(fail_loud=True)
    elif args.cmd == "reindex-elastic-ai":
        from src.elastic_ai_reindex import reindex_elastic_ai
        reindex_elastic_ai(args.days, all_docs=args.all)
    elif args.cmd == "backup":
        from src.backup import run as backup_run
        backup_run()
    elif args.cmd == "variants":
        for vid, title, fork_dir in list_variants():
            mark = " (active)" if vid == active_variant().id else ""
            print(f"  {vid:14}  {fork_dir}{mark}")
            print(f"                 {title}")


if __name__ == "__main__":
    main()
