"""Azure OpenAI -> logs-azure_openai.logs + metrics-azure.open_ai
+ Cognitive Services usage details on metrics-azure.billing (OOTB Billing dashboard)."""
import json
from collections import defaultdict
from datetime import timedelta

from src.generators.azure_billing import _base
from src.generators.common import aligned, iso, log_doc, metric_doc
from src.world.llm_traffic import iter_events
from src.world.model import stable_uuid

SCOPE = "llm"
SAMPLE = 0.4
AOAI_ACCOUNT = "meridian-aoai"
AOAI_RG = "rg-corp-shared-svcs"
# OOTB [Azure OpenAI] Billing filters match_phrase on this exact keyword.
AOAI_RESOURCE_TYPE = "Microsoft.CognitiveServices"


def _aoai_sub(world):
    return next(s for s in world.cfg["azure"]["subscriptions"]
                if s["name"] == "meridian-corp-prod")


def _aoai_resource_id(sub):
    return (f"/subscriptions/{sub['id']}/resourceGroups/{AOAI_RG}"
            f"/providers/Microsoft.CognitiveServices/accounts/{AOAI_ACCOUNT}")


CF_CATEGORIES = ("hate", "sexual", "violence", "self_harm")


def _filter_hits(rng):
    """Azure content-filter result map for the four standard categories."""
    hits = {c: {"filtered": False, "severity": "safe"} for c in CF_CATEGORIES}
    primary = rng.choices(list(CF_CATEGORIES), weights=[35, 20, 25, 20])[0]
    hits[primary] = {
        "filtered": True,
        "severity": rng.choices(["low", "medium", "high"], weights=[50, 35, 15])[0],
    }
    if rng.random() < 0.12:
        other = rng.choice([c for c in CF_CATEGORIES if c != primary])
        hits[other] = {
            "filtered": True,
            "severity": rng.choice(["low", "medium"]),
        }
    return hits


def _log_outcome(rng, ev):
    """ok | response_filter | prompt_filter | 429.

    Independent of ev.ok so the content-filtering dashboard has enough
    prompt-block (error.code) and completion-block (finish_reason) volume.
    """
    roll = rng.random()
    if roll < 0.05:
        return "prompt_filter"
    if roll < 0.13:
        return "response_filter"
    if not ev.ok:
        return "429"
    return "ok"


class _AzureOpenAILogs:
    DATA_STREAM = "logs-azure_openai.logs-default"
    DATASET = "azure_openai.logs"

    def emit(self, world, t0, t1, anchor, content_filter_only=False):
        from src.world.scenarios import rng_for
        rng = rng_for("azopenai", t0.isoformat())
        sub = _aoai_sub(world)
        resource_id = _aoai_resource_id(sub)
        for ev in iter_events(world, t0, t1, anchor):
            if ev.model["provider"] != "azure_openai":
                continue
            if not content_filter_only and rng.random() > SAMPLE:
                continue
            outcome = _log_outcome(rng, ev)
            if content_filter_only and outcome not in ("prompt_filter", "response_filter"):
                continue
            deployment = ev.model.get("deployment", ev.model["id"])
            req_body = json.dumps({
                "model": ev.model["id"],
                "stream": False,
                "messages": [{"role": "user", "content": f"[{ev.app['id']}]"}],
            })
            success = True
            if outcome == "prompt_filter":
                hits = _filter_hits(rng)
                if rng.random() < 0.22:
                    hits["custom_blocklists"] = {
                        "filtered": True,
                        "id": rng.choice([
                            "meridian-blocklist-pii",
                            "meridian-blocklist-competitors",
                            "meridian-blocklist-secrets",
                        ]),
                    }
                success = False
                result_type, result_sig = "Failure", "400"
                resp_body = json.dumps({
                    "error": {
                        "message": ("The response was filtered due to the prompt "
                                    "triggering Azure OpenAI's content management policy."),
                        "type": None,
                        "param": "prompt",
                        "code": "content_filter",
                        "status": 400,
                        "innererror": {
                            "code": "ResponsibleAIPolicyViolation",
                            "content_filter_result": hits,
                        },
                    }
                })
                completion = 0
            elif outcome == "response_filter":
                hits = _filter_hits(rng)
                result_type, result_sig = "Success", "200"
                completion = max(8, ev.output_tokens // 4)
                resp_body = json.dumps({
                    "id": f"chatcmpl-{ev.request_id[:12]}",
                    "choices": [{
                        "finish_reason": "content_filter",
                        "index": 0,
                        "message": {"role": "assistant", "content": None},
                        "content_filter_results": hits,
                    }],
                    "usage": {
                        "prompt_tokens": ev.input_tokens,
                        "completion_tokens": completion,
                        "total_tokens": ev.input_tokens + completion,
                    },
                })
            elif outcome == "429":
                success = False
                result_type, result_sig = "Failure", "429"
                completion = 0
                resp_body = json.dumps({
                    "error": {
                        "code": "429",
                        "message": "Rate limit reached for provisioned deployment.",
                    }
                })
            else:
                result_type, result_sig = "Success", "200"
                completion = ev.output_tokens
                resp_body = json.dumps({
                    "id": f"chatcmpl-{ev.request_id[:12]}",
                    "choices": [{
                        "finish_reason": "stop",
                        "index": 0,
                        "message": {"role": "assistant", "content": "..."},
                    }],
                    "usage": {
                        "prompt_tokens": ev.input_tokens,
                        "completion_tokens": completion,
                        "total_tokens": ev.input_tokens + completion,
                    },
                })
            raw = {
                "time": iso(ev.ts),
                "resourceId": resource_id,
                "operationName": "ChatCompletions_Create",
                "category": "RequestResponse",
                "resultType": result_type,
                "resultSignature": result_sig,
                "isRequestSuccess": success,
                "durationMs": ev.latency_ms,
                "callerIpAddress": "203.0.113.40",
                "correlationId": ev.request_id,
                "identity": {"claims": {"upn": ev.actor_email}},
                "level": "Information",
                "location": world.cfg["azure"]["region"],
                "properties": {
                    "apiName": "Azure OpenAI API",
                    "requestId": ev.request_id,
                    "objectId": stable_uuid("azoid", ev.actor_user),
                    "modelDeploymentName": deployment,
                    "modelName": ev.model["id"],
                    "modelVersion": "2024-08-01",
                    "streamType": "Blocking",
                    "backendRequestBody": req_body,
                    "backendResponseBody": resp_body,
                    "totalTokens": ev.input_tokens + completion,
                    "promptTokens": ev.input_tokens,
                    "completionTokens": completion,
                },
            }
            yield log_doc(self.DATASET, ev.ts, json.dumps(raw))


class _AzureOpenAIMetrics:
    DATA_STREAM = "metrics-azure.open_ai-default"
    DATASET = "azure.open_ai"

    def emit(self, world, t0, t1, anchor):
        buckets = defaultdict(lambda: {
            "requests": 0, "prompt": 0, "generated": 0, "cached": 0,
            "latency_sum": 0, "errors": 0,
        })
        for ev in iter_events(world, t0, t1, anchor):
            if ev.model["provider"] != "azure_openai":
                continue
            mark = int(ev.ts.timestamp() // 300) * 300
            key = (mark, ev.model.get("deployment", ev.model["id"]), ev.model["id"])
            b = buckets[key]
            b["requests"] += 1
            b["prompt"] += ev.input_tokens
            b["generated"] += ev.output_tokens
            b["cached"] += ev.cached_input_tokens
            b["latency_sum"] += ev.latency_ms
            if not ev.ok:
                b["errors"] += 1

        from datetime import datetime, timezone
        sub = _aoai_sub(world)
        resource_id = _aoai_resource_id(sub)
        region = world.cfg["azure"]["region"]
        for (mark, deployment, model_id), b in buckets.items():
            ts = datetime.fromtimestamp(mark, tz=timezone.utc)
            active = max(0, b["prompt"] + b["generated"] - b["cached"])
            cache_pct = 100.0 * b["cached"] / max(1, b["prompt"])
            # PTU dashboard formulas divide by 100 then format as percent.
            ptu_base = 68.0 if "gpt-5.4" in model_id else 36.0
            ptu_pct = min(97.0, ptu_base + active / 4000.0)
            doc = metric_doc(self.DATASET, ts, "monitor", 300_000)
            doc["cloud"] = {"provider": "azure", "region": region}
            doc["azure"] = {
                "subscription_id": sub["id"],
                "resource": {
                    "id": resource_id,
                    "name": AOAI_ACCOUNT,
                    "type": "Microsoft.CognitiveServices/accounts",
                    "group": AOAI_RG,
                },
                "namespace": "Microsoft.CognitiveServices/accounts",
                "timegrain": "PT5M",
                "dimensions": {
                    "model_name": model_id,
                    "model_deployment_name": deployment,
                    "model_version": "2024-08-01",
                    "region": "East US",
                },
                "open_ai": {
                    "requests": {"total": b["requests"]},
                    "processed_prompt_tokens": {"total": b["prompt"]},
                    "generated_tokens": {"total": b["generated"]},
                    "token_transaction": {"total": b["prompt"] + b["generated"]},
                    "active_tokens": {"total": active},
                    "time_to_response": {
                        "avg": b["latency_sum"] / max(1, b["requests"])},
                    "context_tokens_cache_match_rate": {"avg": round(cache_pct, 2)},
                    "provisioned_managed_utilization_v2": {"avg": round(ptu_pct, 2)},
                },
            }
            doc["tags"] = ["synthetic", "azure_openai"]
            yield doc


class _AzureOpenAIBilling:
    """Daily Azure Cost Management usage details for the AOAI account.

    The OOTB [Azure OpenAI] Billing dashboard reads metrics-azure.billing with
    azure.resource.type = Microsoft.CognitiveServices and sums
    azure.billing.pretax_cost, split by azure.billing.product (model meter).
    """
    DATA_STREAM = "metrics-azure.billing-default"
    DATASET = "azure.billing"

    def emit(self, world, t0, t1, anchor):
        sub = _aoai_sub(world)
        resource_id = _aoai_resource_id(sub)
        for ts in aligned(t0, t1, 24 * 60):
            day = ts - timedelta(days=1)
            day_end = ts
            by_meter = defaultdict(float)
            hour = day
            while hour < day_end:
                nxt = min(hour + timedelta(hours=1), day_end)
                for ev in iter_events(world, hour, nxt, anchor):
                    if ev.model["provider"] != "azure_openai":
                        continue
                    model_id = ev.model["id"]
                    billable_in = max(0, ev.input_tokens - ev.cached_input_tokens)
                    by_meter[f"Azure OpenAI - {model_id} Input Tokens"] += (
                        billable_in / 1_000_000.0 * ev.model["input_per_m"])
                    if ev.cached_input_tokens:
                        by_meter[f"Azure OpenAI - {model_id} Cached Input Tokens"] += (
                            ev.cached_input_tokens / 1_000_000.0
                            * ev.model["cached_input_per_m"])
                    if ev.output_tokens:
                        by_meter[f"Azure OpenAI - {model_id} Output Tokens"] += (
                            ev.output_tokens / 1_000_000.0 * ev.model["output_per_m"])
                hour = nxt

            for product, cost in by_meter.items():
                cost = round(cost, 4)
                if cost <= 0:
                    continue
                doc = _base(world, ts, sub, day, cost)
                doc["azure"]["subscription_name"] = sub["name"]
                doc["azure"]["billing"]["product"] = product
                doc["azure"]["resource"] = {
                    "id": resource_id,
                    "name": AOAI_ACCOUNT,
                    "type": AOAI_RESOURCE_TYPE,
                    "group": AOAI_RG,
                    "tags": {
                        "app": "doc-summarizer",
                        "cost_center": "CC-3300",
                        "team": "corpit",
                        "env": "prod",
                    },
                }
                doc["tags"] = ["synthetic", "azure_openai"]
                yield doc


azure_openai_logs = _AzureOpenAILogs()
azure_openai_metrics = _AzureOpenAIMetrics()
azure_openai_billing = _AzureOpenAIBilling()
