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

DASHBOARD_ID = "meridian-finops-llm-observability"
DASHBOARD_ID_CLASSIC = "meridian-finops-llm-observability-classic"
DASHBOARD_ID_DYNAMIC = "meridian-finops-llm-observability-dynamic"  # alias of baseline
DASHBOARD_ID_AI = "meridian-ai-assistant-inference-usage"
DASHBOARD_ID_INFERENCE_USAGE = "kibana-inference-token-usage"

# Resolved at publish time (see src.time_window); kept as module attrs for imports.
_WINDOW = demo_window()
TIME_FROM = _WINDOW["from"]
TIME_TO = _WINDOW["to"]

TS = "@timestamp >= ?_tstart AND @timestamp <= ?_tend"

OOTB = {
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


def table(x, y, w, h, title, query, rows, metrics):
    return {
        "grid": _grid(x, y, w, h),
        "type": "vis",
        "config": {
            "type": "data_table",
            "title": title,
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
        "FROM .slo-observability.summary-v3.6",
        '| WHERE slo.id LIKE "meridian-*"',
        '| EVAL status = CASE(errorBudgetRemaining < 0, "VIOLATED", "HEALTHY")',
        "| EVAL eb_remaining_pct = ROUND(errorBudgetRemaining * 100, 1)",
        "| KEEP slo.name, status, eb_remaining_pct, errorBudgetConsumed",
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
              metrics=["eb_remaining_pct", "errorBudgetConsumed"]),
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
    win = demo_window()
    label = window_label()
    aws_cost = _q(
        "FROM metrics-aws_billing.cur-default",
        f"| WHERE {TS}",
        "| STATS cost = SUM(aws_billing.cur.line_item.unblended_cost)",
    )
    gcp_cost = _q(
        "FROM metrics-gcp.billing-default",
        f"| WHERE {TS}",
        "| STATS cost = SUM(gcp.billing.total)",
    )
    azure_cost = _q(
        "FROM metrics-azure.billing-default",
        f"| WHERE {TS}",
        "| STATS cost = SUM(azure.billing.pretax_cost)",
    )
    llm_cost = _q(
        "FROM traces-apm-default",
        f"| WHERE {TS} AND span.subtype == \"gen_ai\"",
        "| EVAL cost = TO_DOUBLE(labels.llm_cost_usd)",
        "| STATS cost = SUM(cost)",
    )
    cloud_mix = _q(
        "FROM metrics-aws_billing.cur-default, metrics-gcp.billing-default, metrics-azure.billing-default",
        f"| WHERE {TS}",
        "| EVAL cost = COALESCE(aws_billing.cur.line_item.unblended_cost, gcp.billing.total, azure.billing.pretax_cost)",
        "| EVAL provider = data_stream.dataset",
        "| STATS cost = SUM(cost) BY provider",
        "| SORT cost DESC",
    )
    daily_cloud = _q(
        "FROM metrics-aws_billing.cur-default, metrics-gcp.billing-default, metrics-azure.billing-default",
        f"| WHERE {TS}",
        "| EVAL cost = COALESCE(aws_billing.cur.line_item.unblended_cost, gcp.billing.total, azure.billing.pretax_cost)",
        "| EVAL provider = data_stream.dataset",
        "| STATS cost = SUM(cost) BY day = BUCKET(@timestamp, 1d), provider",
        "| SORT day",
    )

    panels = [
        section("FinOps integration — native cloud provider dashboards", 0, [
            markdown(0, 0, 20, 10,
                     "These are the **out-of-the-box Elastic integration dashboards** installed from "
                     "Fleet packages (`aws_billing`, `gcp`, `azure_billing`, `openai`, `anthropic_metrics`, "
                     "`azure_openai`, `aws_bedrock`, `gcp_vertexai`, `apm`). Open them with the same time range.\n\n"
                     "This Meridian dashboard is the cross-provider overlay; provider packs remain "
                     "the source of truth for CUR line items, PTU, Guardrails, etc.\n\n"
                     "Elastic AI Assistant / Agent Builder usage and the managed inference token "
                     "dashboard are linked at right."),
            links_panel(20, 0, 12, 10, "Elastic AI", [
                ("AI Assistant & inference usage", DASHBOARD_ID_AI),
                ("[Elastic] Inference Token Usage", DASHBOARD_ID_INFERENCE_USAGE),
            ]),
            links_panel(32, 0, 16, 10, "Provider FinOps & LLM packs", [
                *OOTB.items(),
                ("[Elastic] Inference Token Usage", DASHBOARD_ID_INFERENCE_USAGE),
                ("AI Assistant & inference usage", DASHBOARD_ID_AI),
            ]),
        ]),
        section("Overview — multi-cloud + LLM spend", 12, [
            markdown(0, 0, 48, 3,
                     "## Meridian Dynamics — FinOps & LLM Observability\n\n"
                     "Cost allocation across AWS accounts, GCP projects, and Azure subscriptions, "
                     "correlated with infrastructure usage, plus end-to-end LLM traces (tokens, cost, "
                     "latency, quality) for every application flow.\n\n"
                     f"Time range is stored with the dashboard (**{label}**). "
                     "Republish after backfill to refresh.\n\n"
                     f"**Baseline (stacked bars/areas):** "
                     f"[FinOps & LLM Observability](#/view/{DASHBOARD_ID}).\n\n"
                     "**Scenario callouts:** cost leak on `meridian-staging` · crypto mining (−12..−9, "
                     "`meridian-dev`) · S3 exposure (−6..−4) · ML burn (−20..−16, GCP) · GenAI ramp "
                     "(from −15) · LLM agent-loop (`checkout-assistant`) · model migration "
                     "(`support-copilot` openai→anthropic) · cache-miss (`rag-research`).\n\n"
                     "**Budget posture:** spend SLOs + ES|QL alerts — see the Budget posture section "
                     f"or [Observability SLOs]({KIBANA_URL}/app/observability/slos)."),
            metric(0, 3, 12, 5, "AWS unblended cost (CUR)", aws_cost, "cost", "USD"),
            metric(12, 3, 12, 5, "GCP billing total", gcp_cost, "cost", "USD"),
            metric(24, 3, 12, 5, "Azure pretax cost", azure_cost, "cost", "USD"),
            metric(36, 3, 12, 5, "LLM cost (APM traces)", llm_cost, "cost", "USD"),
            pie(0, 8, 18, 12, "Spend mix by billing dataset", cloud_mix, "cost", "provider"),
            xy(18, 8, 30, 12, "Daily cost by cloud provider", daily_cloud,
               "day", ["cost"], layer="area", breakdown="provider"),
        ]),
        section("Security → cost — crypto mining & S3 exposure", 36, [
            markdown(0, 0, 48, 3,
                     "## Security incidents that move spend\n\n"
                     "**Crypto-mining** (days −12..−9, `meridian-dev`): GuardDuty "
                     "`CryptoCurrency:EC2/BitcoinTool.B`, CloudTrail brute-force from "
                     "`185.220.101.34`, CPU pegged, EC2 cost spike.\n\n"
                     "**S3 public exposure** (days −6..−4, fintech): "
                     "`Policy:S3/BucketAnonymousAccessGranted`, `PutBucketPolicy`, anonymous scrapes "
                     "of `meridian-fintech-exports`, data-transfer cost.\n\n"
                     "Open OOTB GuardDuty / CloudTrail Discover with the same time range for drill-down."),
            metric(0, 3, 12, 5, "GuardDuty findings",
                   _q("FROM logs-aws.guardduty-default",
                      f"| WHERE {TS}",
                      "| STATS findings = COUNT(*)"),
                   "findings"),
            metric(12, 3, 12, 5, "Crypto findings",
                   _q("FROM logs-aws.guardduty-default",
                      f"| WHERE {TS} AND rule.name LIKE \"CryptoCurrency*\"",
                      "| STATS crypto = COUNT(*)"),
                   "crypto"),
            metric(24, 3, 12, 5, "S3 policy findings",
                   _q("FROM logs-aws.guardduty-default",
                      f"| WHERE {TS} AND rule.name LIKE \"Policy:S3*\"",
                      "| STATS s3_findings = COUNT(*)"),
                   "s3_findings"),
            metric(36, 3, 12, 5, "CloudTrail from attacker IP",
                   _q("FROM logs-aws.cloudtrail-default",
                      f"| WHERE {TS} AND source.ip == \"185.220.101.34\"",
                      "| STATS events = COUNT(*)"),
                   "events"),
            xy(0, 8, 24, 12, "GuardDuty findings by type",
               _q("FROM logs-aws.guardduty-default",
                  f"| WHERE {TS}",
                  "| STATS findings = COUNT(*) BY finding = rule.name",
                  "| SORT findings DESC", "| LIMIT 12"),
               "finding", ["findings"], layer="bar"),
            xy(24, 8, 24, 12, "S3 / bucket CloudTrail actions",
               _q("FROM logs-aws.cloudtrail-default",
                  f"| WHERE {TS} AND (event.action LIKE \"*Bucket*\" OR event.action LIKE \"*Object*\")",
                  "| STATS calls = COUNT(*) BY action = event.action",
                  "| SORT calls DESC", "| LIMIT 12"),
               "action", ["calls"], layer="bar"),
            table(0, 20, 48, 10, "Recent high-severity GuardDuty findings",
                  _q("FROM logs-aws.guardduty-default",
                     f"| WHERE {TS}",
                     "| SORT @timestamp DESC",
                     "| KEEP @timestamp, rule.name, aws.guardduty.severity.value, cloud.account.id",
                     "| LIMIT 40"),
                  ["@timestamp", "rule.name", "cloud.account.id"],
                  ["aws.guardduty.severity.value"]),
        ]),
        section("Cost allocation — account, subscription, service, team, tag, region", 64, [
            markdown(0, 0, 48, 2,
                     "Allocation dimensions from native billing integrations: AWS CUR "
                     "(`usage_account_name`, `product`, `resource_tags`, region), GCP project/service/"
                     "region, Azure subscription/department/product/region, and Cost Explorer "
                     "`cost_center` tags (untagged bucket = `cost_center$`)."),
            xy(0, 2, 24, 12, "AWS cost by linked account",
               _q("FROM metrics-aws_billing.cur-default",
                  f"| WHERE {TS}",
                  "| STATS cost = SUM(aws_billing.cur.line_item.unblended_cost) BY account = aws_billing.cur.line_item.usage_account_name",
                  "| SORT cost DESC", "| LIMIT 12"),
               "account", ["cost"], layer="bar"),
            xy(24, 2, 24, 12, "AWS cost by service",
               _q("FROM metrics-aws_billing.cur-default",
                  f"| WHERE {TS}",
                  "| STATS cost = SUM(aws_billing.cur.line_item.unblended_cost) BY service = aws_billing.cur.product.product",
                  "| SORT cost DESC", "| LIMIT 12"),
               "service", ["cost"], layer="bar"),
            pie(0, 14, 16, 12, "AWS Cost Explorer by cost_center tag",
                _q("FROM metrics-aws.billing-default",
                   f"| WHERE {TS} AND aws.billing.group_definition.key == \"COST_CENTER\"",
                   "| STATS cost = SUM(aws.billing.UnblendedCost.amount) BY tag = aws.billing.group_by.COST_CENTER",
                   "| SORT cost DESC"),
                "cost", "tag"),
            xy(16, 14, 16, 12, "GCP cost by project",
               _q("FROM metrics-gcp.billing-default",
                  f"| WHERE {TS}",
                  "| STATS cost = SUM(gcp.billing.total) BY project = gcp.billing.project_name",
                  "| SORT cost DESC"),
               "project", ["cost"], layer="bar"),
            xy(32, 14, 16, 12, "Azure cost by subscription",
               _q("FROM metrics-azure.billing-default",
                  f"| WHERE {TS}",
                  "| STATS cost = SUM(azure.billing.pretax_cost) BY subscription = azure.subscription_id",
                  "| SORT cost DESC"),
               "subscription", ["cost"], layer="bar"),
            table(0, 26, 24, 12, "AWS CUR allocation — account × service × tags",
                  _q("FROM metrics-aws_billing.cur-default",
                     f"| WHERE {TS}",
                     "| STATS cost = SUM(aws_billing.cur.line_item.unblended_cost), usage = SUM(aws_billing.cur.line_item.usage_amount) BY account = aws_billing.cur.line_item.usage_account_name, service = aws_billing.cur.product.product, tag = aws_billing.cur.resource_tags",
                     "| SORT cost DESC", "| LIMIT 50"),
                  ["account", "service", "tag"], ["cost", "usage"]),
            table(24, 26, 24, 12, "Azure allocation — department × product × region",
                  _q("FROM metrics-azure.billing-default",
                     f"| WHERE {TS}",
                     "| STATS cost = SUM(azure.billing.pretax_cost) BY team = azure.billing.department_name, product = azure.billing.product, region = cloud.region, rg = azure.resource.group",
                     "| SORT cost DESC", "| LIMIT 50"),
                  ["team", "product", "region", "rg"], ["cost"]),
            xy(0, 38, 24, 11, "GCP cost by service",
               _q("FROM metrics-gcp.billing-default",
                  f"| WHERE {TS}",
                  "| STATS cost = SUM(gcp.billing.total) BY service = gcp.billing.service_description",
                  "| SORT cost DESC"),
               "service", ["cost"], layer="bar"),
            xy(24, 38, 24, 11, "GCP cost by region",
               _q("FROM metrics-gcp.billing-default",
                  f"| WHERE {TS}",
                  "| STATS cost = SUM(gcp.billing.total) BY region = gcp.billing.location.region",
                  "| SORT cost DESC"),
               "region", ["cost"], layer="bar"),
        ]),
        section("Engineering & Ops — usage correlated with cost", 118, [
            markdown(0, 0, 48, 2,
                     "Infrastructure usage (EC2 network throughput, CloudTrail API volume) plotted "
                     "alongside CUR EC2 spend so ops can see whether cost moves with work. "
                     "Watch `meridian-staging` for the cost-leak pattern (spend without matching activity)."),
            xy(0, 2, 24, 11, "AWS EC2 daily unblended cost",
               _q("FROM metrics-aws_billing.cur-default",
                  f"| WHERE {TS} AND aws_billing.cur.product.product == \"AmazonEC2\"",
                  "| STATS cost = SUM(aws_billing.cur.line_item.unblended_cost) BY day = BUCKET(@timestamp, 1d)",
                  "| SORT day"),
               "day", ["cost"], layer="line"),
            xy(24, 2, 24, 11, "EC2 NetworkIn rate (usage proxy)",
               _q("FROM metrics-aws.ec2_metrics-default",
                  f"| WHERE {TS}",
                  "| STATS network_in = SUM(aws.ec2.metrics.NetworkIn.rate) BY day = BUCKET(@timestamp, 1d)",
                  "| SORT day"),
               "day", ["network_in"], layer="line"),
            xy(0, 13, 24, 11, "CloudTrail API calls per day",
               _q("FROM logs-aws.cloudtrail-default",
                  f"| WHERE {TS}",
                  "| STATS api_calls = COUNT() BY day = BUCKET(@timestamp, 1d)",
                  "| SORT day"),
               "day", ["api_calls"], layer="line"),
            xy(24, 13, 24, 11, "EC2 network usage by account",
               _q("FROM metrics-aws.ec2_metrics-default",
                  f"| WHERE {TS}",
                  "| STATS network_in = SUM(aws.ec2.metrics.NetworkIn.rate) BY account = cloud.account.name",
                  "| SORT network_in DESC"),
               "account", ["network_in"], layer="bar"),
            table(0, 24, 48, 11, "AWS cost vs usage quantity by account and product",
                  _q("FROM metrics-aws_billing.cur-default",
                     f"| WHERE {TS}",
                     "| STATS cost = SUM(aws_billing.cur.line_item.unblended_cost), usage = SUM(aws_billing.cur.line_item.usage_amount) BY account = aws_billing.cur.line_item.usage_account_name, service = aws_billing.cur.product.product",
                     "| EVAL unit_cost = cost / usage",
                     "| SORT cost DESC", "| LIMIT 40"),
                  ["account", "service"], ["cost", "usage", "unit_cost"]),
        ]),
        section("Historical cost & 7-day run-rate forecast", 156, [
            markdown(0, 0, 48, 2,
                     "Daily CUR history plus a trailing 7-day average run-rate. "
                     "`projected_30d` = last-7-day daily average × 30 (not a statistical model — a FinOps run-rate)."),
            xy(0, 2, 32, 12, "AWS CUR daily unblended cost (history)",
               _q("FROM metrics-aws_billing.cur-default",
                  f"| WHERE {TS}",
                  "| STATS cost = SUM(aws_billing.cur.line_item.unblended_cost) BY day = BUCKET(@timestamp, 1d)",
                  "| SORT day"),
               "day", ["cost"], layer="line"),
            metric(32, 2, 16, 6, "AWS 7-day avg daily cost",
                   _q("FROM metrics-aws_billing.cur-default",
                      f"| WHERE {TS}",
                      "| STATS daily = SUM(aws_billing.cur.line_item.unblended_cost) BY day = BUCKET(@timestamp, 1d)",
                      "| SORT day DESC", "| LIMIT 7",
                      "| STATS avg_7d = AVG(daily)"),
                   "avg_7d", "USD / day"),
            metric(32, 8, 16, 6, "Projected 30-day AWS run-rate",
                   _q("FROM metrics-aws_billing.cur-default",
                      f"| WHERE {TS}",
                      "| STATS daily = SUM(aws_billing.cur.line_item.unblended_cost) BY day = BUCKET(@timestamp, 1d)",
                      "| SORT day DESC", "| LIMIT 7",
                      "| STATS avg_7d = AVG(daily)",
                      "| EVAL projected_30d = avg_7d * 30",
                      "| KEEP projected_30d"),
                   "projected_30d", "USD"),
            xy(0, 14, 24, 11, "GCP daily cost",
               _q("FROM metrics-gcp.billing-default",
                  f"| WHERE {TS}",
                  "| STATS cost = SUM(gcp.billing.total) BY day = BUCKET(@timestamp, 1d)",
                  "| SORT day"),
               "day", ["cost"], layer="line"),
            xy(24, 14, 24, 11, "Azure daily pretax cost",
               _q("FROM metrics-azure.billing-default",
                  f"| WHERE {TS}",
                  "| STATS cost = SUM(azure.billing.pretax_cost) BY day = BUCKET(@timestamp, 1d)",
                  "| SORT day"),
               "day", ["cost"], layer="line"),
        ]),
        budget_posture_section(184),
        section("LLM traces — end-to-end call, tokens, and cost", 208, [
            markdown(0, 0, 48, 2,
                     "APM `gen_ai` spans (`traces-apm-default`) carry prompt/completion/total tokens, "
                     "model, system, latency, outcome, and `labels.llm_cost_usd`. `trace.id` is the "
                     "request id — open APM to inspect the parent FastAPI transaction.\n\n"
                     "**LLM scenarios:** agent-loop burn on `checkout-assistant` (−8..−6) · "
                     "model migration on `support-copilot` (openai→anthropic at −14) · "
                     "cache-miss storm on `rag-research` (−5..−3) · skunkworks GenAI ramp."),
            metric(0, 2, 12, 5, "LLM calls (sampled spans)",
                   _q("FROM traces-apm-default",
                      f"| WHERE {TS} AND span.subtype == \"gen_ai\"",
                      "| STATS calls = COUNT(*)"),
                   "calls"),
            metric(12, 2, 12, 5, "Total tokens",
                   _q("FROM traces-apm-default",
                      f"| WHERE {TS} AND span.subtype == \"gen_ai\"",
                      "| STATS tokens = SUM(gen_ai.usage.total_tokens)"),
                   "tokens"),
            metric(24, 2, 12, 5, "Prompt tokens",
                   _q("FROM traces-apm-default",
                      f"| WHERE {TS} AND span.subtype == \"gen_ai\"",
                      "| STATS prompt = SUM(gen_ai.usage.input_tokens)"),
                   "prompt"),
            metric(36, 2, 12, 5, "Completion tokens",
                   _q("FROM traces-apm-default",
                      f"| WHERE {TS} AND span.subtype == \"gen_ai\"",
                      "| STATS completion = SUM(gen_ai.usage.output_tokens)"),
                   "completion"),
            table(0, 7, 48, 14, "Recent LLM calls — trace, model, tokens, cost, latency",
                  _q("FROM traces-apm-default",
                     f"| WHERE {TS} AND span.subtype == \"gen_ai\"",
                     "| EVAL cost_usd = TO_DOUBLE(labels.llm_cost_usd), latency_ms = span.duration.us / 1000.0",
                     "| SORT @timestamp DESC",
                     "| KEEP @timestamp, trace.id, service.name, gen_ai.request.model, gen_ai.system, gen_ai.usage.input_tokens, gen_ai.usage.output_tokens, gen_ai.usage.total_tokens, cost_usd, latency_ms, event.outcome, labels.team, labels.env",
                     "| LIMIT 100"),
                  ["@timestamp", "trace.id", "service.name", "gen_ai.request.model",
                   "gen_ai.system", "event.outcome", "labels.team", "labels.env"],
                  ["gen_ai.usage.input_tokens", "gen_ai.usage.output_tokens",
                   "gen_ai.usage.total_tokens", "cost_usd", "latency_ms"]),
        ]),
        section("Token usage per request — prompt, completion, total", 232, [
            xy(0, 0, 32, 12, "Daily prompt vs completion tokens (APM spans)",
               _q("FROM traces-apm-default",
                  f"| WHERE {TS} AND span.subtype == \"gen_ai\"",
                  "| STATS prompt = SUM(gen_ai.usage.input_tokens), completion = SUM(gen_ai.usage.output_tokens), total = SUM(gen_ai.usage.total_tokens) BY day = BUCKET(@timestamp, 1d)",
                  "| SORT day"),
               "day", ["prompt", "completion", "total"], layer="area"),
            pie(32, 0, 16, 12, "Prompt vs completion share",
                _q("FROM traces-apm-default",
                   f"| WHERE {TS} AND span.subtype == \"gen_ai\"",
                   "| FORK",
                   "    (STATS tokens = SUM(gen_ai.usage.input_tokens) | EVAL kind = \"prompt\")",
                   "    (STATS tokens = SUM(gen_ai.usage.output_tokens) | EVAL kind = \"completion\")",
                   "| KEEP kind, tokens"),
                "tokens", "kind"),
            xy(0, 12, 24, 11, "OpenAI completions — input vs output tokens",
               _q("FROM logs-openai.completions-default",
                  f"| WHERE {TS}",
                  "| STATS prompt = SUM(openai.completions.input_tokens), completion = SUM(openai.completions.output_tokens) BY day = BUCKET(@timestamp, 1d)",
                  "| SORT day"),
               "day", ["prompt", "completion"], layer="area"),
            xy(24, 12, 24, 11, "Vertex AI — prompt vs candidate tokens",
               _q("FROM logs-gcp_vertexai.prompt_response_logs-default",
                  f"| WHERE {TS}",
                  "| STATS prompt = SUM(gcp.vertexai.prompt_response_logs.full_response.usage_metadata.prompt_token_count), completion = SUM(gcp.vertexai.prompt_response_logs.full_response.usage_metadata.candidates_token_count) BY day = BUCKET(@timestamp, 1d)",
                  "| SORT day"),
               "day", ["prompt", "completion"], layer="area"),
        ]),
        section("LLM cost — model, user, feature, team", 258, [
            xy(0, 0, 24, 12, "LLM cost by model",
               _q("FROM traces-apm-default",
                  f"| WHERE {TS} AND span.subtype == \"gen_ai\"",
                  "| EVAL cost = TO_DOUBLE(labels.llm_cost_usd)",
                  "| STATS cost_usd = SUM(cost), tokens = SUM(gen_ai.usage.total_tokens), calls = COUNT(*) BY model = gen_ai.request.model",
                  "| SORT cost_usd DESC", "| LIMIT 15"),
               "model", ["cost_usd"], layer="bar"),
            xy(24, 0, 24, 12, "LLM cost by team",
               _q("FROM traces-apm-default",
                  f"| WHERE {TS} AND span.subtype == \"gen_ai\"",
                  "| EVAL cost = TO_DOUBLE(labels.llm_cost_usd)",
                  "| STATS cost_usd = SUM(cost), tokens = SUM(gen_ai.usage.total_tokens) BY team = COALESCE(labels.team, \"untagged\")",
                  "| SORT cost_usd DESC"),
               "team", ["cost_usd"], layer="bar"),
            xy(0, 12, 24, 12, "LLM cost by feature / application",
               _q("FROM traces-apm-default",
                  f"| WHERE {TS} AND span.subtype == \"gen_ai\"",
                  "| EVAL cost = TO_DOUBLE(labels.llm_cost_usd)",
                  "| STATS cost_usd = SUM(cost), tokens = SUM(gen_ai.usage.total_tokens), calls = COUNT(*) BY feature = service.name",
                  "| SORT cost_usd DESC"),
               "feature", ["cost_usd"], layer="bar"),
            xy(24, 12, 24, 12, "OpenAI tokens by user",
               _q("FROM logs-openai.completions-default",
                  f"| WHERE {TS}",
                  "| STATS tokens = SUM(openai.base.usage_tokens), requests = SUM(openai.base.num_model_requests) BY user = openai.base.user_id",
                  "| SORT tokens DESC", "| LIMIT 15"),
               "user", ["tokens"], layer="bar"),
            table(0, 24, 24, 12, "Cost × tokens by model and provider",
                  _q("FROM traces-apm-default",
                     f"| WHERE {TS} AND span.subtype == \"gen_ai\"",
                     "| EVAL cost = TO_DOUBLE(labels.llm_cost_usd)",
                     "| STATS cost_usd = SUM(cost), prompt = SUM(gen_ai.usage.input_tokens), completion = SUM(gen_ai.usage.output_tokens), calls = COUNT(*) BY model = gen_ai.request.model, provider = gen_ai.system",
                     "| SORT cost_usd DESC"),
                  ["provider", "model"], ["calls", "prompt", "completion", "cost_usd"]),
            table(24, 24, 24, 12, "Vertex AI tokens by user and app",
                  _q("FROM logs-gcp_vertexai.prompt_response_logs-default",
                     f"| WHERE {TS}",
                     "| STATS tokens = SUM(gcp.vertexai.prompt_response_logs.full_response.usage_metadata.total_token_count), calls = COUNT(*) BY user = user.name, feature = service.name, team = labels.team",
                     "| SORT tokens DESC", "| LIMIT 30"),
                  ["user", "feature", "team"], ["calls", "tokens"]),
        ]),
        section("LLM quality & latency", 298, [
            metric(0, 0, 12, 5, "p95 latency (ms)",
                   _q("FROM traces-apm-default",
                      f"| WHERE {TS} AND span.subtype == \"gen_ai\"",
                      "| STATS p95_ms = PERCENTILE(span.duration.us, 95) / 1000"),
                   "p95_ms"),
            metric(12, 0, 12, 5, "p50 latency (ms)",
                   _q("FROM traces-apm-default",
                      f"| WHERE {TS} AND span.subtype == \"gen_ai\"",
                      "| STATS p50_ms = PERCENTILE(span.duration.us, 50) / 1000"),
                   "p50_ms"),
            metric(24, 0, 12, 5, "Error rate",
                   _q("FROM traces-apm-default",
                      f"| WHERE {TS} AND span.subtype == \"gen_ai\"",
                      "| STATS errors = COUNT(*) WHERE event.outcome == \"failure\", calls = COUNT(*)",
                      "| EVAL error_rate = errors * 1.0 / calls",
                      "| KEEP error_rate"),
                   "error_rate"),
            pie(36, 0, 12, 12, "Call outcome",
                _q("FROM traces-apm-default",
                   f"| WHERE {TS} AND span.subtype == \"gen_ai\"",
                   "| STATS calls = COUNT(*) BY outcome = event.outcome"),
                "calls", "outcome"),
            xy(0, 5, 36, 12, "Latency p95 by model (ms)",
               _q("FROM traces-apm-default",
                  f"| WHERE {TS} AND span.subtype == \"gen_ai\"",
                  "| STATS p95_ms = PERCENTILE(span.duration.us, 95) / 1000, p50_ms = PERCENTILE(span.duration.us, 50) / 1000 BY model = gen_ai.request.model",
                  "| SORT p95_ms DESC", "| LIMIT 15"),
               "model", ["p50_ms", "p95_ms"], layer="bar"),
            xy(0, 17, 48, 11, "Daily p95 latency (ms)",
               _q("FROM traces-apm-default",
                  f"| WHERE {TS} AND span.subtype == \"gen_ai\"",
                  "| STATS p95_ms = PERCENTILE(span.duration.us, 95) / 1000 BY day = BUCKET(@timestamp, 1d)",
                  "| SORT day"),
               "day", ["p95_ms"], layer="line"),
        ]),
        section("Funnel — which user flows consume the most tokens", 330, [
            markdown(0, 0, 48, 3,
                     "Each `service.name` is a Meridian user flow (`checkout-assistant`, `support-copilot`, "
                     "`rag-research`, `skunk-agent-lab`, …). Ranked by total tokens, then cost and calls. "
                     "Shadow-IT (`skunk-agent-lab`, `prompt-playground`) and the agent-loop scenario show up here."),
            xy(0, 3, 28, 14, "Tokens consumed by user flow",
               _q("FROM traces-apm-default",
                  f"| WHERE {TS} AND span.subtype == \"gen_ai\"",
                  "| EVAL cost = TO_DOUBLE(labels.llm_cost_usd)",
                  "| STATS tokens = SUM(gen_ai.usage.total_tokens), cost_usd = SUM(cost), calls = COUNT(*) BY flow = service.name",
                  "| SORT tokens DESC"),
               "flow", ["tokens"], layer="bar"),
            pie(28, 3, 20, 14, "Token share by flow",
                _q("FROM traces-apm-default",
                   f"| WHERE {TS} AND span.subtype == \"gen_ai\"",
                   "| STATS tokens = SUM(gen_ai.usage.total_tokens) BY flow = service.name",
                   "| SORT tokens DESC"),
                "tokens", "flow"),
            table(0, 17, 48, 12, "Flow funnel — tokens, prompt/completion split, cost, latency",
                  _q("FROM traces-apm-default",
                     f"| WHERE {TS} AND span.subtype == \"gen_ai\"",
                     "| EVAL cost = TO_DOUBLE(labels.llm_cost_usd)",
                     "| STATS calls = COUNT(*), prompt = SUM(gen_ai.usage.input_tokens), completion = SUM(gen_ai.usage.output_tokens), tokens = SUM(gen_ai.usage.total_tokens), cost_usd = SUM(cost), p95_ms = PERCENTILE(span.duration.us, 95) / 1000 BY flow = service.name, team = COALESCE(labels.team, \"untagged\"), env = COALESCE(labels.env, service.environment)",
                     "| EVAL tokens_per_call = tokens / calls",
                     "| SORT tokens DESC"),
                  ["flow", "team", "env"],
                  ["calls", "prompt", "completion", "tokens", "tokens_per_call", "cost_usd", "p95_ms"]),
        ]),
    ]

    return {
        "title": "[Meridian] FinOps & LLM Observability — classic",
        "description": (
            "Classic layout: cross-cloud cost allocation tables and bars, security→cost "
            "(crypto / S3), usage-to-cost correlation, and LLM observability tables. "
            "The baseline dashboard is meridian-finops-llm-observability."
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
    """Baseline Meridian FinOps + LLM dashboard (stacked bars/areas, gauges, waffles)."""
    win = demo_window()
    label = window_label()
    aws_trend = _q(
        "FROM metrics-aws_billing.cur-default",
        f"| WHERE {TS}",
        "| STATS cost = SUM(aws_billing.cur.line_item.unblended_cost) BY day = BUCKET(@timestamp, 1d)",
        "| SORT day",
    )
    gcp_trend = _q(
        "FROM metrics-gcp.billing-default",
        f"| WHERE {TS}",
        "| STATS cost = SUM(gcp.billing.total) BY day = BUCKET(@timestamp, 1d)",
        "| SORT day",
    )
    azure_trend = _q(
        "FROM metrics-azure.billing-default",
        f"| WHERE {TS}",
        "| STATS cost = SUM(azure.billing.pretax_cost) BY day = BUCKET(@timestamp, 1d)",
        "| SORT day",
    )
    llm_trend = _q(
        "FROM traces-apm-default",
        f"| WHERE {TS} AND span.subtype == \"gen_ai\"",
        "| EVAL cost = TO_DOUBLE(labels.llm_cost_usd)",
        "| STATS cost = SUM(cost) BY day = BUCKET(@timestamp, 1d)",
        "| SORT day",
    )
    cloud_mix = _q(
        "FROM metrics-aws_billing.cur-default, metrics-gcp.billing-default, metrics-azure.billing-default",
        f"| WHERE {TS}",
        "| EVAL cost = COALESCE(aws_billing.cur.line_item.unblended_cost, gcp.billing.total, azure.billing.pretax_cost)",
        "| EVAL provider = data_stream.dataset",
        "| STATS cost = SUM(cost) BY provider",
        "| SORT cost DESC",
    )
    daily_cloud = _q(
        "FROM metrics-aws_billing.cur-default, metrics-gcp.billing-default, metrics-azure.billing-default",
        f"| WHERE {TS}",
        "| EVAL cost = COALESCE(aws_billing.cur.line_item.unblended_cost, gcp.billing.total, azure.billing.pretax_cost)",
        "| EVAL provider = data_stream.dataset",
        "| STATS cost = SUM(cost) BY day = BUCKET(@timestamp, 1d), provider",
        "| SORT day",
    )
    acct_svc = _q(
        "FROM metrics-aws_billing.cur-default",
        f"| WHERE {TS}",
        "| STATS cost = SUM(aws_billing.cur.line_item.unblended_cost) BY account = aws_billing.cur.line_item.usage_account_name, service = aws_billing.cur.product.product",
        "| SORT cost DESC", "| LIMIT 40",
    )
    cost_by_acct_day = _q(
        "FROM metrics-aws_billing.cur-default",
        f"| WHERE {TS}",
        "| STATS cost = SUM(aws_billing.cur.line_item.unblended_cost) BY day = BUCKET(@timestamp, 1d), account = aws_billing.cur.line_item.usage_account_name",
        "| SORT day",
    )
    cc_tag = _q(
        "FROM metrics-aws.billing-default",
        f"| WHERE {TS} AND aws.billing.group_definition.key == \"COST_CENTER\"",
        "| STATS cost = SUM(aws.billing.UnblendedCost.amount) BY tag = aws.billing.group_by.COST_CENTER",
        "| SORT cost DESC",
    )
    gcp_proj_svc = _q(
        "FROM metrics-gcp.billing-default",
        f"| WHERE {TS}",
        "| STATS cost = SUM(gcp.billing.total) BY project = gcp.billing.project_name, service = gcp.billing.service_description",
        "| SORT cost DESC",
    )
    azure_dept = _q(
        "FROM metrics-azure.billing-default",
        f"| WHERE {TS}",
        "| STATS cost = SUM(azure.billing.pretax_cost) BY team = azure.billing.department_name, product = azure.billing.product",
        "| SORT cost DESC", "| LIMIT 30",
    )
    ec2_cost_day = _q(
        "FROM metrics-aws_billing.cur-default",
        f"| WHERE {TS} AND aws_billing.cur.product.product == \"AmazonEC2\"",
        "| STATS cost = SUM(aws_billing.cur.line_item.unblended_cost) BY day = BUCKET(@timestamp, 1d)",
        "| SORT day",
    )
    net_day = _q(
        "FROM metrics-aws.ec2_metrics-default",
        f"| WHERE {TS}",
        "| STATS network_in = SUM(aws.ec2.metrics.NetworkIn.rate) BY day = BUCKET(@timestamp, 1d)",
        "| SORT day",
    )
    forecast = _q(
        "FROM metrics-aws_billing.cur-default",
        f"| WHERE {TS}",
        "| STATS daily = SUM(aws_billing.cur.line_item.unblended_cost) BY day = BUCKET(@timestamp, 1d)",
        "| SORT day DESC", "| LIMIT 7",
        "| STATS avg_7d = AVG(daily)",
        "| EVAL projected_30d = avg_7d * 30, min = 0, max = avg_7d * 45, goal = avg_7d * 28",
    )
    flow_model = _q(
        "FROM traces-apm-default",
        f"| WHERE {TS} AND span.subtype == \"gen_ai\"",
        "| EVAL cost = TO_DOUBLE(labels.llm_cost_usd)",
        "| STATS tokens = SUM(gen_ai.usage.total_tokens), cost_usd = SUM(cost) BY flow = service.name, model = gen_ai.request.model",
        "| SORT tokens DESC", "| LIMIT 40",
    )
    tokens_by_flow_day = _q(
        "FROM traces-apm-default",
        f"| WHERE {TS} AND span.subtype == \"gen_ai\"",
        "| STATS tokens = SUM(gen_ai.usage.total_tokens) BY day = BUCKET(@timestamp, 1d), flow = service.name",
        "| SORT day",
    )
    latency_by_model_day = _q(
        "FROM traces-apm-default",
        f"| WHERE {TS} AND span.subtype == \"gen_ai\"",
        "| STATS p95_ms = PERCENTILE(span.duration.us, 95) / 1000 BY day = BUCKET(@timestamp, 1d), model = gen_ai.request.model",
        "| SORT day",
    )
    tokens_day = _q(
        "FROM traces-apm-default",
        f"| WHERE {TS} AND span.subtype == \"gen_ai\"",
        "| STATS prompt = SUM(gen_ai.usage.input_tokens), completion = SUM(gen_ai.usage.output_tokens) BY day = BUCKET(@timestamp, 1d)",
        "| SORT day",
    )
    flow_tokens = _q(
        "FROM traces-apm-default",
        f"| WHERE {TS} AND span.subtype == \"gen_ai\"",
        "| EVAL cost = TO_DOUBLE(labels.llm_cost_usd)",
        "| STATS prompt = SUM(gen_ai.usage.input_tokens), completion = SUM(gen_ai.usage.output_tokens), tokens = SUM(gen_ai.usage.total_tokens), cost_usd = SUM(cost) BY flow = service.name",
        "| SORT tokens DESC",
    )
    team_cost = _q(
        "FROM traces-apm-default",
        f"| WHERE {TS} AND span.subtype == \"gen_ai\"",
        "| EVAL cost = TO_DOUBLE(labels.llm_cost_usd)",
        "| STATS cost_usd = SUM(cost) BY team = COALESCE(labels.team, \"untagged\")",
        "| SORT cost_usd DESC",
    )
    model_tokens = _q(
        "FROM traces-apm-default",
        f"| WHERE {TS} AND span.subtype == \"gen_ai\"",
        "| STATS tokens = SUM(gen_ai.usage.total_tokens) BY model = gen_ai.request.model",
        "| SORT tokens DESC", "| LIMIT 16",
    )
    error_gauge = _q(
        "FROM traces-apm-default",
        f"| WHERE {TS} AND span.subtype == \"gen_ai\"",
        "| STATS errors = COUNT(*) WHERE event.outcome == \"failure\", calls = COUNT(*)",
        "| EVAL error_rate = errors * 1.0 / calls, min = 0, max = 0.08, goal = 0.01",
    )
    p95_gauge = _q(
        "FROM traces-apm-default",
        f"| WHERE {TS} AND span.subtype == \"gen_ai\"",
        "| STATS p95_ms = PERCENTILE(span.duration.us, 95) / 1000",
        "| EVAL min = 0, max = 8000, goal = 1500",
    )
    outcome = _q(
        "FROM traces-apm-default",
        f"| WHERE {TS} AND span.subtype == \"gen_ai\"",
        "| STATS calls = COUNT(*) BY outcome = event.outcome",
    )
    users = _q(
        "FROM logs-openai.completions-default",
        f"| WHERE {TS}",
        "| STATS tokens = SUM(openai.base.usage_tokens) BY user = openai.base.user_id",
        "| SORT tokens DESC", "| LIMIT 12",
    )

    panels = [
        section("Scoreboard — sparkline KPIs", 0, [
            markdown(0, 0, 48, 3,
                     "## Meridian Dynamics — FinOps & LLM Observability\n\n"
                     "Baseline Meridian FinOps + LLM view: stacked bars/areas, gauges, "
                     "waffles, tag clouds, and dual-axis usage vs cost.\n\n"
                     f"Time range: **{label}**. "
                     f"Security→cost (crypto / S3) lives on the "
                     f"[classic](#/view/{DASHBOARD_ID_CLASSIC}).\n\n"
                     f"[Open classic](#/view/{DASHBOARD_ID_CLASSIC}) · "
                     f"Scenarios: cost leak · ML burn · GenAI ramp · agent-loop · migration · cache-miss.\n\n"
                     f"**Budgets:** [Meridian FinOps AI Assistant]({AGENT_CHAT_URL}) · "
                     f"[Observability SLOs]({KIBANA_URL}/app/observability/slos) · "
                     f"`python -m src.cli agent`."),
            metric(0, 3, 12, 6, "AWS CUR", aws_trend, "cost", "USD · sparkline", trend=True),
            metric(12, 3, 12, 6, "GCP billing", gcp_trend, "cost", "USD · sparkline", trend=True),
            metric(24, 3, 12, 6, "Azure pretax", azure_trend, "cost", "USD · sparkline", trend=True),
            metric(36, 3, 12, 6, "LLM cost (APM)", llm_trend, "cost", "USD · sparkline", trend=True),
            waffle(0, 9, 16, 14, "Cloud spend mix", cloud_mix, "cost", "provider"),
            xy(16, 9, 32, 14, "Daily cost by cloud (stacked area)",
               daily_cloud, "day", ["cost"], layer="area_stacked", breakdown="provider"),
        ]),
        section("Allocation — stacked bars, area, waffle", 26, [
            xy(0, 0, 28, 16, "AWS cost by service — stacked by account",
               acct_svc, "service", ["cost"], layer="bar_stacked", breakdown="account"),
            waffle(28, 0, 20, 16, "AWS cost_center tags", cc_tag, "cost", "tag"),
            xy(0, 16, 48, 14, "AWS cost by account over day (stacked area)",
               cost_by_acct_day, "day", ["cost"], layer="area_stacked", breakdown="account"),
            xy(0, 30, 24, 14, "GCP cost by service — stacked by project",
               gcp_proj_svc, "service", ["cost"], layer="bar_stacked", breakdown="project"),
            xy(24, 30, 24, 14, "Azure cost by product — stacked by department",
               azure_dept, "product", ["cost"], layer="bar_stacked", breakdown="team"),
        ]),
        section("Usage vs cost — dual axis", 76, [
            xy_dual(
                0, 0, 48, 14, "EC2 unblended cost vs NetworkIn (dual axis)",
                {
                    "type": "area",
                    "data_source": _esql(ec2_cost_day),
                    "x": {"column": "day"},
                    "y": [{"column": "cost", "axis": "y"}],
                },
                {
                    "type": "line",
                    "data_source": _esql(net_day),
                    "x": {"column": "day"},
                    "y": [{"column": "network_in", "axis": "y2"}],
                },
            ),
            xy(0, 14, 24, 12, "AWS daily cost (smooth)",
               aws_trend, "day", ["cost"], layer="area"),
            gauge(24, 14, 24, 12, "AWS 30-day run-rate vs 7-day average",
                  forecast, "projected_30d", shape="arc",
                  min_col="min", max_col="max", goal_col="goal",
                  subtitle="USD projected"),
        ]),
        budget_posture_section(106),
        section("LLM landscape — models, teams, flows", 130, [
            tag_cloud(0, 0, 24, 14, "Models sized by tokens",
                      model_tokens, "tokens", "model"),
            waffle(24, 0, 24, 14, "LLM cost by team",
                   team_cost, "cost_usd", "team"),
            treemap(0, 14, 28, 16, "Token treemap — flow × model",
                    flow_model, "tokens", ["flow", "model"]),
            xy(28, 14, 20, 16, "Tokens by user flow",
               flow_tokens, "flow", ["tokens"], layer="bar_horizontal"),
        ]),
        section("LLM tokens & latency over time", 164, [
            xy(0, 0, 48, 14, "Tokens by flow over day (stacked area)",
               tokens_by_flow_day, "day", ["tokens"], layer="area_stacked", breakdown="flow"),
            xy(0, 14, 48, 14, "p95 latency by model over day (ms)",
               latency_by_model_day, "day", ["p95_ms"], layer="line", breakdown="model"),
            xy(0, 28, 32, 12, "Prompt vs completion (stacked area)",
               tokens_day, "day", ["prompt", "completion"], layer="area_stacked"),
            xy(32, 28, 16, 12, "OpenAI tokens by user",
               users, "user", ["tokens"], layer="bar_horizontal"),
        ]),
        section("Quality gauges & funnel", 194, [
            gauge(0, 0, 16, 12, "LLM error rate",
                  error_gauge, "error_rate", shape="arc",
                  min_col="min", max_col="max", goal_col="goal",
                  subtitle="failures / calls"),
            gauge(16, 0, 16, 12, "p95 latency",
                  p95_gauge, "p95_ms", shape="semi_circle",
                  min_col="min", max_col="max", goal_col="goal",
                  subtitle="ms"),
            pie(32, 0, 16, 12, "Call outcome",
                outcome, "calls", "outcome"),
            xy(0, 12, 24, 14, "Prompt vs completion by flow",
               flow_tokens, "flow", ["prompt", "completion"],
               layer="bar_horizontal_stacked"),
            xy(24, 12, 24, 14, "Cost by flow — stacked by model",
               flow_model, "flow", ["cost_usd"],
               layer="bar_horizontal_stacked", breakdown="model"),
        ]),
        section("Provider packs", 224, [
            links_panel(0, 0, 24, 10, "This family", [
                ("This baseline dashboard", DASHBOARD_ID),
                ("Classic layout", DASHBOARD_ID_CLASSIC),
                ("Dynamic alias (same as baseline)", DASHBOARD_ID_DYNAMIC),
                ("AI Assistant & inference usage", DASHBOARD_ID_AI),
                ("[Elastic] Inference Token Usage", DASHBOARD_ID_INFERENCE_USAGE),
            ]),
            links_panel(24, 0, 24, 10, "Provider FinOps & LLM packs", [
                *OOTB.items(),
                ("[Elastic] Inference Token Usage", DASHBOARD_ID_INFERENCE_USAGE),
                ("AI Assistant & inference usage", DASHBOARD_ID_AI),
            ]),
        ]),
    ]

    return {
        "title": "[Meridian] FinOps & LLM Observability",
        "description": (
            "Baseline Meridian FinOps + LLM dashboard: stacked bars and areas, "
            "gauges, waffles, tag clouds, and dual-axis usage vs cost."
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
    print("== data views ==")
    _ensure_data_view("traces-*", "traces-*")
    _ensure_data_view("metrics-*", "metrics-*")
    _ensure_data_view("logs-*", "logs-*")
    urls = []
    baseline = build_dashboard()
    if include_baseline:
        print(f"== PUT dashboard {DASHBOARD_ID} (baseline) ==")
        urls.append(_put_dashboard(DASHBOARD_ID, baseline))
    if include_dynamic_alias:
        # Same body/title as baseline so old bookmarks stay current.
        print(f"== PUT dashboard {DASHBOARD_ID_DYNAMIC} (alias of baseline) ==")
        urls.append(_put_dashboard(DASHBOARD_ID_DYNAMIC, baseline))
    if include_classic:
        print(f"== PUT dashboard {DASHBOARD_ID_CLASSIC} ==")
        urls.append(_put_dashboard(DASHBOARD_ID_CLASSIC, build_classic_dashboard()))
    if include_ai:
        from src.dashboards_ai import publish_ai
        urls.append(publish_ai())
    return urls

