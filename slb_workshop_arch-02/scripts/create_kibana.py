#!/usr/bin/env python3
"""Create ARCH-02 Kibana data views and the governance evidence dashboard."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from client import (  # noqa: E402
    CONFIGS,
    DASHBOARD_FILE,
    DASHBOARD_ID,
    DASHBOARD_TITLE,
    DATA_VIEWS,
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
    )


def upsert_dashboard() -> dict:
    raw = json.loads((CONFIGS / "kibana" / DASHBOARD_FILE).read_text())
    payloads = (raw, {"data": raw})
    last_error: RuntimeError | None = None
    for body in payloads:
        try:
            return kibana_request("PUT", f"/api/dashboards/{DASHBOARD_ID}", body)
        except RuntimeError as exc:
            last_error = exc
            try:
                created = kibana_request("POST", "/api/dashboards", body)
                created_id = created.get("id")
                if created_id and created_id != DASHBOARD_ID:
                    print(
                        f"note: Kibana assigned dashboard id={created_id} "
                        f"(wanted {DASHBOARD_ID})"
                    )
                return created
            except RuntimeError as post_exc:
                last_error = post_exc
    raise last_error or RuntimeError("dashboard create failed")


def main() -> None:
    for view_id, title, name in DATA_VIEWS:
        view = upsert_data_view(view_id, title, name)
        dv = view.get("data_view", view)
        print(f"data_view: {dv.get('name') or name} id={dv.get('id') or view_id}")

    print(kibana_url("/app/discover#/?_a=(index:'arch02-ecs-app')"))
    print(kibana_url("/app/discover#/?_a=(index:'arch02-otel-app')"))

    try:
        dash = upsert_dashboard()
        dash_id = dash.get("id") or DASHBOARD_ID
        print(f"dashboard: {DASHBOARD_TITLE} id={dash_id}")
        print(kibana_url(f"/app/dashboards#/view/{dash_id}"))
    except RuntimeError as exc:
        print(f"dashboard skipped: {exc}")
        print("use Discover data views and scripts/verify.py for evidence")


if __name__ == "__main__":
    main()
