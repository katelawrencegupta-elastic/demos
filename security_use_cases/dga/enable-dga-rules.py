#!/usr/bin/env python3
"""Install and enable Elastic Security DGA detection rules for this demo.

Requires an API key with write access to Kibana system indices (e.g. a
superuser key from Kibana → Stack Management → API keys). The Logstash
ingest key cannot modify detection rules.

Usage:
  cp .env.example .env   # set ELASTIC_HOSTS and ELASTIC_API_KEY
  python3 enable-dga-rules.py

Reads Elastic credentials from .env in this directory (see elastic_env.py).
"""

from __future__ import annotations

import base64
import copy
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib import error, request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from elastic_env import load_elastic_env

DGA_TAG = "Use Case: Domain Generation Algorithm Detection"
ALERTING_INDEX = ".kibana_alerting_cases_9.4.1_001"
TASK_INDEX = ".kibana_task_manager_9.4.1_001"
SECURITY_INDEX = ".kibana_security_solution_9.4.1_001"
QUERY_TEMPLATE_ALERT_ID = "92440218-b4c3-4ebb-96cf-cf88ab35eca9"

# Prebuilt rule_ids for the four DGA use-case rules.
DGA_RULE_IDS = [
    "ff0d807d-869b-4a0d-a493-52bc46d2f1b1",  # Potential DGA Activity (ML)
    "da7f5803-1cd4-42fd-a890-0173ae80ac69",  # High DGA probability score
    "f3403393-1fd9-4686-8f6e-596c58bc00b4",  # Predicted DGA domain
    "bcaa15ce-2d41-44d7-a322-918f9db77766",  # SUNBURST DNS domain
]

DEMO_EXTRA_INDICES = ["logs-dga.dns-*"]


def load_env() -> tuple[str, str]:
    return load_elastic_env(__file__, admin=True)


class Client:
    def __init__(self, hosts: str, api_key: str) -> None:
        self.hosts = hosts
        self.headers = {
            "Authorization": f"ApiKey {base64.b64encode(api_key.encode()).decode()}",
            "Content-Type": "application/json",
        }

    def call(self, method: str, path: str, body: dict | None = None) -> dict:
        data = json.dumps(body).encode() if body is not None else None
        req = request.Request(f"{self.hosts}{path}", data=data, headers=self.headers, method=method)
        try:
            with request.urlopen(req) as resp:
                raw = resp.read()
                return json.loads(raw) if raw else {}
        except error.HTTPError as exc:
            detail = exc.read().decode()
            raise RuntimeError(f"{method} {path} -> {exc.code}: {detail}") from exc

    def search(self, index: str, body: dict) -> list[dict]:
        return self.call("POST", f"/{index}/_search", body).get("hits", {}).get("hits", [])

    def get_alert_by_rule_id(self, rule_id: str) -> dict | None:
        hits = self.search(
            ALERTING_INDEX,
            {"size": 1, "query": {"term": {"alert.params.ruleId": rule_id}}},
        )
        return hits[0] if hits else None

    def can_write_kibana(self) -> bool:
        probe_id = f"alert:write-probe-{uuid.uuid4()}"
        try:
            self.call(
                "PUT",
                f"/{ALERTING_INDEX}/_doc/{probe_id}",
                {"type": "alert", "alert": {"name": "probe"}},
            )
            self.call("DELETE", f"/{ALERTING_INDEX}/_doc/{probe_id}")
            return True
        except RuntimeError:
            return False


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def latest_security_rule(client: Client, rule_id: str) -> dict:
    hits = client.search(
        SECURITY_INDEX,
        {
            "size": 1,
            "sort": [{"security-rule.version": "desc"}],
            "query": {"term": {"security-rule.rule_id": rule_id}},
        },
    )
    if not hits:
        raise RuntimeError(f"prebuilt security-rule template not found for {rule_id}")
    return hits[0]["_source"]["security-rule"]


def merge_indices(indices: list[str] | None) -> list[str] | None:
    if not indices:
        return indices
    merged = list(indices)
    for idx in DEMO_EXTRA_INDICES:
        if idx not in merged:
            merged.append(idx)
    return merged


def enable_alert(client: Client, alert_doc_id: str, name: str) -> None:
    ts = now_iso()
    client.call(
        "POST",
        f"/{ALERTING_INDEX}/_update/{alert_doc_id}",
        {"doc": {"alert": {"enabled": True, "updatedAt": ts, "lastEnabledAt": ts}}},
    )
    task_id = alert_doc_id.removeprefix("alert:")
    try:
        client.call(
            "POST",
            f"/{TASK_INDEX}/_update/task:{task_id}",
            {"doc": {"task": {"enabled": True}}},
        )
    except RuntimeError:
        pass
    print(f"enabled: {name}")


def install_query_rule(client: Client, template: dict, security_rule: dict) -> None:
    alert_id = str(uuid.uuid4())
    ts = now_iso()
    doc = copy.deepcopy(template)
    alert = doc["alert"]
    sr = security_rule

    alert["name"] = sr["name"]
    alert["tags"] = sr["tags"]
    alert["enabled"] = True
    alert["schedule"] = {"interval": sr.get("interval", "5m")}
    alert["createdAt"] = ts
    alert["updatedAt"] = ts
    alert["lastEnabledAt"] = ts
    alert["scheduledTaskId"] = alert_id
    alert["revision"] = 0
    alert["executionStatus"] = {
        "status": "pending",
        "lastExecutionDate": None,
        "lastDuration": 0,
        "error": None,
        "warning": None,
    }
    alert["lastRun"] = None
    alert["nextRun"] = None
    alert["running"] = False

    params = alert["params"]
    for key, value in sr.items():
        if key == "rule_id":
            params["ruleId"] = value
        elif key == "timestamp_override":
            params["timestampOverride"] = value
        elif key == "interval":
            continue
        else:
            params[key] = value
    params["immutable"] = True
    params["index"] = merge_indices(params.get("index"))
    params["ruleSource"] = {
        "type": "external",
        "isCustomized": False,
        "customizedFields": [],
        "hasBaseVersion": True,
    }

    doc["updated_at"] = ts
    doc["created_at"] = ts
    client.call("PUT", f"/{ALERTING_INDEX}/_doc/alert:{alert_id}", doc)
    client.call(
        "PUT",
        f"/{TASK_INDEX}/_doc/task:{alert_id}",
        {
            "task": {
                "taskType": "alerting:siem.queryRule",
                "params": json.dumps(
                    {"alertId": alert_id, "spaceId": "default", "consumer": "siem"}
                ),
                "state": json.dumps(
                    {
                        "alertTypeState": {"isLoggedRequestsEnabled": False},
                        "alertInstances": {},
                        "alertRecoveredInstances": {},
                        "summaryActions": {},
                        "previousStartedAt": None,
                    }
                ),
                "scope": ["alerting"],
                "enabled": True,
                "schedule": {"interval": sr.get("interval", "5m")},
                "traceparent": "",
                "stateVersion": 1,
                "attempts": 0,
                "scheduledAt": ts,
                "startedAt": None,
                "retryAt": None,
                "runAt": ts,
                "status": "idle",
                "partition": hash(alert_id) % 50,
                "ownerId": None,
            },
            "type": "task",
            "references": [],
            "managed": False,
            "coreMigrationVersion": "8.8.0",
            "typeMigrationVersion": "10.8.0",
            "updated_at": ts,
            "created_at": ts,
        },
    )
    print(f"installed: {sr['name']} (alert:{alert_id})")


def patch_query_indices(client: Client, hit: dict) -> None:
    alert = hit["_source"]["alert"]
    params = alert.get("params", {})
    if params.get("type") != "query":
        return
    current = params.get("index") or []
    merged = merge_indices(current)
    if merged == current:
        return
    client.call(
        "POST",
        f"/{ALERTING_INDEX}/_update/{hit['_id']}",
        {"doc": {"alert": {"params": {"index": merged}, "updatedAt": now_iso()}}},
    )
    print(f"patched indices for: {alert['name']} -> {merged}")


def main() -> None:
    hosts, api_key = load_env()
    client = Client(hosts, api_key)

    if not client.can_write_kibana():
        sys.exit(
            "This API key cannot write Kibana indices.\n"
            "Create a superuser API key in Kibana (Stack Management → API keys)\n"
            "and set ELASTIC_ADMIN_API_KEY in .env, then rerun."
        )

    template = client.call("GET", f"/{ALERTING_INDEX}/_doc/alert:{QUERY_TEMPLATE_ALERT_ID}")[
        "_source"
    ]

    print("DGA detection rules:")
    for rule_id in DGA_RULE_IDS:
        hit = client.get_alert_by_rule_id(rule_id)
        if hit:
            alert = hit["_source"]["alert"]
            name = alert["name"]
            enabled = alert.get("enabled", False)
            print(f"  [{'on' if enabled else 'off'}] {name}")
            if not enabled:
                enable_alert(client, hit["_id"], name)
            patch_query_indices(client, hit)
        else:
            sr = latest_security_rule(client, rule_id)
            print(f"  [missing] {sr['name']}")
            if sr.get("type") == "query":
                install_query_rule(client, template, sr)
            else:
                print(
                    f"    skipped install for ML rule {rule_id}; install "
                    f"'{sr['name']}' from Kibana → Rules → Add Elastic rules."
                )

    print("\nDone. Query rules now include logs-dga.dns-* for the demo generator.")


if __name__ == "__main__":
    main()
