"""AWS Bedrock -> logs-aws_bedrock.invocation + metrics-aws_bedrock.runtime."""
import json
from collections import defaultdict

from src.generators.common import aligned, iso, isos, log_doc, metric_doc
from src.world.llm_traffic import iter_events
from src.world.model import stable_uuid

SCOPE = "llm"
# Sample rate for per-invocation logs (usage still fully reflected in runtime metrics)
INVOCATION_SAMPLE = 0.35


class _BedrockInvocation:
    DATA_STREAM = "logs-aws_bedrock.invocation-default"
    DATASET = "aws_bedrock.invocation"

    def emit(self, world, t0, t1, anchor):
        from src.world.scenarios import rng_for
        rng = rng_for("bedrock_inv", t0.isoformat())
        # Prefer mlops / fintech accounts for Bedrock
        acct = next((a for a in world.aws_accounts if a["name"] == "meridian-mlops"),
                    world.aws_accounts[0])
        for ev in iter_events(world, t0, t1, anchor):
            if ev.model["provider"] != "aws_bedrock":
                continue
            if rng.random() > INVOCATION_SAMPLE:
                continue
            region = rng.choice(world.cfg["aws"]["regions"])
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
                    "inputBodyJson": {
                        "anthropic_version": "bedrock-2023-05-31",
                        "max_tokens": 2048,
                        "messages": [{"role": "user", "content": f"[{ev.app['id']}] request"}],
                    },
                },
                "output": {
                    "outputContentType": "application/json",
                    "outputTokenCount": ev.output_tokens,
                    "outputBodyJson": {
                        "stop_reason": "end_turn" if ev.ok else "error",
                        "usage": {"input_tokens": ev.input_tokens,
                                  "output_tokens": ev.output_tokens},
                    },
                },
                "result": "SUCCESS" if ev.ok else "FAILURE",
            }
            if not ev.ok:
                raw["errorCode"] = ev.status
                raw["error"] = f"Bedrock {ev.status}"
            yield log_doc(self.DATASET, ev.ts, json.dumps(raw))


class _BedrockRuntime:
    DATA_STREAM = "metrics-aws_bedrock.runtime-default"
    DATASET = "aws_bedrock.runtime"

    def emit(self, world, t0, t1, anchor):
        # Aggregate to 5-min CloudWatch-style points
        buckets = defaultdict(lambda: {
            "invocations": 0, "errors": 0, "throttles": 0,
            "input": 0, "output": 0, "latency_sum": 0,
        })
        for ev in iter_events(world, t0, t1, anchor):
            if ev.model["provider"] != "aws_bedrock":
                continue
            # floor to 5-min
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
                else:
                    b["errors"] += 1

        acct = next((a for a in world.aws_accounts if a["name"] == "meridian-mlops"),
                    world.aws_accounts[0])
        from datetime import datetime, timezone
        for (mark, model_id), b in buckets.items():
            ts = datetime.fromtimestamp(mark, tz=timezone.utc)
            doc = metric_doc(self.DATASET, ts, "runtime", 300_000)
            doc["event"]["module"] = "aws"
            doc["cloud"] = {
                "provider": "aws", "region": "us-east-1",
                "account": {"id": acct["id"], "name": acct["name"]},
            }
            doc["aws"] = {"cloudwatch": {"namespace": "AWS/Bedrock"}}
            doc["aws_bedrock"] = {"runtime": {
                "model_id": model_id,
                "invocations": b["invocations"],
                "invocation_latency": int(b["latency_sum"] / max(1, b["invocations"])),
                "input_token_count": b["input"],
                "output_token_count": b["output"],
                "invocation_client_errors": b["errors"],
                "invocation_server_errors": 0,
                "invocation_throttles": b["throttles"],
            }}
            doc["tags"] = ["synthetic", "bedrock"]
            yield doc


bedrock_invocation = _BedrockInvocation()
bedrock_runtime = _BedrockRuntime()
