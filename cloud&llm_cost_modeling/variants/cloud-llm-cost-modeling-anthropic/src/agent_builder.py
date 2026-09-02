"""Provision Meridian FinOps AI Assistant (Elastic Agent Builder).

Creates ES|QL tools and a chat agent that answer billing, SLO, and alert
questions against the seeded Meridian demo data.

API refs:
  POST/PUT /api/agent_builder/tools
  POST/PUT /api/agent_builder/agents
"""
from __future__ import annotations

import requests
import yaml

from src.budgets import budget_numbers
from src.config import KBN_HEADERS, KIBANA_URL, ROOT

AGENT_CONFIG = ROOT / "config" / "finops_agent.yaml"
TAGS = ["meridian", "finops", "workshop"]

TOOLS_API = f"{KIBANA_URL}/api/agent_builder/tools"
AGENTS_API = f"{KIBANA_URL}/api/agent_builder/agents"
AGENT_CHAT_URL = f"{KIBANA_URL}/app/agent_builder/chat"


def load_agent_config() -> dict:
    with open(AGENT_CONFIG) as f:
        return yaml.safe_load(f)


def _kbn(method: str, url: str, **kwargs):
    kwargs.setdefault("headers", KBN_HEADERS)
    kwargs.setdefault("timeout", 60)
    return requests.request(method, url, **kwargs)


def _budgets_block(nums: dict) -> str:
    lines = [
        f"- AWS monthly budget: ${nums['aws_monthly_usd']:,.0f}",
        f"- AWS daily SLO ceiling: ${nums['aws_daily_ceiling_usd']:,.0f}",
        f"- Staging daily SLO ceiling: ${nums['staging_daily_ceiling_usd']:,.0f}",
        f"- Staging daily alert floor: ${nums['staging_daily_alert_usd']:,.0f}",
        f"- checkout-assistant daily SLO ceiling: ${nums['checkout_daily_ceiling_usd']:.2f}",
        f"- checkout-assistant 7d alert floor: ${nums['checkout_7d_alert_usd']:.2f}",
        f"- GCP meridian-ml-prod 7d alert floor: ${nums['gcp_ml_7d_alert_usd']:,.0f}",
    ]
    return "\n".join(lines)


def _render_esql(template: str, nums: dict) -> str:
    return template.format(
        aws_monthly_usd=int(nums["aws_monthly_usd"]),
        staging_daily_ceiling_usd=int(nums["staging_daily_ceiling_usd"]),
        staging_daily_alert_usd=int(nums["staging_daily_alert_usd"]),
        gcp_ml_7d_alert_usd=int(nums["gcp_ml_7d_alert_usd"]),
    ).strip()


def _tool_body(spec: dict, nums: dict) -> dict:
    return {
        "id": spec["id"],
        "type": "esql",
        "description": spec["description"].strip(),
        "tags": TAGS,
        "configuration": {
            "query": _render_esql(spec["esql"], nums),
            "params": spec.get("params") or {},
        },
    }


def _upsert_tool(tool_id: str, create_body: dict, update_body: dict, fail_loud: bool) -> bool:
    r = _kbn("GET", f"{TOOLS_API}/{tool_id}")
    if r.status_code == 200:
        r = _kbn("PUT", f"{TOOLS_API}/{tool_id}", json=update_body)
        action = "updated"
    elif r.status_code == 404:
        r = _kbn("POST", TOOLS_API, json=create_body)
        action = "created"
    else:
        msg = f"  [fail] tool GET {tool_id}: {r.status_code} {r.text[:240]}"
        if fail_loud:
            raise SystemExit(msg)
        print(msg.replace("[fail]", "[warn]"))
        return False

    if r.status_code >= 300:
        msg = f"  [fail] tool {action} {tool_id}: {r.status_code} {r.text[:400]}"
        if r.status_code in (403, 404) and not fail_loud:
            print(msg.replace("[fail]", "[warn]"))
            return False
        if fail_loud:
            raise SystemExit(msg)
        print(msg.replace("[fail]", "[warn]"))
        return False
    print(f"  [ok] tool {action}: {tool_id}")
    return True


def _agent_body(cfg: dict, tool_ids: list[str], nums: dict) -> dict:
    agent = cfg["agent"]
    instructions = cfg["instructions"].format(
        budgets_block=_budgets_block(nums),
        kibana_url=KIBANA_URL,
    ).strip()
    body = {
        "id": agent["id"],
        "name": agent["name"],
        "description": agent["description"].strip(),
        "labels": agent.get("labels") or TAGS,
        "avatar_color": agent.get("avatar_color"),
        "avatar_symbol": agent.get("avatar_symbol"),
        "access_control": {"access_mode": agent.get("access_mode", "public")},
        "configuration": {
            "instructions": instructions,
            "tools": [{"tool_ids": tool_ids}],
            "enable_elastic_capabilities": bool(
                agent.get("enable_elastic_capabilities", False)),
        },
    }
    # Omit null avatar fields if absent
    if not body.get("avatar_color"):
        body.pop("avatar_color", None)
    if not body.get("avatar_symbol"):
        body.pop("avatar_symbol", None)
    return body


def _upsert_agent(agent_id: str, body: dict, fail_loud: bool) -> bool:
    r = _kbn("GET", f"{AGENTS_API}/{agent_id}")
    if r.status_code == 200:
        update = {
            "name": body["name"],
            "description": body["description"],
            "labels": body["labels"],
            "configuration": body["configuration"],
        }
        if "avatar_color" in body:
            update["avatar_color"] = body["avatar_color"]
        if "avatar_symbol" in body:
            update["avatar_symbol"] = body["avatar_symbol"]
        if "access_control" in body:
            update["access_control"] = body["access_control"]
        r = _kbn("PUT", f"{AGENTS_API}/{agent_id}", json=update)
        action = "updated"
    elif r.status_code == 404:
        r = _kbn("POST", AGENTS_API, json=body)
        action = "created"
    else:
        msg = f"  [fail] agent GET {agent_id}: {r.status_code} {r.text[:240]}"
        if fail_loud:
            raise SystemExit(msg)
        print(msg.replace("[fail]", "[warn]"))
        return False

    if r.status_code >= 300:
        msg = f"  [fail] agent {action} {agent_id}: {r.status_code} {r.text[:400]}"
        if r.status_code in (403, 404) and not fail_loud:
            print(msg.replace("[fail]", "[warn]"))
            return False
        if fail_loud:
            raise SystemExit(msg)
        print(msg.replace("[fail]", "[warn]"))
        return False
    print(f"  [ok] agent {action}: {agent_id} ({body['name']})")
    return True


def ensure_agent(fail_loud: bool = False) -> None:
    """Upsert FinOps ES|QL tools and the Meridian FinOps AI Assistant agent."""
    cfg = load_agent_config()
    nums = budget_numbers()
    tool_ids: list[str] = []

    print("== FinOps AI Assistant tools ==")
    for spec in cfg.get("tools") or []:
        create_body = _tool_body(spec, nums)
        update_body = {
            "description": create_body["description"],
            "tags": create_body["tags"],
            "configuration": create_body["configuration"],
        }
        if _upsert_tool(spec["id"], create_body, update_body, fail_loud):
            tool_ids.append(spec["id"])

    print("== Meridian FinOps AI Assistant ==")
    agent = cfg["agent"]
    body = _agent_body(cfg, tool_ids, nums)
    _upsert_agent(agent["id"], body, fail_loud)


def verify_agent() -> bool:
    cfg = load_agent_config()
    agent_id = cfg["agent"]["id"]
    ok = True
    print("== FinOps AI Assistant ==")
    for spec in cfg.get("tools") or []:
        r = _kbn("GET", f"{TOOLS_API}/{spec['id']}")
        if r.status_code == 200:
            print(f"  [ok] tool {spec['id']}")
        else:
            print(f"  [fail] tool {spec['id']}: {r.status_code}")
            ok = False

    r = _kbn("GET", f"{AGENTS_API}/{agent_id}")
    if r.status_code == 200:
        name = r.json().get("name", agent_id)
        tools = r.json().get("configuration", {}).get("tools", [])
        n_tools = len(tools[0].get("tool_ids", [])) if tools else 0
        print(f"  [ok] agent {agent_id} ({name}, {n_tools} tools)")
    else:
        print(f"  [fail] agent {agent_id}: {r.status_code}")
        ok = False

    print(f"  Chat:     {AGENT_CHAT_URL}")
    return ok


def agent_id() -> str:
    return load_agent_config()["agent"]["id"]
