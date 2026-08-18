"""APM traces for LLM calls -> traces-apm-default (OTel gen_ai semantic conventions)."""
from src.generators.common import iso
from src.world.llm_traffic import iter_events
from src.world.model import stable_uuid

SCOPE = "llm"
DATA_STREAM = "traces-apm-default"
DATASET = "apm"
# Sample a subset so volume stays manageable alongside provider logs
SAMPLE = 0.25

PROVIDER_SYSTEM = {
    "openai": "openai",
    "anthropic": "anthropic",
    "google": "gcp.gemini",
    "aws_bedrock": "aws.bedrock",
    "azure_openai": "az.ai.openai",
}


def emit(world, t0, t1, anchor):
    from src.world.scenarios import rng_for
    rng = rng_for("llmapm", t0.isoformat())
    for ev in iter_events(world, t0, t1, anchor):
        if rng.random() > SAMPLE:
            continue
        tx_id = stable_uuid("apmtx", ev.request_id).replace("-", "")[:16]
        span_id = stable_uuid("apmspan", ev.request_id).replace("-", "")[:16]
        duration_us = ev.latency_ms * 1000
        outcome = "success" if ev.ok else "failure"
        op = "chat" if ev.op == "chat" else "embeddings"

        # Transaction
        yield {
            "@timestamp": iso(ev.ts),
            "data_stream": {"type": "traces", "dataset": "apm", "namespace": "default"},
            "processor": {"event": "transaction", "name": "transaction"},
            "observer": {"type": "apm-server", "version": "9.2.0"},
            "agent": {"name": "python", "version": "6.22.0"},
            "service": {
                "name": ev.app["id"],
                "environment": ev.app["env"],
                "language": {"name": "python"},
                "framework": {"name": "fastapi"},
            },
            "transaction": {
                "id": tx_id,
                "name": f"POST /v1/{op}",
                "type": "request",
                "duration": {"us": duration_us},
                "result": "HTTP 2xx" if ev.ok else "HTTP 5xx",
                "sampled": True,
            },
            "event": {"outcome": outcome},
            "trace": {"id": tx_id},
            "timestamp": {"us": int(ev.ts.timestamp() * 1_000_000)},
            "labels": ev.labels,
            "user": {"name": ev.actor_user, "email": ev.actor_email},
            "tags": ["synthetic", "llm"],
        }

        # Exit span to the LLM provider
        yield {
            "@timestamp": iso(ev.ts),
            "data_stream": {"type": "traces", "dataset": "apm", "namespace": "default"},
            "processor": {"event": "span", "name": "transaction"},
            "observer": {"type": "apm-server", "version": "9.2.0"},
            "agent": {"name": "python", "version": "6.22.0"},
            "service": {
                "name": ev.app["id"],
                "environment": ev.app["env"],
                "language": {"name": "python"},
            },
            "transaction": {"id": tx_id},
            "trace": {"id": tx_id},
            "parent": {"id": tx_id},
            "span": {
                "id": span_id,
                "name": f"{PROVIDER_SYSTEM[ev.model['provider']]}.{op} {ev.model['id']}",
                "type": "external",
                "subtype": "gen_ai",
                "action": op,
                "duration": {"us": duration_us},
            },
            "event": {"outcome": outcome},
            "timestamp": {"us": int(ev.ts.timestamp() * 1_000_000)},
            "gen_ai": {
                "system": PROVIDER_SYSTEM[ev.model["provider"]],
                "operation": {"name": op},
                "request": {"model": ev.model["id"]},
                "usage": {
                    "input_tokens": ev.input_tokens,
                    "output_tokens": ev.output_tokens,
                    "total_tokens": ev.input_tokens + ev.output_tokens,
                },
            },
            "labels": {**ev.labels, "llm_cost_usd": str(ev.cost_usd)},
            "tags": ["synthetic", "llm"],
        }
