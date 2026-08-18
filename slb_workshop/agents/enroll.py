#!/usr/bin/env python3
"""Enroll the three workshop Elastic Agents into Fleet policy sre-01-workshop.

Fetches the enrollment token from Kibana (does not write it to disk) and
recreates agents/docker-compose.yml in Fleet mode.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from client import kibana_request  # noqa: E402

sys.path.insert(0, str(ROOT / "agents"))
from syslog_factory import ensure_log_files  # noqa: E402

POLICY_ID = "sre-01-workshop"
POLICY_NAME = "sre-01-workshop"
DEFAULT_FLEET_URL = (
    "https://cecd277c19e246068d5a2ff685d6f72a.fleet.us-central1.gcp.elastic.cloud:443"
)


def ensure_policy() -> dict:
    policies = kibana_request("GET", "/api/fleet/agent_policies?perPage=100")
    existing = next(
        (p for p in policies.get("items", []) if p.get("id") == POLICY_ID or p.get("name") == POLICY_NAME),
        None,
    )
    if existing:
        return existing
    created = kibana_request(
        "POST",
        "/api/fleet/agent_policies?sys_monitoring=true",
        {
            "id": POLICY_ID,
            "name": POLICY_NAME,
            "namespace": "default",
            "description": "SLB SRE-01 workshop — Fleet-managed Elastic Agents (aks-sre-01..03)",
            "monitoring_enabled": ["logs", "metrics"],
        },
    )
    return created.get("item", created)


def fleet_url() -> str:
    hosts = kibana_request("GET", "/api/fleet/fleet_server_hosts")
    default = next((h for h in hosts.get("items", []) if h.get("is_default")), None)
    urls = (default or {}).get("host_urls") or []
    return urls[0] if urls else os.getenv("FLEET_URL", DEFAULT_FLEET_URL)


def enrollment_token(policy_id: str) -> str:
    keys = kibana_request("GET", "/api/fleet/enrollment_api_keys?perPage=100")
    items = keys.get("items") or keys.get("list") or []
    match = next((k for k in items if k.get("policy_id") == policy_id and k.get("active") and k.get("api_key")), None)
    if match:
        return match["api_key"]
    created = kibana_request(
        "POST",
        "/api/fleet/enrollment_api_keys",
        {"name": POLICY_NAME, "policy_id": policy_id},
    )
    token = created.get("item", created).get("api_key")
    if not token:
        raise RuntimeError("Fleet did not return an enrollment token")
    return token


def compose_up(url: str, token: str) -> None:
    env = os.environ.copy()
    env["FLEET_URL"] = url
    env["FLEET_ENROLLMENT_TOKEN"] = token
    cmd = [
        "docker",
        "compose",
        "--env-file",
        str(ROOT / ".env"),
        "-f",
        str(ROOT / "agents" / "docker-compose.yml"),
        "up",
        "-d",
        "--force-recreate",
        "--remove-orphans",
    ]
    subprocess.run(cmd, cwd=ROOT, env=env, check=True)


def main() -> None:
    policy = ensure_policy()
    policy_id = policy["id"]
    url = fleet_url()
    token = enrollment_token(policy_id)
    print(f"Enrolling agents into policy {policy.get('name')} ({policy_id})")
    print(f"Fleet URL: {url}")
    ensure_log_files()
    compose_up(url, token)
    print("Containers recreated. Confirm in Kibana: Fleet → Agents")


if __name__ == "__main__":
    main()
