"""Publish Elastic Co. Kibana dashboards (ES|QL panels)."""
from __future__ import annotations

import json

import requests

from src.config import KBN_HEADERS, KIBANA_DIR, KIBANA_URL

TS = "@timestamp <= ?_tend AND @timestamp > ?_tstart"
DEMO = 'labels.demo == "elastic-co"'
SVCS = (
    '"edge-gateway", "checkout-api", "payments-api", '
    '"identity-service", "inventory-service", "fraud-service", "notification-service"'
)


def _q(*lines: str) -> str:
    return "\n".join(lines)


def _esql(query: str) -> dict:
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
    shape_cfg = (
        {"type": "bullet", "orientation": "horizontal"}
        if shape == "bullet"
        else {"type": shape}
    )
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
            "styling": {"cells": {"labels": {"visible": False}}},
            "axis": {
                "x": {"labels": {"visible": True, "orientation": "horizontal"}},
                "y": {"labels": {"visible": True}},
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
                "font_size": {"min": 14, "max": 64},
                "caption": {"visible": False},
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
        },
    }


def xy(x, y, w, h, title, query, x_col, y_cols, layer="bar", breakdown=None):
    layer_cfg = {
        "type": layer,
        "data_source": _esql(query),
        "x": {"column": x_col},
        "y": [{"column": c} for c in y_cols],
    }
    if breakdown:
        layer_cfg["breakdown_by"] = {"column": breakdown}
    styling = None
    if layer in ("area", "area_stacked", "line"):
        styling = {
            "interpolation": "smooth",
            "areas": {"fill": "gradient", "fill_opacity": 0.7},
            "points": {"visibility": "auto"},
        }
    config = {
        "type": "xy",
        "title": title,
        "layers": [layer_cfg],
        "legend": {"visibility": "visible", "position": "right"},
        "axis": {
            "x": {
                "title": {"visible": False},
                "scale": "temporal" if "BUCKET" in x_col or x_col == "bucket" else None,
                "domain": {"type": "fit", "rounding": False}
                if "BUCKET" in x_col
                else None,
            },
            "y": {"title": {"visible": True}},
        },
    }
    # Clean null axis keys
    config["axis"]["x"] = {k: v for k, v in config["axis"]["x"].items() if v is not None}
    if styling:
        config["styling"] = styling
    return {"grid": _grid(x, y, w, h), "type": "vis", "config": config}


def xy_dual(x, y, w, h, title, layer_a, layer_b):
    return {
        "grid": _grid(x, y, w, h),
        "type": "vis",
        "config": {
            "type": "xy",
            "title": title,
            "layers": [layer_a, layer_b],
            "legend": {"visibility": "visible", "position": "right"},
            "axis": {
                "x": {
                    "title": {"visible": False},
                    "scale": "temporal",
                    "domain": {"type": "fit", "rounding": False},
                },
                "y": {"title": {"visible": True}},
                "y2": {"title": {"visible": True}},
            },
            "styling": {
                "interpolation": "smooth",
                "areas": {"fill": "gradient", "fill_opacity": 0.55},
            },
        },
    }


def build_distributed_traces() -> dict:
    txn_trend = _q(
        "FROM traces-apm-default",
        f"| WHERE {TS} AND {DEMO}",
        "| WHERE processor.event == \"transaction\"",
        f"| WHERE service.name IN ({SVCS})",
        "| STATS count = COUNT(*) BY bucket = BUCKET(@timestamp, 40, ?_tstart, ?_tend)",
        "| SORT bucket",
    )
    fail_trend = _q(
        "FROM traces-apm-default",
        f"| WHERE {TS} AND {DEMO}",
        "| WHERE processor.event == \"transaction\" AND event.outcome == \"failure\"",
        "| STATS count = COUNT(*) BY bucket = BUCKET(@timestamp, 40, ?_tstart, ?_tend)",
        "| SORT bucket",
    )
    checkout_p95_trend = _q(
        "FROM traces-apm-default",
        f"| WHERE {TS} AND {DEMO}",
        "| WHERE processor.event == \"transaction\" AND service.name == \"checkout-api\"",
        "| STATS p95_ms = PERCENTILE(transaction.duration.us, 95) / 1000 "
        "BY bucket = BUCKET(@timestamp, 40, ?_tstart, ?_tend)",
        "| SORT bucket",
    )
    slow_db_trend = _q(
        "FROM traces-apm-default",
        f"| WHERE {TS} AND {DEMO}",
        "| WHERE span.type == \"db\" AND span.subtype == \"postgresql\"",
        "| WHERE span.duration.us > 2000000",
        "| STATS count = COUNT(*) BY bucket = BUCKET(@timestamp, 40, ?_tstart, ?_tend)",
        "| SORT bucket",
    )

    err_gauge = _q(
        "FROM traces-apm-default",
        f"| WHERE {TS} AND {DEMO}",
        "| WHERE processor.event == \"transaction\"",
        f"| WHERE service.name IN ({SVCS})",
        "| STATS errors = COUNT(*) WHERE event.outcome == \"failure\", calls = COUNT(*)",
        "| EVAL error_rate = errors * 1.0 / calls, min = 0.0, max = 0.25, goal = 0.01",
    )
    p95_gauge = _q(
        "FROM traces-apm-default",
        f"| WHERE {TS} AND {DEMO}",
        "| WHERE processor.event == \"transaction\" AND service.name == \"checkout-api\"",
        "| STATS p95_ms = PERCENTILE(transaction.duration.us, 95) / 1000",
        "| EVAL min = 0.0, max = 5000.0, goal = 400.0",
    )
    db_gauge = _q(
        "FROM traces-apm-default",
        f"| WHERE {TS} AND {DEMO}",
        "| WHERE span.type == \"db\" AND span.subtype == \"postgresql\"",
        "| STATS p95_ms = PERCENTILE(span.duration.us, 95) / 1000",
        "| EVAL min = 0.0, max = 4000.0, goal = 100.0",
    )

    vol_by_svc = _q(
        "FROM traces-apm-default",
        f"| WHERE {TS} AND {DEMO}",
        "| WHERE processor.event == \"transaction\"",
        f"| WHERE service.name IN ({SVCS})",
        "| STATS count = COUNT(*) BY service.name",
    )
    outcome = _q(
        "FROM traces-apm-default",
        f"| WHERE {TS} AND {DEMO}",
        "| WHERE processor.event == \"transaction\"",
        f"| WHERE service.name IN ({SVCS})",
        "| STATS count = COUNT(*) BY event.outcome",
    )
    treemap_svc_tenant = _q(
        "FROM traces-apm-default",
        f"| WHERE {TS} AND {DEMO}",
        "| WHERE processor.event == \"transaction\"",
        f"| WHERE service.name IN ({SVCS})",
        "| STATS count = COUNT(*) BY service.name, tenant.id",
    )
    heat_tenant_svc = _q(
        "FROM traces-apm-default",
        f"| WHERE {TS} AND {DEMO}",
        "| WHERE processor.event == \"transaction\"",
        f"| WHERE service.name IN ({SVCS})",
        "| STATS p95_ms = PERCENTILE(transaction.duration.us, 95) / 1000 "
        "BY tenant.id, service.name",
    )
    # Serverless Dashboards API rejects ES|QL heatmaps; use matrix bars instead.
    heat_time_svc = _q(
        "FROM traces-apm-default",
        f"| WHERE {TS} AND {DEMO}",
        "| WHERE processor.event == \"transaction\"",
        f"| WHERE service.name IN ({SVCS})",
        "| STATS p95_ms = PERCENTILE(transaction.duration.us, 95) / 1000 "
        "BY bucket = BUCKET(@timestamp, 24, ?_tstart, ?_tend), service.name",
    )
    deps_tree = _q(
        "FROM traces-apm-default",
        f"| WHERE {TS} AND {DEMO}",
        "| WHERE processor.event == \"span\"",
        "| WHERE destination.service.resource IS NOT NULL",
        "| STATS count = COUNT(*), p95_ms = PERCENTILE(span.duration.us, 95) / 1000 "
        "BY service.name, destination.service.resource",
    )
    tx_cloud = _q(
        "FROM traces-apm-default",
        f"| WHERE {TS} AND {DEMO}",
        "| WHERE processor.event == \"transaction\"",
        f"| WHERE service.name IN ({SVCS})",
        "| STATS count = COUNT(*) BY transaction.name",
    )
    area_svc = _q(
        "FROM traces-apm-default",
        f"| WHERE {TS} AND {DEMO}",
        "| WHERE processor.event == \"transaction\"",
        f"| WHERE service.name IN ({SVCS})",
        "| STATS count = COUNT(*) BY bucket = BUCKET(@timestamp, 50, ?_tstart, ?_tend), "
        "service.name",
    )
    dual_count = _q(
        "FROM traces-apm-default",
        f"| WHERE {TS} AND {DEMO}",
        "| WHERE processor.event == \"transaction\" AND service.name == \"checkout-api\"",
        "| STATS count = COUNT(*) BY bucket = BUCKET(@timestamp, 40, ?_tstart, ?_tend)",
        "| SORT bucket",
    )
    dual_p95 = _q(
        "FROM traces-apm-default",
        f"| WHERE {TS} AND {DEMO}",
        "| WHERE processor.event == \"transaction\" AND service.name == \"checkout-api\"",
        "| STATS p95_ms = PERCENTILE(transaction.duration.us, 95) / 1000 "
        "BY bucket = BUCKET(@timestamp, 40, ?_tstart, ?_tend)",
        "| SORT bucket",
    )
    tenant_lines = _q(
        "FROM traces-apm-default",
        f"| WHERE {TS} AND {DEMO}",
        "| WHERE processor.event == \"transaction\" AND service.name == \"checkout-api\"",
        "| STATS p95_ms = PERCENTILE(transaction.duration.us, 95) / 1000 "
        "BY bucket = BUCKET(@timestamp, 40, ?_tstart, ?_tend), tenant.id",
    )
    span_breakdown = _q(
        "FROM traces-apm-default",
        f"| WHERE {TS} AND {DEMO}",
        "| WHERE processor.event == \"span\"",
        "| STATS p95_ms = PERCENTILE(span.duration.us, 95) / 1000, n = COUNT(*) "
        "BY span.subtype",
        "| SORT p95_ms DESC",
    )

    panels = [
        markdown(
            0,
            0,
            48,
            3,
            "## Elastic Co. — Distributed traces (dynamic)\n\n"
            "**edge-gateway → checkout-api → payments-api** + **orders-db** (postgres). "
            "Treemaps, heatmaps, gauges, waffles, tag clouds, dual-axis volume vs latency. "
            "Filter `labels.demo: elastic-co` · time **Last 6 hours**.",
        ),
        # Scoreboard with sparklines
        metric(0, 3, 12, 7, "Transactions", txn_trend, "count", "sparkline", trend=True),
        metric(12, 3, 12, 7, "Failures", fail_trend, "count", "sparkline", trend=True),
        metric(
            24,
            3,
            12,
            7,
            "Checkout p95 (ms)",
            checkout_p95_trend,
            "p95_ms",
            "sparkline",
            trend=True,
        ),
        metric(
            36,
            3,
            12,
            7,
            "Slow DB spans",
            slow_db_trend,
            "count",
            ">2s postgres",
            trend=True,
        ),
        # Gauges + waffle + pie
        gauge(
            0,
            10,
            12,
            12,
            "Error rate",
            err_gauge,
            "error_rate",
            shape="arc",
            min_col="min",
            max_col="max",
            goal_col="goal",
            subtitle="failures / txns",
        ),
        gauge(
            12,
            10,
            12,
            12,
            "Checkout p95",
            p95_gauge,
            "p95_ms",
            shape="semi_circle",
            min_col="min",
            max_col="max",
            goal_col="goal",
            subtitle="ms · goal 400",
        ),
        gauge(
            24,
            10,
            12,
            12,
            "Postgres p95",
            db_gauge,
            "p95_ms",
            shape="arc",
            min_col="min",
            max_col="max",
            goal_col="goal",
            subtitle="ms · goal 100",
        ),
        waffle(36, 10, 12, 12, "Outcome mix", outcome, "count", "event.outcome"),
        # Flow landscape
        treemap(
            0,
            22,
            28,
            16,
            "Traffic treemap — service × tenant",
            treemap_svc_tenant,
            "count",
            ["service.name", "tenant.id"],
        ),
        pie(28, 22, 20, 16, "Txn share by service", vol_by_svc, "count", "service.name"),
        treemap(
            0,
            38,
            28,
            16,
            "Dependency treemap — caller → destination",
            deps_tree,
            "count",
            ["service.name", "destination.service.resource"],
        ),
        tag_cloud(
            28,
            38,
            20,
            16,
            "Transaction names",
            tx_cloud,
            "count",
            "transaction.name",
        ),
        # Latency matrix (heatmap alternative — ES|QL heatmap not supported here)
        xy(
            0,
            54,
            48,
            14,
            "p95 latency matrix — tenant × service (ms)",
            heat_tenant_svc,
            "tenant.id",
            ["p95_ms"],
            layer="bar",
            breakdown="service.name",
        ),
        xy(
            0,
            68,
            48,
            14,
            "p95 latency over time by service (ms)",
            heat_time_svc,
            "bucket",
            ["p95_ms"],
            layer="area",
            breakdown="service.name",
        ),
        # Motion / dual axis
        xy(
            0,
            82,
            48,
            14,
            "Transaction volume by service (stacked area)",
            area_svc,
            "bucket",
            ["count"],
            layer="area_stacked",
            breakdown="service.name",
        ),
        xy_dual(
            0,
            96,
            48,
            14,
            "Checkout volume vs p95 latency (dual axis)",
            {
                "type": "area",
                "data_source": _esql(dual_count),
                "x": {"column": "bucket"},
                "y": [{"column": "count", "axis": "y"}],
            },
            {
                "type": "line",
                "data_source": _esql(dual_p95),
                "x": {"column": "bucket"},
                "y": [{"column": "p95_ms", "axis": "y2"}],
            },
        ),
        xy(
            0,
            110,
            32,
            14,
            "Checkout p95 by tenant over time",
            tenant_lines,
            "bucket",
            ["p95_ms"],
            layer="line",
            breakdown="tenant.id",
        ),
        xy(
            32,
            110,
            16,
            14,
            "Span subtype p95 (ms)",
            span_breakdown,
            "span.subtype",
            ["p95_ms"],
            layer="bar_horizontal",
        ),
    ]

    return {
        "title": "Elastic Co. — Distributed Traces",
        "description": (
            "Dynamic cross-service APM dashboard: gauges, treemaps, heatmaps, "
            "waffles, tag clouds, stacked areas, dual-axis volume vs latency."
        ),
        "time_range": {"from": "now-6h", "to": "now"},
        "options": {
            "use_margins": True,
            "sync_colors": True,
            "sync_cursor": True,
            "sync_tooltips": True,
            "hide_panel_titles": False,
        },
        "query": {"expression": "labels.demo: elastic-co", "language": "kql"},
        "panels": panels,
    }


def build_e2e_tracing() -> dict:
    """Checkout request path: gateway → services → db/cache/kafka."""
    hop = (
        'EVAL hop = CASE('
        'service.name == "edge-gateway", 1, '
        'service.name == "identity-service", 2, '
        'service.name == "checkout-api", 3, '
        'service.name == "inventory-service", 4, '
        'service.name == "fraud-service", 5, '
        'service.name == "payments-api", 6, '
        'service.name == "notification-service", 7, '
        '99)'
    )
    traces_n = _q(
        "FROM traces-apm-default",
        f"| WHERE {TS} AND {DEMO}",
        '| WHERE processor.event == "transaction" AND service.name == "edge-gateway"',
        "| STATS count = COUNT(*) BY bucket = BUCKET(@timestamp, 40, ?_tstart, ?_tend)",
        "| SORT bucket",
    )
    hops_n = _q(
        "FROM traces-apm-default",
        f"| WHERE {TS} AND {DEMO}",
        '| WHERE processor.event == "transaction"',
        f"| WHERE service.name IN ({SVCS})",
        "| STATS hops = COUNT_DISTINCT(service.name) BY trace.id",
        "| STATS avg_hops = AVG(hops)",
    )
    e2e_p95 = _q(
        "FROM traces-apm-default",
        f"| WHERE {TS} AND {DEMO}",
        '| WHERE processor.event == "transaction" AND service.name == "edge-gateway"',
        "| STATS p95_ms = PERCENTILE(transaction.duration.us, 95) / 1000 "
        "BY bucket = BUCKET(@timestamp, 40, ?_tstart, ?_tend)",
        "| SORT bucket",
    )
    slow_db = _q(
        "FROM traces-apm-default",
        f"| WHERE {TS} AND {DEMO}",
        '| WHERE span.type == "db" AND span.subtype == "postgresql"',
        "| WHERE span.duration.us > 2000000",
        "| STATS count = COUNT(*) BY bucket = BUCKET(@timestamp, 40, ?_tstart, ?_tend)",
        "| SORT bucket",
    )
    err_gauge = _q(
        "FROM traces-apm-default",
        f"| WHERE {TS} AND {DEMO}",
        '| WHERE processor.event == "transaction" AND service.name == "edge-gateway"',
        '| STATS errors = COUNT(*) WHERE event.outcome == "failure", calls = COUNT(*)',
        "| EVAL error_rate = errors * 1.0 / calls, min = 0.0, max = 0.25, goal = 0.01",
    )
    e2e_gauge = _q(
        "FROM traces-apm-default",
        f"| WHERE {TS} AND {DEMO}",
        '| WHERE processor.event == "transaction" AND service.name == "edge-gateway"',
        "| STATS p95_ms = PERCENTILE(transaction.duration.us, 95) / 1000",
        "| EVAL min = 0.0, max = 5000.0, goal = 400.0",
    )
    db_gauge = _q(
        "FROM traces-apm-default",
        f"| WHERE {TS} AND {DEMO}",
        '| WHERE span.type == "db" AND span.subtype == "postgresql"',
        "| STATS p95_ms = PERCENTILE(span.duration.us, 95) / 1000",
        "| EVAL min = 0.0, max = 4000.0, goal = 100.0",
    )
    outcome = _q(
        "FROM traces-apm-default",
        f"| WHERE {TS} AND {DEMO}",
        '| WHERE processor.event == "transaction" AND service.name == "edge-gateway"',
        "| STATS count = COUNT(*) BY event.outcome",
    )
    hop_flow = _q(
        "FROM traces-apm-default",
        f"| WHERE {TS} AND {DEMO}",
        '| WHERE processor.event == "span"',
        "| WHERE destination.service.resource IS NOT NULL",
        "| STATS n = COUNT(*), p95_ms = PERCENTILE(span.duration.us, 95) / 1000 "
        "BY service.name, destination.service.resource",
    )
    hop_p95 = _q(
        "FROM traces-apm-default",
        f"| WHERE {TS} AND {DEMO}",
        '| WHERE processor.event == "transaction"',
        f"| WHERE service.name IN ({SVCS})",
        f"| {hop}",
        "| STATS p95_ms = PERCENTILE(transaction.duration.us, 95) / 1000, "
        "n = COUNT(*) BY hop, service.name",
        "| SORT hop",
    )
    span_p95 = _q(
        "FROM traces-apm-default",
        f"| WHERE {TS} AND {DEMO}",
        '| WHERE processor.event == "span"',
        "| STATS p95_ms = PERCENTILE(span.duration.us, 95) / 1000, n = COUNT(*) "
        "BY span.name, service.name",
        "| SORT p95_ms DESC",
        "| LIMIT 12",
    )
    tenant_e2e = _q(
        "FROM traces-apm-default",
        f"| WHERE {TS} AND {DEMO}",
        '| WHERE processor.event == "transaction" AND service.name == "edge-gateway"',
        "| STATS p95_ms = PERCENTILE(transaction.duration.us, 95) / 1000 "
        "BY bucket = BUCKET(@timestamp, 40, ?_tstart, ?_tend), tenant.id",
    )
    tenant_bar = _q(
        "FROM traces-apm-default",
        f"| WHERE {TS} AND {DEMO}",
        '| WHERE processor.event == "transaction" AND service.name == "edge-gateway"',
        "| STATS p95_ms = PERCENTILE(transaction.duration.us, 95) / 1000, "
        "n = COUNT(*) BY tenant.id",
        "| SORT p95_ms DESC",
    )
    fail_by_svc = _q(
        "FROM traces-apm-default",
        f"| WHERE {TS} AND {DEMO}",
        '| WHERE processor.event == "transaction" AND event.outcome == "failure"',
        f"| WHERE service.name IN ({SVCS})",
        "| STATS fails = COUNT(*) BY service.name",
        "| SORT fails DESC",
    )
    slow_traces = _q(
        "FROM traces-apm-default",
        f"| WHERE {TS} AND {DEMO}",
        '| WHERE processor.event == "transaction" AND service.name == "edge-gateway"',
        "| STATS duration_ms = MAX(transaction.duration.us) / 1000 "
        "BY trace.id, tenant.id, event.outcome",
        "| SORT duration_ms DESC",
        "| LIMIT 15",
    )
    orch_corr = _q(
        "FROM logs-elasticco.orchestrator-default",
        f"| WHERE {TS} AND {DEMO}",
        "| WHERE trace.id IS NOT NULL",
        "| STATS n = COUNT(*) BY tenant.id, orchestrator.task_id",
    )
    dual_count = _q(
        "FROM traces-apm-default",
        f"| WHERE {TS} AND {DEMO}",
        '| WHERE processor.event == "transaction" AND service.name == "edge-gateway"',
        "| STATS count = COUNT(*) BY bucket = BUCKET(@timestamp, 40, ?_tstart, ?_tend)",
        "| SORT bucket",
    )
    dual_p95 = _q(
        "FROM traces-apm-default",
        f"| WHERE {TS} AND {DEMO}",
        '| WHERE processor.event == "transaction" AND service.name == "edge-gateway"',
        "| STATS p95_ms = PERCENTILE(transaction.duration.us, 95) / 1000 "
        "BY bucket = BUCKET(@timestamp, 40, ?_tstart, ?_tend)",
        "| SORT bucket",
    )

    panels = [
        markdown(
            0,
            0,
            48,
            4,
            "## Elastic Co. — End-to-end checkout trace\n\n"
            "**edge-gateway → identity-service → checkout-api → "
            "inventory / fraud / payments → postgres + redis + kafka → "
            "notification-service**\n\n"
            "Root span `POST /checkout` · `labels.demo: elastic-co` · time **Last 6 hours**. "
            "Copy a `trace.id` from the slow-traces chart into **APM → Traces** for the waterfall. "
            "Hero example: `271f8e318871e99f577feb2cb22cd2d3` (acme-retail, correlated to orchestrator logs).",
        ),
        metric(0, 4, 12, 7, "Checkout traces", traces_n, "count", "root POST /checkout", trend=True),
        metric(12, 4, 12, 7, "Services per trace", hops_n, "avg_hops", "distinct hops"),
        metric(24, 4, 12, 7, "E2E p95 (ms)", e2e_p95, "p95_ms", "edge-gateway", trend=True),
        metric(36, 4, 12, 7, "Slow DB spans", slow_db, "count", ">2s postgres", trend=True),
        gauge(
            0, 11, 12, 12, "E2E error rate", err_gauge, "error_rate",
            shape="arc", min_col="min", max_col="max", goal_col="goal",
            subtitle="gateway failures",
        ),
        gauge(
            12, 11, 12, 12, "E2E p95", e2e_gauge, "p95_ms",
            shape="semi_circle", min_col="min", max_col="max", goal_col="goal",
            subtitle="ms · goal 400",
        ),
        gauge(
            24, 11, 12, 12, "Postgres p95", db_gauge, "p95_ms",
            shape="arc", min_col="min", max_col="max", goal_col="goal",
            subtitle="ms · goal 100",
        ),
        waffle(36, 11, 12, 12, "Trace outcome", outcome, "count", "event.outcome"),
        treemap(
            0, 23, 28, 16,
            "Trace flow — caller → destination",
            hop_flow, "n",
            ["service.name", "destination.service.resource"],
        ),
        pie(
            28, 23, 20, 16,
            "Destination share",
            _q(
                "FROM traces-apm-default",
                f"| WHERE {TS} AND {DEMO}",
                '| WHERE processor.event == "span"',
                "| WHERE destination.service.resource IS NOT NULL",
                "| STATS n = COUNT(*) BY destination.service.resource",
            ),
            "n",
            "destination.service.resource",
        ),
        xy(
            0, 39, 24, 14,
            "p95 by hop (waterfall order, ms)",
            hop_p95, "service.name", ["p95_ms"],
            layer="bar_horizontal",
        ),
        xy(
            24, 39, 24, 14,
            "Slowest spans (p95 ms)",
            span_p95, "span.name", ["p95_ms"],
            layer="bar_horizontal",
            breakdown="service.name",
        ),
        xy(
            0, 53, 32, 14,
            "E2E p95 by tenant over time (ms)",
            tenant_e2e, "bucket", ["p95_ms"],
            layer="line",
            breakdown="tenant.id",
        ),
        xy(
            32, 53, 16, 14,
            "E2E p95 by tenant (ms)",
            tenant_bar, "tenant.id", ["p95_ms"],
            layer="bar_horizontal",
        ),
        xy_dual(
            0, 67, 32, 14,
            "Trace volume vs E2E p95 (dual axis)",
            {
                "type": "area",
                "data_source": _esql(dual_count),
                "x": {"column": "bucket"},
                "y": [{"column": "count", "axis": "y"}],
            },
            {
                "type": "line",
                "data_source": _esql(dual_p95),
                "x": {"column": "bucket"},
                "y": [{"column": "p95_ms", "axis": "y2"}],
            },
        ),
        xy(
            32, 67, 16, 14,
            "Failures by hop",
            fail_by_svc, "service.name", ["fails"],
            layer="bar_horizontal",
        ),
        xy(
            0, 81, 32, 16,
            "Slowest traces (ms) — copy trace.id into APM → Traces",
            slow_traces,
            "trace.id",
            ["duration_ms"],
            layer="bar_horizontal",
            breakdown="tenant.id",
        ),
        treemap(
            32, 81, 16, 16,
            "Orchestrator tasks × tenant (same trace.id)",
            orch_corr, "n",
            ["tenant.id", "orchestrator.task_id"],
        ),
    ]
    return {
        "title": "Elastic Co. — End-to-End Tracing",
        "description": (
            "Checkout request path across 7 services: hop flow, waterfall latency, "
            "tenant comparison, slow traces, and orchestrator correlation."
        ),
        "time_range": {"from": "now-6h", "to": "now"},
        "options": {
            "use_margins": True,
            "sync_colors": True,
            "sync_cursor": True,
            "sync_tooltips": True,
            "hide_panel_titles": False,
        },
        "query": {"expression": "labels.demo: elastic-co", "language": "kql"},
        "panels": panels,
    }


def build_eks_restarts() -> dict:
    """U3 monitor: EKS pod restarts → OOMKilled / BackOff → memory vs limit."""
    oom_n = _q(
        "FROM logs-elasticco.k8s.event-default",
        f"| WHERE {TS} AND {DEMO}",
        '| WHERE kubernetes.event.reason == "OOMKilled"',
        "| STATS count = COUNT(*)",
    )
    backoff_n = _q(
        "FROM logs-elasticco.k8s.event-default",
        f"| WHERE {TS} AND {DEMO}",
        '| WHERE kubernetes.event.reason == "BackOff"',
        "| STATS count = COUNT(*)",
    )
    max_restarts = _q(
        "FROM metrics-elasticco.k8s.pod-default",
        f"| WHERE {TS} AND {DEMO}",
        '| WHERE service.name == "checkout-api"',
        "| STATS max_restarts = MAX(kubernetes.pod.restart.count)",
    )
    mem_pct = _q(
        "FROM metrics-elasticco.k8s.pod-default",
        f"| WHERE {TS} AND {DEMO}",
        '| WHERE service.name == "checkout-api"',
        "| STATS mem_pct = MAX(kubernetes.pod.memory.usage.limit.pct)",
        "| EVAL min = 0.0, max = 1.0, goal = 0.80",
    )
    mem_trend = _q(
        "FROM metrics-elasticco.k8s.pod-default",
        f"| WHERE {TS} AND {DEMO}",
        '| WHERE service.name == "checkout-api"',
        "| STATS rss_mib = AVG(kubernetes.pod.memory.usage.bytes) / 1024 / 1024, "
        "limit_mib = MAX(kubernetes.pod.memory.limit.bytes) / 1024 / 1024 "
        "BY bucket = BUCKET(@timestamp, 40, ?_tstart, ?_tend)",
        "| SORT bucket",
    )
    restart_trend = _q(
        "FROM metrics-elasticco.k8s.pod-default",
        f"| WHERE {TS} AND {DEMO}",
        '| WHERE service.name == "checkout-api"',
        "| STATS restarts = MAX(kubernetes.pod.restart.count) "
        "BY bucket = BUCKET(@timestamp, 40, ?_tstart, ?_tend), kubernetes.pod.name",
        "| SORT bucket",
    )
    event_trend = _q(
        "FROM logs-elasticco.k8s.event-default",
        f"| WHERE {TS} AND {DEMO}",
        '| WHERE kubernetes.event.reason IN ("OOMKilled", "BackOff")',
        "| STATS count = COUNT(*) BY bucket = BUCKET(@timestamp, 40, ?_tstart, ?_tend), "
        "kubernetes.event.reason",
        "| SORT bucket",
    )
    event_pie = _q(
        "FROM logs-elasticco.k8s.event-default",
        f"| WHERE {TS} AND {DEMO}",
        "| WHERE kubernetes.event.reason IS NOT NULL",
        "| STATS count = COUNT(*) BY kubernetes.event.reason",
    )
    by_pod = _q(
        "FROM metrics-elasticco.k8s.pod-default",
        f"| WHERE {TS} AND {DEMO}",
        '| WHERE service.name == "checkout-api"',
        "| STATS restarts = MAX(kubernetes.pod.restart.count), "
        "mem_pct = MAX(kubernetes.pod.memory.usage.limit.pct) "
        "BY kubernetes.pod.name",
        "| SORT restarts DESC",
    )
    oom_pods = _q(
        "FROM logs-elasticco.k8s.event-default",
        f"| WHERE {TS} AND {DEMO}",
        '| WHERE kubernetes.event.reason IN ("OOMKilled", "BackOff")',
        "| STATS events = COUNT(*) BY kubernetes.pod.name, kubernetes.event.reason, service.version",
        "| SORT events DESC",
    )

    panels = [
        markdown(
            0,
            0,
            48,
            4,
            "## Elastic Co. — EKS restart monitor\n\n"
            "Cluster **eks-elastic-prod-usc1** · Deployment **checkout-api** · "
            "`labels.demo: elastic-co`. Restarts are the symptom; **OOMKilled** + "
            "**v2.4.1** / `CartCache.retainAll` is the reason. Time range **Last 6 hours**.",
        ),
        metric(0, 4, 12, 7, "OOMKilled events", oom_n, "count", "k8s Warning", trend=True),
        metric(12, 4, 12, 7, "BackOff events", backoff_n, "count", "restart loop", trend=True),
        metric(24, 4, 12, 7, "Max pod restarts", max_restarts, "max_restarts", "checkout-api"),
        gauge(
            36, 4, 12, 7, "Memory vs limit", mem_pct, "mem_pct",
            shape="arc", min_col="min", max_col="max", goal_col="goal",
            subtitle="peak · goal 80%",
        ),
        xy(
            0, 11, 24, 14,
            "Checkout-api memory vs limit (MiB)",
            mem_trend, "bucket", ["rss_mib", "limit_mib"],
            layer="line",
        ),
        xy(
            24, 11, 24, 14,
            "Restart count by pod",
            restart_trend, "bucket", ["restarts"],
            layer="line",
            breakdown="kubernetes.pod.name",
        ),
        xy(
            0, 25, 32, 14,
            "OOMKilled / BackOff over time",
            event_trend, "bucket", ["count"],
            layer="bar",
            breakdown="kubernetes.event.reason",
        ),
        pie(32, 25, 16, 14, "K8s event reasons", event_pie, "count", "kubernetes.event.reason"),
        xy(
            0, 39, 24, 14,
            "Restarts by checkout-api pod",
            by_pod, "kubernetes.pod.name", ["restarts"],
            layer="bar_horizontal",
        ),
        xy(
            24, 39, 24, 14,
            "OOM / BackOff events by pod",
            oom_pods, "kubernetes.pod.name", ["events"],
            layer="bar_horizontal",
            breakdown="kubernetes.event.reason",
        ),
    ]
    return {
        "title": "Elastic Co. — EKS Restarts",
        "description": (
            "Monitor checkout-api pod restarts on eks-elastic-prod-usc1: "
            "restart count, OOMKilled/BackOff events, and memory vs limit."
        ),
        "time_range": {"from": "now-6h", "to": "now"},
        "options": {
            "use_margins": True,
            "sync_colors": True,
            "sync_cursor": True,
            "sync_tooltips": True,
            "hide_panel_titles": False,
        },
        "query": {"expression": "labels.demo: elastic-co", "language": "kql"},
        "panels": panels,
    }


def _put_dashboard(dash_id: str, body: dict) -> str:
    r = requests.put(
        f"{KIBANA_URL}/api/dashboards/{dash_id}",
        headers=KBN_HEADERS,
        json=body,
        timeout=120,
    )
    if r.status_code >= 300:
        r2 = requests.put(
            f"{KIBANA_URL}/api/dashboards/{dash_id}",
            headers=KBN_HEADERS,
            json={"dashboard": body},
            timeout=120,
        )
        if r2.status_code >= 300:
            print(f"[fail] dashboard {dash_id}: {r.status_code} {r.text[:800]}")
            print(f"       retry: {r2.status_code} {r2.text[:800]}")
            raise SystemExit(1)
    # Persist JSON snapshots
    snapshots = {
        "elasticco-distributed-traces": "dashboard-distributed-traces.json",
        "elasticco-e2e-tracing": "dashboard-e2e-tracing.json",
        "elasticco-eks-restarts": "dashboard-eks-restarts.json",
    }
    if dash_id in snapshots:
        (KIBANA_DIR / snapshots[dash_id]).write_text(json.dumps(body, indent=2) + "\n")
    url = f"{KIBANA_URL}/app/dashboards#/view/{dash_id}"
    print(f"[ok] dashboard {body['title']}")
    print(f"  {url}")
    return url


def publish_incident_overview() -> str:
    body = json.loads((KIBANA_DIR / "dashboard-incident-overview.json").read_text())
    return _put_dashboard("elasticco-incident-overview", body)


def publish_distributed_traces() -> str:
    return _put_dashboard("elasticco-distributed-traces", build_distributed_traces())


def publish_e2e_tracing() -> str:
    return _put_dashboard("elasticco-e2e-tracing", build_e2e_tracing())


def publish_eks_restarts() -> str:
    return _put_dashboard("elasticco-eks-restarts", build_eks_restarts())


def publish_all() -> list[str]:
    return [
        publish_incident_overview(),
        publish_distributed_traces(),
        publish_e2e_tracing(),
        publish_eks_restarts(),
    ]
