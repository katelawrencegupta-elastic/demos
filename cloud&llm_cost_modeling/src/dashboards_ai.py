"""Publish Meridian Elastic AI Assistant + inference usage dashboard."""
from src.dashboards import (
    DASHBOARD_ID, DASHBOARD_ID_DYNAMIC, TS, TIME_FROM,
    gauge, links_panel, markdown, metric, pie, section, table,
    treemap, waffle, xy, _put_dashboard, _ensure_data_view, _q,
)

DASHBOARD_ID_AI = "meridian-ai-assistant-inference-usage"
TIME_TO_AI = "2026-08-26T00:00:00.000Z"

TRACES = "traces-agent_builder.otel-default"
USAGE = "logs-elastic.inference_token_usage-default"


def build_ai_assistant_dashboard():
    chat = f'span.name LIKE "chat *"'
    chain = (
        'span.name LIKE "invoke_agent *" AND '
        'attributes.elastic.inference.span.kind == "CHAIN"'
    )
    agent_span = (
        'span.name LIKE "invoke_agent *" AND '
        'attributes.elastic.inference.span.kind == "AGENT"'
    )
    tool = 'span.name LIKE "execute_tool *"'

    rounds = _q("FROM " + TRACES, f"| WHERE {TS} AND {chain}",
                "| STATS rounds = COUNT(*)")
    llm_reqs = _q("FROM " + TRACES, f"| WHERE {TS} AND {chat}",
                  "| STATS requests = COUNT(*)")
    tokens_in = _q("FROM " + TRACES, f"| WHERE {TS} AND {chat}",
                   "| STATS tokens = SUM(TO_LONG(attributes.gen_ai.usage.input_tokens))")
    tokens_out = _q("FROM " + TRACES, f"| WHERE {TS} AND {chat}",
                    "| STATS tokens = SUM(TO_LONG(attributes.gen_ai.usage.output_tokens))")
    usage_cost = _q("FROM " + USAGE, f"| WHERE {TS}",
                    "| STATS cost = SUM(labels.cost_usd)")
    error_g = _q("FROM " + TRACES, f"| WHERE {TS} AND {tool}",
                 "| STATS errors = COUNT(*) WHERE status.code == \"Error\", calls = COUNT(*)",
                 "| EVAL error_rate = errors * 1.0 / calls, min = 0, max = 0.12, goal = 0.02")
    p95_g = _q("FROM " + TRACES, f"| WHERE {TS} AND {chain}",
               "| STATS p95_s = PERCENTILE(duration, 95) / 1000000000.0",
               "| EVAL min = 0, max = 60, goal = 8")

    tokens_day = _q(
        "FROM " + TRACES, f"| WHERE {TS} AND {chat}",
        "| STATS input = SUM(TO_LONG(attributes.gen_ai.usage.input_tokens)), "
        "output = SUM(TO_LONG(attributes.gen_ai.usage.output_tokens)) "
        "BY day = BUCKET(@timestamp, 1d)",
        "| SORT day",
    )
    rounds_day = _q(
        "FROM " + TRACES, f"| WHERE {TS} AND {chain}",
        "| STATS rounds = COUNT(*) BY day = BUCKET(@timestamp, 1d), "
        "agent = attributes.gen_ai.agent.name",
        "| SORT day",
    )
    tokens_model = _q(
        "FROM " + TRACES, f"| WHERE {TS} AND {chat}",
        "| STATS input = SUM(TO_LONG(attributes.gen_ai.usage.input_tokens)), "
        "output = SUM(TO_LONG(attributes.gen_ai.usage.output_tokens)), "
        "requests = COUNT(*) "
        "BY model = attributes.gen_ai.request.model, "
        "provider = attributes.gen_ai.provider.name",
        "| SORT input DESC",
    )
    agent_vol = _q(
        "FROM " + TRACES, f"| WHERE {TS} AND {agent_span}",
        "| STATS runs = COUNT(*), "
        "p95_s = PERCENTILE(duration, 95) / 1000000000.0 "
        "BY agent = attributes.gen_ai.agent.name",
        "| SORT runs DESC",
    )
    tool_tbl = _q(
        "FROM " + TRACES, f"| WHERE {TS} AND {tool}",
        "| STATS calls = COUNT(*), "
        "errors = COUNT(*) WHERE status.code == \"Error\", "
        "avg_ms = AVG(duration) / 1000000.0 "
        "BY tool = attributes.gen_ai.tool.name",
        "| EVAL error_rate = errors * 1.0 / calls",
        "| SORT calls DESC",
    )
    users = _q(
        "FROM " + TRACES, f"| WHERE {TS} AND {chain}",
        "| STATS rounds = COUNT(*) BY user = COALESCE(user.name, user.hash), "
        "team = COALESCE(labels.team, \"untagged\")",
        "| SORT rounds DESC", "| LIMIT 20",
    )

    feat_tokens = _q(
        "FROM " + USAGE, f"| WHERE {TS}",
        "| STATS tokens = SUM(token_usage.total_tokens), "
        "prompt = SUM(token_usage.prompt_tokens), "
        "completion = SUM(token_usage.completion_tokens), "
        "requests = COUNT(*), cost = SUM(labels.cost_usd) "
        "BY feature = inference.feature_name",
        "| SORT tokens DESC",
    )
    feat_day = _q(
        "FROM " + USAGE, f"| WHERE {TS}",
        "| STATS tokens = SUM(token_usage.total_tokens) "
        "BY day = BUCKET(@timestamp, 1d), feature = inference.feature_name",
        "| SORT day",
    )
    model_cost = _q(
        "FROM " + USAGE, f"| WHERE {TS}",
        "| STATS tokens = SUM(token_usage.total_tokens), "
        "cost = SUM(labels.cost_usd), requests = COUNT(*) "
        "BY model = model.model_id, provider = model.provider, "
        "task = inference.task_type",
        "| SORT cost DESC", "| LIMIT 20",
    )
    eis_mix = _q(
        "FROM " + USAGE, f"| WHERE {TS}",
        "| EVAL origin = CASE(inference.service == \"elastic\", \"Elastic Inference Service\", \"BYO / external\")",
        "| STATS tokens = SUM(token_usage.total_tokens), cost = SUM(labels.cost_usd) BY origin",
        "| SORT tokens DESC",
    )
    connector_tree = _q(
        "FROM " + USAGE, f"| WHERE {TS}",
        "| STATS tokens = SUM(token_usage.total_tokens), cost = SUM(labels.cost_usd) "
        "BY feature = inference.feature_name, connector = inference.connector_id",
        "| SORT tokens DESC", "| LIMIT 40",
    )
    task_waffle = _q(
        "FROM " + USAGE, f"| WHERE {TS}",
        "| STATS requests = COUNT(*) BY task = inference.task_type",
        "| SORT requests DESC",
    )
    team_cost = _q(
        "FROM " + USAGE, f"| WHERE {TS}",
        "| STATS cost = SUM(labels.cost_usd), tokens = SUM(token_usage.total_tokens) "
        "BY team = labels.team",
        "| SORT cost DESC",
    )
    thinking = _q(
        "FROM " + USAGE, f"| WHERE {TS}",
        "| STATS thinking = SUM(token_usage.thinking_tokens), "
        "cached = SUM(token_usage.cached_tokens), "
        "prompt = SUM(token_usage.prompt_tokens) "
        "BY day = BUCKET(@timestamp, 1d)",
        "| SORT day",
    )

    panels = [
        section("Elastic AI — Assistant, Agent Builder, and inference", 0, [
            markdown(0, 0, 48, 4,
                     "## Meridian Dynamics — Elastic AI Assistant & inference usage\n\n"
                     "Native **Agent Builder** OTel traces (`traces-agent_builder.otel-default`) "
                     "plus **inference token usage** (`logs-elastic.inference_token_usage-default`) "
                     "for Observability / Security AI Assistant, Agent Builder copilots, "
                     "Search Playground, Streams, and EIS endpoints (chat, ELSER, e5, rerank).\n\n"
                     "Same backfill window as the FinOps dashboard. EIS = Elastic Inference Service."),
            metric(0, 4, 8, 5, "Conversation rounds", rounds, "rounds"),
            metric(8, 4, 8, 5, "LLM requests", llm_reqs, "requests"),
            metric(16, 4, 8, 5, "Input tokens", tokens_in, "tokens"),
            metric(24, 4, 8, 5, "Output tokens", tokens_out, "tokens"),
            metric(32, 4, 8, 5, "Estimated inference cost", usage_cost, "cost", "USD"),
            gauge(40, 4, 8, 10, "Tool error rate",
                  error_g, "error_rate", shape="arc",
                  min_col="min", max_col="max", goal_col="goal",
                  subtitle="failures / tool calls"),
            xy(0, 9, 24, 12, "Daily input vs output tokens (chat spans)",
               tokens_day, "day", ["input", "output"], layer="area"),
            xy(24, 9, 16, 12, "Daily conversation rounds by agent",
               rounds_day, "day", ["rounds"], layer="area_stacked",
               breakdown="agent"),
        ]),
        section("AI Assistant & Agent Builder — agents, models, tools", 26, [
            markdown(0, 0, 48, 2,
                     "Operational view from Agent Builder traces: `chat *` spans carry tokens and model, "
                     "`invoke_agent *` + `CHAIN`/`AGENT` span kinds are conversation rounds vs executions, "
                     "`execute_tool *` is tool use (ES|QL, search, mappings, skills)."),
            treemap(0, 2, 24, 14, "Tokens by model × provider",
                    tokens_model, "input", ["provider", "model"]),
            xy(24, 2, 24, 14, "Agent executions",
               agent_vol, "agent", ["runs"], layer="bar_horizontal"),
            table(0, 16, 28, 12, "Tool calls — volume, errors, latency",
                  tool_tbl, ["tool"], ["calls", "errors", "error_rate", "avg_ms"]),
            table(28, 16, 20, 12, "Top users by conversation rounds",
                  users, ["user", "team"], ["rounds"]),
            xy(0, 28, 24, 12, "Daily conversation rounds by agent",
               rounds_day, "day", ["rounds"], layer="area_stacked",
               breakdown="agent"),
            xy(24, 28, 24, 12, "LLM requests by model",
               _q("FROM " + TRACES, f"| WHERE {TS} AND {chat}",
                  "| STATS requests = COUNT(*) BY model = attributes.gen_ai.request.model",
                  "| SORT requests DESC", "| LIMIT 12"),
               "model", ["requests"], layer="bar_horizontal"),
            gauge(0, 40, 16, 10, "Conversation round p95",
                  p95_g, "p95_s", shape="semi_circle",
                  min_col="min", max_col="max", goal_col="goal",
                  subtitle="seconds"),
            pie(16, 40, 16, 10, "LLM requests by provider",
                _q("FROM " + TRACES, f"| WHERE {TS} AND {chat}",
                   "| STATS requests = COUNT(*) BY provider = attributes.gen_ai.provider.name"),
                "requests", "provider"),
            pie(32, 40, 16, 10, "Tokens by model",
                _q("FROM " + TRACES, f"| WHERE {TS} AND {chat}",
                   "| STATS tokens = SUM(TO_LONG(attributes.gen_ai.usage.input_tokens)) "
                   "BY model = attributes.gen_ai.request.model",
                   "| SORT tokens DESC", "| LIMIT 8"),
                "tokens", "model"),
        ]),
        section("Inference token usage — features, EIS, connectors", 80, [
            markdown(0, 0, 48, 2,
                     "Kibana inference-plugin shape: `token_usage.*`, `model.*`, `inference.feature_id` / "
                     "`connector_id`. Features include Observability AI Assistant, Agent Builder, "
                     "Security AI Assistant, Search Playground, and Streams Significant Events. "
                     "Chat completions plus ELSER / e5 / rerank task types."),
            waffle(0, 2, 16, 12, "Tokens: EIS vs BYO connectors",
                   eis_mix, "tokens", "origin"),
            xy(16, 2, 32, 12, "Daily tokens by Kibana AI feature",
               feat_day, "day", ["tokens"], layer="area_stacked",
               breakdown="feature"),
            xy(0, 14, 24, 12, "Tokens by feature",
               feat_tokens, "feature", ["tokens"], layer="bar_horizontal"),
            xy(24, 14, 24, 12, "Estimated cost by team",
               team_cost, "team", ["cost"], layer="bar"),
            treemap(0, 26, 28, 14, "Tokens — feature × connector",
                    connector_tree, "tokens", ["feature", "connector"]),
            waffle(28, 26, 20, 14, "Requests by inference task type",
                   task_waffle, "requests", "task"),
            table(0, 40, 48, 12, "Model × provider × task — tokens, cost, requests",
                  model_cost, ["provider", "model", "task"],
                  ["requests", "tokens", "cost"]),
            xy(0, 52, 48, 11, "Prompt vs cached vs thinking tokens (daily)",
               thinking, "day", ["prompt", "cached", "thinking"],
               layer="area_stacked"),
        ]),
        section("Related dashboards", 146, [
            markdown(0, 0, 24, 8,
                     "**Streams**\n\n"
                     "- `traces-agent_builder.otel-default` — Agent Builder OTel spans\n"
                     "- `logs-elastic.inference_token_usage-default` — feature-attributed tokens\n\n"
                     "Enable Kibana **GenAI Settings → Token usage tracking** for the "
                     "managed `[Elastic] Inference Token Usage` dashboard on live traffic."),
            links_panel(24, 0, 24, 8, "Meridian FinOps family", [
                ("FinOps & LLM Observability", DASHBOARD_ID),
                ("FinOps & LLM — dynamic", DASHBOARD_ID_DYNAMIC),
                ("This AI Assistant dashboard", DASHBOARD_ID_AI),
            ]),
        ]),
    ]

    return {
        "title": "[Meridian] Elastic AI Assistant & inference usage",
        "description": (
            "Observability / Security AI Assistant and Agent Builder operations "
            "(conversations, tokens, latency, tools) plus Elastic inference usage "
            "by feature, model, connector, EIS vs BYO, and estimated cost."
        ),
        "time_range": {"from": TIME_FROM, "to": TIME_TO_AI},
        "options": {
            "use_margins": True,
            "sync_colors": True,
            "sync_cursor": True,
            "sync_tooltips": True,
            "hide_panel_titles": False,
        },
        "query": {"expression": "", "language": "kql"},
        "panels": panels,
    }


def publish_ai():
    print("== data views (AI Assistant) ==")
    _ensure_data_view("traces-agent_builder.otel-*", "traces-agent_builder.otel-*")
    _ensure_data_view("logs-elastic.inference_token_usage-*",
                      "logs-elastic.inference_token_usage-*")
    from src.setup_cmd import patch_inference_token_usage_dashboard
    print("== OOTB [Elastic] Inference Token Usage ==")
    patch_inference_token_usage_dashboard()
    print(f"== PUT dashboard {DASHBOARD_ID_AI} ==")
    return _put_dashboard(DASHBOARD_ID_AI, build_ai_assistant_dashboard())
