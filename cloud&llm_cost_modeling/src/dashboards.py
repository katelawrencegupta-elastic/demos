"""Publish Meridian FinOps + LLM Observability Kibana dashboards.

Uses the Kibana Dashboards API (inline ES|QL visualizations) so the panels
query native integration data streams already in the project.
"""
import json

import requests

from src.agent_builder import AGENT_CHAT_URL, agent_id
from src.budgets import budget_numbers
from src.config import KBN_HEADERS, KIBANA_URL
from src.time_window import demo_window, window_label
from src.variant import active_variant, filter_o_otb_links

DASHBOARD_ID = "meridian-finops-llm-observability"
DASHBOARD_ID_CLASSIC = "meridian-finops-llm-observability-classic"
DASHBOARD_ID_DYNAMIC = "meridian-finops-llm-observability-dynamic"  # alias of baseline
DASHBOARD_ID_AI = "meridian-ai-assistant-inference-usage"
DASHBOARD_ID_INFERENCE_USAGE = "kibana-inference-token-usage"


def dash_id(which: str) -> str:
    """Kibana dashboard id for the active workshop variant."""
    bases = {
        "baseline": DASHBOARD_ID,
        "classic": DASHBOARD_ID_CLASSIC,
        "dynamic": DASHBOARD_ID_DYNAMIC,
        "ai": DASHBOARD_ID_AI,
    }
    return bases[which] + active_variant().dash_suffix()


def _ootb_items():
    return list(filter_o_otb_links(OOTB).items())

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
    "APM Monitoring Overview": "apm-fab02b1d-fdd4-4c42-8ea9-a2be32f8cf61",
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


def links_panel(x, y, w, h, title, items):
    return {
        "grid": _grid(x, y, w, h),
        "type": "links",
        "config": {
            "title": title,
            "links": [
                {
                    "label": label,
                    "type": "dashboardLink",
                    "destination": dest,
                    "options": {
                        "use_filters": False,
                        "use_time_range": True,
                        "open_in_new_tab": True,
                    },
                }
                for label, dest in items
            ],
        },
    }


def section(title, y, panels, collapsed=False):
    return {
        "title": title,
        "collapsed": collapsed,
        "grid": {"y": y},
        "panels": panels,
    }


def budget_posture_section(y: int):
    """FinOps spend vs ceilings — mirrors config/budgets.yaml + SLO/alert deep links."""
    b = budget_numbers()
    aws_mtd = float(b["aws_monthly_usd"])
    staging_ceil = float(b["staging_daily_ceiling_usd"])
    checkout_7d = float(b["checkout_7d_alert_usd"])
    aws_daily = float(b["aws_daily_ceiling_usd"])
    checkout_daily = float(b["checkout_daily_ceiling_usd"])

    mtd_vs_budget = _q(
        "FROM metrics-aws_billing.cur-default",
        f"| WHERE {TS}",
        "| STATS spend = SUM(aws_billing.cur.line_item.unblended_cost)",
        f"| EVAL budget = {aws_mtd}, min = 0, max = budget * 2, goal = budget",
    )
    staging_vs_ceil = _q(
        "FROM metrics-aws_billing.cur-default",
        f"| WHERE {TS}",
        '| WHERE aws_billing.cur.line_item.usage_account_name == "meridian-staging"',
        "| STATS daily = SUM(aws_billing.cur.line_item.unblended_cost) BY day = BUCKET(@timestamp, 1d)",
        "| SORT day DESC", "| LIMIT 1",
        f"| EVAL spend = daily, budget = {staging_ceil}, min = 0, max = budget * 8, goal = budget",
        "| KEEP spend, budget, min, max, goal",
    )
    checkout_vs_alert = _q(
        "FROM traces-apm-default",
        f"| WHERE {TS} AND span.subtype == \"gen_ai\" AND service.name == \"checkout-assistant\"",
        "| EVAL cost = TO_DOUBLE(labels.llm_cost_usd)",
        "| STATS spend = SUM(cost)",
        f"| EVAL budget = {checkout_7d}, min = 0, max = budget * 3, goal = budget",
    )
    aws_daily_vs_ceil = _q(
        "FROM metrics-aws_billing.cur-default",
        f"| WHERE {TS}",
        "| STATS daily = SUM(aws_billing.cur.line_item.unblended_cost) BY day = BUCKET(@timestamp, 1d)",
        "| SORT day DESC", "| LIMIT 1",
        f"| EVAL spend = daily, budget = {aws_daily}, min = 0, max = budget * 2, goal = budget",
        "| KEEP spend, budget, min, max, goal",
    )
    slo_posture = _q(
        # Canonical summary alias (ignore_global_filters on panel — no @timestamp).
        "FROM .slo-observability.summary-v3.6",
        '| WHERE slo.id LIKE "meridian-*" AND status != "NO_DATA"',
        "| EVAL eb_remaining_pct = ROUND(errorBudgetRemaining * 100, 1)",
        "| KEEP slo.name, status, eb_remaining_pct, errorBudgetConsumed, sliValue",
        "| SORT status DESC, slo.name",
    )

    return section("Budget posture — spend SLOs & alerts", y, [
        markdown(
            0, 0, 48, 4,
            "## Budget posture\n\n"
            "Meridian treats cloud + LLM spend as error budgets. Thresholds come from "
            "`config/budgets.yaml` (intentionally tight so the seeded timeline shows breaches).\n\n"
            f"- **AWS monthly budget:** ${aws_mtd:,.0f} · **AWS daily SLO ceiling:** ${aws_daily:,.0f}\n"
            f"- **Staging daily SLO ceiling:** ${staging_ceil:,.0f} (cost_leak)\n"
            f"- **checkout-assistant daily SLO ceiling:** ${checkout_daily:.2f} · "
            f"**7d alert floor:** ${checkout_7d:.2f} (agent-loop)\n\n"
            "**Workshop posture:** AWS daily + staging cost-leak SLOs should show **VIOLATED**; "
            "checkout-assistant breaches during the agent-loop window (−8..−6).\n\n"
            f"[Observability SLOs]({KIBANA_URL}/app/observability/slos) · "
            f"[Observability Alerts]({KIBANA_URL}/app/observability/alerts) · "
            f"[Alerting rules]({KIBANA_URL}/app/management/insightsAndAlerting/triggersActions/rules)\n\n"
            f"**Meridian FinOps AI Assistant:** [Open in Agent Builder]({AGENT_CHAT_URL}) "
            f"(agent `{agent_id()}`). Provision: `python -m src.cli agent` · `python -m src.cli budgets`.",
        ),
        gauge(0, 4, 12, 12, "AWS window spend vs monthly budget",
              mtd_vs_budget, "spend", shape="arc",
              min_col="min", max_col="max", goal_col="goal",
              subtitle="USD (goal = budget)"),
        gauge(12, 4, 12, 12, "Latest AWS daily vs SLO ceiling",
              aws_daily_vs_ceil, "spend", shape="arc",
              min_col="min", max_col="max", goal_col="goal",
              subtitle="USD / day"),
        gauge(24, 4, 12, 12, "Staging latest day vs SLO ceiling",
              staging_vs_ceil, "spend", shape="arc",
              min_col="min", max_col="max", goal_col="goal",
              subtitle="meridian-staging"),
        gauge(36, 4, 12, 12, "checkout-assistant window vs alert",
              checkout_vs_alert, "spend", shape="arc",
              min_col="min", max_col="max", goal_col="goal",
              subtitle="USD LLM (APM)"),
        table(0, 16, 48, 10, "Meridian spend SLO posture (error budget)",
              slo_posture,
              rows=["slo.name", "status"],
              metrics=["eb_remaining_pct", "errorBudgetConsumed", "sliValue"],
              ignore_global_filters=True),
    ])


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
        "title": "[Meridian] FinOps & LLM Observability — classic",
        "description": (
            "Classic layout scoped to the active workshop variant: cost allocation, "
            "security→cost (when AWS security data is seeded), and LLM observability."
        ),
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
    """Baseline Meridian FinOps + LLM dashboard (variant-scoped panels)."""
    from src.dashboard_sections import build_baseline_sections
    win = demo_window()
    label = window_label()
    vtitle = active_variant().title
    panels = build_baseline_sections(None, label, vtitle)

    return {
        "title": "[Meridian] FinOps & LLM Observability",
        "description": (
            "Variant-scoped Meridian FinOps + LLM dashboard: only panels for integrations "
            "included in the active workshop fork."
        ),
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
    """Publish Meridian dashboards.

    Baseline is the current stacked-bar/area layout (former \"dynamic\").
    Classic is the older table/bar layout with the security→cost section.
    The -dynamic Kibana id is kept as an alias of baseline for existing links.
    """
    v = active_variant()
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

