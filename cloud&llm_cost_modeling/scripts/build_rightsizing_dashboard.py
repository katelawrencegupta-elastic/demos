"""Rebuild finops-rightsizing-overview with panels that render on Serverless.

Vega / visualization panelRefName panels are stripped on Serverless import.
This rewrite embeds Lens ES|QL + formBased panels by value only (same pattern
as spend-vs-savings). Linked explorer = bubble scatter + action bars side by
side (tooltips via Lens), not Vega brush.

Usage:
  .venv/bin/python scripts/build_rightsizing_dashboard.py
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NDJSON = ROOT / "kibana" / "live" / "dashboards.ndjson"
DASH_ID = "finops-rightsizing-overview"

# Data view used by the rightsizing queue table on this dashboard
RS_DATA_VIEW_ID = "52ad367e-9784-4289-82c2-daae4cb532e3"
RS_LATEST = "finops-rightsizing-latest*"
EC2 = "metrics-aws.ec2_metrics-*"
RDS = "metrics-aws.rds-*"

ACCOUNT_CASE = """EVAL account = CASE(
    cloud.account.id == "985408759551", "apm-stage",
    cloud.account.id == "041298796264", "monitoring / elastic-integration",
    cloud.account.id == "439106060789", "ESF (439106060789)",
    cloud.account.id == "119672459156", "ESF (119672459156)",
    cloud.account.id
)"""


def _adhoc_id(title: str) -> str:
    digest = hashlib.sha256(title.encode()).hexdigest()
    return f"{title}-{digest}"


def _lens_panel(panel_id: str, title: str, attrs: dict, x: int, y: int, w: int, h: int) -> dict:
    return {
        "type": "vis",
        "panelIndex": panel_id,
        "gridData": {"x": x, "y": y, "w": w, "h": h, "i": panel_id},
        "embeddableConfig": {
            "title": title,
            "hide_title": False,
            "attributes": attrs,
            "enhancements": {},
        },
    }


def _metric(label: str, kuery: str, field: str = "finops.rightsizing.estimated_monthly_savings",
            op: str = "sum") -> dict:
    col = {
        "operationType": op,
        "sourceField": field if op != "count" else "___records___",
        "dataType": "number",
        "isBucketed": False,
        "filter": {"language": "kuery", "query": kuery},
        "label": label,
        "customLabel": True,
        "params": {"emptyAsNull": True},
    }
    if op == "count":
        col["sourceField"] = "___records___"
    return {
        "visualizationType": "lnsMetric",
        "title": "",
        "references": [
            {"type": "index-pattern", "id": RS_DATA_VIEW_ID,
             "name": "indexpattern-datasource-layer-layer_0"}
        ],
        "version": 2,
        "state": {
            "datasourceStates": {
                "formBased": {
                    "layers": {
                        "layer_0": {
                            "sampling": 1,
                            "ignoreGlobalFilters": False,
                            "columns": {"metric_accessor_metric": col},
                            "columnOrder": ["metric_accessor_metric"],
                        }
                    }
                }
            },
            "internalReferences": [],
            "visualization": {
                "layerId": "layer_0",
                "layerType": "data",
                "metricAccessor": "metric_accessor_metric",
                "showBar": False,
                "density": "compact",
                "valueFontMode": "default",
                "titlesTextAlign": "left",
                "primaryAlign": "right",
                "primaryPosition": "bottom",
            },
            "adHocDataViews": {},
            "query": {"language": "kuery", "query": ""},
            "filters": [],
        },
    }


def _esql_bar(esql: str, x_field: str, y_field: str, x_label: str, y_label: str,
              index_title: str = RS_LATEST) -> dict:
    aid = _adhoc_id(index_title)
    layer = "bar_horizontal_0"
    return {
        "visualizationType": "lnsXY",
        "version": 2,
        "title": "",
        "state": {
            "datasourceStates": {
                "textBased": {
                    "layers": {
                        layer: {
                            "index": aid,
                            "query": {"esql": esql},
                            "columns": [
                                {"columnId": f"{layer}_x", "fieldName": x_field,
                                 "label": x_label, "customLabel": True,
                                 "meta": {"type": "string"}},
                                {"columnId": f"{layer}_y_0", "fieldName": y_field,
                                 "label": y_label, "customLabel": True,
                                 "meta": {"type": "number"}},
                            ],
                            "ignoreGlobalFilters": False,
                        }
                    }
                }
            },
            "internalReferences": [
                {"type": "index-pattern", "id": aid,
                 "name": f"indexpattern-datasource-layer-{layer}"}
            ],
            "visualization": {
                "preferredSeriesType": "bar_horizontal",
                "legend": {"isVisible": False, "position": "right", "maxLines": 1},
                "xTitle": x_label,
                "yTitle": y_label,
                "yLeftScale": "linear",
                "axisTitlesVisibilitySettings": {"x": True, "yLeft": True, "yRight": True},
                "tickLabelsVisibilitySettings": {"x": True, "yLeft": True, "yRight": True},
                "gridlinesVisibilitySettings": {"x": True, "yLeft": True, "yRight": True},
                "xExtent": {"mode": "dataBounds", "niceValues": False},
                "yLeftExtent": {"mode": "full", "niceValues": True},
                "labelsOrientation": {"x": 0, "yLeft": 0, "yRight": 0},
                "hideEndzones": True,
                "valueLabels": "show",
                "minBarHeight": 1,
                "layers": [{
                    "layerId": layer,
                    "accessors": [f"{layer}_y_0"],
                    "layerType": "data",
                    "seriesType": "bar_horizontal",
                    "xAccessor": f"{layer}_x",
                    "yConfig": [{"axisMode": "left", "forAccessor": f"{layer}_y_0"}],
                }],
            },
            "adHocDataViews": {
                aid: {
                    "id": aid, "title": index_title, "name": index_title,
                    "sourceFilters": [], "allowNoIndex": False, "type": "esql",
                }
            },
            "filters": [],
            "query": {"esql": esql},
        },
        "references": [],
    }


def _esql_scatter(esql: str, x_field: str, y_field: str, breakdown: str,
                  index_title: str, x_label: str, y_label: str) -> dict:
    aid = _adhoc_id(index_title + "|scatter")
    layer = "scatter_0"
    return {
        "visualizationType": "lnsXY",
        "version": 2,
        "title": "",
        "state": {
            "datasourceStates": {
                "textBased": {
                    "layers": {
                        layer: {
                            "index": aid,
                            "query": {"esql": esql},
                            "columns": [
                                {"columnId": f"{layer}_x", "fieldName": x_field,
                                 "label": x_label, "customLabel": True,
                                 "meta": {"type": "number"}},
                                {"columnId": f"{layer}_y_0", "fieldName": y_field,
                                 "label": y_label, "customLabel": True,
                                 "meta": {"type": "number"}},
                                {"columnId": f"{layer}_breakdown", "fieldName": breakdown,
                                 "label": breakdown, "customLabel": True,
                                 "meta": {"type": "string"}},
                            ],
                            "ignoreGlobalFilters": False,
                        }
                    }
                }
            },
            "internalReferences": [
                {"type": "index-pattern", "id": aid,
                 "name": f"indexpattern-datasource-layer-{layer}"}
            ],
            "visualization": {
                "preferredSeriesType": "line",
                "legend": {"isVisible": True, "showSingleSeries": True,
                           "position": "right", "maxLines": 1},
                "xTitle": x_label,
                "yTitle": y_label,
                "yLeftScale": "linear",
                "pointVisibility": "always",
                "fittingFunction": "None",
                "axisTitlesVisibilitySettings": {"x": True, "yLeft": True, "yRight": True},
                "tickLabelsVisibilitySettings": {"x": True, "yLeft": True, "yRight": True},
                "gridlinesVisibilitySettings": {"x": True, "yLeft": True, "yRight": True},
                "xExtent": {"mode": "dataBounds", "niceValues": False},
                "yLeftExtent": {"mode": "full", "niceValues": True},
                "hideEndzones": True,
                "layers": [{
                    "layerId": layer,
                    "accessors": [f"{layer}_y_0"],
                    "layerType": "data",
                    "seriesType": "line",
                    "xAccessor": f"{layer}_x",
                    "splitAccessors": [f"{layer}_breakdown"],
                    "yConfig": [{"axisMode": "left", "forAccessor": f"{layer}_y_0"}],
                }],
            },
            "adHocDataViews": {
                aid: {
                    "id": aid, "title": index_title, "name": index_title,
                    "sourceFilters": [], "allowNoIndex": False, "type": "esql",
                }
            },
            "filters": [],
            "query": {"esql": esql},
        },
        "references": [],
    }


def _esql_heatmap(esql: str, index_title: str = EC2) -> dict:
    aid = _adhoc_id(index_title + "|heat")
    layer = "heat_0"
    return {
        "visualizationType": "lnsHeatmap",
        "version": 2,
        "title": "",
        "state": {
            "datasourceStates": {
                "textBased": {
                    "layers": {
                        layer: {
                            "index": aid,
                            "query": {"esql": esql},
                            "columns": [
                                {"columnId": f"{layer}_x", "fieldName": "t",
                                 "label": "Week", "customLabel": True,
                                 "meta": {"type": "date"}},
                                {"columnId": f"{layer}_y", "fieldName": "instance",
                                 "label": "Instance", "customLabel": True,
                                 "meta": {"type": "string"}},
                                {"columnId": f"{layer}_value", "fieldName": "cpu",
                                 "label": "CPU %", "customLabel": True,
                                 "meta": {"type": "number"}},
                            ],
                            "ignoreGlobalFilters": False,
                        }
                    }
                }
            },
            "internalReferences": [
                {"type": "index-pattern", "id": aid,
                 "name": f"indexpattern-datasource-layer-{layer}"}
            ],
            "visualization": {
                "layerId": layer,
                "layerType": "data",
                "shape": "heatmap",
                "legend": {"isVisible": True, "position": "right", "maxLines": 1},
                "gridConfig": {
                    "isCellLabelVisible": False,
                    "isYAxisLabelVisible": True,
                    "isXAxisLabelVisible": True,
                    "isYAxisTitleVisible": False,
                    "isXAxisTitleVisible": False,
                },
                "valueAccessor": f"{layer}_value",
                "xAccessor": f"{layer}_x",
                "yAccessor": f"{layer}_y",
            },
            "adHocDataViews": {
                aid: {
                    "id": aid, "title": index_title, "name": index_title,
                    "sourceFilters": [], "allowNoIndex": False, "type": "esql",
                }
            },
            "filters": [],
            "query": {"esql": esql},
        },
        "references": [],
    }




def build_panels(kept: list[dict]) -> list[dict]:
    # Reposition kept panels
    for p in kept:
        pid = p.get("panelIndex")
        if pid == "finops-hub-tabs":
            p["gridData"] = {"x": 0, "y": 0, "w": 48, "h": 5, "i": pid}
        elif pid == "rs-acct":
            p["gridData"] = {"x": 0, "y": 5, "w": 12, "h": 2, "i": pid}
        elif pid == "rs-md":
            p["gridData"] = {"x": 0, "y": 7, "w": 12, "h": 12, "i": pid}
            p["embeddableConfig"]["content"] = (
                "## How to read this\n"
                "- **Identified** = open + in_progress. **Captured** = done. "
                "**Parked** = hidden. Never add identified and captured.\n"
                "- **Actions:** downsize, upsize, stop_idle, delete_volume, "
                "migrate_generation, gp2_to_gp3, purchase_ri_sp, schedule_offhours, "
                "rightsize_lambda.\n"
                "- Bubble chart: hover for action mix; copy ARN from the table "
                "into `elk-finops-rightsize-run`.\n"
                "- Scatter / heatmap / RDS are live CloudWatch **evidence**, not recs.\n"
                "- Spike-workflow idle rows may show **$0** — do not invent USD.\n\n"
                "[Spend vs savings](/s/finops/app/dashboards#/view/finops-spend-vs-savings)"
            )
        elif pid == "rs-notes":
            p["gridData"] = {"x": 36, "y": 7, "w": 12, "h": 12, "i": pid}
            p["embeddableConfig"]["content"] = (
                "## Actions\n"
                "| Action | Finding |\n|---|---|\n"
                "| downsize / upsize | OVER / UNDER |\n"
                "| stop_idle | IDLE |\n"
                "| delete_volume | UNATTACHED |\n"
                "| migrate_generation | gen refresh |\n"
                "| gp2_to_gp3 | volume |\n"
                "| purchase_ri_sp | coverage |\n"
                "| schedule_offhours | nights |\n"
                "| rightsize_lambda | memory |\n"
            )
        elif pid == "rs-table":
            p["gridData"] = {"x": 0, "y": 61, "w": 48, "h": 14, "i": pid}
        elif pid == "rs-rds-table":
            p["gridData"] = {"x": 24, "y": 89, "w": 24, "h": 12, "i": pid}

    action_esql = (
        "FROM finops-rightsizing-latest*\n"
        '| WHERE finops.rightsizing.status IN ("open", "in_progress")\n'
        "| STATS identified = ROUND(SUM(finops.rightsizing.estimated_monthly_savings), 2)\n"
        "    BY action = finops.rightsizing.action\n"
        "| SORT identified DESC\n| LIMIT 12"
    )
    type_esql = (
        "FROM finops-rightsizing-latest*\n"
        '| WHERE finops.rightsizing.status IN ("open", "in_progress")\n'
        "| STATS identified = ROUND(SUM(finops.rightsizing.estimated_monthly_savings), 2)\n"
        "    BY resource_type = finops.rightsizing.resource_type\n"
        "| SORT identified DESC"
    )
    status_esql = (
        "FROM finops-rightsizing-latest*\n"
        "| STATS recs = COUNT(*), usd = ROUND(SUM(finops.rightsizing.estimated_monthly_savings), 2)\n"
        "    BY status = finops.rightsizing.status\n"
        "| SORT recs DESC"
    )
    bubble_esql = (
        "FROM finops-rightsizing-latest*\n"
        '| WHERE finops.rightsizing.status IN ("open", "in_progress")\n'
        f"| {ACCOUNT_CASE}\n"
        "| STATS identified = ROUND(SUM(finops.rightsizing.estimated_monthly_savings), 2),\n"
        "        recs = COUNT(*)\n"
        "    BY action = finops.rightsizing.action\n"
        "| SORT identified DESC\n| LIMIT 12"
    )
    scatter_esql = (
        f"FROM {EC2}\n"
        "| WHERE @timestamp >= ?_tstart AND @timestamp < ?_tend\n"
        "    AND cloud.instance.id IS NOT NULL\n"
        "| STATS cpu_avg = ROUND(AVG(host.cpu.usage) * 100, 2),\n"
        "        cpu_p95 = ROUND(PERCENTILE(host.cpu.usage, 95) * 100, 2)\n"
        "    BY instance = COALESCE(cloud.instance.name, cloud.instance.id),\n"
        "       machine = cloud.machine.type\n"
        "| WHERE cpu_avg IS NOT NULL\n"
        "| SORT cpu_avg ASC\n| LIMIT 60"
    )
    heat_esql = (
        f"FROM {EC2}\n"
        "| WHERE @timestamp >= ?_tstart AND @timestamp < ?_tend\n"
        "    AND cloud.instance.name IS NOT NULL\n"
        "| STATS cpu = ROUND(AVG(host.cpu.usage) * 100, 1)\n"
        "    BY t = DATE_TRUNC(1 week, @timestamp), instance = cloud.instance.name\n"
        "| INLINE STATS avg_cpu = AVG(cpu) BY instance\n"
        "| INLINE STATS cutoff_lo = PERCENTILE(avg_cpu, 10), cutoff_hi = PERCENTILE(avg_cpu, 90)\n"
        "| WHERE avg_cpu <= cutoff_lo OR avg_cpu >= cutoff_hi\n"
        "| SORT avg_cpu ASC, instance ASC, t ASC\n"
        "| KEEP t, instance, cpu"
    )
    rds_esql = (
        f"FROM {RDS}\n"
        "| WHERE @timestamp >= ?_tstart AND @timestamp < ?_tend\n"
        "    AND aws.rds.metrics.DBLoad.avg IS NOT NULL\n"
        "| STATS dbload_avg = ROUND(AVG(aws.rds.metrics.DBLoad.avg), 4)\n"
        "    BY db = aws.dimensions.DBInstanceIdentifier\n"
        "| SORT dbload_avg ASC\n| LIMIT 20"
    )

    viz = [
        _lens_panel("rs-m-identified", "Identified monthly savings (open + in progress)",
                    _metric("Identified / mo",
                            'finops.rightsizing.status : ("open" or "in_progress")'),
                    12, 5, 9, 6),
        _lens_panel("rs-m-captured", "Captured savings (done only — do not add to identified)",
                    _metric("Captured / mo",
                            'finops.rightsizing.status : "done"'),
                    21, 5, 9, 6),
        _lens_panel("rs-m-parked", "Parked / hidden (not in identified)",
                    _metric("Parked / mo", 'finops.rightsizing.status : "hidden"'),
                    12, 11, 9, 6),
        _lens_panel("rs-m-recs", "Recs in snapshot (open + in progress)",
                    _metric("Open + WIP recs",
                            'finops.rightsizing.status : ("open" or "in_progress")',
                            op="count"),
                    21, 11, 9, 6),
        _lens_panel("rs-v-action", "Identified by action",
                    _esql_bar(action_esql, "action", "identified", "Action", "Identified USD / mo"),
                    0, 19, 18, 14),
        _lens_panel("rs-v-type", "Identified by resource type",
                    _esql_bar(type_esql, "resource_type", "identified", "Type", "Identified USD / mo"),
                    18, 19, 15, 14),
        _lens_panel("rs-v-status", "Queue by status",
                    _esql_bar(status_esql, "status", "recs", "Status", "Recs"),
                    33, 19, 15, 14),
        # Compact explorer row (no Vega — stripped on Serverless import)
        _lens_panel("rs-v-bubble", "Identified USD vs rec count by action",
                    _esql_scatter(bubble_esql, "identified", "recs", "action",
                                  RS_LATEST, "Identified USD / mo", "Open recs"),
                    0, 33, 24, 14),
        _lens_panel("rs-v-scatter", "EC2 waste: CPU avg vs p95 (evidence)",
                    _esql_scatter(scatter_esql, "cpu_avg", "cpu_p95", "machine",
                                  EC2, "CPU avg %", "CPU p95 %"),
                    24, 33, 24, 14),
        _lens_panel("rs-v-heat", "EC2 CPU heatmap weekly (evidence)",
                    _esql_heatmap(heat_esql), 0, 47, 24, 14),
        _lens_panel("rs-v-rds", "RDS lowest DBLoad (evidence)",
                    _esql_bar(rds_esql, "db", "dbload_avg", "DB instance", "Avg DBLoad", RDS),
                    24, 47, 24, 14),
    ]
    return kept + viz


def main() -> None:
    objects = [json.loads(l) for l in NDJSON.read_text().splitlines() if l.strip()]
    by_id = {}
    order = []
    for o in objects:
        key = (o.get("type"), o.get("id"))
        if key not in by_id:
            order.append(key)
        by_id[key] = o

    dash_key = ("dashboard", DASH_ID)
    dash = copy.deepcopy(by_id[dash_key])
    attrs = dash["attributes"]
    panels = json.loads(attrs["panelsJSON"])
    keep_ids = {"finops-hub-tabs", "rs-acct", "rs-md", "rs-notes", "rs-table", "rs-rds-table"}
    kept = [p for p in panels if p.get("panelIndex") in keep_ids]

    new_panels = build_panels(kept)
    attrs["panelsJSON"] = json.dumps(new_panels)
    attrs["description"] = (
        "Identified = open + in_progress; Captured = done; never add. "
        "Lens metrics + ES|QL charts (Serverless-safe). Expanded actions catalog."
    )
    attrs["optionsJSON"] = json.dumps({
        "autoApplyFilters": True,
        "hidePanelTitles": False,
        "hidePanelBorders": False,
        "useMargins": True,
        "syncColors": False,
        "syncTooltips": True,
        "syncCursor": True,
    })

    # Keep hub + data-view refs; drop broken visualization refs
    refs = [
        r for r in (dash.get("references") or [])
        if r.get("type") != "visualization"
    ]
    keep_ip = {
        "rs-table:indexpattern-datasource-layer-layer_0",
        "rs-rds-table:indexpattern-datasource-layer-layer_0",
        "rs-acct:optionsListDataView",
    }
    # Metric panels need RS_DATA_VIEW_ID refs — add them
    for mid in ("rs-m-identified", "rs-m-captured", "rs-m-parked", "rs-m-recs"):
        refs.append({
            "name": f"{mid}:indexpattern-datasource-layer-layer_0",
            "type": "index-pattern",
            "id": RS_DATA_VIEW_ID,
        })
    refs = [
        r for r in refs
        if r.get("type") != "index-pattern"
        or r.get("name") in keep_ip
        or r.get("name", "").startswith("rs-m-")
    ]
    seen = set()
    uniq = []
    for r in refs:
        key = (r.get("type"), r.get("id"), r.get("name"))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(r)
    dash["references"] = uniq
    by_id[dash_key] = dash

    # Drop standalone vega-rs visualization objects (unused; panels are by-value)
    order = [k for k in order if not (
        k[0] == "visualization" and str(k[1]).startswith("elk-finops-vega-rs-")
    )]
    by_id = {k: v for k, v in by_id.items() if k in set(order) or k == dash_key}
    if dash_key not in order:
        order.append(dash_key)

    lines = [json.dumps(by_id[k], separators=(",", ":")) for k in order if k in by_id]
    NDJSON.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"updated {NDJSON}")
    print(f"  panels: {len(new_panels)}")
    for p in new_panels:
        print(f"    {p['type']:16} {p['panelIndex']}")


if __name__ == "__main__":
    main()
