"""Variant-scoped Meridian FinOps dashboard sections."""
from __future__ import annotations

from src.dashboard_caps import DashboardCaps, TS, caps_from_variant
from src.dashboards import (
    AGENT_CHAT_URL,
    DASHBOARD_ID_INFERENCE_USAGE,
    KIBANA_URL,
    _ootb_items,
    _q,
    budget_posture_section,
    dash_id,
    gauge,
    links_panel,
    markdown,
    metric,
    pie,
    section,
    table,
    tag_cloud,
    treemap,
    waffle,
    xy,
    xy_dual,
)


def _section_height(panels: list) -> int:
    bottom = 0
    for p in panels:
        g = p.get("grid") or {}
        bottom = max(bottom, int(g.get("y", 0)) + int(g.get("h", 0)))
    return bottom


def _stack(section_specs: list[tuple[str, list] | None]) -> list:
    out = []
    y = 0
    for spec in section_specs:
        if not spec:
            continue
        title, panels = spec
        if not panels:
            continue
        out.append(section(title, y, panels))
        y += _section_height(panels) + 2
    return out


def _metric_row(y: int, specs: list[tuple], h: int = 6) -> list:
    if not specs:
        return []
    w = max(48 // len(specs), 8)
    panels = []
    for i, spec in enumerate(specs):
        title, query, col = spec[0], spec[1], spec[2]
        subtitle = spec[3] if len(spec) > 3 else None
        trend = spec[4] if len(spec) > 4 else False
        panels.append(metric(i * w, y, w, h, title, query, col,
                              subtitle or "USD", trend=trend))
    return panels


def _intro_lines(caps: DashboardCaps, label: str, vtitle: str) -> str:
    lines = [
        f"## {vtitle}\n",
        "Panels scoped to this workshop variant — only integrations with seeded data.\n",
        f"Time range: **{label}**.",
    ]
    if caps.classic_layout:
        lines.append(
            f" Security→cost (crypto / S3) on the "
            f"[classic](#/view/{dash_id('classic')}) layout."
        )
    if caps.budgets:
        lines.append(
            f"\n\n**Budgets:** [FinOps AI Assistant]({AGENT_CHAT_URL}) · "
            f"[Observability SLOs]({KIBANA_URL}/app/observability/slos)."
        )
    if caps.ess:
        lines.append(
            "\n\n**ESS billing:** "
            "[Billing](#/view/ess_billing-billingdashboard) · "
            "[Credits](#/view/ess_billing-creditsdashboard)."
        )
    return "".join(lines)


def _baseline_scoreboard(caps: DashboardCaps, label: str, vtitle: str, q: dict) -> list:
    intro_h = 5 if caps.budgets or caps.ess else 4
    panels = [markdown(0, 0, 48, intro_h, _intro_lines(caps, label, vtitle))]
    kpis = []
    if caps.aws_cur:
        kpis.append(("AWS CUR", q["aws_trend"], "cost", "USD · sparkline", True))
    if caps.gcp_billing:
        kpis.append(("GCP billing", q["gcp_trend"], "cost", "USD · sparkline", True))
    if caps.azure_billing:
        kpis.append(("Azure pretax", q["azure_trend"], "cost", "USD · sparkline", True))
    if caps.llm_apm:
        kpis.append(("LLM cost (APM)", q["llm_trend"], "cost", "USD · sparkline", True))
    if caps.bedrock and not caps.aws_cur:
        kpis.append(("Bedrock invocations", q["bedrock_invocations"], "calls", "count", True))
    if caps.anthropic and not caps.llm_apm:
        kpis.append(("Anthropic tokens", q["anthropic_tokens"], "tokens", "usage API", True))
    panels.extend(_metric_row(intro_h, kpis))
    y2 = intro_h + (6 if kpis else 0)
    if caps.multi_cloud_billing and q.get("cloud_mix"):
        panels.append(waffle(0, y2, 16, 14, "Cloud spend mix", q["cloud_mix"], "cost", "provider"))
        panels.append(xy(16, y2, 32, 14, "Daily cost by cloud (stacked area)",
                         q["daily_cloud"], "day", ["cost"],
                         layer="area_stacked", breakdown="provider"))
    elif caps.aws_cur and q.get("aws_trend"):
        panels.append(xy(0, y2, 48, 14, "AWS CUR daily cost",
                         q["aws_trend"], "day", ["cost"], layer="area"))
    elif caps.gcp_billing and q.get("gcp_trend"):
        panels.append(xy(0, y2, 48, 14, "GCP billing daily",
                         q["gcp_trend"], "day", ["cost"], layer="area"))
    elif caps.azure_billing and q.get("azure_trend"):
        panels.append(xy(0, y2, 48, 14, "Azure pretax daily",
                         q["azure_trend"], "day", ["cost"], layer="area"))
    return panels


def _baseline_allocation(caps: DashboardCaps, q: dict) -> list:
    panels = []
    y = 0
    if caps.aws_cur:
        panels.append(xy(0, y, 28, 16, "AWS cost by service — stacked by account",
                         q["acct_svc"], "service", ["cost"],
                         layer="bar_stacked", breakdown="account"))
        if caps.aws_tags:
            panels.append(waffle(28, y, 20, 16, "AWS cost_center tags",
                                 q["cc_tag"], "cost", "tag"))
        y += 16
        panels.append(xy(0, y, 48, 14, "AWS cost by account over day (stacked area)",
                         q["cost_by_acct_day"], "day", ["cost"],
                         layer="area_stacked", breakdown="account"))
        y += 14
    if caps.gcp_billing:
        panels.append(xy(0, y, 48, 14, "GCP cost by service — stacked by project",
                         q["gcp_proj_svc"], "service", ["cost"],
                         layer="bar_stacked", breakdown="project"))
        y += 14
    if caps.azure_billing:
        panels.append(xy(0, y, 48, 14, "Azure cost by product — stacked by department",
                         q["azure_dept"], "product", ["cost"],
                         layer="bar_stacked", breakdown="team"))
    return panels


def _baseline_usage_cost(caps: DashboardCaps, q: dict) -> list:
    if not (caps.aws_cur and caps.aws_ec2):
        return []
    return [
        xy_dual(
            0, 0, 48, 14, "EC2 unblended cost vs NetworkIn (dual axis)",
            {"type": "area", "data_source": {"type": "esql", "query": q["ec2_cost_day"]},
             "x": {"column": "day"}, "y": [{"column": "cost", "axis": "y"}]},
            {"type": "line", "data_source": {"type": "esql", "query": q["net_day"]},
             "x": {"column": "day"}, "y": [{"column": "network_in", "axis": "y2"}]},
        ),
        xy(0, 14, 24, 12, "AWS daily cost (smooth)",
           q["aws_trend"], "day", ["cost"], layer="area"),
        gauge(24, 14, 24, 12, "AWS 30-day run-rate vs 7-day average",
              q["forecast"], "projected_30d", shape="arc",
              min_col="min", max_col="max", goal_col="goal", subtitle="USD projected"),
    ]


def _baseline_llm_landscape(caps: DashboardCaps, q: dict) -> list:
    if not caps.llm_apm:
        return []
    return [
        tag_cloud(0, 0, 24, 14, "Models sized by tokens",
                  q["model_tokens"], "tokens", "model"),
        waffle(24, 0, 24, 14, "LLM cost by team", q["team_cost"], "cost_usd", "team"),
        treemap(0, 14, 28, 16, "Token treemap — flow × model",
                q["flow_model"], "tokens", ["flow", "model"]),
        xy(28, 14, 20, 16, "Tokens by user flow",
           q["flow_tokens"], "flow", ["tokens"], layer="bar_horizontal"),
    ]


def _baseline_llm_time(caps: DashboardCaps, q: dict) -> list:
    if not caps.llm_apm:
        return []
    panels = [
        xy(0, 0, 48, 14, "Tokens by flow over day (stacked area)",
           q["tokens_by_flow_day"], "day", ["tokens"],
           layer="area_stacked", breakdown="flow"),
        xy(0, 14, 48, 14, "p95 latency by model over day (ms)",
           q["latency_by_model_day"], "day", ["p95_ms"],
           layer="line", breakdown="model"),
        xy(0, 28, 32, 12, "Prompt vs completion (stacked area)",
           q["tokens_day"], "day", ["prompt", "completion"], layer="area_stacked"),
    ]
    if caps.openai:
        panels.append(xy(32, 28, 16, 12, "OpenAI tokens by user",
                         q["users"], "user", ["tokens"], layer="bar_horizontal"))
    return panels


def _baseline_llm_quality(caps: DashboardCaps, q: dict) -> list:
    if not caps.llm_apm:
        return []
    return [
        gauge(0, 0, 16, 12, "LLM error rate", q["error_gauge"], "error_rate",
              shape="arc", min_col="min", max_col="max", goal_col="goal",
              subtitle="failures / calls"),
        gauge(16, 0, 16, 12, "p95 latency", q["p95_gauge"], "p95_ms",
              shape="semi_circle", min_col="min", max_col="max", goal_col="goal",
              subtitle="ms"),
        pie(32, 0, 16, 12, "Call outcome", q["outcome"], "calls", "outcome"),
        xy(0, 12, 24, 14, "Prompt vs completion by flow",
           q["flow_tokens"], "flow", ["prompt", "completion"],
           layer="bar_horizontal_stacked"),
        xy(24, 12, 24, 14, "Cost by flow — stacked by model",
           q["flow_model"], "flow", ["cost_usd"],
           layer="bar_horizontal_stacked", breakdown="model"),
    ]


def _baseline_bedrock_native(caps: DashboardCaps, q: dict) -> list:
    if not caps.bedrock:
        return []
    return [
        metric(0, 0, 12, 6, "Invocations", q["bedrock_invocations"], "calls"),
        metric(12, 0, 12, 6, "Input tokens", q["bedrock_in_tokens"], "tokens"),
        metric(24, 0, 12, 6, "Output tokens", q["bedrock_out_tokens"], "tokens"),
        metric(36, 0, 12, 6, "Guardrail blocks", q["bedrock_guardrail_blocks"], "blocks"),
        xy(0, 6, 24, 14, "Invocations by model",
           q["bedrock_by_model"], "model", ["calls"], layer="bar"),
        xy(24, 6, 24, 14, "Runtime invocations vs errors",
           q["bedrock_runtime_day"], "day", ["invocations", "errors"], layer="area"),
        xy(0, 20, 48, 12, "Guardrail policy interventions",
           q["bedrock_guardrails"], "policy", ["interventions"], layer="bar"),
    ]


def _baseline_anthropic_native(caps: DashboardCaps, q: dict) -> list:
    if not caps.anthropic:
        return []
    return [
        xy(0, 0, 24, 14, "Anthropic usage tokens by model",
           q["anthropic_usage_model"], "model", ["tokens"], layer="bar_stacked",
           breakdown="kind"),
        xy(24, 0, 24, 14, "Anthropic daily cost (USD)",
           q["anthropic_cost_day"], "day", ["cost_usd"], layer="area"),
        xy(0, 14, 48, 12, "Rate-limit headroom by model",
           q["anthropic_rate_limits"], "model", ["remaining_pct"], layer="bar"),
    ]


def _baseline_openai_native(caps: DashboardCaps, q: dict) -> list:
    if not caps.openai:
        return []
    return [
        xy(0, 0, 32, 14, "OpenAI completions — tokens by model",
           q["openai_tokens_model"], "model", ["tokens"], layer="bar_stacked",
           breakdown="kind"),
        xy(32, 0, 16, 14, "OpenAI requests by model",
           q["openai_requests_model"], "model", ["requests"], layer="bar"),
        xy(0, 14, 48, 12, "OpenAI rate-limit utilization",
           q["openai_rate_limits"], "model", ["utilization"], layer="bar"),
    ]


def _baseline_vertex_native(caps: DashboardCaps, q: dict) -> list:
    if not caps.vertex:
        return []
    return [
        xy(0, 0, 24, 14, "Vertex prompt tokens by model",
           q["vertex_tokens_model"], "model", ["tokens"], layer="bar"),
        xy(24, 0, 24, 14, "Vertex online prediction latency (p95)",
           q["vertex_latency"], "model", ["p95_ms"], layer="bar"),
        xy(0, 14, 48, 12, "Vertex audit — API calls by action",
           q["vertex_audit"], "action", ["calls"], layer="bar"),
    ]


def _baseline_azure_openai_native(caps: DashboardCaps, q: dict) -> list:
    if not caps.azure_openai:
        return []
    return [
        xy(0, 0, 24, 14, "Azure OpenAI — tokens by deployment",
           q["az_oai_tokens"], "deployment", ["tokens"], layer="bar"),
        xy(24, 0, 24, 14, "Azure OpenAI — requests by category",
           q["az_oai_category"], "category", ["requests"], layer="bar"),
        xy(0, 14, 48, 12, "Azure OpenAI daily cost",
           q["az_oai_cost_day"], "day", ["cost"], layer="area"),
    ]


def _baseline_provider_packs(caps: DashboardCaps) -> list:
    family = [("This baseline dashboard", dash_id("baseline"))]
    if caps.classic_layout:
        family.extend([
            ("Classic layout", dash_id("classic")),
            ("Dynamic alias (same as baseline)", dash_id("dynamic")),
        ])
    if caps.ai_dashboard:
        family.append(("AI Assistant & inference usage", dash_id("ai")))
    family.append(("[Elastic] Inference Token Usage", DASHBOARD_ID_INFERENCE_USAGE))
    ootb = list(_ootb_items())
    ootb_extra = [
        ("[Elastic] Inference Token Usage", DASHBOARD_ID_INFERENCE_USAGE),
    ]
    if caps.ai_dashboard:
        ootb_extra.append(("AI Assistant & inference usage", dash_id("ai")))
    return [
        links_panel(0, 0, 24, 10, "This family", family),
        links_panel(24, 0, 24, 10, "Provider FinOps & LLM packs", ootb + ootb_extra),
    ]


def baseline_queries() -> dict:
    """ES|QL snippets shared by baseline section builders."""
    return {
        "aws_trend": _q(
            "FROM metrics-aws_billing.cur-default", f"| WHERE {TS}",
            "| STATS cost = SUM(aws_billing.cur.line_item.unblended_cost) BY day = BUCKET(@timestamp, 1d)",
            "| SORT day"),
        "gcp_trend": _q(
            "FROM metrics-gcp.billing-default", f"| WHERE {TS}",
            "| STATS cost = SUM(gcp.billing.total) BY day = BUCKET(@timestamp, 1d)",
            "| SORT day"),
        "azure_trend": _q(
            "FROM metrics-azure.billing-default", f"| WHERE {TS}",
            "| STATS cost = SUM(azure.billing.pretax_cost) BY day = BUCKET(@timestamp, 1d)",
            "| SORT day"),
        "llm_trend": _q(
            "FROM traces-apm-default", f'| WHERE {TS} AND span.subtype == "gen_ai"',
            "| EVAL cost = TO_DOUBLE(labels.llm_cost_usd)",
            "| STATS cost = SUM(cost) BY day = BUCKET(@timestamp, 1d)", "| SORT day"),
        "acct_svc": _q(
            "FROM metrics-aws_billing.cur-default", f"| WHERE {TS}",
            "| STATS cost = SUM(aws_billing.cur.line_item.unblended_cost) "
            "BY account = aws_billing.cur.line_item.usage_account_name, "
            "service = aws_billing.cur.product.product",
            "| SORT cost DESC", "| LIMIT 40"),
        "cost_by_acct_day": _q(
            "FROM metrics-aws_billing.cur-default", f"| WHERE {TS}",
            "| STATS cost = SUM(aws_billing.cur.line_item.unblended_cost) "
            "BY day = BUCKET(@timestamp, 1d), account = aws_billing.cur.line_item.usage_account_name",
            "| SORT day"),
        "cc_tag": _q(
            "FROM metrics-aws.billing-default", f"| WHERE {TS}",
            '| WHERE aws.billing.group_definition.key == "COST_CENTER"',
            "| STATS cost = SUM(aws.billing.UnblendedCost.amount) "
            "BY tag = aws.billing.group_by.COST_CENTER", "| SORT cost DESC"),
        "gcp_proj_svc": _q(
            "FROM metrics-gcp.billing-default", f"| WHERE {TS}",
            "| STATS cost = SUM(gcp.billing.total) "
            "BY project = gcp.billing.project_name, service = gcp.billing.service_description",
            "| SORT cost DESC"),
        "azure_dept": _q(
            "FROM metrics-azure.billing-default", f"| WHERE {TS}",
            "| STATS cost = SUM(azure.billing.pretax_cost) "
            "BY team = azure.billing.department_name, product = azure.billing.product",
            "| SORT cost DESC", "| LIMIT 30"),
        "ec2_cost_day": _q(
            "FROM metrics-aws_billing.cur-default", f"| WHERE {TS}",
            '| WHERE aws_billing.cur.product.product == "AmazonEC2"',
            "| STATS cost = SUM(aws_billing.cur.line_item.unblended_cost) BY day = BUCKET(@timestamp, 1d)",
            "| SORT day"),
        "net_day": _q(
            "FROM metrics-aws.ec2_metrics-default", f"| WHERE {TS}",
            "| STATS network_in = SUM(aws.ec2.metrics.NetworkIn.rate) BY day = BUCKET(@timestamp, 1d)",
            "| SORT day"),
        "forecast": _q(
            "FROM metrics-aws_billing.cur-default", f"| WHERE {TS}",
            "| STATS daily = SUM(aws_billing.cur.line_item.unblended_cost) BY day = BUCKET(@timestamp, 1d)",
            "| SORT day DESC", "| LIMIT 7", "| STATS avg_7d = AVG(daily)",
            "| EVAL projected_30d = avg_7d * 30, min = 0, max = avg_7d * 45, goal = avg_7d * 28"),
        "flow_model": _q(
            "FROM traces-apm-default", f'| WHERE {TS} AND span.subtype == "gen_ai"',
            "| EVAL cost = TO_DOUBLE(labels.llm_cost_usd)",
            "| STATS tokens = SUM(gen_ai.usage.total_tokens), cost_usd = SUM(cost) "
            "BY flow = service.name, model = gen_ai.request.model",
            "| SORT tokens DESC", "| LIMIT 40"),
        "tokens_by_flow_day": _q(
            "FROM traces-apm-default", f'| WHERE {TS} AND span.subtype == "gen_ai"',
            "| STATS tokens = SUM(gen_ai.usage.total_tokens) "
            "BY day = BUCKET(@timestamp, 1d), flow = service.name", "| SORT day"),
        "latency_by_model_day": _q(
            "FROM traces-apm-default", f'| WHERE {TS} AND span.subtype == "gen_ai"',
            "| STATS p95_ms = PERCENTILE(span.duration.us, 95) / 1000 "
            "BY day = BUCKET(@timestamp, 1d), model = gen_ai.request.model", "| SORT day"),
        "tokens_day": _q(
            "FROM traces-apm-default", f'| WHERE {TS} AND span.subtype == "gen_ai"',
            "| STATS prompt = SUM(gen_ai.usage.input_tokens), "
            "completion = SUM(gen_ai.usage.output_tokens) BY day = BUCKET(@timestamp, 1d)",
            "| SORT day"),
        "flow_tokens": _q(
            "FROM traces-apm-default", f'| WHERE {TS} AND span.subtype == "gen_ai"',
            "| EVAL cost = TO_DOUBLE(labels.llm_cost_usd)",
            "| STATS prompt = SUM(gen_ai.usage.input_tokens), "
            "completion = SUM(gen_ai.usage.output_tokens), "
            "tokens = SUM(gen_ai.usage.total_tokens), cost_usd = SUM(cost) BY flow = service.name",
            "| SORT tokens DESC"),
        "team_cost": _q(
            "FROM traces-apm-default", f'| WHERE {TS} AND span.subtype == "gen_ai"',
            "| EVAL cost = TO_DOUBLE(labels.llm_cost_usd)",
            "| STATS cost_usd = SUM(cost) BY team = COALESCE(labels.team, \"untagged\")",
            "| SORT cost_usd DESC"),
        "model_tokens": _q(
            "FROM traces-apm-default", f'| WHERE {TS} AND span.subtype == "gen_ai"',
            "| STATS tokens = SUM(gen_ai.usage.total_tokens) BY model = gen_ai.request.model",
            "| SORT tokens DESC", "| LIMIT 16"),
        "error_gauge": _q(
            "FROM traces-apm-default", f'| WHERE {TS} AND span.subtype == "gen_ai"',
            '| STATS errors = COUNT(*) WHERE event.outcome == "failure", calls = COUNT(*)',
            "| EVAL error_rate = errors * 1.0 / calls, min = 0, max = 0.08, goal = 0.01"),
        "p95_gauge": _q(
            "FROM traces-apm-default", f'| WHERE {TS} AND span.subtype == "gen_ai"',
            "| STATS p95_ms = PERCENTILE(span.duration.us, 95) / 1000",
            "| EVAL min = 0, max = 8000, goal = 1500"),
        "outcome": _q(
            "FROM traces-apm-default", f'| WHERE {TS} AND span.subtype == "gen_ai"',
            "| STATS calls = COUNT(*) BY outcome = event.outcome"),
        "users": _q(
            "FROM logs-openai.completions-default", f"| WHERE {TS}",
            "| STATS tokens = SUM(openai.base.usage_tokens) BY user = openai.base.user_id",
            "| SORT tokens DESC", "| LIMIT 12"),
        "bedrock_invocations": _q(
            "FROM logs-aws_bedrock.invocation-default", f"| WHERE {TS}",
            "| STATS calls = COUNT(*)"),
        "bedrock_in_tokens": _q(
            "FROM logs-aws_bedrock.invocation-default", f"| WHERE {TS}",
            "| STATS tokens = SUM(gen_ai.usage.input_tokens)"),
        "bedrock_out_tokens": _q(
            "FROM logs-aws_bedrock.invocation-default", f"| WHERE {TS}",
            "| STATS tokens = SUM(gen_ai.usage.output_tokens)"),
        "bedrock_guardrail_blocks": _q(
            "FROM metrics-aws_bedrock.guardrails-default", f"| WHERE {TS}",
            "| STATS blocks = SUM(aws_bedrock.guardrails.guardrail_intervened_count)"),
        "bedrock_by_model": _q(
            "FROM logs-aws_bedrock.invocation-default", f"| WHERE {TS}",
            "| STATS calls = COUNT(*) BY model = aws_bedrock.invocation.model_id",
            "| SORT calls DESC", "| LIMIT 12"),
        "bedrock_runtime_day": _q(
            "FROM metrics-aws_bedrock.runtime-default", f"| WHERE {TS}",
            "| STATS invocations = SUM(aws_bedrock.runtime.invocations), "
            "errors = SUM(aws_bedrock.runtime.invocation_client_errors) "
            "BY day = BUCKET(@timestamp, 1d)", "| SORT day"),
        "bedrock_guardrails": _q(
            "FROM metrics-aws_bedrock.guardrails-default", f"| WHERE {TS}",
            "| STATS interventions = SUM(aws_bedrock.guardrails.guardrail_intervened_count) "
            "BY policy = aws_bedrock.guardrails.guardrail_policy_type",
            "| SORT interventions DESC"),
        "anthropic_tokens": _q(
            "FROM metrics-anthropic_metrics.usage-default", f"| WHERE {TS}",
            "| STATS tokens = SUM(anthropic.usage.input_tokens) + SUM(anthropic.usage.output_tokens)"),
        "anthropic_usage_model": _q(
            "FROM metrics-anthropic_metrics.usage-default", f"| WHERE {TS}",
            "| STATS input = SUM(anthropic.usage.input_tokens), "
            "output = SUM(anthropic.usage.output_tokens) "
            "BY model = anthropic.usage.model, kind = anthropic.usage.type",
            "| EVAL tokens = input + output", "| SORT tokens DESC", "| LIMIT 20"),
        "anthropic_cost_day": _q(
            "FROM metrics-anthropic_metrics.cost-default", f"| WHERE {TS}",
            "| STATS cost_usd = SUM(anthropic.cost.amount) / 100 "
            "BY day = BUCKET(@timestamp, 1d)", "| SORT day"),
        "anthropic_rate_limits": _q(
            "FROM metrics-anthropic_metrics.rate_limit-default", f"| WHERE {TS}",
            "| STATS remaining = AVG(anthropic.rate_limit.remaining), "
            "limit = AVG(anthropic.rate_limit.limit) BY model = anthropic.rate_limit.model",
            "| EVAL remaining_pct = remaining * 100.0 / limit", "| SORT remaining_pct"),
        "openai_tokens_model": _q(
            "FROM logs-openai.completions-default", f"| WHERE {TS}",
            "| STATS prompt = SUM(openai.completions.input_tokens), "
            "completion = SUM(openai.completions.output_tokens) "
            "BY model = openai.base.model, kind = openai.base.object",
            "| EVAL tokens = prompt + completion", "| SORT tokens DESC", "| LIMIT 20"),
        "openai_requests_model": _q(
            "FROM logs-openai.completions-default", f"| WHERE {TS}",
            "| STATS requests = SUM(openai.base.num_model_requests) "
            "BY model = openai.base.model", "| SORT requests DESC"),
        "openai_rate_limits": _q(
            "FROM logs-openai.rate_limits-default", f"| WHERE {TS}",
            "| STATS utilization = AVG(openai.rate_limits.max_requests_per_1_minute) "
            "BY model = openai.rate_limits.model", "| SORT utilization DESC"),
        "vertex_tokens_model": _q(
            "FROM logs-gcp_vertexai.prompt_response_logs-default", f"| WHERE {TS}",
            "| STATS tokens = SUM(gcp.vertexai.prompt_response_logs.full_response.usage_metadata.total_token_count) "
            "BY model = gcp.vertexai.prompt_response_logs.full_response.model_version",
            "| SORT tokens DESC", "| LIMIT 12"),
        "vertex_latency": _q(
            "FROM metrics-gcp_vertexai.metrics-default", f"| WHERE {TS}",
            "| STATS p95_ms = PERCENTILE(gcp.vertexai.metrics.value, 95) "
            "BY model = gcp.vertexai.metrics.model_user_id", "| SORT p95_ms DESC"),
        "vertex_audit": _q(
            "FROM logs-gcp_vertexai.auditlogs-default", f"| WHERE {TS}",
            "| STATS calls = COUNT(*) BY action = event.action",
            "| SORT calls DESC", "| LIMIT 12"),
        "az_oai_tokens": _q(
            "FROM logs-azure_openai.logs-default", f"| WHERE {TS}",
            "| STATS tokens = SUM(azure.open_ai.properties.backend_response_body.usage.total_tokens) "
            "BY deployment = azure.open_ai.properties.model_deployment_name",
            "| SORT tokens DESC"),
        "az_oai_category": _q(
            "FROM logs-azure_openai.logs-default", f"| WHERE {TS}",
            "| STATS requests = COUNT(*) BY category = azure.open_ai.category",
            "| SORT requests DESC"),
        "az_oai_cost_day": _q(
            "FROM metrics-azure.billing-default", f"| WHERE {TS}",
            '| WHERE azure.billing.product LIKE "*OpenAI*" OR azure.billing.meter_category == "Cognitive Services"',
            "| STATS cost = SUM(azure.billing.pretax_cost) BY day = BUCKET(@timestamp, 1d)",
            "| SORT day"),
    }


def build_baseline_sections(caps: DashboardCaps | None, label: str, vtitle: str) -> list:
    caps = caps or caps_from_variant()
    q = baseline_queries()
    if caps.cloud_mix_query(_q):
        q["cloud_mix"] = caps.cloud_mix_query(_q)
        q["daily_cloud"] = caps.daily_cloud_query(_q)

    sections: list = []
    y = 0

    def push(title: str, panels: list) -> None:
        nonlocal y
        if not panels:
            return
        sections.append(section(title, y, panels))
        y += _section_height(panels) + 2

    push("Scoreboard — sparkline KPIs", _baseline_scoreboard(caps, label, vtitle, q))
    push("Allocation — stacked bars, area, waffle", _baseline_allocation(caps, q))
    push("Usage vs cost — dual axis", _baseline_usage_cost(caps, q))
    if caps.budgets:
        sections.append(budget_posture_section(y))
        y += _section_height(sections[-1].get("panels") or []) + 2
    push("Amazon Bedrock — native integration", _baseline_bedrock_native(caps, q))
    push("Anthropic — native metrics", _baseline_anthropic_native(caps, q))
    push("OpenAI — native usage logs", _baseline_openai_native(caps, q))
    push("GCP Vertex AI — native logs & metrics", _baseline_vertex_native(caps, q))
    push("Azure OpenAI — native logs & billing", _baseline_azure_openai_native(caps, q))
    push("LLM landscape — models, teams, flows", _baseline_llm_landscape(caps, q))
    push("LLM tokens & latency over time", _baseline_llm_time(caps, q))
    push("Quality gauges & funnel", _baseline_llm_quality(caps, q))
    push("Provider packs", _baseline_provider_packs(caps))
    return sections


# --- Classic layout (variant-scoped) ---


def _classic_overview(caps: DashboardCaps, label: str, vtitle: str, q: dict) -> list:
    kpis = []
    if caps.aws_cur:
        kpis.append(("AWS unblended cost (CUR)", q["aws_cost"], "cost", "USD"))
    if caps.gcp_billing:
        kpis.append(("GCP billing total", q["gcp_cost"], "cost", "USD"))
    if caps.azure_billing:
        kpis.append(("Azure pretax cost", q["azure_cost"], "cost", "USD"))
    if caps.llm_apm:
        kpis.append(("LLM cost (APM traces)", q["llm_cost"], "cost", "USD"))
    panels = [
        markdown(0, 0, 48, 3,
                 f"## {vtitle}\n\n"
                 f"Classic layout scoped to this variant. Time range: **{label}**.\n\n"
                 f"**Baseline:** [FinOps dashboard](#/view/{dash_id('baseline')})."),
    ]
    panels.extend(_metric_row(3, kpis, h=5))
    y = 8 if kpis else 3
    if caps.multi_cloud_billing and q.get("cloud_mix"):
        panels.append(pie(0, y, 18, 12, "Spend mix by billing dataset",
                          q["cloud_mix"], "cost", "provider"))
        panels.append(xy(18, y, 30, 12, "Daily cost by cloud provider", q["daily_cloud"],
                         "day", ["cost"], layer="area", breakdown="provider"))
    return panels


def _classic_security(caps: DashboardCaps, q: dict) -> list:
    if not caps.aws_security:
        return []
    return [
        markdown(0, 0, 48, 3,
                 "## Security incidents that move spend\n\n"
                 "Crypto-mining and S3 exposure scenarios on `meridian-dev` / fintech."),
        metric(0, 3, 12, 5, "GuardDuty findings", q["gd_all"], "findings"),
        metric(12, 3, 12, 5, "Crypto findings", q["gd_crypto"], "crypto"),
        metric(24, 3, 12, 5, "S3 policy findings", q["gd_s3"], "s3_findings"),
        metric(36, 3, 12, 5, "CloudTrail from attacker IP", q["ct_attacker"], "events"),
        xy(0, 8, 24, 12, "GuardDuty findings by type", q["gd_by_type"],
           "finding", ["findings"], layer="bar"),
        xy(24, 8, 24, 12, "S3 / bucket CloudTrail actions", q["ct_bucket"],
           "action", ["calls"], layer="bar"),
        table(0, 20, 48, 10, "Recent high-severity GuardDuty findings", q["gd_table"],
              ["@timestamp", "rule.name", "cloud.account.id"],
              ["aws.guardduty.severity.value"]),
    ]


def _classic_allocation(caps: DashboardCaps, q: dict) -> list:
    panels = [
        markdown(0, 0, 48, 2,
                 "Allocation from native billing integrations for this variant."),
    ]
    y = 2
    if caps.aws_cur:
        panels.extend([
            xy(0, y, 24, 12, "AWS cost by linked account", q["aws_by_acct"],
               "account", ["cost"], layer="bar"),
            xy(24, y, 24, 12, "AWS cost by service", q["aws_by_svc"],
               "service", ["cost"], layer="bar"),
        ])
        y += 12
        if caps.aws_tags:
            panels.append(pie(0, y, 16, 12, "AWS Cost Explorer by cost_center tag",
                              q["cc_tag"], "cost", "tag"))
    if caps.gcp_billing:
        panels.append(xy(16 if caps.aws_tags else 0, y, 16, 12, "GCP cost by project",
                         q["gcp_by_proj"], "project", ["cost"], layer="bar"))
    if caps.azure_billing:
        panels.append(xy(32 if caps.gcp_billing else 16, y, 16, 12, "Azure cost by subscription",
                         q["azure_by_sub"], "subscription", ["cost"], layer="bar"))
    return panels


def _classic_engineering(caps: DashboardCaps, q: dict) -> list:
    if not (caps.aws_cur and caps.aws_ec2):
        return []
    return [
        markdown(0, 0, 48, 2, "EC2 CUR spend vs network usage (cost-leak pattern on staging)."),
        xy(0, 2, 24, 11, "AWS EC2 daily unblended cost", q["ec2_cost_day"],
           "day", ["cost"], layer="line"),
        xy(24, 2, 24, 11, "EC2 NetworkIn rate (usage proxy)", q["net_day"],
           "day", ["network_in"], layer="line"),
    ]


def _classic_llm_traces(caps: DashboardCaps, q: dict) -> list:
    if not caps.llm_apm:
        return []
    return [
        markdown(0, 0, 48, 2, "APM `gen_ai` spans — tokens, cost, latency, outcome."),
        metric(0, 2, 12, 5, "LLM calls", q["llm_calls"], "calls"),
        metric(12, 2, 12, 5, "Total tokens", q["llm_tokens"], "tokens"),
        metric(24, 2, 12, 5, "Prompt tokens", q["llm_prompt"], "prompt"),
        metric(36, 2, 12, 5, "Completion tokens", q["llm_completion"], "completion"),
        table(0, 7, 48, 14, "Recent LLM calls", q["llm_table"],
              ["@timestamp", "trace.id", "service.name", "gen_ai.request.model",
               "gen_ai.system", "event.outcome", "labels.team", "labels.env"],
              ["gen_ai.usage.input_tokens", "gen_ai.usage.output_tokens",
               "gen_ai.usage.total_tokens", "cost_usd", "latency_ms"]),
    ]


def _classic_llm_funnel(caps: DashboardCaps, q: dict) -> list:
    if not caps.llm_apm:
        return []
    return [
        markdown(0, 0, 48, 3, "User flows ranked by tokens and cost."),
        xy(0, 3, 28, 14, "Tokens consumed by user flow", q["flow_funnel"],
           "flow", ["tokens"], layer="bar"),
        pie(28, 3, 20, 14, "Token share by flow", q["flow_share"], "tokens", "flow"),
    ]


def classic_queries() -> dict:
    q = baseline_queries()
    q.update({
        "aws_cost": _q("FROM metrics-aws_billing.cur-default", f"| WHERE {TS}",
                       "| STATS cost = SUM(aws_billing.cur.line_item.unblended_cost)"),
        "gcp_cost": _q("FROM metrics-gcp.billing-default", f"| WHERE {TS}",
                       "| STATS cost = SUM(gcp.billing.total)"),
        "azure_cost": _q("FROM metrics-azure.billing-default", f"| WHERE {TS}",
                         "| STATS cost = SUM(azure.billing.pretax_cost)"),
        "llm_cost": _q("FROM traces-apm-default", f'| WHERE {TS} AND span.subtype == "gen_ai"',
                        "| EVAL cost = TO_DOUBLE(labels.llm_cost_usd)", "| STATS cost = SUM(cost)"),
        "gd_all": _q("FROM logs-aws.guardduty-default", f"| WHERE {TS}", "| STATS findings = COUNT(*)"),
        "gd_crypto": _q("FROM logs-aws.guardduty-default", f"| WHERE {TS}",
                        '| WHERE rule.name LIKE "CryptoCurrency*"', "| STATS crypto = COUNT(*)"),
        "gd_s3": _q("FROM logs-aws.guardduty-default", f"| WHERE {TS}",
                    '| WHERE rule.name LIKE "Policy:S3*"', "| STATS s3_findings = COUNT(*)"),
        "ct_attacker": _q("FROM logs-aws.cloudtrail-default", f"| WHERE {TS}",
                          '| WHERE source.ip == "185.220.101.34"', "| STATS events = COUNT(*)"),
        "gd_by_type": _q("FROM logs-aws.guardduty-default", f"| WHERE {TS}",
                         "| STATS findings = COUNT(*) BY finding = rule.name",
                         "| SORT findings DESC", "| LIMIT 12"),
        "ct_bucket": _q("FROM logs-aws.cloudtrail-default", f"| WHERE {TS}",
                        '| WHERE event.action LIKE "*Bucket*" OR event.action LIKE "*Object*"',
                        "| STATS calls = COUNT(*) BY action = event.action",
                        "| SORT calls DESC", "| LIMIT 12"),
        "gd_table": _q("FROM logs-aws.guardduty-default", f"| WHERE {TS}",
                       "| SORT @timestamp DESC",
                       "| KEEP @timestamp, rule.name, aws.guardduty.severity.value, cloud.account.id",
                       "| LIMIT 40"),
        "aws_by_acct": _q("FROM metrics-aws_billing.cur-default", f"| WHERE {TS}",
                          "| STATS cost = SUM(aws_billing.cur.line_item.unblended_cost) "
                          "BY account = aws_billing.cur.line_item.usage_account_name",
                          "| SORT cost DESC", "| LIMIT 12"),
        "aws_by_svc": _q("FROM metrics-aws_billing.cur-default", f"| WHERE {TS}",
                         "| STATS cost = SUM(aws_billing.cur.line_item.unblended_cost) "
                         "BY service = aws_billing.cur.product.product",
                         "| SORT cost DESC", "| LIMIT 12"),
        "gcp_by_proj": _q("FROM metrics-gcp.billing-default", f"| WHERE {TS}",
                          "| STATS cost = SUM(gcp.billing.total) BY project = gcp.billing.project_name",
                          "| SORT cost DESC"),
        "azure_by_sub": _q("FROM metrics-azure.billing-default", f"| WHERE {TS}",
                           "| STATS cost = SUM(azure.billing.pretax_cost) "
                           "BY subscription = azure.subscription_id", "| SORT cost DESC"),
        "llm_calls": _q("FROM traces-apm-default", f'| WHERE {TS} AND span.subtype == "gen_ai"',
                         "| STATS calls = COUNT(*)"),
        "llm_tokens": _q("FROM traces-apm-default", f'| WHERE {TS} AND span.subtype == "gen_ai"',
                         "| STATS tokens = SUM(gen_ai.usage.total_tokens)"),
        "llm_prompt": _q("FROM traces-apm-default", f'| WHERE {TS} AND span.subtype == "gen_ai"',
                          "| STATS prompt = SUM(gen_ai.usage.input_tokens)"),
        "llm_completion": _q("FROM traces-apm-default", f'| WHERE {TS} AND span.subtype == "gen_ai"',
                             "| STATS completion = SUM(gen_ai.usage.output_tokens)"),
        "llm_table": _q("FROM traces-apm-default", f'| WHERE {TS} AND span.subtype == "gen_ai"',
                        "| EVAL cost_usd = TO_DOUBLE(labels.llm_cost_usd), "
                        "latency_ms = span.duration.us / 1000.0",
                        "| SORT @timestamp DESC",
                        "| KEEP @timestamp, trace.id, service.name, gen_ai.request.model, "
                        "gen_ai.system, gen_ai.usage.input_tokens, gen_ai.usage.output_tokens, "
                        "gen_ai.usage.total_tokens, cost_usd, latency_ms, event.outcome, "
                        "labels.team, labels.env", "| LIMIT 100"),
        "flow_funnel": _q("FROM traces-apm-default", f'| WHERE {TS} AND span.subtype == "gen_ai"',
                          "| EVAL cost = TO_DOUBLE(labels.llm_cost_usd)",
                          "| STATS tokens = SUM(gen_ai.usage.total_tokens), cost_usd = SUM(cost), "
                          "calls = COUNT(*) BY flow = service.name", "| SORT tokens DESC"),
        "flow_share": _q("FROM traces-apm-default", f'| WHERE {TS} AND span.subtype == "gen_ai"',
                         "| STATS tokens = SUM(gen_ai.usage.total_tokens) BY flow = service.name",
                         "| SORT tokens DESC"),
    })
    return q


def build_classic_sections(caps: DashboardCaps | None, label: str, vtitle: str) -> list:
    caps = caps or caps_from_variant()
    q = classic_queries()
    if caps.cloud_mix_query(_q):
        q["cloud_mix"] = caps.cloud_mix_query(_q)
        q["daily_cloud"] = caps.daily_cloud_query(_q)

    link_panels = _baseline_provider_packs(caps)
    sections: list = []
    y = 0

    def push(title: str, panels: list) -> None:
        nonlocal y
        if not panels:
            return
        sections.append(section(title, y, panels))
        y += _section_height(panels) + 2

    push("FinOps integration — native provider dashboards", [
        markdown(0, 0, 20, 10,
                 "OOTB Elastic integration dashboards for this variant. "
                 "Open with the same time range."),
        *link_panels,
    ])
    push("Overview — spend KPIs", _classic_overview(caps, label, vtitle, q))
    push("Security → cost — crypto mining & S3 exposure", _classic_security(caps, q))
    push("Cost allocation", _classic_allocation(caps, q))
    push("Engineering & Ops — usage correlated with cost", _classic_engineering(caps, q))
    if caps.budgets:
        sections.append(budget_posture_section(y))
        y += _section_height(sections[-1].get("panels") or []) + 2
    push("LLM traces — end-to-end call, tokens, and cost", _classic_llm_traces(caps, q))
    push("Funnel — which user flows consume the most tokens", _classic_llm_funnel(caps, q))
    return sections
