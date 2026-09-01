"""Active workshop variant — scopes generators, Fleet setup, and dashboards."""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from src.config import ROOT

VARIANTS_FILE = ROOT / "config" / "variants.yaml"
ACTIVE_FILE = ROOT / "config" / "active_variant.yaml"


@dataclass(frozen=True)
class Variant:
    id: str
    title: str
    fork_dir: str
    default_scope: str
    generator_names: frozenset[str]
    packages: tuple[str, ...]
    setup: dict[str, bool]
    dashboards: dict[str, bool]
    ootb_link_labels: frozenset[str]

    @property
    def is_all(self) -> bool:
        return self.id == "all"

    def dash_suffix(self) -> str:
        return "" if self.is_all else f"-{self.id}"

    def setup_enabled(self, key: str) -> bool:
        return bool(self.setup.get(key))

    def has_generator(self, name: str) -> bool:
        return self.is_all or name in self.generator_names


def _load_catalog() -> dict[str, Any]:
    with open(VARIANTS_FILE, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _active_id() -> str:
    env = os.environ.get("MERIDIAN_VARIANT", "").strip()
    if env:
        return env
    if ACTIVE_FILE.is_file():
        data = yaml.safe_load(ACTIVE_FILE.read_text(encoding="utf-8")) or {}
        if data.get("variant"):
            return str(data["variant"])
    return "all"


def _resolve_generator_names(spec: dict[str, Any]) -> frozenset[str]:
    gens = spec.get("generators")
    if gens == "all" or gens is None:
        from src.generators import ALL_NAMES
        return ALL_NAMES
    return frozenset(str(g) for g in gens)


def _resolve_ootb_labels(catalog: dict[str, Any], spec: dict[str, Any]) -> frozenset[str]:
    groups = catalog.get("ootb_groups") or {}
    labels: set[str] = set()
    for key in spec.get("ootb_links") or []:
        for label in groups.get(key, []):
            labels.add(label)
    return frozenset(labels)


@lru_cache(maxsize=1)
def active_variant() -> Variant:
    catalog = _load_catalog()
    vid = _active_id()
    variants = catalog.get("variants") or {}
    if vid not in variants:
        known = ", ".join(sorted(variants))
        raise SystemExit(f"Unknown variant {vid!r} (known: {known})")
    spec = variants[vid]
    return Variant(
        id=vid,
        title=spec["title"],
        fork_dir=spec["fork_dir"],
        default_scope=spec.get("default_scope", "all"),
        generator_names=_resolve_generator_names(spec),
        packages=tuple(spec.get("packages") or []),
        setup=dict(spec.get("setup") or {}),
        dashboards=dict(spec.get("dashboards") or {}),
        ootb_link_labels=_resolve_ootb_labels(catalog, spec),
    )


def list_variants() -> list[tuple[str, str, str]]:
    catalog = _load_catalog()
    out = []
    for vid, spec in (catalog.get("variants") or {}).items():
        out.append((vid, spec["title"], spec["fork_dir"]))
    return sorted(out, key=lambda x: (x[0] != "all", x[0]))


def filter_o_otb_links(ootb: dict[str, str]) -> dict[str, str]:
    v = active_variant()
    if v.is_all:
        return ootb
    return {k: val for k, val in ootb.items() if k in v.ootb_link_labels}
