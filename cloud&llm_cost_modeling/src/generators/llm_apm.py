"""APM traces for LLM calls -> traces-apm-default (OTel gen_ai semantic conventions)."""
from src.generators.common import iso
from src.world.llm_traffic import iter_events
from src.world.model import stable_uuid

SCOPE = "llm"
DATA_STREAM = "traces-apm-default"
DATASET = "apm"
# Sample a subset so volume stays manageable alongside provider logs
SAMPLE = 0.25
# Managed traces-apm mapping only ships span.duration.us / representative_count.
# ES|QL errors with "Unknown column [span.subtype]" on an empty/rolled index
# unless these fields are declared. Default APM retention is too short for a
# multi-month FinOps backfill; keep traces for the full demo window.
APM_RETENTION = "180d"
CUSTOM_COMPONENT = "traces-apm@custom"

PROVIDER_SYSTEM = {
    "openai": "openai",
    "anthropic": "anthropic",
    "google": "gcp.gemini",
    "aws_bedrock": "aws.bedrock",
    "azure_openai": "az.ai.openai",
}

# Dotted keys merge with traces-apm@mappings (span.duration.us, …).
GENAI_PROPERTIES = {
    "span.subtype": {"type": "keyword"},
    "span.type": {"type": "keyword"},
    "span.name": {"type": "keyword"},
    "span.action": {"type": "keyword"},
    "span.id": {"type": "keyword"},
    "event.outcome": {"type": "keyword"},
    "service.name": {"type": "keyword"},
    "service.environment": {"type": "keyword"},
    "trace.id": {"type": "keyword"},
    "transaction.name": {"type": "keyword"},
    "transaction.type": {"type": "keyword"},
    "labels.llm_cost_usd": {"type": "double"},
    "labels.team": {"type": "keyword"},
    "labels.env": {"type": "keyword"},
    "labels.app": {"type": "keyword"},
    "labels.cost_center": {"type": "keyword"},
    "numeric_labels.llm_cost_usd": {
        "type": "scaled_float",
        "scaling_factor": 1_000_000,
    },
    "gen_ai.system": {"type": "keyword"},
    "gen_ai.operation.name": {"type": "keyword"},
    "gen_ai.request.model": {"type": "keyword"},
    "gen_ai.usage.input_tokens": {"type": "long"},
    "gen_ai.usage.output_tokens": {"type": "long"},
    "gen_ai.usage.total_tokens": {"type": "long"},
}

_TEMPLATE_OK = False


def ensure_apm_genai_mappings(fail_loud: bool = False):
    """Declare gen_ai span fields and extend traces-apm retention for ES|QL."""
    global _TEMPLATE_OK
    if _TEMPLATE_OK:
        return
    from src.config import ELASTIC_URL, ES_HEADERS
    import requests

    body = {
        "template": {
            "lifecycle": {"data_retention": APM_RETENTION},
            "mappings": {"properties": GENAI_PROPERTIES},
        },
        "_meta": {
            "description": "Meridian gen_ai span fields + 180d retention for ES|QL dashboards",
            "managed": False,
        },
    }
    r = requests.put(
        f"{ELASTIC_URL}/_component_template/{CUSTOM_COMPONENT}",
        headers=ES_HEADERS, json=body, timeout=30)
    if r.status_code >= 300:
        msg = f"  [fail] {CUSTOM_COMPONENT}: {r.status_code} {r.text[:240]}"
        if fail_loud:
            raise SystemExit(msg)
        print(msg.replace("[fail]", "[warn]"))
    else:
        print(f"  [ok] component template {CUSTOM_COMPONENT} ({APM_RETENTION})")

    r = requests.put(
        f"{ELASTIC_URL}/{DATA_STREAM}/_mapping",
        headers=ES_HEADERS, timeout=30,
        json={"properties": GENAI_PROPERTIES})
    if r.status_code >= 300:
        # Stream may not exist until first backfill — template covers new indices.
        print(f"  [warn] {DATA_STREAM} mapping: {r.status_code} {r.text[:240]}")
    else:
        print(f"  [ok] {DATA_STREAM} mapping updated")

    r = requests.put(
        f"{ELASTIC_URL}/_data_stream/{DATA_STREAM}/_lifecycle",
        headers=ES_HEADERS, timeout=30,
        json={"data_retention": APM_RETENTION})
    if r.status_code >= 300:
        print(f"  [warn] {DATA_STREAM} lifecycle: {r.status_code} {r.text[:240]}")
    else:
        print(f"  [ok] {DATA_STREAM} retention {APM_RETENTION}")

    _TEMPLATE_OK = True


def emit(world, t0, t1, anchor):
    from src.world.scenarios import rng_for
    ensure_apm_genai_mappings()
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
            "labels": {**ev.labels, "llm_cost_usd": ev.cost_usd},
            "numeric_labels": {"llm_cost_usd": ev.cost_usd},
            "tags": ["synthetic", "llm"],
        }
