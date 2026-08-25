"""Elastic AI Assistant + inference usage.

Emits:
  * traces-agent_builder.otel-default — native Agent Builder OTel spans
    (same shape as Kibana: chat / invoke_agent / execute_tool)
  * logs-elastic.inference_token_usage-default — Kibana inference plugin
    token-usage documents (feature, connector, model, token counts)

Analysts at Meridian use Observability AI Assistant, Agent Builder
copilots, Security AI Assistant, and EIS (ELSER / e5 / rerank) endpoints.
"""
from dataclasses import dataclass

from src.generators.common import iso, poisson_count, spread
from src.world.llm import token_cost_usd
from src.world.model import stable_uuid
from src.world.scenarios import (
    activity_multiplier, crypto_incident_active, genai_ramp_multiplier,
    rng_for,
)

SCOPE = "elastic-ai"

_TEMPLATE_OK = False

RESOURCE = {
    "attributes": {
        "service.name": "kibana",
        "cloud.provider": "gcp",
        "cloud.region": "us-central1",
        "deployment.environment.name": "production",
    }
}
SCOPE_ATTR = {"name": "inference"}

# Built-in + Meridian custom agents. feature_id values match Kibana's
# inference feature registry (token-usage tracking / Feature Settings).
AGENTS = [
    {
        "id": "elastic-ai-agent", "name": "Elastic AI Agent", "weight": 38,
        "feature_id": "observability_ai_assistant_inference_subfeature",
        "parent_feature_id": "observability_ai_assistant_inference_parent_feature",
        "feature_name": "Observability AI Assistant",
        "bus": ["ecommerce", "mlplatform", "corpit", "fintech"],
    },
    {
        "id": "finops-copilot", "name": "FinOps Copilot", "weight": 16,
        "feature_id": "agent_builder",
        "parent_feature_id": "agent_builder_parent",
        "feature_name": "Agent Builder",
        "bus": ["corpit", "ecommerce", "mlplatform"],
    },
    {
        "id": "obs-oncall", "name": "Observability On-Call", "weight": 14,
        "feature_id": "agent_builder",
        "parent_feature_id": "agent_builder_parent",
        "feature_name": "Agent Builder",
        "bus": ["ecommerce", "corpit", "mlplatform"],
    },
    {
        "id": "sec-triage", "name": "Security Triage", "weight": 12,
        "feature_id": "security_ai_assistant",
        "parent_feature_id": "security_ai_assistant_parent",
        "feature_name": "Security AI Assistant",
        "bus": ["corpit", "fintech"],
    },
    {
        "id": "search-assistant", "name": "Search Assistant", "weight": 10,
        "feature_id": "search_playground",
        "parent_feature_id": "search",
        "feature_name": "Search Playground",
        "bus": ["fintech", "ecommerce", "mlplatform"],
    },
    {
        "id": "streams-discovery", "name": "Streams Significant Events", "weight": 6,
        "feature_id": "streams_sig_events_discovery",
        "parent_feature_id": "streams_significant_events",
        "feature_name": "Streams Significant Events",
        "bus": ["ecommerce", "corpit"],
    },
    {
        "id": "prompt-lab", "name": "Prompt Lab", "weight": 4,
        "feature_id": "agent_builder",
        "parent_feature_id": "agent_builder_parent",
        "feature_name": "Agent Builder",
        "bus": ["skunkworks", "mlplatform"],
    },
]

CHAT_MODELS = [
    {
        "id": "anthropic-claude-4.6-sonnet", "provider": "elastic",
        "connector": ".anthropic-claude-4.6-sonnet-chat_completion",
        "service": "elastic", "tier": "standard",
        "input_per_m": 3.0, "output_per_m": 15.0, "cached_input_per_m": 0.30,
        "weight": 42,
    },
    {
        "id": "anthropic-claude-4.5-haiku", "provider": "elastic",
        "connector": ".anthropic-claude-4.5-haiku-chat_completion",
        "service": "elastic", "tier": "cheap",
        "input_per_m": 0.80, "output_per_m": 4.0, "cached_input_per_m": 0.08,
        "weight": 22,
    },
    {
        "id": "openai-gpt-5.4", "provider": "openai",
        "connector": ".openai-gpt-5.4-chat_completion",
        "service": "openai", "tier": "standard",
        "input_per_m": 2.50, "output_per_m": 15.0, "cached_input_per_m": 0.25,
        "weight": 14,
    },
    {
        "id": "elastic-llm-v2", "provider": "elastic",
        "connector": ".gp-llm-v2-chat_completion",
        "service": "elastic", "tier": "standard",
        "input_per_m": 2.0, "output_per_m": 8.0, "cached_input_per_m": 0.20,
        "weight": 12,
    },
    {
        "id": "google-gemini-3.1-flash-lite", "provider": "google",
        "connector": ".google-gemini-3.1-flash-lite-chat_completion",
        "service": "google", "tier": "cheap",
        "input_per_m": 0.10, "output_per_m": 0.40, "cached_input_per_m": 0.01,
        "weight": 10,
    },
]

FAST_MODEL = CHAT_MODELS[1]  # haiku — generate_title / cheap follow-ups

TOOLS = [
    ("platform.core.execute_esql", 0.28),
    ("platform.core.search", 0.18),
    ("platform.core.list_indices", 0.12),
    ("platform.core.get_index_mapping", 0.08),
    ("attachments.read", 0.10),
    ("load_skill", 0.08),
    ("ask_user_question", 0.04),
    ("custom", 0.12),
]

# Semantic search / rerank inference that sits behind platform.core.search
SEARCH_INFERENCE = [
    {
        "id": ".elser-2-elastic", "task_type": "sparse_embedding",
        "provider": "elastic", "service": "elastic",
        "connector": ".elser-2-elastic", "input_per_m": 0.05, "weight": 55,
    },
    {
        "id": ".multilingual-e5-small-elasticsearch", "task_type": "text_embedding",
        "provider": "elasticsearch", "service": "elasticsearch",
        "connector": ".multilingual-e5-small-elasticsearch",
        "input_per_m": 0.02, "weight": 25,
    },
    {
        "id": ".rerank-v1-elasticsearch", "task_type": "rerank",
        "provider": "elasticsearch", "service": "elasticsearch",
        "connector": ".rerank-v1-elasticsearch",
        "input_per_m": 0.08, "weight": 20,
    },
]


@dataclass
class LlmCall:
    model: dict
    input_tokens: int
    output_tokens: int
    cached_tokens: int
    thinking_tokens: int
    latency_ns: int
    ok: bool
    feature_id: str  # may be agent_builder_fast for title gen


@dataclass
class Round:
    ts: object
    agent: dict
    actor: object
    conversation_id: str
    trace_id: str
    chain_ns: int
    llm_calls: list
    tools: list  # (name, duration_ns, ok)
    search_inf: list  # SEARCH_INFERENCE docs for this round


def _hex32(*parts):
    return stable_uuid(*parts).replace("-", "")


def _hex16(*parts):
    return _hex32(*parts)[:16]


def _user_hash(user: str) -> str:
    return stable_uuid("userhash", user).replace("-", "")[:16]


def _pick(rng, items, weight_key="weight"):
    return rng.choices(items, weights=[i[weight_key] for i in items], k=1)[0]


def _tokens(rng, model, kind="chat"):
    if kind == "title":
        inp = rng.randint(180, 420)
        out = rng.randint(8, 18)
        return inp, out, 0, 0
    inp = max(80, int(rng.gauss(2800, 1400)))
    if model["tier"] == "cheap":
        inp = max(60, int(inp * 0.45))
    out = max(40, int(rng.gauss(420, 220)))
    if model["tier"] == "flagship":
        out = int(out * rng.uniform(1.4, 2.2))
    cached = int(inp * rng.uniform(0.15, 0.55)) if rng.random() < 0.35 else 0
    thinking = int(out * rng.uniform(0.4, 1.8)) if model["id"].endswith("sonnet") and rng.random() < 0.2 else 0
    return inp, out, cached, thinking


def _latency_ns(rng, model, output_tokens):
    base_ms = {"cheap": 420, "standard": 1400, "flagship": 2800}[model["tier"]]
    ms = max(80, int(base_ms + output_tokens * rng.uniform(1.5, 4.0) + rng.gauss(0, 80)))
    return ms * 1_000_000


def iter_rounds(world, t0, t1, anchor):
    rng = rng_for("elastic-ai", t0.isoformat())
    hours = (t1 - t0).total_seconds() / 3600.0
    mult = activity_multiplier(world, t0, anchor)
    # ~10 analyst rounds / hour at peak; crypto incident and genai ramp lift it
    rate = 10.0 * mult * hours
    if crypto_incident_active(world, t0, anchor):
        rate *= 2.4
    rate *= 0.55 + 0.45 * genai_ramp_multiplier(world, t0, anchor)
    n = poisson_count(rng, rate)

    humans = [i for i in world.identities if not i.is_service]
    for i in range(n):
        ts = spread(rng, t0, t1)
        agents = list(AGENTS)
        weights = [a["weight"] for a in agents]
        if crypto_incident_active(world, ts, anchor):
            for j, a in enumerate(agents):
                if a["id"] in ("sec-triage", "obs-oncall", "elastic-ai-agent"):
                    weights[j] *= 3.5
        agent = rng.choices(agents, weights=weights, k=1)[0]
        pool = [h for h in humans if h.bu in agent["bus"]] or humans
        actor = rng.choice(pool)

        n_llm = 1 + (rng.random() < 0.55) + (rng.random() < 0.18)
        llm_calls = []
        for k in range(n_llm):
            model = _pick(rng, CHAT_MODELS)
            if agent["id"] == "prompt-lab" and rng.random() < 0.5:
                model = CHAT_MODELS[2]  # BYO OpenAI in the skunkworks lab
            inp, out, cached, thinking = _tokens(rng, model)
            ok = rng.random() > 0.015
            llm_calls.append(LlmCall(
                model=model, input_tokens=inp, output_tokens=out,
                cached_tokens=cached, thinking_tokens=thinking,
                latency_ns=_latency_ns(rng, model, out), ok=ok,
                feature_id=agent["feature_id"],
            ))
        if rng.random() < 0.35:
            inp, out, cached, thinking = _tokens(rng, FAST_MODEL, kind="title")
            llm_calls.append(LlmCall(
                model=FAST_MODEL, input_tokens=inp, output_tokens=out,
                cached_tokens=cached, thinking_tokens=0,
                latency_ns=_latency_ns(rng, FAST_MODEL, out),
                ok=True, feature_id="agent_builder_fast",
            ))

        n_tools = rng.choices([0, 1, 2, 3, 4, 5], weights=[8, 22, 28, 22, 14, 6])[0]
        tools = []
        search_inf = []
        for _ in range(n_tools):
            name = rng.choices([t[0] for t in TOOLS], weights=[t[1] for t in TOOLS])[0]
            ok = rng.random() > (0.08 if name == "custom" else 0.025)
            dur = int(max(0.8, rng.gauss(180, 90)) * 1_000_000)  # ~ms → ns
            if name == "platform.core.execute_esql":
                dur = int(max(5, rng.gauss(420, 200)) * 1_000_000)
            tools.append((name, dur, ok))
            if name == "platform.core.search":
                inf = _pick(rng, SEARCH_INFERENCE)
                tok = rng.randint(64, 900)
                search_inf.append((inf, tok))

        chain_ns = (sum(c.latency_ns for c in llm_calls)
                    + sum(d for _, d, _ in tools)
                    + int(rng.uniform(40, 180) * 1_000_000))
        conv = _hex16("conv", actor.user, t0.isoformat(), i)
        trace = _hex32("trace", actor.user, t0.isoformat(), i)
        yield Round(ts, agent, actor, conv, trace, chain_ns, llm_calls, tools, search_inf)


def _span(ts, trace_id, span_id, parent_id, name, kind, duration_ns, ok, attrs,
          extra_root=None):
    doc = {
        "@timestamp": iso(ts),
        "data_stream": {
            "type": "traces", "dataset": "agent_builder.otel", "namespace": "default",
        },
        "resource": RESOURCE,
        "scope": SCOPE_ATTR,
        "trace_id": trace_id,
        "span_id": span_id,
        "parent_span_id": parent_id or "0" * 16,
        "name": name,
        "kind": kind,
        "duration": int(duration_ns),
        "status": {"code": "Ok" if ok else "Error"},
        "attributes": attrs,
    }
    if extra_root:
        doc.update(extra_root)
    return doc


class AgentBuilderTraces:
    DATA_STREAM = "traces-agent_builder.otel-default"
    DATASET = "agent_builder.otel"

    def emit(self, world, t0, t1, anchor):
        for rnd in iter_rounds(world, t0, t1, anchor):
            chain_id = _hex16("chain", rnd.trace_id)
            agent_id = _hex16("agent", rnd.trace_id)
            base = {
                "gen_ai.agent.id": rnd.agent["id"],
                "gen_ai.agent.name": rnd.agent["name"],
                "gen_ai.conversation.id": rnd.conversation_id,
                "gen_ai.provider.name": "Elastic",
                "user.hash": _user_hash(rnd.actor.user),
                "user.name": rnd.actor.user,
                "labels.team": rnd.actor.bu,
                "labels.role": rnd.actor.role,
            }
            extra = {
                "user": {"name": rnd.actor.user, "hash": _user_hash(rnd.actor.user)},
                "labels": {"team": rnd.actor.bu, "role": rnd.actor.role},
            }
            yield _span(
                rnd.ts, rnd.trace_id, chain_id, None,
                f"invoke_agent {rnd.agent['name']}", "Internal",
                rnd.chain_ns, True,
                {**base, "elastic.inference.span.kind": "CHAIN",
                 "gen_ai.operation.name": "invoke_agent",
                 "kibana.inference.root": True},
                extra_root=extra,
            )
            yield _span(
                rnd.ts, rnd.trace_id, agent_id, chain_id,
                f"invoke_agent {rnd.agent['name']}", "Internal",
                max(1, rnd.chain_ns - 20_000_000), True,
                {**base, "elastic.inference.span.kind": "AGENT",
                 "gen_ai.operation.name": "invoke_agent",
                 "kibana.inference.root": False},
                extra_root=extra,
            )
            parent = agent_id
            for k, call in enumerate(rnd.llm_calls):
                sid = _hex16("chat", rnd.trace_id, k)
                title = call.feature_id == "agent_builder_fast"
                name = ("generate_title" if title
                        else f"chat {call.model['id']}")
                attrs = {
                    **base,
                    "elastic.inference.span.kind": "LLM",
                    "gen_ai.operation.name": "chat",
                    "gen_ai.provider.name": call.model["provider"],
                    "gen_ai.request.model": call.model["id"],
                    "gen_ai.response.model": call.model["id"],
                    "gen_ai.usage.input_tokens": call.input_tokens,
                    "gen_ai.usage.output_tokens": call.output_tokens,
                    "gen_ai.input.messages": "[]",
                    "kibana.inference.root": False,
                }
                yield _span(
                    rnd.ts, rnd.trace_id, sid, parent, name, "Client",
                    call.latency_ns, call.ok, attrs, extra_root=extra)
            for k, (tool, dur, ok) in enumerate(rnd.tools):
                sid = _hex16("tool", rnd.trace_id, k)
                yield _span(
                    rnd.ts, rnd.trace_id, sid, parent,
                    f"execute_tool {tool}", "Internal", dur, ok,
                    {**base,
                     "elastic.inference.span.kind": "TOOL",
                     "gen_ai.operation.name": "execute_tool",
                     "gen_ai.tool.name": tool,
                     "gen_ai.tool.type": "builtin" if not tool.startswith("custom") else "extension",
                     "kibana.inference.root": False},
                    extra_root=extra,
                )


def _usage_doc(ts, call_or_inf, agent, actor, *, embedding=False):
    if embedding:
        inf, tok = call_or_inf
        prompt, completion, thinking, cached = tok, 0, 0, 0
        total = tok
        model_id = inf["id"]
        provider = inf["provider"]
        connector = inf["connector"]
        service = inf["service"]
        task = inf["task_type"]
        cost = (tok / 1_000_000.0) * inf["input_per_m"]
        feature_id = agent["feature_id"]
    else:
        call = call_or_inf
        prompt, completion = call.input_tokens, call.output_tokens
        thinking, cached = call.thinking_tokens, call.cached_tokens
        total = prompt + completion + thinking
        model_id = call.model["id"]
        provider = call.model["provider"]
        connector = call.model["connector"]
        service = call.model["service"]
        task = "chat_completion"
        cost = token_cost_usd(call.model, prompt, completion, cached)
        feature_id = call.feature_id
    parent = agent["parent_feature_id"]
    feature_name = ("Agent Builder (fast)" if feature_id == "agent_builder_fast"
                    else agent["feature_name"])
    return {
        "@timestamp": iso(ts),
        "data_stream": {
            "type": "logs", "dataset": "elastic.inference_token_usage",
            "namespace": "default",
        },
        "token_usage": {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "thinking_tokens": thinking,
            "total_tokens": total,
            "cached_tokens": cached,
        },
        "model": {
            "model_id": model_id,
            "model_name": model_id,
            "model_creator": provider,
            "provider": provider,
        },
        "inference": {
            "connector_id": connector,
            "feature_id": feature_id,
            "parent_feature_id": parent,
            "feature_name": feature_name,
            "task_type": task,
            "endpoint_id": connector,
            "service": service,
        },
        "user": {"name": actor.user, "id": actor.email},
        "labels": {
            "team": actor.bu,
            "role": actor.role,
            "cost_usd": round(cost, 8),
            "eis": service == "elastic",
        },
        "tags": ["synthetic", "elastic-ai"],
    }


class InferenceTokenUsage:
    DATA_STREAM = "logs-elastic.inference_token_usage-default"
    DATASET = "elastic.inference_token_usage"

    def emit(self, world, t0, t1, anchor):
        _ensure_template()
        for rnd in iter_rounds(world, t0, t1, anchor):
            for call in rnd.llm_calls:
                yield _usage_doc(rnd.ts, call, rnd.agent, rnd.actor)
            for inf in rnd.search_inf:
                yield _usage_doc(rnd.ts, inf, rnd.agent, rnd.actor, embedding=True)


def _ensure_template():
    """Idempotent mapping so ES|QL keyword/long fields are typed."""
    global _TEMPLATE_OK
    if _TEMPLATE_OK:
        return
    from src.config import ELASTIC_URL, ES_HEADERS
    import requests
    body = {
        "index_patterns": ["logs-elastic.inference_token_usage-*"],
        "data_stream": {},
        "priority": 210,
        "template": {
            "mappings": {
                "properties": {
                    "@timestamp": {"type": "date"},
                    "token_usage": {"properties": {
                        "prompt_tokens": {"type": "long"},
                        "completion_tokens": {"type": "long"},
                        "thinking_tokens": {"type": "long"},
                        "total_tokens": {"type": "long"},
                        "cached_tokens": {"type": "long"},
                    }},
                    "model": {"properties": {
                        "model_id": {"type": "keyword"},
                        "model_name": {"type": "keyword"},
                        "model_creator": {"type": "keyword"},
                        "provider": {"type": "keyword"},
                    }},
                    "inference": {"properties": {
                        "connector_id": {"type": "keyword"},
                        "feature_id": {"type": "keyword"},
                        "parent_feature_id": {"type": "keyword"},
                        "feature_name": {"type": "keyword"},
                        "task_type": {"type": "keyword"},
                        "endpoint_id": {"type": "keyword"},
                        "service": {"type": "keyword"},
                    }},
                    "user": {"properties": {
                        "name": {"type": "keyword"},
                        "id": {"type": "keyword"},
                    }},
                    "labels": {"properties": {
                        "team": {"type": "keyword"},
                        "role": {"type": "keyword"},
                        "cost_usd": {"type": "double"},
                        "eis": {"type": "boolean"},
                    }},
                }
            }
        },
    }
    r = requests.put(
        f"{ELASTIC_URL}/_index_template/meridian-inference-token-usage",
        headers=ES_HEADERS, json=body, timeout=30)
    if r.status_code >= 300:
        print(f"  [warn] inference token-usage template: {r.status_code} {r.text[:200]}")
    _TEMPLATE_OK = True


agent_builder_traces = AgentBuilderTraces()
inference_token_usage = InferenceTokenUsage()
