"""Publish ELK Co FinOps + LLM Observability Kibana dashboards.

Uses the Kibana Dashboards API (inline ES|QL visualizations) so the panels
query native integration data streams already in the project.
"""
import json

import requests

from src.agent_builder import AGENT_CHAT_URL, agent_id
from src.budgets import budget_numbers
from src.config import KBN_HEADERS, KIBANA_ROOT, KIBANA_URL
from src.time_window import demo_window, window_label
from src.variant import active_variant, filter_o_otb_links

DASHBOARD_ID = "elk-finops-llm-observability"
DASHBOARD_ID_CLASSIC = "elk-finops-llm-observability-classic"
DASHBOARD_ID_DYNAMIC = "elk-finops-llm-observability-dynamic"  # alias of baseline
DASHBOARD_ID_AI = "elk-ai-assistant-inference-usage"
DASHBOARD_ID_INFERENCE_USAGE = "kibana-inference-token-usage"

# Short labels appended to the ELK Co hub title.
DASHBOARD_SCOPE_LABELS = {
    "all": "",
    "aws": "AWS",
    "gcp": "GCP + Vertex AI",
    "azure": "Azure + Azure OpenAI",
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "bedrock": "Amazon Bedrock",
    "elastic-ai": "Elastic AI",
}


def dash_id(which: str) -> str:
    """Kibana dashboard id for the active workshop variant."""
    bases = {
        "baseline": DASHBOARD_ID,
        "classic": DASHBOARD_ID_CLASSIC,
        "dynamic": DASHBOARD_ID_DYNAMIC,
        "ai": DASHBOARD_ID_AI,
    }
    return bases[which] + active_variant().dash_suffix()


def finops_dashboard_title(*, classic: bool = False) -> str:
    """`[ELK Co] FinOps & LLM Observability` plus the variant scope."""
    v = active_variant()
    base = "[ELK Co] FinOps & LLM Observability"
    scope = DASHBOARD_SCOPE_LABELS.get(v.id, v.id)
    title = f"{base} — {scope}" if scope else base
    if classic:
        title += " — classic"
    return title


def finops_dashboard_description(*, classic: bool = False) -> str:
    v = active_variant()
    layout = "Classic layout" if classic else "Baseline layout"
    scope = DASHBOARD_SCOPE_LABELS.get(v.id) or v.title
    if v.is_all:
        return f"{layout}: multi-cloud FinOps + LLM observability."
    return (
        f"{layout} for {scope}: only panels whose data is seeded by the "
        f"{v.id} workshop variant."
    )


_DASH_EXISTS_CACHE: dict[str, bool] = {}


def clear_dashboard_exists_cache() -> None:
    _DASH_EXISTS_CACHE.clear()


def dashboard_exists(did: str) -> bool:
    """True if the Dashboards API can load this id in the active or default space."""
    if not did or did.startswith("/"):
        return True
    if did in _DASH_EXISTS_CACHE:
        return _DASH_EXISTS_CACHE[did]
    for base in (KIBANA_URL, KIBANA_ROOT):
        try:
            r = requests.get(
                f"{base}/api/dashboards/{did}",
                headers=KBN_HEADERS, timeout=20,
            )
        except requests.RequestException:
            continue
        if r.status_code == 200:
            _DASH_EXISTS_CACHE[did] = True
            return True
    _DASH_EXISTS_CACHE[did] = False
    return False


def resolve_link_item(label: str, dest: str, *, short: str | None = None):
    """Normalize an OOTB/hub tab item to ``(display_label, destination)``."""
    return (short or label, dest)


def _ootb_items():
    """Variant-filtered OOTB dashboard links."""
    return [
        resolve_link_item(label, dest)
        for label, dest in filter_o_otb_links(OOTB).items()
    ]

# Resolved at publish time (see src.time_window); kept as module attrs for imports.
_WINDOW = demo_window()
TIME_FROM = _WINDOW["from"]
TIME_TO = _WINDOW["to"]

TS = "@timestamp >= ?_tstart AND @timestamp <= ?_tend"

OOTB = {
    "[Metrics ESS Billing] Billing dashboard": "ess_billing-billingdashboard",
    "[Metrics ESS Billing] Credits dashboard": "ess_billing-creditsdashboard",
    "AWS CUR — current month": "aws_billing-01aace34-9219-4c6c-80a9-b903af48950f",
    "AWS CUR — all time": "aws_billing-81918d21-70c6-4bc0-a03e-9e298460a525",
    "GCP Billing Overview": "gcp-76c9e920-e890-11ea-bf8c-d13ebf358a78",
    "Azure Billing Overview": "azure_billing-d3efeb30-c1c7-11ea-b7e7-0f48178cdb3c",
    "Anthropic Cost & Billing": "anthropic_metrics-2bd61c2c-4418-458f-a79e-12a74c34b2f0",
    "OpenAI Usage Overview": "openai-651bb059-f606-44fc-b704-2078d0af26da",
    "Azure OpenAI Billing": "azure_openai-f5bbc591-5e6b-4af7-b6c5-b02065a06455",
    "Azure OpenAI Overview": "azure_openai-21d9a0d0-e6a0-4b34-bc6d-ce6560a1dab3",
    "Amazon Bedrock Overview": "aws_bedrock-2a19b571-251b-487b-84b2-abd887efb8a4",
    "Amazon Bedrock Guardrails": "aws_bedrock-14fd745a-d3c1-4ebe-bd25-00b465336cde",
    "GCP Vertex AI Metrics": "gcp_vertexai-1b42c117-7971-424d-8015-c02f1317824d",
    "[Elastic] Inference Token Usage": DASHBOARD_ID_INFERENCE_USAGE,
}


def _q(*lines):
    return "\n".join(lines)


def _esql(query):
    return {"type": "esql", "query": query}


def _grid(x, y, w, h):
    return {"x": x, "y": y, "w": w, "h": h}


def markdown(x, y, w, h, content, title=""):
    return {
        "grid": _grid(x, y, w, h),
        "type": "markdown",
        "config": {"content": content, "title": title, "hide_title": not title},
    }


def metric(x, y, w, h, title, query, column, subtitle=None, trend=False):
    primary = {"type": "primary", "column": column}
    if subtitle:
        primary["subtitle"] = subtitle
    if trend:
        primary["background_chart"] = {"type": "trend"}
    return {
        "grid": _grid(x, y, w, h),
        "type": "vis",
        "config": {
            "type": "metric",
            "title": title,
            "data_source": _esql(query),
            "metrics": [primary],
        },
    }


def gauge(x, y, w, h, title, query, column, shape="arc",
          min_col=None, max_col=None, goal_col=None, subtitle=None):
    metric_cfg = {"column": column, "ticks": {"visible": True, "mode": "bands"}}
    if subtitle:
        metric_cfg["subtitle"] = subtitle
    if min_col:
        metric_cfg["min"] = {"column": min_col}
    if max_col:
        metric_cfg["max"] = {"column": max_col}
    if goal_col:
        metric_cfg["goal"] = {"column": goal_col}
    shape_cfg = {"type": "bullet", "orientation": "horizontal"} if shape == "bullet" else {"type": shape}
    return {
        "grid": _grid(x, y, w, h),
        "type": "vis",
        "config": {
            "type": "gauge",
            "title": title,
            "data_source": _esql(query),
            "metric": metric_cfg,
            "styling": {"shape": shape_cfg},
        },
    }


def treemap(x, y, w, h, title, query, metric_col, group_cols):
    return {
        "grid": _grid(x, y, w, h),
        "type": "vis",
        "config": {
            "type": "treemap",
            "title": title,
            "data_source": _esql(query),
            "metrics": [{"column": metric_col}],
            "group_by": [{"column": c} for c in group_cols],
            "styling": {
                "labels": {"visible": True},
                "values": {"visible": True, "mode": "percentage"},
            },
            "legend": {"visibility": "visible", "position": "right"},
        },
    }


def heatmap(x, y, w, h, title, query, metric_col, x_col, y_col):
    # ES|QL heatmaps need `y` (not breakdown_by — that is accepted then stripped).
    # Vertical x labels avoid overlapping daily date ticks on ~30d windows.
    return {
        "grid": _grid(x, y, w, h),
        "type": "vis",
        "config": {
            "type": "heatmap",
            "title": title,
            "data_source": _esql(query),
            "metric": {"column": metric_col},
            "x": {"column": x_col},
            "y": {"column": y_col},
            "legend": {"visibility": "visible", "position": "right"},
            "axis": {
                "x": {
                    "title": {"text": "", "visible": False},
                    "labels": {"visible": True, "orientation": "vertical"},
                    "scale": "ordinal",
                },
                "y": {
                    "labels": {"visible": True},
                    "title": {"visible": False},
                },
            },
        },
    }


def waffle(x, y, w, h, title, query, metric_col, group_col):
    return {
        "grid": _grid(x, y, w, h),
        "type": "vis",
        "config": {
            "type": "waffle",
            "title": title,
            "data_source": _esql(query),
            "metrics": [{"column": metric_col}],
            "group_by": [{"column": group_col}],
            "legend": {"visibility": "visible", "position": "right"},
        },
    }


def tag_cloud(x, y, w, h, title, query, metric_col, tag_col):
    return {
        "grid": _grid(x, y, w, h),
        "type": "vis",
        "config": {
            "type": "tag_cloud",
            "title": title,
            "data_source": _esql(query),
            "metric": {"column": metric_col},
            "tag_by": {"column": tag_col},
            "styling": {
                "font_size": {"min": 14, "max": 72},
                "caption": {"visible": False},
            },
        },
    }


def xy(x, y, w, h, title, query, x_col, y_cols, layer="bar", breakdown=None,
       y2_cols=None):
    y_axis = [{"column": c} for c in y_cols]
    if y2_cols:
        y_axis += [{"column": c, "axis": "y2"} for c in y2_cols]
    layer_cfg = {
        "type": layer,
        "data_source": _esql(query),
        "x": {"column": x_col},
        "y": y_axis,
    }
    if breakdown:
        layer_cfg["breakdown_by"] = {"column": breakdown}
    styling = None
    if layer in ("area", "area_stacked", "area_percentage", "line"):
        styling = {
            "interpolation": "smooth",
            "areas": {"fill": "gradient", "fill_opacity": 0.75},
            "points": {"visibility": "auto"},
        }
    config = {
        "type": "xy",
        "title": title,
        "layers": [layer_cfg],
        "legend": {"visibility": "visible", "position": "right"},
        "axis": {
            "x": {"title": {"visible": True}},
            "y": {"title": {"visible": True}},
            "y2": {"title": {"visible": True}} if y2_cols else {"title": {"visible": False}},
        },
    }
    if styling:
        config["styling"] = styling
    return {
        "grid": _grid(x, y, w, h),
        "type": "vis",
        "config": config,
    }


def xy_dual(x, y, w, h, title, layer_a, layer_b):
    """Two ES|QL layers; second series is intended for the Y2 axis."""
    return {
        "grid": _grid(x, y, w, h),
        "type": "vis",
        "config": {
            "type": "xy",
            "title": title,
            "layers": [layer_a, layer_b],
            "legend": {"visibility": "visible", "position": "right"},
            "axis": {
                "x": {"title": {"visible": True}},
                "y": {"title": {"visible": True}},
                "y2": {"title": {"visible": True}},
            },
            "styling": {
                "interpolation": "smooth",
                "areas": {"fill": "gradient", "fill_opacity": 0.55},
            },
        },
    }


def pie(x, y, w, h, title, query, metric_col, group_col):
    return {
        "grid": _grid(x, y, w, h),
        "type": "vis",
        "config": {
            "type": "pie",
            "title": title,
            "data_source": _esql(query),
            "metrics": [{"column": metric_col}],
            "group_by": [{"column": group_col}],
            "styling": {
                "donut_hole": "m",
                "labels": {"visible": True, "position": "inside"},
                "values": {"visible": True, "mode": "percentage"},
            },
            "legend": {"visibility": "visible", "position": "right"},
        },
    }


def table(x, y, w, h, title, query, rows, metrics, ignore_global_filters=False):
    return {
        "grid": _grid(x, y, w, h),
        "type": "vis",
        "config": {
            "type": "data_table",
            "title": title,
            "ignore_global_filters": ignore_global_filters,
            "data_source": _esql(query),
            "rows": [{"column": c} for c in rows],
            "metrics": [{"column": c} for c in metrics],
            "styling": {"paging": 20, "row_numbers": {"visible": True}},
        },
    }


def links_panel(x, y, w, h, title, items, *, layout=None, hide_title=False,
                open_in_new_tab=True, use_filters=False):
    """Links embeddable. Use layout='horizontal' for AWS-hub-style tab bars.

    Each item is ``(label, destination)`` for a dashboard link, or
    ``(label, destination, "externalLink")`` for an app/path URL (e.g. ``/app/apm``).
    """
    links = []
    for item in items:
        if len(item) == 3:
            label, dest, ltype = item
        else:
            label, dest = item[0], item[1]
            ltype = "externalLink" if str(dest).startswith("/") else "dashboardLink"
        if ltype == "externalLink":
            links.append({
                "label": label,
                "type": "externalLink",
                "destination": dest,
                "options": {"open_in_new_tab": open_in_new_tab},
            })
        else:
            links.append({
                "label": label,
                "type": "dashboardLink",
                "destination": dest,
                "options": {
                    "use_filters": use_filters,
                    "use_time_range": True,
                    "open_in_new_tab": open_in_new_tab,
                },
            })
    cfg = {
        "title": title,
        "hide_title": hide_title,
        "links": links,
    }
    if layout:
        cfg["layout"] = layout
    return {
        "grid": _grid(x, y, w, h),
        "type": "links",
        "config": cfg,
    }


# Short hub-tab labels (AWS live hub style) for OOTB + family dashboards.
_HUB_TAB_SHORT = {
    "GCP Billing Overview": "GCP Billing",
    "Azure Billing Overview": "Azure Billing",
    "AWS CUR — current month": "AWS CUR",
    "AWS CUR — all time": "AWS CUR (all time)",
    "GCP Vertex AI Metrics": "Vertex AI",
    "Azure OpenAI Overview": "Azure OpenAI",
    "Azure OpenAI Billing": "Azure OpenAI Billing",
    "Amazon Bedrock Overview": "Bedrock",
    "Amazon Bedrock Guardrails": "Bedrock Guardrails",
    "OpenAI Usage Overview": "OpenAI",
    "Anthropic Cost & Billing": "Anthropic",
    "[Elastic] Inference Token Usage": "Inference tokens",
    "[Metrics ESS Billing] Billing dashboard": "ESS Billing",
    "[Metrics ESS Billing] Credits dashboard": "ESS Credits",
}

# Stable left→right order matching the AWS hub (Overview first, then billing,
# provider LLM, inference, ESS).
_HUB_TAB_OOTB_ORDER = (
    "GCP Billing Overview",
    "Azure Billing Overview",
    "AWS CUR — current month",
    "GCP Vertex AI Metrics",
    "Azure OpenAI Overview",
    "Amazon Bedrock Overview",
    "OpenAI Usage Overview",
    "Anthropic Cost & Billing",
    "[Elastic] Inference Token Usage",
    "[Metrics ESS Billing] Billing dashboard",
    "[Metrics ESS Billing] Credits dashboard",
)


def hub_tabs_items(caps=None):
    """Horizontal hub-tab destinations for the active workshop variant."""
    from src.dashboard_caps import caps_from_variant
    caps = caps or caps_from_variant()
    items = [("Overview", dash_id("baseline"))]
    ootb = filter_o_otb_links(OOTB)
    for full in _HUB_TAB_OOTB_ORDER:
        dest = ootb.get(full)
        if dest:
            items.append(resolve_link_item(
                full, dest, short=_HUB_TAB_SHORT.get(full, full)))
    if caps.ai_dashboard:
        items.append(("AI Assistant", dash_id("ai")))
    return items


def hub_tabs_panel(caps=None):
    """Full-width horizontal FinOps tab bar (same UX as the AWS live hub)."""
    return links_panel(
        0, 0, 48, 5, "FinOps dashboards", hub_tabs_items(caps),
        layout="horizontal", hide_title=False,
        open_in_new_tab=False, use_filters=True,
    )


def section(title, y, panels, collapsed=False):
    return {
        "title": title,
        "collapsed": collapsed,
        "grid": {"y": y},
        "panels": panels,
    }


def budget_posture_section(y: int, caps=None):
    """FinOps spend vs ceilings — gauges match the active workshop variant."""
    from src.dashboard_caps import caps_from_variant
    caps = caps or caps_from_variant()
    b = budget_numbers()
    checkout_7d = float(b["checkout_7d_alert_usd"])
    checkout_daily = float(b["checkout_daily_ceiling_usd"])
    bullets = []
    gauges = []

    if caps.aws_cur:
        aws_mtd = float(b["aws_monthly_usd"])
        staging_ceil = float(b["staging_daily_ceiling_usd"])
        aws_daily = float(b["aws_daily_ceiling_usd"])
        bullets.extend([
            f"- **AWS monthly budget:** ${aws_mtd:,.0f} · **AWS daily SLO ceiling:** ${aws_daily:,.0f}",
            f"- **Staging daily SLO ceiling:** ${staging_ceil:,.0f} (cost_leak)",
        ])
        gauges.extend([
            ("AWS window spend vs monthly budget", _q(
                "FROM metrics-aws_billing.cur-default", f"| WHERE {TS}",
                "| STATS spend = SUM(aws_billing.cur.line_item.unblended_cost)",
                f"| EVAL budget = {aws_mtd}, min = 0, max = budget * 2, goal = budget",
            ), "USD (goal = budget)"),
            ("Latest AWS daily vs SLO ceiling", _q(
                "FROM metrics-aws_billing.cur-default", f"| WHERE {TS}",
                "| STATS daily = SUM(aws_billing.cur.line_item.unblended_cost) "
                "BY day = BUCKET(@timestamp, 1d)",
                "| SORT day DESC", "| LIMIT 1",
                f"| EVAL spend = daily, budget = {aws_daily}, min = 0, max = budget * 2, goal = budget",
                "| KEEP spend, budget, min, max, goal",
            ), "USD / day"),
            ("Staging latest day vs SLO ceiling", _q(
                "FROM metrics-aws_billing.cur-default", f"| WHERE {TS}",
                '| WHERE aws_billing.cur.line_item.usage_account_name == "elk-staging"',
                "| STATS daily = SUM(aws_billing.cur.line_item.unblended_cost) "
                "BY day = BUCKET(@timestamp, 1d)",
                "| SORT day DESC", "| LIMIT 1",
                f"| EVAL spend = daily, budget = {staging_ceil}, min = 0, max = budget * 8, goal = budget",
                "| KEEP spend, budget, min, max, goal",
            ), "elk-staging"),
        ])

    if caps.gcp_billing:
        gcp_ml = float(b["gcp_ml_7d_alert_usd"])
        gcp_daily_goal = gcp_ml / 7.0
        bullets.append(
            f"- **GCP elk-ml-prod 7d alert:** ${gcp_ml:,.0f} "
            f"(~${gcp_daily_goal:,.0f}/day)"
        )
        gauges.extend([
            ("GCP ML project vs 7d alert", _q(
                "FROM metrics-gcp.billing-default", f"| WHERE {TS}",
                '| WHERE gcp.billing.project_name == "elk-ml-prod"',
                "| STATS spend = SUM(gcp.billing.total)",
                f"| EVAL budget = {gcp_ml}, min = 0, max = budget * 3, goal = budget",
            ), "elk-ml-prod"),
            ("Latest GCP daily vs 7d/7 goal", _q(
                "FROM metrics-gcp.billing-default", f"| WHERE {TS}",
                "| STATS daily = SUM(gcp.billing.total) BY day = BUCKET(@timestamp, 1d)",
                "| SORT day DESC", "| LIMIT 1",
                f"| EVAL spend = daily, budget = {gcp_daily_goal}, min = 0, "
                "max = budget * 4, goal = budget",
                "| KEEP spend, budget, min, max, goal",
            ), "USD / day"),
        ])

    if caps.azure_billing:
        gauges.append((
            "Azure pretax (window)",
            _q(
                "FROM metrics-azure.billing-default", f"| WHERE {TS}",
                "| STATS spend = SUM(azure.billing.pretax_cost)",
                "| EVAL budget = spend, min = 0, max = spend * 2, goal = spend",
            ),
            "USD pretax",
        ))
        bullets.append("- **Azure pretax:** window total (no dedicated SLO ceiling in budgets.yaml).")

    if caps.llm_apm:
        bullets.append(
            f"- **checkout-assistant daily SLO ceiling:** ${checkout_daily:.2f} · "
            f"**7d alert floor:** ${checkout_7d:.2f} (agent-loop)"
        )
        gauges.append((
            "checkout-assistant window vs alert",
            _q(
                "FROM traces-apm-default",
                f'| WHERE {TS} AND span.subtype == "gen_ai" AND service.name == "checkout-assistant"',
                "| EVAL cost = TO_DOUBLE(labels.llm_cost_usd)",
                "| STATS spend = SUM(cost)",
                f"| EVAL budget = {checkout_7d}, min = 0, max = budget * 3, goal = budget",
            ),
            "USD LLM (APM)",
        ))

    slo_posture = _q(
        "FROM .slo-observability.summary-v3.6",
        '| WHERE slo.id LIKE "elk-*" AND status != "NO_DATA"',
        "| EVAL eb_remaining_pct = ROUND(errorBudgetRemaining * 100, 1)",
        "| KEEP slo.name, status, eb_remaining_pct, errorBudgetConsumed, sliValue",
        "| SORT status DESC, slo.name",
    )
    intro = (
        "## Budget posture\n\n"
        "ELK Co treats cloud + LLM spend as error budgets. Thresholds come from "
        "`config/budgets.yaml` (intentionally tight so the seeded timeline shows breaches).\n\n"
        + ("\n".join(bullets) + "\n\n" if bullets else "")
        + f"[Observability SLOs]({KIBANA_URL}/app/observability/slos) · "
        f"[Observability Alerts]({KIBANA_URL}/app/observability/alerts) · "
        f"[Alerting rules]({KIBANA_URL}/app/management/insightsAndAlerting/triggersActions/rules)\n\n"
        f"**ELK Co FinOps AI Assistant:** [Open in Agent Builder]({AGENT_CHAT_URL}) "
        f"(agent `{agent_id()}`). Provision: `python -m src.cli agent` · `python -m src.cli budgets`."
    )
    panels = [markdown(0, 0, 48, 4, intro)]
    if gauges:
        w = max(48 // len(gauges), 8)
        for i, (title, query, subtitle) in enumerate(gauges):
            panels.append(gauge(
                i * w, 4, w, 12, title, query, "spend", shape="arc",
                min_col="min", max_col="max", goal_col="goal", subtitle=subtitle,
            ))
        table_y = 16
    else:
        table_y = 4
    panels.append(table(
        0, table_y, 48, 10, "ELK Co spend SLO posture (error budget)",
        slo_posture,
        rows=["slo.name", "status"],
        metrics=["eb_remaining_pct", "errorBudgetConsumed", "sliValue"],
        ignore_global_filters=True,
    ))
    return section("Budget posture — spend SLOs & alerts", y, panels)


def _ensure_data_view(view_id, title, time_field="@timestamp"):
    r = requests.get(f"{KIBANA_URL}/api/data_views/data_view/{view_id}",
                     headers=KBN_HEADERS, timeout=30)
    if r.status_code == 200:
        print(f"  [ok] data view {view_id}")
        return
    r = requests.post(
        f"{KIBANA_URL}/api/data_views/data_view",
        headers=KBN_HEADERS, timeout=30,
        json={"data_view": {
            "id": view_id,
            "title": title,
            "name": title,
            "timeFieldName": time_field,
        }, "override": True},
    )
    if r.status_code >= 300:
        print(f"  [warn] data view {view_id}: {r.status_code} {r.text[:240]}")
    else:
        print(f"  [ok] data view {view_id} created")


def build_classic_dashboard():
    from src.dashboard_sections import build_classic_sections
    win = demo_window()
    label = window_label()
    vtitle = active_variant().title
    panels = build_classic_sections(None, label, vtitle)

    return {
        "title": finops_dashboard_title(classic=True),
        "description": finops_dashboard_description(classic=True),
        "time_range": win,
        "options": {
            "use_margins": True,
            "sync_colors": False,
            "sync_cursor": True,
            "sync_tooltips": False,
            "hide_panel_titles": False,
        },
        "query": {"expression": "", "language": "kql"},
        "panels": panels,
    }


def build_dashboard():
    """Baseline ELK Co FinOps + LLM dashboard (variant-scoped panels)."""
    from src.dashboard_sections import build_baseline_sections
    win = demo_window()
    label = window_label()
    vtitle = active_variant().title
    panels = build_baseline_sections(None, label, vtitle)

    return {
        "title": finops_dashboard_title(),
        "description": finops_dashboard_description(),
        "time_range": win,
        "options": {
            "use_margins": True,
            "sync_colors": True,
            "sync_cursor": True,
            "sync_tooltips": True,
            "hide_panel_titles": False,
        },
        "query": {"expression": "", "language": "kql"},
        "pinned_panels": [
            {
                "type": "time_slider_control",
                "width": "large",
                "grow": True,
                "config": {"title": "Scrub time"},
            }
        ],
        "panels": panels,
    }
def _put_dashboard(dash_id, body):
    r = requests.put(
        f"{KIBANA_URL}/api/dashboards/{dash_id}",
        headers=KBN_HEADERS, timeout=60, json=body,
    )
    if r.status_code >= 300:
        err = r.text
        # Only strip pinned_panels when that field itself is rejected (not when
        # "time_slider_control" merely appears in the allowed-types list).
        if "pinned_panels" in err and (
            "Unrecognized" in err or "not allowed" in err
            or '"path": [\n            "pinned_panels"' in err
            or '"pinned_panels"' in err and "Invalid" in err
        ):
            body = dict(body)
            body.pop("pinned_panels", None)
            print(f"  retrying {dash_id} without pinned_panels ...")
            r = requests.put(
                f"{KIBANA_URL}/api/dashboards/{dash_id}",
                headers=KBN_HEADERS, timeout=60, json=body,
            )
            err = r.text if r.status_code >= 300 else err
        if r.status_code >= 300 and "styling" in err and "cells" in err:
            body = json.loads(json.dumps(body))
            for panel in body.get("panels") or []:
                cfg = panel.get("config") or {}
                cfg.pop("styling", None)
                for child in panel.get("panels") or []:
                    (child.get("config") or {}).pop("styling", None)
            print(f"  retrying {dash_id} without vis styling ...")
            r = requests.put(
                f"{KIBANA_URL}/api/dashboards/{dash_id}",
                headers=KBN_HEADERS, timeout=60, json=body,
            )
        if r.status_code >= 300:
            print(f"[fail] {dash_id} {r.status_code}")
            try:
                print(json.dumps(r.json(), indent=2)[:5000])
            except Exception:
                print(err[:4000])
            raise SystemExit(1)
    url = f"{KIBANA_URL}/app/dashboards#/view/{dash_id}"
    print(f"[ok] {r.status_code} {body['title']}")
    print(f"  {url}")
    return url


def publish(include_baseline=True, include_classic=False, include_dynamic_alias=True,
            include_ai=True):
    """Publish FinOps dashboards.

    Baseline is the current stacked-bar/area layout (former \"dynamic\").
    Classic is the older table/bar layout with the security→cost section.
    The -dynamic Kibana id is kept as an alias of baseline for existing links.
    """
    from src.profile import uses_live_aws_hub

    if uses_live_aws_hub():
        from src.live_dashboards import publish as live_publish
        return live_publish()
    clear_dashboard_exists_cache()
    v = active_variant()
    print(f"== {finops_dashboard_title()} (variant={v.id}) ==")
    if not v.is_all:
        include_baseline = v.dashboards.get("baseline", False)
        include_classic = v.dashboards.get("classic", False)
        include_dynamic_alias = v.dashboards.get("dynamic", False)
        include_ai = v.dashboards.get("ai", False)
    print("== data views ==")
    _ensure_data_view("traces-*", "traces-*")
    _ensure_data_view("metrics-*", "metrics-*")
    _ensure_data_view("logs-*", "logs-*")
    urls = []
    baseline = build_dashboard()
    baseline_id = dash_id("baseline")
    dynamic_id = dash_id("dynamic")
    classic_id = dash_id("classic")
    if include_baseline:
        print(f"== PUT dashboard {baseline_id} (baseline) ==")
        urls.append(_put_dashboard(baseline_id, baseline))
    if include_dynamic_alias:
        print(f"== PUT dashboard {dynamic_id} (alias of baseline) ==")
        urls.append(_put_dashboard(dynamic_id, baseline))
    if include_classic:
        print(f"== PUT dashboard {classic_id} ==")
        urls.append(_put_dashboard(classic_id, build_classic_dashboard()))
    if include_ai:
        from src.dashboards_ai import publish_ai
        urls.append(publish_ai())
    return urls

