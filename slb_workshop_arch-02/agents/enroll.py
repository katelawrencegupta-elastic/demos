#!/usr/bin/env python3
"""Create ARCH-02 Fleet policies and enroll workshop Elastic Agents.

Policies encode the collection-model standard:
  - arch-02-platform-prod     shared / regulated collectors (default path)
  - arch-02-drilling-prod     domain team allowed on Fleet
  - arch-02-platform-nonprod  same allow-list, namespace = environment

Enrollment tokens are fetched from Kibana and passed to Docker. They are not
written to disk.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from client import kibana_request  # noqa: E402

POLICIES = (
    {
        "id": "arch-02-platform-prod",
        "name": "arch-02-platform-prod",
        "namespace": "prod",
        "description": "Platform-owned Fleet policy for shared / regulated collectors. Integration allow-list: System only.",
        "package_name": "system-arch-02-platform-prod",
        "token_env": "FLEET_ENROLLMENT_TOKEN_PLATFORM",
    },
    {
        "id": "arch-02-drilling-prod",
        "name": "arch-02-drilling-prod",
        "namespace": "prod",
        "description": "Domain team (drilling-apps) on the approved Fleet path. Platform still owns the integration allow-list.",
        "package_name": "system-arch-02-drilling-prod",
        "token_env": "FLEET_ENROLLMENT_TOKEN_DRILLING",
    },
    {
        "id": "arch-02-platform-nonprod",
        "name": "arch-02-platform-nonprod",
        "namespace": "nonprod",
        "description": "Same platform allow-list as prod. Namespace is environment — not team, region, or alice-test.",
        "package_name": "system-arch-02-platform-nonprod",
        "token_env": "FLEET_ENROLLMENT_TOKEN_NONPROD",
    },
)

PROBE_POLICY_ID = "arch-02-probe"


def _items(payload: dict, *keys: str) -> list:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            return value
    return []


def delete_probe() -> None:
    try:
        kibana_request("POST", f"/api/fleet/agent_policies/delete", {"agentPolicyId": PROBE_POLICY_ID})
        print(f"deleted probe policy: {PROBE_POLICY_ID}")
    except RuntimeError as exc:
        if "404" not in str(exc) and "not found" not in str(exc).lower():
            print(f"note: probe delete: {exc}")


def ensure_policy(spec: dict) -> dict:
    policies = kibana_request("GET", "/api/fleet/agent_policies?perPage=100")
    existing = next(
        (
            p
            for p in _items(policies, "items")
            if p.get("id") == spec["id"] or p.get("name") == spec["name"]
        ),
        None,
    )
    if existing:
        print(f"policy exists: {existing.get('name')} ns={existing.get('namespace')}")
        return existing
    created = kibana_request(
        "POST",
        "/api/fleet/agent_policies?sys_monitoring=true",
        {
            "id": spec["id"],
            "name": spec["name"],
            "namespace": spec["namespace"],
            "description": spec["description"],
            "monitoring_enabled": ["logs", "metrics"],
        },
    )
    item = created.get("item", created)
    print(f"policy created: {item.get('name')} ns={item.get('namespace')}")
    return item


def system_package_version() -> str:
    pkg = kibana_request("GET", "/api/fleet/epm/packages/system")
    item = pkg.get("item") or pkg
    version = item.get("version")
    if not version:
        raise RuntimeError("Fleet did not return a System integration version")
    return version


def ensure_system_integration(spec: dict, policy_id: str, version: str) -> None:
    packages = kibana_request("GET", "/api/fleet/package_policies?perPage=200")
    existing = [
        p
        for p in _items(packages, "items")
        if (p.get("package") or {}).get("name") == "system"
        and (p.get("policy_id") == policy_id or policy_id in (p.get("policy_ids") or []))
    ]
    if existing:
        current = existing[0]
        print(f"  system integration already on {spec['name']} ({current.get('name')})")
        if current.get("namespace") != spec["namespace"]:
            kibana_request(
                "PUT",
                f"/api/fleet/package_policies/{current['id']}",
                {
                    "name": current.get("name"),
                    "description": current.get("description")
                    or "Host logs and metrics — ARCH-02 System allow-list",
                    "namespace": spec["namespace"],
                    "policy_id": policy_id,
                    "enabled": True,
                    "package": current.get("package"),
                    "inputs": current.get("inputs") or [],
                },
            )
            print(f"  namespace set to {spec['namespace']}")
        return

    try:
        kibana_request("POST", f"/api/fleet/epm/packages/system/{version}", {"force": True})
    except RuntimeError as exc:
        if "-> 409" not in str(exc) and "already installed" not in str(exc).lower():
            print(f"  note: system package install: {exc}")

    created = kibana_request(
        "POST",
        "/api/fleet/package_policies",
        {
            "name": spec["package_name"],
            "description": "Host logs and metrics — ARCH-02 System allow-list",
            "namespace": spec["namespace"],
            "policy_id": policy_id,
            "policy_ids": [policy_id],
            "enabled": True,
            "inputs": {},
            "package": {"name": "system", "version": version},
        },
    )
    name = (created.get("item") or created).get("name", spec["package_name"])
    print(f"  system integration: {name} v{version} ns={spec['namespace']}")


def fleet_url() -> str:
    hosts = kibana_request("GET", "/api/fleet/fleet_server_hosts")
    default = next((h for h in _items(hosts, "items") if h.get("is_default")), None)
    urls = (default or {}).get("host_urls") or []
    if urls:
        return urls[0]
    override = os.getenv("FLEET_URL")
    if override:
        return override
    raise RuntimeError("No Fleet Server URL from Kibana and FLEET_URL is unset")


def enrollment_token(policy_id: str, name: str) -> str:
    keys = kibana_request("GET", "/api/fleet/enrollment_api_keys?perPage=100")
    items = _items(keys, "items", "list")
    match = next(
        (k for k in items if k.get("policy_id") == policy_id and k.get("active") and k.get("api_key")),
        None,
    )
    if match:
        return match["api_key"]
    created = kibana_request(
        "POST",
        "/api/fleet/enrollment_api_keys",
        {"name": name, "policy_id": policy_id},
    )
    token = created.get("item", created).get("api_key")
    if not token:
        raise RuntimeError(f"Fleet did not return an enrollment token for {name}")
    return token


def compose_up(url: str, tokens: dict[str, str]) -> None:
    env = os.environ.copy()
    env["FLEET_URL"] = url
    env.update(tokens)
    if "DOCKER_HOST" not in env and Path("/var/run/docker.sock").exists():
        env["DOCKER_HOST"] = "unix:///var/run/docker.sock"
    cmd = [
        "docker",
        "compose",
        "--env-file",
        str(ROOT / ".env"),
        "-f",
        str(ROOT / "agents" / "docker-compose.yml"),
        "up",
        "-d",
        "--remove-orphans",
    ]
    subprocess.run(cmd, cwd=ROOT, env=env, check=True)


def list_agents() -> None:
    agents = kibana_request("GET", "/api/fleet/agents?perPage=50")
    items = _items(agents, "items")
    print(f"fleet agents: {len(items)}")
    for agent in items:
        local = (agent.get("local_metadata") or {}).get("host") or {}
        print(
            f"  {local.get('hostname') or agent.get('id')}  "
            f"policy={agent.get('policy_id')}  status={agent.get('status')}"
        )


def main() -> None:
    policies_only = "--policies-only" in sys.argv
    delete_probe()
    version = system_package_version()
    print(f"system package: {version}")

    tokens: dict[str, str] = {}
    for spec in POLICIES:
        policy = ensure_policy(spec)
        policy_id = policy["id"]
        ensure_system_integration(spec, policy_id, version)
        tokens[spec["token_env"]] = enrollment_token(policy_id, spec["name"])

    url = fleet_url()
    print(f"Fleet URL: {url}")

    if policies_only:
        print("policies ready (--policies-only). Enroll later with agents/enroll.py")
        return

    try:
        compose_up(url, tokens)
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        print(f"agents not started: {exc}")
        print("policies and enrollment tokens are ready. Start Docker, then re-run agents/enroll.py")
        raise SystemExit(1) from exc

    print("Containers started. Confirm in Kibana: Fleet → Agents")
    list_agents()


if __name__ == "__main__":
    main()
