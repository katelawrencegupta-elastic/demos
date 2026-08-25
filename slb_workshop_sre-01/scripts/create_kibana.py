#!/usr/bin/env python3
"""Create the workshop Kibana data views and dashboards."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from client import (  # noqa: E402
    COMPARE_DASHBOARD_ID,
    COMPARE_DASHBOARD_TITLE,
    COMPARE_DATA_VIEWS,
    CONFIGS,
    DASHBOARD_ID,
    DATA_VIEW_ID,
    DATA_VIEW_NAME,
    DATA_VIEW_TITLE,
    METRICS_DASHBOARD_ID,
    METRICS_DASHBOARD_TITLE,
    TRACES_DASHBOARD_ID,
    TRACES_DASHBOARD_TITLE,
    kibana_request,
    kibana_url,
)


def upsert_data_view(view_id: str, title: str, name: str) -> dict:
    return kibana_request(
        "POST",
        "/api/data_views/data_view",
        {
            "data_view": {
                "id": view_id,
                "title": title,
                "name": name,
                "timeFieldName": "@timestamp",
                "allowNoIndex": True,
            },
            "override": True,
        },
        api_version=None,
    )


def upsert_dashboard(dashboard_id: str, filename: str) -> dict:
    body = json.loads((CONFIGS / "kibana" / filename).read_text())
    try:
        kibana_request("GET", f"/api/dashboards/{dashboard_id}")
        return kibana_request("PUT", f"/api/dashboards/{dashboard_id}", body)
    except RuntimeError as exc:
        if "-> 404" not in str(exc):
            # GET failed for another reason; still try PUT (creates on some versions)
            pass
    try:
        return kibana_request("PUT", f"/api/dashboards/{dashboard_id}", body)
    except RuntimeError:
        created = kibana_request("POST", "/api/dashboards", body)
        created_id = created.get("id")
        if created_id and created_id != dashboard_id:
            print(f"note: Kibana assigned dashboard id={created_id} (wanted {dashboard_id})")
        return created


def _print_dashboard(dash: dict, fallback_id: str, fallback_title: str) -> None:
    dash_id = dash.get("id") or fallback_id
    data = dash.get("data") if isinstance(dash.get("data"), dict) else dash
    title = data.get("title") or fallback_title
    print(f"dashboard: {title} id={dash_id}")
    print(kibana_url(f"/app/dashboards#/view/{dash_id}"))


def main() -> None:
    views = [
        (DATA_VIEW_ID, DATA_VIEW_TITLE, DATA_VIEW_NAME),
        *COMPARE_DATA_VIEWS,
    ]
    for view_id, title, name in views:
        view = upsert_data_view(view_id, title, name)
        dv = view.get("data_view", view)
        print(f"data_view: {dv.get('name') or name} id={dv.get('id') or view_id}")

    print(kibana_url(f"/app/discover#/?_a=(index:'{DATA_VIEW_ID}')"))

    platform = upsert_dashboard(DASHBOARD_ID, "dashboard.json")
    _print_dashboard(platform, DASHBOARD_ID, "SRE-01 Workshop — Platform logs")

    compare = upsert_dashboard(COMPARE_DASHBOARD_ID, "dashboard-agents-vs-edot.json")
    _print_dashboard(compare, COMPARE_DASHBOARD_ID, COMPARE_DASHBOARD_TITLE)

    metrics = upsert_dashboard(METRICS_DASHBOARD_ID, "dashboard-metrics.json")
    _print_dashboard(metrics, METRICS_DASHBOARD_ID, METRICS_DASHBOARD_TITLE)

    traces = upsert_dashboard(TRACES_DASHBOARD_ID, "dashboard-traces.json")
    _print_dashboard(traces, TRACES_DASHBOARD_ID, TRACES_DASHBOARD_TITLE)


if __name__ == "__main__":
    main()
