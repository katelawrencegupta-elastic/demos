"""Shared Meridian LLM traffic engine.

Yields per-request UsageEvent objects used by native provider generators
(OpenAI usage buckets, Anthropic metrics, Bedrock invocations, APM traces, etc.).
"""
from dataclasses import dataclass
from datetime import datetime

from src.world.llm import load_llm_catalog, token_cost_usd
from src.world.scenarios import (activity_multiplier, genai_ramp_multiplier,
                                 llm_agent_loop_active, llm_cache_miss_active,
                                 llm_migration_provider, sunday_batch_factor,
                                 rng_for)
from src.generators.common import poisson_count, spread
from src.world.model import stable_uuid


@dataclass
class UsageEvent:
    ts: datetime
    app: dict
    model: dict
    op: str                 # chat | embeddings
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int
    cost_usd: float
    latency_ms: int
    ok: bool
    status: str
    actor_user: str
    actor_email: str
    labels: dict
    request_id: str


def _tags(world, app, rng):
    bu = world.bu(app["bu"])
    tags = {"team": app["bu"], "env": app["env"], "app": app["id"]}
    if bu["cost_center"] is None:
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
    if model["tier"] == "reasoning":
        out = int(out * rng.uniform(2.5, 5.0))
    cached = 0
    if cache_rate > 0 and rng.random() < cache_rate:
        cached = int(inp * rng.uniform(0.5, 0.95))
    return inp, out, cached


def _latency_ms(rng, model, input_tokens, output_tokens):
    base = {"cheap": 280, "standard": 650, "flagship": 1100,
            "reasoning": 4200, "embedding": 90}[model["tier"]]
    return int(base + input_tokens * 0.02 + output_tokens * 0.08 + rng.gauss(0, 40))


def iter_events(world, t0, t1, anchor, catalog=None):
    """Yield UsageEvent for every synthetic LLM call in [t0, t1)."""
    catalog = catalog or load_llm_catalog()
    rng = rng_for("llmevt", t0.isoformat())
    hours = (t1 - t0).total_seconds() / 3600
    mult = activity_multiplier(world, t0, anchor)
    mid = t0 + (t1 - t0) / 2

    for app in catalog.apps:
        rate = app["base_rpm"] * mult * hours
        if app["id"] == "catalog-search-embed":
            rate *= sunday_batch_factor(t0)
        if app["bu"] == "skunkworks":
            rate *= genai_ramp_multiplier(world, mid, anchor)
        if (app["id"] == world.scenarios["llm_agent_loop"]["app"]
                and llm_agent_loop_active(world, mid, anchor)):
            rate *= world.scenarios["llm_agent_loop"]["rate_multiplier"]

        cache_rate = app["cache_hit_rate"]
        if (app["id"] == world.scenarios["llm_cache_miss_storm"]["app"]
                and llm_cache_miss_active(world, mid, anchor)):
            cache_rate = world.scenarios["llm_cache_miss_storm"]["cache_hit_rate"]

        forced = llm_migration_provider(world, app["id"], mid, anchor)
        for _ in range(poisson_count(rng, rate)):
            ts = spread(rng, t0, t1)
            model = catalog.pick_model(rng, app, provider=forced)
            op = rng.choice(app["ops"])
            if op not in model["ops"]:
                op = model["ops"][0]
            inp, out, cached = _tokens(rng, app, model, op, cache_rate)
            ok = rng.random() > 0.015
            status = "success" if ok else rng.choice(["error", "timeout", "rate_limited"])
            humans = world.humans_in_bu(app["bu"]) or world.identities
            actor = rng.choice(humans)
            yield UsageEvent(
                ts=ts, app=app, model=model, op=op,
                input_tokens=inp, output_tokens=out,
                cached_input_tokens=cached,
                cost_usd=token_cost_usd(model, inp, out, cached),
                latency_ms=max(40, _latency_ms(rng, model, inp, out)),
                ok=ok, status=status,
                actor_user=actor.user, actor_email=actor.email,
                labels=_tags(world, app, rng),
                request_id=stable_uuid("llmr", ts.isoformat(), rng.random()),
            )
