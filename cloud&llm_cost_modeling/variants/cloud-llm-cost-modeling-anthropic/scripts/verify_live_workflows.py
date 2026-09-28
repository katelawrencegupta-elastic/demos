#!/usr/bin/env python3
"""Verify (and optionally deep-smoke) live ELK Co FinOps workflows.

Usage:
  .venv/bin/python scripts/verify_live_workflows.py --deployment aws
  .venv/bin/python scripts/verify_live_workflows.py --deployment aws --deep
  .venv/bin/python -m src.cli --deployment aws workflow --smoke
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

from src.config import apply_deployment, deployment_summary  # noqa: E402
from src.workflows import ensure_workflows, verify_workflows  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description="Verify live FinOps workflows")
    p.add_argument("--deployment", default=None, help="named DEPLOY_<NAME>_* target")
    p.add_argument(
        "--ensure",
        action="store_true",
        help="upsert workflows before verify (default: verify only)",
    )
    p.add_argument(
        "--deep",
        action="store_true",
        help="also run spend-spike auto-approve and wait for completion",
    )
    args = p.parse_args()
    if args.deployment:
        apply_deployment(args.deployment)
        os.environ["FINOPS_DEPLOYMENT"] = args.deployment

    s = deployment_summary()
    print(
        f"== deployment: {s['deployment']}  variant={s['variant']}  "
        f"profile={s['profile']} =="
    )
    print(f"  kibana: {s['kibana']}  (space={s['space']})")

    if args.ensure:
        if not ensure_workflows(fail_loud=False):
            print("  [fail] ensure_workflows")
            return 1

    ok = verify_workflows()
    if args.deep:
        from src.live_smoke import check_workflow_run_auto
        deep_ok, deep_msg = check_workflow_run_auto(deep=True)
        print(f"  [{'ok' if deep_ok else 'fail'}] deep run: {deep_msg}")
        ok = ok and deep_ok

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
