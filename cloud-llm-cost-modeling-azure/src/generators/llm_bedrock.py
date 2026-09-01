"""AWS Bedrock -> invocation logs, runtime metrics, and Guardrails metrics."""
import json
from collections import defaultdict
from datetime import datetime, timezone

from src.generators.common import isos, log_doc, metric_doc
from src.world.llm_traffic import iter_events

SCOPE = "llm"
# Sample rate for per-invocation logs (usage still fully reflected in runtime metrics)
INVOCATION_SAMPLE = 0.35
# Share of Bedrock calls that attach a Guardrail (OOTB Guardrails dashboard).
GUARDRAIL_ATTACH_RATE = 0.55
# Of attached calls, share that are blocked / intervened with a violation.
GUARDRAIL_VIOLATION_RATE = 0.28

# CloudWatch GuardrailPolicyType dimension values.
_POLICY_TYPES = (
    "ContentPolicy",
    "TopicPolicy",
    "WordPolicy",
    "SensitiveInformationPolicy",
    "ContextualGroundingPolicy",
)

# Raw ModelInvocationLog uses camelCase; the Fleet pipeline snake_cases these.
_POLICY_TRACE = {
    "ContentPolicy": ("contentPolicy", "filters", {
        "type": "VIOLENCE", "action": "BLOCKED", "confidence": "HIGH",
    }),
    "TopicPolicy": ("topicPolicy", "topics", {
        "name": "financial_advice", "type": "DENY", "action": "BLOCKED",
    }),
    "WordPolicy": ("wordPolicy", "customWords", {
        "match": "competitor-acme", "action": "BLOCKED",
    }),
    "SensitiveInformationPolicy": ("sensitiveInformationPolicy", "piiEntities", {
        "type": "US_SOCIAL_SECURITY_NUMBER", "action": "ANONYMIZED", "match": "***-**-****",
    }),
    "ContextualGroundingPolicy": ("contextualGroundingPolicy", "filters", {
        "type": "GROUNDING", "action": "BLOCKED", "threshold": 0.75, "score": 0.31,
        "match": True,
    }),
}


def _guardrails(acct_id: str, region: str) -> list[dict]:
    return [
        {
            "id": "meridianpii0block01",
            "name": "meridian-pii-block",
            "arn": (f"arn:aws:bedrock:{region}:{acct_id}:"
                    "guardrail/meridianpii0block01"),
            "version": "2",
        },
        {
            "id": "meridiantoxicontent1",
            "name": "meridian-toxic-content",
            "arn": (f"arn:aws:bedrock:{region}:{acct_id}:"
                    "guardrail/meridiantoxicontent1"),
            "version": "3",
        },
        {
            "id": "meridiantopicdeny001",
            "name": "meridian-topic-deny",
            "arn": (f"arn:aws:bedrock:{region}:{acct_id}:"
                    "guardrail/meridiantopicdeny001"),
            "version": "1",
        },
    ]


def _completion_text(ev) -> str:
    return (f"[{ev.app['id']}] Synthetic Bedrock response for {ev.model['id']} "
            f"({ev.input_tokens}+{ev.output_tokens} tokens).")


def _guardrail_trace(guardrail: dict, policy_type: str, source: str) -> dict:
    """Build amazon-bedrock-trace.guardrail payload the Fleet script expects.

    gen_ai.guardrail_id is extracted only from `.input` / `.inputAssessment`
    keys, so always populate `input` even when the intervention was on Output.
    """
    key, list_key, detail = _POLICY_TRACE[policy_type]
    assessment = {guardrail["id"]: {key: {list_key: [dict(detail)]}}}
    # Non-intervened path still needs the guardrail id key present.
    out = {"input": assessment}
    if source == "Output":
        out["outputs"] = [assessment]
    return out


def _output_body_json(ev, guardrail=None, intervened=False, policy_type=None,
                      source="Input") -> list:
    """Streaming-style chunks the OOTB pipeline expects.

    - List + delta.text → aws_bedrock.invocation.output.completion_text
    - amazon-bedrock-invocationMetrics → gen_ai.performance.(start_)response_time
    - amazon-bedrock-trace / guardrailAction → gen_ai.guardrail_id + compliance
    """
    text = _completion_text(ev)
    if intervened:
        text = ("Sorry, I cannot help with that request. "
                f"(guardrail {guardrail['name']} intervened via {policy_type})")
    first_byte = max(1, int(ev.latency_ms * 0.28))
    stop = {
        "type": "message_stop",
        "amazon-bedrock-invocationMetrics": {
            "inputTokenCount": ev.input_tokens,
            "outputTokenCount": ev.output_tokens if not intervened else 24,
            "invocationLatency": int(ev.latency_ms),
            "firstByteLatency": first_byte,
        },
    }
    if guardrail is not None:
        pt = policy_type or "ContentPolicy"
        if intervened:
            stop["amazon-bedrock-trace"] = {
                "guardrail": _guardrail_trace(guardrail, pt, source),
            }
            stop["amazon-bedrock-guardrailAction"] = "INTERVENED"
            stop["stopReason"] = "guardrail_intervened"
        else:
            # Attach guardrail id without a violation (no INTERVENED action).
            stop["amazon-bedrock-trace"] = {
                "guardrail": {"input": {guardrail["id"]: {}}},
            }
            stop["amazon-bedrock-guardrailAction"] = "NONE"
    return [
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": text},
        },
        stop,
    ]


def _input_body_json(ev) -> dict:
    mid = ev.model["id"]
    prompt = f"[{ev.app['id']}] request"
    if mid.startswith("anthropic."):
        return {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 2048,
            "messages": [{"role": "user", "content": prompt}],
        }
    if mid.startswith("meta."):
        return {
            "prompt": prompt,
            "max_gen_len": 2048,
            "temperature": 0.5,
            "top_p": 0.9,
        }
    return {"inputText": prompt, "textGenerationConfig": {"maxTokenCount": 2048}}


class _BedrockInvocation:
    DATA_STREAM = "logs-aws_bedrock.invocation-default"
    DATASET = "aws_bedrock.invocation"

    def emit(self, world, t0, t1, anchor):
        from src.world.scenarios import rng_for
        rng = rng_for("bedrock_inv", t0.isoformat())
        acct = next((a for a in world.aws_accounts if a["name"] == "meridian-mlops"),
                    world.aws_accounts[0])
        for ev in iter_events(world, t0, t1, anchor):
            if ev.model["provider"] != "aws_bedrock":
                continue
            if rng.random() > INVOCATION_SAMPLE:
                continue
            region = rng.choice(world.cfg["aws"]["regions"])
            rails = _guardrails(acct["id"], region)
            guardrail = None
            intervened = False
            policy_type = None
            source = "Input"
            if rng.random() < GUARDRAIL_ATTACH_RATE:
                guardrail = rng.choice(rails)
                source = rng.choice(["Input", "Output"])
                policy_type = rng.choice(_POLICY_TYPES)
                intervened = rng.random() < GUARDRAIL_VIOLATION_RATE
            raw = {
                "schemaType": "ModelInvocationLog",
                "schemaVersion": "1.0",
                "timestamp": isos(ev.ts),
                "accountId": acct["id"],
                "region": region,
                "requestId": ev.request_id,
                "operation": "InvokeModel",
                "modelId": ev.model["id"],
                "identity": {
                    "arn": f"arn:aws:iam::{acct['id']}:user/{ev.actor_user}",
                },
                "input": {
                    "inputContentType": "application/json",
                    "inputTokenCount": ev.input_tokens,
                    "inputBodyJson": _input_body_json(ev),
                },
                "output": {
                    "outputContentType": "application/json",
                    "outputTokenCount": (
                        24 if intervened else ev.output_tokens),
                    "outputBodyJson": _output_body_json(
                        ev, guardrail=guardrail, intervened=intervened,
                        policy_type=policy_type, source=source),
                },
                "result": ("FAILURE" if (not ev.ok or intervened) else "SUCCESS"),
            }
            if guardrail is not None:
                raw["guardrailId"] = guardrail["id"]
                raw["guardrailArn"] = guardrail["arn"]
                raw["guardrailVersion"] = guardrail["version"]
            if not ev.ok and not intervened:
                raw["errorCode"] = ev.status
                raw["error"] = f"Bedrock {ev.status}"
            elif intervened:
                raw["errorCode"] = "GuardrailIntervened"
                raw["error"] = f"Guardrail {guardrail['name']} intervened"
            yield log_doc(self.DATASET, ev.ts, json.dumps(raw))


class _BedrockRuntime:
    DATA_STREAM = "metrics-aws_bedrock.runtime-default"
    DATASET = "aws_bedrock.runtime"

    def emit(self, world, t0, t1, anchor):
        buckets = defaultdict(lambda: {
            "invocations": 0, "errors": 0, "throttles": 0, "server_errors": 0,
            "input": 0, "output": 0, "latency_sum": 0, "images": 0,
        })
        from src.world.scenarios import rng_for
        rng = rng_for("bedrock_rt", t0.isoformat())
        for ev in iter_events(world, t0, t1, anchor):
            if ev.model["provider"] != "aws_bedrock":
                continue
            mark = int(ev.ts.timestamp() // 300) * 300
            key = (mark, ev.model["id"])
            b = buckets[key]
            b["invocations"] += 1
            b["input"] += ev.input_tokens
            b["output"] += ev.output_tokens
            b["latency_sum"] += ev.latency_ms
            if not ev.ok:
                if ev.status == "rate_limited":
                    b["throttles"] += 1
                elif ev.status in ("500", "503", "internal_error"):
                    b["server_errors"] += 1
                else:
                    b["errors"] += 1
            # Sparse image generations so Overview image panels are non-empty.
            if rng.random() < 0.02:
                b["images"] += 1

        acct = next((a for a in world.aws_accounts if a["name"] == "meridian-mlops"),
                    world.aws_accounts[0])
        for (mark, model_id), b in buckets.items():
            ts = datetime.fromtimestamp(mark, tz=timezone.utc)
            doc = metric_doc(self.DATASET, ts, "runtime", 300_000)
            doc["event"]["module"] = "aws"
            doc["cloud"] = {
                "provider": "aws", "region": "us-east-1",
                "account": {"id": acct["id"], "name": acct["name"]},
            }
            doc["aws"] = {"cloudwatch": {"namespace": "AWS/Bedrock"}}
            runtime = {
                "model_id": model_id,
                "invocations": b["invocations"],
                "invocation_latency": int(b["latency_sum"] / max(1, b["invocations"])),
                "input_token_count": b["input"],
                "output_token_count": b["output"],
                "invocation_client_errors": b["errors"],
                "invocation_server_errors": b["server_errors"],
                "invocation_throttles": b["throttles"],
            }
            if b["images"]:
                runtime["output_image_count"] = b["images"]
            doc["aws_bedrock"] = {"runtime": runtime}
            doc["tags"] = ["synthetic", "bedrock"]
            yield doc


class _BedrockGuardrails:
    """CloudWatch AWS/Bedrock/Guardrails → metrics-aws_bedrock.guardrails."""
    DATA_STREAM = "metrics-aws_bedrock.guardrails-default"
    DATASET = "aws_bedrock.guardrails"

    def emit(self, world, t0, t1, anchor):
        from src.world.scenarios import rng_for
        rng = rng_for("bedrock_gr", t0.isoformat())
        # Bucket ApplyGuardrail traffic derived from Bedrock LLM events.
        # key: (mark, guardrail_id, source) → counts
        buckets = defaultdict(lambda: {
            "invocations": 0, "intervened": 0, "latency_sum": 0,
            "text_units": 0, "client_errors": 0, "server_errors": 0,
            "throttles": 0, "by_policy": defaultdict(lambda: {
                "intervened": 0, "text_units": 0,
            }),
        })
        acct = next((a for a in world.aws_accounts if a["name"] == "meridian-mlops"),
                    world.aws_accounts[0])
        region = "us-east-1"
        rails = _guardrails(acct["id"], region)
        rail_by_id = {g["id"]: g for g in rails}

        for ev in iter_events(world, t0, t1, anchor):
            if ev.model["provider"] != "aws_bedrock":
                continue
            if rng.random() > GUARDRAIL_ATTACH_RATE:
                continue
            mark = int(ev.ts.timestamp() // 300) * 300
            guardrail = rng.choice(rails)
            # Input + Output are both evaluated on most ApplyGuardrail paths.
            for source in ("Input", "Output"):
                key = (mark, guardrail["id"], source)
                b = buckets[key]
                b["invocations"] += 1
                # ~1 text unit per 1k characters; synthetic tokens ≈ chars/4.
                units = max(1, (ev.input_tokens if source == "Input"
                                else ev.output_tokens) // 250)
                b["text_units"] += units
                b["latency_sum"] += max(5, int(ev.latency_ms * 0.12))
                if rng.random() < GUARDRAIL_VIOLATION_RATE:
                    b["intervened"] += 1
                    pt = rng.choice(_POLICY_TYPES)
                    b["by_policy"][pt]["intervened"] += 1
                    b["by_policy"][pt]["text_units"] += units
                if not ev.ok and rng.random() < 0.15:
                    if ev.status == "rate_limited":
                        b["throttles"] += 1
                    elif ev.status in ("500", "503", "internal_error"):
                        b["server_errors"] += 1
                    else:
                        b["client_errors"] += 1

        for (mark, gid, source), b in buckets.items():
            if b["invocations"] <= 0:
                continue
            ts = datetime.fromtimestamp(mark, tz=timezone.utc)
            gr = rail_by_id[gid]
            avg_lat = int(b["latency_sum"] / b["invocations"])

            def _base_doc(extra: dict):
                doc = metric_doc(self.DATASET, ts, "guardrails", 300_000)
                doc["event"]["module"] = "aws"
                doc["cloud"] = {
                    "provider": "aws", "region": region,
                    "account": {"id": acct["id"], "name": acct["name"]},
                }
                doc["aws"] = {
                    "cloudwatch": {"namespace": "AWS/Bedrock/Guardrails"},
                }
                doc["aws_bedrock"] = {"guardrails": {
                    "operation": "ApplyGuardrail",
                    "guardrail_arn": gr["arn"],
                    "guardrail_version": gr["version"],
                    "guardrail_content_source": source,
                    **extra,
                }}
                doc["tags"] = ["synthetic", "bedrock", "guardrails"]
                return doc

            # Aggregate (no policy type) — panels filter
            # `not aws_bedrock.guardrails.guardrail_policy_type : *`.
            yield _base_doc({
                "invocations": b["invocations"],
                "invocation_latency": avg_lat,
                "text_unit_count": b["text_units"],
                "invocations_intervened": b["intervened"],
                "invocation_client_errors": b["client_errors"],
                "invocation_server_errors": b["server_errors"],
                "invocation_throttles": b["throttles"],
            })

            # Per-policy series for intervention / text-unit-by-policy panels.
            for pt, pb in b["by_policy"].items():
                if pb["intervened"] <= 0 and pb["text_units"] <= 0:
                    continue
                yield _base_doc({
                    "guardrail_policy_type": pt,
                    "invocations_intervened": pb["intervened"],
                    "text_unit_count": max(pb["text_units"], pb["intervened"]),
                    "invocations": pb["intervened"],
                    "invocation_latency": avg_lat,
                })


bedrock_invocation = _BedrockInvocation()
bedrock_runtime = _BedrockRuntime()
bedrock_guardrails = _BedrockGuardrails()
