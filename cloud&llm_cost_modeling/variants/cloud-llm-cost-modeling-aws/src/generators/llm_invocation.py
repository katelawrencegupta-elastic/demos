"""Per-request LLM invocations -> logs-llm.invocation-default.

ORPHAN — not registered in src.generators.select() / ALL. Live LLM traffic
goes through native provider generators + llm_apm. Kept for reference only.

Documents follow OpenTelemetry GenAI semantic conventions (gen_ai.*) plus
Meridian org labels so spend can be attributed to BU / app / cost_center
and correlated with cloud activity.
"""
from src.generators.common import iso, poisson_count, spread
from src.world.llm import load_llm_catalog, token_cost_usd
from src.world.model import stable_uuid
from src.world.scenarios import (activity_multiplier, genai_ramp_multiplier,
                                 llm_agent_loop_active, llm_cache_miss_active,
                                 llm_migration_provider, sunday_batch_factor,
                                 rng_for)

DATA_STREAM = "logs-llm.invocation-default"
DATASET = "llm.invocation"
SCOPE = "llm"

PROVIDER_SYSTEM = {
    "openai": "openai",
    "anthropic": "anthropic",
    "google": "gcp.gemini",
    "aws_bedrock": "aws.bedrock",
    "azure_openai": "az.ai.openai",
}
FINISH = ["stop", "stop", "stop", "stop", "length", "content_filter"]


def _tags(world, app, rng):
    bu = world.bu(app["bu"])
    tags = {"team": app["bu"], "env": app["env"], "app": app["id"]}
    if bu["cost_center"] is None:
        # skunkworks shadow IT — mostly untagged
        return {} if rng.random() < 0.7 else {"app": app["id"], "team": app["bu"]}
    if rng.random() < 0.15:
        return {"team": app["bu"], "env": app["env"], "app": app["id"]}
    tags["cost_center"] = bu["cost_center"]
    return tags


def _tokens(rng, app, model, op, cache_rate):
    inp = max(16, int(rng.gauss(app["avg_input"], app["avg_input"] * 0.35)))
    if op == "embeddings":
        return inp, 0, 0
    out = max(8, int(rng.gauss(app["avg_output"], app["avg_output"] * 0.4)))
    # reasoning models emit extra "thinking" counted in output
    if model["tier"] == "reasoning":
        out = int(out * rng.uniform(2.5, 5.0))
    cached = int(inp * cache_rate) if cache_rate > 0 and rng.random() < cache_rate else 0
    if cached:
        cached = int(inp * rng.uniform(0.5, 0.95))
    return inp, out, cached


def _latency_ms(rng, model, input_tokens, output_tokens):
    base = {"cheap": 280, "standard": 650, "flagship": 1100,
            "reasoning": 4200, "embedding": 90}[model["tier"]]
    return int(base + input_tokens * 0.02 + output_tokens * 0.08 + rng.gauss(0, 40))


def _doc(world, catalog, rng, ts, app, model, op, cache_rate):
    inp, out, cached = _tokens(rng, app, model, op, cache_rate)
    cost = token_cost_usd(model, inp, out, cached)
    latency = max(40, _latency_ms(rng, model, inp, out))
    ok = rng.random() > 0.015
    status = "success" if ok else rng.choice(["error", "timeout", "rate_limited"])
    finish = "error" if not ok else rng.choice(FINISH)
    tags = _tags(world, app, rng)
    humans = world.humans_in_bu(app["bu"]) or world.identities
    actor = rng.choice(humans)

    gen_ai = {
        "system": PROVIDER_SYSTEM[model["provider"]],
        "operation": {"name": "chat" if op == "chat" else "embeddings"},
        "request": {
            "model": model["id"],
            "temperature": round(rng.uniform(0.0, 0.9), 2) if op == "chat" else None,
        },
        "response": {
            "id": "chatcmpl-" + stable_uuid("cmpl", ts.isoformat(), rng.random())[:20],
            "finish_reasons": [finish],
        },
        "usage": {
            "input_tokens": inp,
            "output_tokens": out,
            "total_tokens": inp + out,
            "cached_input_tokens": cached,
        },
        "provider": {"name": model["provider"]},
    }
    if gen_ai["request"]["temperature"] is None:
        del gen_ai["request"]["temperature"]
    if model.get("deployment"):
        gen_ai["request"]["deployment"] = model["deployment"]

    return {
        "@timestamp": iso(ts),
        "data_stream": {"type": "logs", "dataset": DATASET, "namespace": "default"},
        "event": {
            "kind": "event",
            "category": ["api"],
            "type": ["access"],
            "action": f"gen_ai.{op}",
            "outcome": "success" if ok else "failure",
            "duration": latency * 1_000_000,
            "id": stable_uuid("llminv", ts.isoformat(), rng.random()),
        },
        "gen_ai": gen_ai,
        "llm": {
            "model": {"id": model["id"], "family": model["family"], "tier": model["tier"]},
            "provider": model["provider"],
            "operation": op,
            "status": status,
            "latency_ms": latency,
            "cost": {"usd": cost, "currency": "USD"},
            "cache": {"hit": cached > 0, "input_tokens": cached},
        },
        "labels": tags,
        "service": {
            "name": app["id"],
            "environment": app["env"],
            "type": "llm-gateway",
        },
        "organization": {"name": world.cfg["company"]},
        "user": {"name": actor.user, "email": actor.email},
        "cloud": {"provider": {
            "openai": "saas", "anthropic": "saas", "google": "gcp",
            "aws_bedrock": "aws", "azure_openai": "azure",
        }[model["provider"]]},
        "tags": ["synthetic", "llm"],
        "ecs": {"version": "8.11.0"},
    }


def emit(world, t0, t1, anchor, catalog=None):
    catalog = catalog or load_llm_catalog()
    rng = rng_for("llminv", t0.isoformat())
    hours = (t1 - t0).total_seconds() / 3600
    mult = activity_multiplier(world, t0, anchor)
    mid = t0 + (t1 - t0) / 2

    for app in catalog.apps:
        rate = app["base_rpm"] * mult * hours
        # Sunday embedding batch for catalog-search-embed
        if app["id"] == "catalog-search-embed":
            rate *= sunday_batch_factor(t0)
        # Shadow-IT genai ramp on skunkworks apps
        if app["bu"] == "skunkworks":
            rate *= genai_ramp_multiplier(world, mid, anchor)
        # Agent loop explosion
        if (app["id"] == world.scenarios["llm_agent_loop"]["app"]
                and llm_agent_loop_active(world, mid, anchor)):
            rate *= world.scenarios["llm_agent_loop"]["rate_multiplier"]

        cache_rate = app["cache_hit_rate"]
        if (app["id"] == world.scenarios["llm_cache_miss_storm"]["app"]
                and llm_cache_miss_active(world, mid, anchor)):
            cache_rate = world.scenarios["llm_cache_miss_storm"]["cache_hit_rate"]

        forced = llm_migration_provider(world, app["id"], mid, anchor)
        n = poisson_count(rng, rate)
        for _ in range(n):
            ts = spread(rng, t0, t1)
            model = catalog.pick_model(rng, app, provider=forced)
            op = rng.choice(app["ops"])
            # ensure model supports the op
            if op not in model["ops"]:
                op = model["ops"][0]
            yield _doc(world, catalog, rng, ts, app, model, op, cache_rate)
