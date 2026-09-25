"""Reset an ELK Co FinOps cluster: wipe data + remove Kibana objects.

Usage:
  .venv/bin/python scripts/reset_environment.py --deployment gcp
  .venv/bin/python scripts/reset_environment.py --deployment azure --delete-streams
  .venv/bin/python scripts/reset_environment.py --skip-kibana   # data only
  .venv/bin/python scripts/reset_environment.py --delete-space  # drop KIBANA_SPACE
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _early_deployment_from_argv() -> None:
    argv = sys.argv[1:]
    for i, arg in enumerate(argv):
        if arg == "--deployment" and i + 1 < len(argv):
            os.environ["FINOPS_DEPLOYMENT"] = argv[i + 1]
            return
        if arg.startswith("--deployment="):
            os.environ["FINOPS_DEPLOYMENT"] = arg.split("=", 1)[1]
            return


_early_deployment_from_argv()

import requests
import yaml

from scripts.wipe_workshop_streams import wipe_stream
from src.budgets import load_budgets
from src.config import (
    ELASTIC_URL,
    ES_HEADERS,
    KBN_HEADERS,
    KIBANA_ROOT,
    KIBANA_SPACE,
    KIBANA_URL,
    apply_deployment,
    deployment_summary,
)
from src.generators import ALL
from src.profile import is_live
from src.rightsizing import DATA_STREAM as RIGHTSIZING_DS
from src.rightsizing import DEST_INDEX as RIGHTSIZING_DEST
from src.rightsizing import TRANSFORM_ID as RIGHTSIZING_TRANSFORM
from src.workflows import WORKFLOW_IDS

# Prior workflow ids (GEV / pre-rename) — wipe so renames do not leave orphans.
LEGACY_WORKFLOW_IDS = (
    "gev-finops-spend-spike-case",
    "gev-finops-spend-spike-hitl",
    "gev-finops-spend-spike-auto-approve",
    "gev-finops-rightsize-case",
    "gev-finops-rightsize-auto-approve",
)

DASHBOARD_BASES = (
    "elk-finops-llm-observability",
    "elk-finops-llm-observability-classic",
    "elk-finops-llm-observability-dynamic",
    "elk-ai-assistant-inference-usage",
    # prior Meridian ids — delete on reset so renames do not leave orphans
    "meridian-finops-llm-observability",
    "meridian-finops-llm-observability-classic",
    "meridian-finops-llm-observability-dynamic",
    "meridian-ai-assistant-inference-usage",
)

LIVE_DASHBOARD_IDS = (
    "elk-finops-llm-observability-dynamic-aws",
    "meridian-finops-llm-observability-dynamic-aws",  # prior Meridian id
    "finops-aws-billing-overview-unblended",
    "finops-spend-vs-savings",
    "finops-rightsizing-overview",
    # leftover AWS Hub v2 experiment (removed from catalog)
    "aws-hub-overview",
    "aws-hub-cost-explorer",
    "aws-hub-spend-vs-savings",
    "aws-hub-rightsizing",
    "aws-hub-security",
    "aws-hub-bedrock-llm",
)

EXTRA_STREAMS = (
    "metrics-ess_billing.billing-default",
    "metrics-ess_billing.credits-default",
    RIGHTSIZING_DS,
)


def _kbn(method: str, path: str, *, root: bool = False, **kwargs) -> requests.Response:
    base = KIBANA_ROOT if root else KIBANA_URL
    kwargs.setdefault("headers", KBN_HEADERS)
    kwargs.setdefault("timeout", 60)
    return requests.request(method, f"{base}{path}", **kwargs)


def _es(method: str, path: str, **kwargs) -> requests.Response:
    kwargs.setdefault("headers", ES_HEADERS)
    kwargs.setdefault("timeout", 120)
    return requests.request(method, f"{ELASTIC_URL}{path}", **kwargs)


def _variant_ids() -> list[str]:
    with open(ROOT / "config" / "variants.yaml", encoding="utf-8") as f:
        catalog = yaml.safe_load(f)
    return sorted((catalog.get("variants") or {}).keys())


def _dashboard_ids() -> list[str]:
    ids: list[str] = list(LIVE_DASHBOARD_IDS) if is_live() else []
    for vid in _variant_ids():
        suffix = "" if vid == "all" else f"-{vid}"
        for base in DASHBOARD_BASES:
            ids.append(f"{base}{suffix}")
    # de-dupe, preserve order
    seen: set[str] = set()
    out: list[str] = []
    for did in ids:
        if did not in seen:
            seen.add(did)
            out.append(did)
    return out


def wipe_data() -> int:
    streams = sorted({g.DATA_STREAM for g in ALL} | set(EXTRA_STREAMS))
    print(f"== Wipe {len(streams)} data streams ==")
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
    streams = sorted({g.DATA_STREAM for g in ALL} | set(EXTRA_STREAMS))
    print(f"== Delete {len(streams)} data streams ==")
    for ds in streams:
        r = _es("DELETE", f"/_data_stream/{ds}")
        if r.status_code in (404, 400):
            print(f"  [skip] {ds}: {r.status_code}")
        elif r.status_code >= 300:
            print(f"  [warn] {ds}: {r.status_code} {r.text[:200]}")
        else:
            print(f"  [ok] deleted data stream {ds}")


def delete_rightsizing_transform() -> None:
    print("== Remove rightsizing transform ==")
    _es("POST", f"/_transform/{RIGHTSIZING_TRANSFORM}/_stop?force=true")
    r = _es("DELETE", f"/_transform/{RIGHTSIZING_TRANSFORM}?force=true")
    if r.status_code in (404, 400):
        print(f"  [skip] transform {RIGHTSIZING_TRANSFORM}")
    elif r.status_code >= 300:
        print(f"  [warn] transform {RIGHTSIZING_TRANSFORM}: {r.status_code} {r.text[:200]}")
    else:
        print(f"  [ok] deleted transform {RIGHTSIZING_TRANSFORM}")
    r = _es("DELETE", f"/{RIGHTSIZING_DEST}")
    if r.status_code in (404, 400):
        print(f"  [skip] index {RIGHTSIZING_DEST}")
    elif r.status_code >= 300:
        print(f"  [warn] index {RIGHTSIZING_DEST}: {r.status_code} {r.text[:200]}")
    else:
        print(f"  [ok] deleted index {RIGHTSIZING_DEST}")


def delete_workflows() -> None:
    print("== Remove FinOps workflows ==")
    for wid in (*WORKFLOW_IDS, *LEGACY_WORKFLOW_IDS):
        r = _kbn("DELETE", f"/api/workflows/workflow/{wid}")
        if r.status_code == 404:
            continue
        if r.status_code >= 300:
            print(f"  [warn] workflow {wid}: {r.status_code} {r.text[:200]}")
        else:
            print(f"  [ok] deleted workflow {wid}")


def delete_kibana_objects() -> None:
    print("== Remove ELK Co / FinOps dashboards ==")
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

    agent_path = ROOT / ("config/live/finops_agent.yaml" if is_live() else "config/finops_agent.yaml")
    agent_cfg = yaml.safe_load(agent_path.read_text())
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

    delete_workflows()


def delete_kibana_space() -> None:
    space = (KIBANA_SPACE or "").strip()
    if not space or space.lower() == "default":
        print("== Skip space delete (default / unset) ==")
        return
    print(f"== Delete Kibana space {space} ==")
    r = _kbn("DELETE", f"/api/spaces/space/{space}", root=True)
    if r.status_code == 404:
        print(f"  [skip] space {space} not found")
    elif r.status_code >= 300:
        print(f"  [warn] space {space}: {r.status_code} {r.text[:300]}")
    else:
        print(f"  [ok] deleted space {space}")


def main() -> int:
    p = argparse.ArgumentParser(description="Reset ELK Co FinOps cluster")
    p.add_argument(
        "--deployment",
        default=None,
        metavar="NAME",
        help="named Elastic Cloud target from .env (DEPLOY_<NAME>_*)",
    )
    p.add_argument("--skip-kibana", action="store_true",
                   help="only wipe Elasticsearch data (keep dashboards/SLOs/agent)")
    p.add_argument("--delete-streams", action="store_true",
                   help="after wipe, DELETE data streams (not just documents)")
    p.add_argument("--delete-space", action="store_true",
                   help="also DELETE the configured KIBANA_SPACE (finops)")
    args = p.parse_args()

    if args.deployment:
        apply_deployment(args.deployment)

    s = deployment_summary()
    print(f"== Reset target: {s['deployment']} ==")
    print(f"  elastic: {s['elastic']}")
    print(f"  kibana:  {s['kibana']}  (space={s['space']}, profile={s['profile']})")

    delete_rightsizing_transform()
    errors = wipe_data()
    if args.delete_streams:
        delete_data_streams()
    if not args.skip_kibana:
        delete_kibana_objects()
        if args.delete_space or is_live():
            # Live FinOps lives in a dedicated space — drop it for a clean slate.
            delete_kibana_space()
    print("== reset complete ==")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
