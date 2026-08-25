#!/usr/bin/env python3
"""Create ARCH-02 Kibana data views.

Prefers the Kibana HTTP API. On Elastic Cloud Hosted the URL in .env is often
the Elasticsearch endpoint, so we fall back to writing index-pattern saved
objects into `.kibana` (they show up in Discover after Kibana loads).
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from elasticsearch import AuthorizationException

from client import (  # noqa: E402
    CONFIGS,
    DASHBOARD_FILE,
    DASHBOARD_ID,
    DASHBOARD_TITLE,
    DATA_VIEWS,
    get_client,
    kibana_request,
    kibana_url,
)


def upsert_data_view_http(view_id: str, title: str, name: str) -> dict:
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


def upsert_data_view_es(view_id: str, title: str, name: str) -> None:
    es = get_client()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    doc_id = f"index-pattern:{view_id}"
    body = {
        "type": "index-pattern",
        "namespaces": ["default"],
        "index-pattern": {
            "title": title,
            "name": name,
            "timeFieldName": "@timestamp",
            "allowNoIndex": True,
        },
        "references": [],
        "managed": False,
        "coreMigrationVersion": "8.8.0",
        "typeMigrationVersion": "8.0.0",
        "updated_at": now,
    }
    es.index(index=".kibana", id=doc_id, document=body, refresh="wait_for")


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
    http_ok = True
    for view_id, title, name in DATA_VIEWS:
        try:
            view = upsert_data_view_http(view_id, title, name)
            dv = view.get("data_view", view)
            print(f"data_view: {dv.get('name') or name} id={dv.get('id') or view_id}")
        except RuntimeError as exc:
            http_ok = False
            print("Kibana HTTP API unavailable (KIBANA_URL is Elasticsearch)")
            print("writing data views to .kibana via Elasticsearch")
            break

    if not http_ok:
        try:
            for view_id, title, name in DATA_VIEWS:
                upsert_data_view_es(view_id, title, name)
                print(f"data_view: {name} id={view_id} (via .kibana)")
        except AuthorizationException:
            print(
                "data views not created: this API key cannot write restricted "
                ".kibana indices, and KIBANA_URL is the Elasticsearch endpoint"
            )
            print("open Discover from the Elastic Cloud Kibana URL and add:")
            for view_id, title, name in DATA_VIEWS:
                print(f"  - {name}: {title}")
            return

    print(kibana_url("/app/discover#/?_a=(index:'arch02-ecs-app')"))
    print(kibana_url("/app/discover#/?_a=(index:'arch02-otel-app')"))

    if not http_ok:
        print(
            "open Discover from the Elastic Cloud Kibana URL "
            "(the host in .env is Elasticsearch, not Kibana)"
        )
        return

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
