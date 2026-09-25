"""Provision FinOps AI Assistant (Elastic Agent Builder).

Creates ES|QL / workflow tools and a chat agent. Tool definitions come from
config/finops_agent.yaml (synthetic) or config/live/finops_agent.yaml (live).
"""
from __future__ import annotations

import requests
import yaml

from src.budgets import substitutions
from src.config import KBN_HEADERS, KIBANA_URL, ROOT
from src.profile import LIVE_DIR, uses_live_aws_hub

TAGS = ["elk-co", "finops", "workshop"]
LIVE_TAGS = ["elk-co", "finops"]

TOOLS_API = f"{KIBANA_URL}/api/agent_builder/tools"
AGENTS_API = f"{KIBANA_URL}/api/agent_builder/agents"
AGENT_CHAT_URL = f"{KIBANA_URL}/app/agent_builder/chat"


def agent_config_path():
    return LIVE_DIR / "finops_agent.yaml" if uses_live_aws_hub() else ROOT / "config" / "finops_agent.yaml"


def load_agent_config() -> dict:
    with open(agent_config_path()) as f:
        return yaml.safe_load(f)


def _kbn(method: str, url: str, **kwargs):
    kwargs.setdefault("headers", KBN_HEADERS)
    kwargs.setdefault("timeout", 60)
    return requests.request(method, url, **kwargs)


def _tags(cfg: dict | None = None) -> list:
    cfg = cfg or load_agent_config()
    agent = cfg.get("agent") or {}
    return list(agent.get("labels") or (LIVE_TAGS if uses_live_aws_hub() else TAGS))


def _budgets_block(mapping: dict) -> str:
    if uses_live_aws_hub():
        return "\n".join([
            f"- Calendar MTD linked unblended alert: ${mapping['aws_mtd_budget_usd']:,.0f}",
            f"- Trailing-30d budget alert: ${mapping['aws_trailing_30d_budget_usd']:,.0f}",
            f"- Daily SLO ceilings: org ${mapping['aws_daily_ceiling_usd']:,.0f}, "
            f"stage `{mapping['stage_account_id']}` ${mapping['staging_daily_ceiling_usd']:,.0f}, "
            f"monitoring `{mapping['monitoring_account_id']}` "
            f"${mapping['monitoring_daily_ceiling_usd']:,.0f}, "
            f"ESF pair ${mapping['esf_daily_ceiling_usd']:,.0f}, "
            f"Agent Builder {int(mapping['inference_daily_tokens']):,} tokens/day",
            f"- Stage daily alert floor: ${mapping['staging_daily_alert_usd']:,.0f}",
            f"- Agent Builder 7d token alert: {int(mapping['inference_7d_tokens']):,} tokens",
        ])
    return "\n".join([
        f"- AWS monthly budget: ${mapping['aws_monthly_usd']:,.0f}",
        f"- AWS daily SLO ceiling: ${mapping['aws_daily_ceiling_usd']:,.0f}",
        f"- Staging daily SLO ceiling: ${mapping['staging_daily_ceiling_usd']:,.0f}",
        f"- Staging daily alert floor: ${mapping['staging_daily_alert_usd']:,.0f}",
        f"- checkout-assistant daily SLO ceiling: ${mapping['checkout_daily_ceiling_usd']:.2f}",
        f"- checkout-assistant 7d alert floor: ${mapping['checkout_7d_alert_usd']:.2f}",
        f"- GCP elk-ml-prod 7d alert floor: ${mapping['gcp_ml_7d_alert_usd']:,.0f}",
    ])


def _render(template: str, mapping: dict) -> str:
    return template.format(**mapping).strip()


def _tool_body(spec: dict, mapping: dict, tags: list) -> dict:
    tool_type = spec.get("type") or "esql"
    body = {
        "id": spec["id"],
        "type": tool_type,
        "description": spec["description"].strip(),
        "tags": spec.get("tags") or tags,
    }
    if tool_type == "workflow":
        body["configuration"] = {"workflow_id": spec["workflow_id"]}
        return body
    body["configuration"] = {
        "query": _render(spec["esql"], mapping),
        "params": spec.get("params") or {},
    }
    return body


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


def _agent_body(cfg: dict, tool_ids: list[str], mapping: dict) -> dict:
    agent = cfg["agent"]
    fmt = dict(mapping)
    fmt["budgets_block"] = _budgets_block(mapping)
    fmt.setdefault("kibana_url", KIBANA_URL)
    instructions = cfg["instructions"].format(**fmt).strip()
    body = {
        "id": agent["id"],
        "name": agent["name"],
        "description": agent["description"].strip(),
        "labels": agent.get("labels") or _tags(cfg),
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
    """Upsert FinOps tools and the FinOps AI Assistant agent."""
    cfg = load_agent_config()
    mapping = substitutions()
    tags = _tags(cfg)
    tool_ids: list[str] = []

    print("== FinOps AI Assistant tools ==")
    for spec in cfg.get("tools") or []:
        create_body = _tool_body(spec, mapping, tags)
        update_body = {
            "description": create_body["description"],
            "tags": create_body["tags"],
            "configuration": create_body["configuration"],
        }
        if _upsert_tool(spec["id"], create_body, update_body, fail_loud):
            tool_ids.append(spec["id"])

    for extra in cfg.get("attach_tools") or []:
        if extra not in tool_ids:
            tool_ids.append(extra)

    print("== ELK Co FinOps AI Assistant ==" if uses_live_aws_hub()
          else "== FinOps AI Assistant ==")
    agent = cfg["agent"]
    body = _agent_body(cfg, tool_ids, mapping)
    _upsert_agent(agent["id"], body, fail_loud)


def verify_agent() -> bool:
    cfg = load_agent_config()
    aid = cfg["agent"]["id"]
    ok = True
    print("== FinOps AI Assistant ==")
    for spec in cfg.get("tools") or []:
        r = _kbn("GET", f"{TOOLS_API}/{spec['id']}")
        if r.status_code == 200:
            print(f"  [ok] tool {spec['id']}")
        else:
            print(f"  [fail] tool {spec['id']}: {r.status_code}")
            ok = False

    r = _kbn("GET", f"{AGENTS_API}/{aid}")
    if r.status_code == 200:
        name = r.json().get("name", aid)
        tools = r.json().get("configuration", {}).get("tools", [])
        n_tools = len(tools[0].get("tool_ids", [])) if tools else 0
        print(f"  [ok] agent {aid} ({name}, {n_tools} tools)")
    else:
        print(f"  [fail] agent {aid}: {r.status_code}")
        ok = False

    print(f"  Chat:     {AGENT_CHAT_URL}")
    return ok


def agent_id() -> str:
    return load_agent_config()["agent"]["id"]
