"""Reset a Meridian workshop cluster: wipe synthetic data + remove Kibana objects.

Usage:
  .venv/bin/python scripts/reset_environment.py
  .venv/bin/python scripts/reset_environment.py --skip-kibana   # data only
  .venv/bin/python scripts/reset_environment.py --delete-streams  # also drop data streams
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests
import yaml

from scripts.wipe_workshop_streams import wipe_stream
from src.budgets import load_budgets
from src.config import ELASTIC_URL, ES_HEADERS, KBN_HEADERS, KIBANA_URL, ROOT
from src.generators import ALL

DASHBOARD_BASES = (
    "meridian-finops-llm-observability",
    "meridian-finops-llm-observability-classic",
    "meridian-finops-llm-observability-dynamic",
    "meridian-ai-assistant-inference-usage",
)


def _kbn(method: str, path: str, **kwargs) -> requests.Response:
    kwargs.setdefault("headers", KBN_HEADERS)
    kwargs.setdefault("timeout", 60)
    return requests.request(method, f"{KIBANA_URL}{path}", **kwargs)


def _variant_ids() -> list[str]:
    with open(ROOT / "config" / "variants.yaml", encoding="utf-8") as f:
        catalog = yaml.safe_load(f)
    return sorted((catalog.get("variants") or {}).keys())


def _dashboard_ids() -> list[str]:
    ids: list[str] = []
    for vid in _variant_ids():
        suffix = "" if vid == "all" else f"-{vid}"
        for base in DASHBOARD_BASES:
            ids.append(f"{base}{suffix}")
    return ids


def wipe_data() -> int:
    streams = sorted({g.DATA_STREAM for g in ALL})
    print(f"== Wipe {len(streams)} workshop data streams ==")
    errors = 0
    for ds in streams:
        print(f"  {ds} ...", flush=True)
        try:
            result = wipe_stream(ds)
            print(f"  [ok] {ds}: {result}", flush=True)
        except Exception as e:
            errors += 1
            print(f"  [fail] {ds}: {e}", flush=True)
    return errors


def delete_data_streams() -> None:
    streams = sorted({g.DATA_STREAM for g in ALL})
    print(f"== Delete {len(streams)} data streams ==")
    for ds in streams:
        r = requests.delete(
            f"{ELASTIC_URL}/_data_stream/{ds}",
            headers=ES_HEADERS,
            timeout=120,
        )
        if r.status_code in (404, 400):
            print(f"  [skip] {ds}: {r.status_code}")
        elif r.status_code >= 300:
            print(f"  [warn] {ds}: {r.status_code} {r.text[:200]}")
        else:
            print(f"  [ok] deleted data stream {ds}")


def delete_kibana_objects() -> None:
    print("== Remove Meridian dashboards ==")
    for did in _dashboard_ids():
        r = _kbn("DELETE", f"/api/dashboards/{did}")
        if r.status_code == 404:
            continue
        if r.status_code >= 300:
            print(f"  [warn] dashboard {did}: {r.status_code} {r.text[:200]}")
        else:
            print(f"  [ok] deleted dashboard {did}")

    cfg = load_budgets()
    print("== Remove FinOps SLOs ==")
    for spec in cfg.get("slos") or []:
        sid = spec["id"]
        r = _kbn("DELETE", f"/api/observability/slos/{sid}")
        if r.status_code == 404:
            continue
        if r.status_code >= 300:
            print(f"  [warn] SLO {sid}: {r.status_code} {r.text[:200]}")
        else:
            print(f"  [ok] deleted SLO {sid}")

    print("== Remove FinOps alert rules ==")
    rule_ids = {a["id"] for a in (cfg.get("alerts") or [])}
    for spec in cfg.get("slos") or []:
        if spec.get("burn_rate_alert"):
            rule_ids.add(f"{spec['id']}-burn")
    for rid in sorted(rule_ids):
        r = _kbn("DELETE", f"/api/alerting/rule/{rid}")
        if r.status_code == 404:
            continue
        if r.status_code >= 300:
            print(f"  [warn] rule {rid}: {r.status_code} {r.text[:200]}")
        else:
            print(f"  [ok] deleted rule {rid}")

    agent_cfg = yaml.safe_load((ROOT / "config" / "finops_agent.yaml").read_text())
    agent_id = agent_cfg["agent"]["id"]
    print("== Remove FinOps AI Assistant ==")
    r = _kbn("DELETE", f"/api/agent_builder/agents/{agent_id}")
    if r.status_code == 404:
        print(f"  [skip] agent {agent_id}")
    elif r.status_code >= 300:
        print(f"  [warn] agent {agent_id}: {r.status_code} {r.text[:200]}")
    else:
        print(f"  [ok] deleted agent {agent_id}")

    print("== Remove FinOps ES|QL tools ==")
    for tool in agent_cfg.get("tools") or []:
        tid = tool["id"]
        r = _kbn("DELETE", f"/api/agent_builder/tools/{tid}")
        if r.status_code == 404:
            continue
        if r.status_code >= 300:
            print(f"  [warn] tool {tid}: {r.status_code} {r.text[:200]}")
        else:
            print(f"  [ok] deleted tool {tid}")


def main() -> int:
    p = argparse.ArgumentParser(description="Reset Meridian workshop cluster")
    p.add_argument("--skip-kibana", action="store_true",
                   help="only wipe Elasticsearch data (keep dashboards/SLOs/agent)")
    p.add_argument("--delete-streams", action="store_true",
                   help="after wipe, DELETE data streams (not just documents)")
    args = p.parse_args()

    print(f"== Reset target: {KIBANA_URL} ==")
    errors = wipe_data()
    if args.delete_streams:
        delete_data_streams()
    if not args.skip_kibana:
        delete_kibana_objects()
    print("== reset complete ==")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
