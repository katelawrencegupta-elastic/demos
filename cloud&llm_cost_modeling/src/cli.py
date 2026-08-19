"""CLI: setup | sample | backfill | stream | verify."""
import argparse
import json
import time
from datetime import timedelta

import requests

from src.config import ELASTIC_URL, ES_HEADERS, KIBANA_URL
from src.generators import select
from src.sink.elastic import BulkSink, es_search
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
}


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
    gens = select(scope)
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
            continue
        count = res["hits"]["total"]["value"]
        total += count
        aggs = res["aggregations"]
        rng = (f"{aggs['min_ts'].get('value_as_string', '?')[:16]} .. "
               f"{aggs['max_ts'].get('value_as_string', '?')[:16]}")
        print(f"  {ds}: {count:,} docs  [{rng}]")
    print(f"  TOTAL: {total:,} docs")

    print("\n== scenario / integration spot-checks ==")
    if scope in ("all", "cloud"):
        try:
            r = es_search("logs-aws.guardduty-default", {
                "size": 0, "track_total_hits": True,
                "query": {"prefix": {"rule.name": "CryptoCurrency"}}})
            print(f"  GuardDuty crypto findings: {r['hits']['total']['value']}")
        except requests.HTTPError:
            pass

    if scope in ("all", "llm", "openai-extra"):
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
            ("logs-aws_bedrock.invocation-default", "Bedrock invocations"),
            ("metrics-aws_bedrock.runtime-default", "Bedrock runtime"),
            ("logs-azure_openai.logs-default", "Azure OpenAI logs"),
            ("metrics-azure.open_ai-default", "Azure OpenAI metrics"),
            ("metrics-azure.billing-default", "Azure billing (incl. OpenAI)"),
            ("logs-gcp_vertexai.prompt_response_logs-default", "Vertex prompt logs"),
            ("metrics-gcp_vertexai.metrics-default", "Vertex metrics"),
            ("traces-apm-default", "APM traces"),
        ]
        for ds, label in checks:
            try:
                r = es_search(ds, {"size": 0, "track_total_hits": True})
                print(f"  {label}: {r['hits']['total']['value']:,}")
            except requests.HTTPError as e:
                print(f"  {label}: FAIL {e}")

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

    print("\n== kibana ==")
    print(f"  Discover:   {KIBANA_URL}/app/discover")
    print(f"  Dashboards: {KIBANA_URL}/app/dashboards")
    print("  Search: OpenAI, Anthropic, Bedrock, Azure OpenAI, Vertex AI, APM")


def main():
    p = argparse.ArgumentParser(
        prog="synthcloud",
        description="Multi-cloud + LLM synthetic data factory for Elastic")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("setup", help="install integrations, patch TSDS, check access")
    s_sample = sub.add_parser("sample", help="validate one doc per log generator")
    s_sample.add_argument(
        "--scope", choices=["all", "cloud", "llm", "openai-extra"], default="all")
    b = sub.add_parser("backfill", help="bulk-index historical data")
    b.add_argument("--days", type=int, default=30)
    b.add_argument(
        "--scope", choices=["all", "cloud", "llm", "openai-extra"], default="all")
    s = sub.add_parser("stream", help="continuously emit live events")
    s.add_argument("--tick", type=int, default=60)
    s.add_argument(
        "--scope", choices=["all", "cloud", "llm", "openai-extra"], default="all")
    v = sub.add_parser("verify", help="doc counts and scenario spot checks")
    v.add_argument(
        "--scope", choices=["all", "cloud", "llm", "openai-extra"], default="all")
    d = sub.add_parser("dashboards", help="publish FinOps + LLM Kibana dashboards")
    d.add_argument("--variant", choices=["original", "dynamic", "all"], default="dynamic")
    sub.add_parser("backup", help="snapshot Kibana/Fleet/ES objects into ./elastic")
    args = p.parse_args()

    if args.cmd == "setup":
        from src import setup_cmd
        setup_cmd.run()
    elif args.cmd == "sample":
        cmd_sample(args.scope)
    elif args.cmd == "backfill":
        cmd_backfill(args.days, args.scope)
    elif args.cmd == "stream":
        cmd_stream(args.tick, args.scope)
    elif args.cmd == "verify":
        cmd_verify(args.scope)
    elif args.cmd == "dashboards":
        from src.dashboards import publish
        publish(
            include_original=args.variant in ("original", "all"),
            include_dynamic=args.variant in ("dynamic", "all"),
        )
    elif args.cmd == "backup":
        from src.backup import run as backup_run
        backup_run()


if __name__ == "__main__":
    main()
