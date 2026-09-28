#!/usr/bin/env python3
"""Pre-demo readiness gate: consistency + fork drift + optional panel smoke.

Usage:
  .venv/bin/python scripts/pre_demo_gate.py
  .venv/bin/python scripts/pre_demo_gate.py --deployment azure --deployment gcp
  .venv/bin/python scripts/pre_demo_gate.py --skip-drift --skip-smoke
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = ROOT / ".venv" / "bin" / "python"
if not PY.is_file():
    PY = Path(sys.executable)

# Load .env so DEPLOY_<NAME>_FINOPS_PROFILE is visible for --live detection.
try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except Exception:
    pass


def _run(label: str, argv: list[str]) -> int:
    print(f"\n== {label} ==")
    print(" ", " ".join(argv))
    r = subprocess.run(argv, cwd=ROOT)
    if r.returncode:
        print(f"  [fail] {label} exit={r.returncode}")
    else:
        print(f"  [ok] {label}")
    return r.returncode


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Pre-demo consistency / drift / smoke gate")
    p.add_argument(
        "--deployment",
        action="append",
        default=[],
        metavar="NAME",
        help="run panel_smoke against this deployment (repeatable)",
    )
    p.add_argument("--skip-consistency", action="store_true")
    p.add_argument("--skip-drift", action="store_true")
    p.add_argument("--skip-smoke", action="store_true")
    args = p.parse_args(argv)

    rc = 0
    if not args.skip_consistency:
        rc |= _run(
            "variant_consistency",
            [str(PY), "scripts/variant_consistency.py"],
        )
    if not args.skip_drift:
        rc |= _run(
            "check_fork_drift",
            [str(PY), "scripts/check_fork_drift.py"],
        )
    if not args.skip_smoke:
        deps = args.deployment or []
        if not deps:
            print("\n== panel_smoke skipped (pass --deployment NAME) ==")
        for dep in deps:
            smoke_argv = [str(PY), "scripts/panel_smoke.py", "--deployment", dep]
            # Live AWS hub uses Cost Explorer NDJSON ids — synthetic panel targets 404.
            profile = (
                os.environ.get(f"DEPLOY_{dep.upper()}_FINOPS_PROFILE", "")
                or ""
            ).strip().lower()
            if profile in ("live", "gev", "gev-live"):
                smoke_argv.append("--live")
            rc |= _run(f"panel_smoke[{dep}]", smoke_argv)
    if rc:
        print("\nPRE-DEMO GATE: FAIL")
        return 1
    print("\nPRE-DEMO GATE: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
