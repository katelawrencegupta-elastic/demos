#!/usr/bin/env python3
"""Fail if workshop forks drift from master critical paths.

Runtime demos should use the master ``cloud&llm_cost_modeling/`` tree.
Forks under ``variants/`` are regenerated workshop handouts — refresh with
``scripts/fork_project.py --all --force`` when master changes.

Usage:
  .venv/bin/python scripts/check_fork_drift.py
  .venv/bin/python scripts/check_fork_drift.py --json-out /tmp/drift.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
VARIANTS_ROOT = ROOT / "variants"

# Paths that must stay byte-identical to master after a force re-fork.
CRITICAL_PATHS = (
    "src/budgets.py",
    "src/dashboards.py",
    "src/dashboards_ai.py",
    "src/agent_builder.py",
    "src/config.py",
    "config/budgets.yaml",
    "config/budgets_azure.yaml",
    "config/budgets_gcp.yaml",
    "config/budgets_llm.yaml",
    "config/budgets_bedrock.yaml",
    "config/variants.yaml",
)


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _load_fork_dirs() -> list[tuple[str, str]]:
    with open(ROOT / "config" / "variants.yaml", encoding="utf-8") as f:
        variants = yaml.safe_load(f)["variants"]
    return [(vid, spec["fork_dir"]) for vid, spec in sorted(variants.items())]


def check_drift() -> list[dict]:
    findings: list[dict] = []
    for vid, fork_dir in _load_fork_dirs():
        fork_root = VARIANTS_ROOT / fork_dir
        if not fork_root.is_dir():
            findings.append(
                {
                    "variant": vid,
                    "fork": fork_dir,
                    "path": "(missing fork)",
                    "ok": False,
                    "detail": f"fork directory missing: {fork_root}",
                }
            )
            continue
        for rel in CRITICAL_PATHS:
            master_p = ROOT / rel
            fork_p = fork_root / rel
            m_hash = _sha256(master_p)
            f_hash = _sha256(fork_p)
            if m_hash is None:
                findings.append(
                    {
                        "variant": vid,
                        "fork": fork_dir,
                        "path": rel,
                        "ok": False,
                        "detail": f"missing on master: {master_p}",
                    }
                )
                continue
            if f_hash is None:
                findings.append(
                    {
                        "variant": vid,
                        "fork": fork_dir,
                        "path": rel,
                        "ok": False,
                        "detail": "missing in fork",
                    }
                )
                continue
            if m_hash != f_hash:
                findings.append(
                    {
                        "variant": vid,
                        "fork": fork_dir,
                        "path": rel,
                        "ok": False,
                        "detail": "content differs from master",
                    }
                )
            else:
                findings.append(
                    {
                        "variant": vid,
                        "fork": fork_dir,
                        "path": rel,
                        "ok": True,
                        "detail": "match",
                    }
                )
    return findings


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Check master↔fork drift on critical paths")
    p.add_argument("--json-out", default=None, help="write full findings JSON")
    p.add_argument(
        "--quiet-ok",
        action="store_true",
        help="only print failures",
    )
    args = p.parse_args(argv)

    findings = check_drift()
    fails = [f for f in findings if not f["ok"]]
    by_fork: dict[str, list] = {}
    for f in fails:
        by_fork.setdefault(f["fork"], []).append(f)

    if not args.quiet_ok:
        n_ok = sum(1 for f in findings if f["ok"])
        print(f"== fork drift: {n_ok} ok, {len(fails)} drift across {len(_load_fork_dirs())} forks ==")
    for fork, items in sorted(by_fork.items()):
        print(f"  [drift] {fork}")
        for it in items:
            print(f"    - {it['path']}: {it['detail']}")

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(findings, indent=2), encoding="utf-8")
        print(f"wrote {args.json_out}")

    if fails:
        print(
            "\nRe-fork from master to refresh handouts:\n"
            "  .venv/bin/python scripts/fork_project.py --all --force"
        )
        return 1
    print("PASS: forks match master on critical paths")
    return 0


if __name__ == "__main__":
    sys.exit(main())
