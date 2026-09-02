#!/usr/bin/env python3
"""Materialize provider/integration-scoped forks of the Meridian demo project.

Each fork is a self-contained copy with config/active_variant.yaml set so
setup/backfill/dashboards only touch the relevant integrations.

Examples:
  python scripts/fork_project.py --list
  python scripts/fork_project.py --all
  python scripts/fork_project.py aws gcp azure
  python scripts/fork_project.py --force openai
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DEMOS = ROOT.parent

SKIP_NAMES = {
    ".venv",
    "__pycache__",
    ".git",
    ".env",
    ".DS_Store",
    "elastic",
}

README_FORK = """# {title}

Provider/integration-scoped fork of the Meridian synthetic data factory.

- **Variant:** `{variant}`
- **Source:** `{source}`

## Quickstart

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env   # set ELASTIC_URL, ELASTIC_API_KEY, KIBANA_URL

.venv/bin/python -m src.cli setup
.venv/bin/python -m src.cli backfill
.venv/bin/python -m src.cli verify
.venv/bin/python -m src.cli dashboards --variant all
```

List all workshop variants: `python -m src.cli variants`

Re-fork from the master project:

```bash
python scripts/fork_project.py --force {variant}
```
"""


def _load_variants() -> dict:
    with open(ROOT / "config" / "variants.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)["variants"]


def _copy_tree(src: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        if item.name in SKIP_NAMES:
            continue
        target = dest / item.name
        if item.is_dir():
            shutil.copytree(item, target, ignore=shutil.ignore_patterns(*SKIP_NAMES))
        else:
            shutil.copy2(item, target)


def fork_variant(variant: str, *, force: bool = False, dest_root: Path | None = None) -> Path:
    variants = _load_variants()
    if variant not in variants:
        known = ", ".join(sorted(variants))
        raise SystemExit(f"Unknown variant {variant!r} (known: {known})")

    spec = variants[variant]
    dest = (dest_root or DEMOS) / spec["fork_dir"]
    if dest.exists():
        if not force:
            print(f"skip {dest.name} (exists — pass --force to replace)")
            return dest
        shutil.rmtree(dest)

    print(f"fork {variant} -> {dest}")
    _copy_tree(ROOT, dest)

    active = dest / "config" / "active_variant.yaml"
    active.write_text(f"variant: {variant}\n", encoding="utf-8")

    readme = dest / "FORK.md"
    readme.write_text(
        README_FORK.format(
            title=spec["title"],
            variant=variant,
            source=ROOT.name,
        ),
        encoding="utf-8",
    )
    print(f"  wrote {active.relative_to(dest)}")
    print(f"  wrote {readme.name}")
    return dest


def main(argv: list[str] | None = None) -> int:
    variants = _load_variants()
    p = argparse.ArgumentParser(description="Fork Meridian demo by cloud/integration variant")
    p.add_argument(
        "variants",
        nargs="*",
        help="variant ids (default: all). e.g. aws gcp azure openai",
    )
    p.add_argument("--all", action="store_true", help="fork every variant in config/variants.yaml")
    p.add_argument("--list", action="store_true", help="list variant ids and destination dirs")
    p.add_argument("--force", action="store_true", help="replace existing fork directories")
    p.add_argument(
        "--dest",
        type=Path,
        default=None,
        help=f"parent directory for forks (default: {DEMOS})",
    )
    args = p.parse_args(argv)

    if args.list:
        for vid, spec in sorted(variants.items()):
            print(f"{vid:14}  {spec['fork_dir']}")
            print(f"{'':14}  {spec['title']}")
        return 0

    targets = sorted(variants) if args.all else args.variants
    if not targets:
        p.error("pass variant ids, or use --all")

    dest_root = args.dest or DEMOS
    for variant in targets:
        fork_variant(variant, force=args.force, dest_root=dest_root)
    print(f"\nDone. Forks live under {dest_root}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
