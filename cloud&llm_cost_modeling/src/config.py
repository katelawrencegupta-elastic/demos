"""Environment / connection configuration.

Supports multiple named Elastic Cloud deployments in one `.env`:

    FINOPS_DEPLOYMENT=gcp

    DEPLOY_GCP_ELASTIC_URL=https://….es….elastic.cloud:443
    DEPLOY_GCP_ELASTIC_API_KEY=…
    DEPLOY_GCP_KIBANA_URL=https://….kb….elastic.cloud
    DEPLOY_GCP_KIBANA_SPACE=finops
    DEPLOY_GCP_FINOPS_PROFILE=synthetic
    DEPLOY_GCP_VARIANT=gcp

    DEPLOY_AZURE_ELASTIC_URL=…
    DEPLOY_AZURE_VARIANT=azure
    …

Select with `FINOPS_DEPLOYMENT=<name>` or `python -m src.cli --deployment <name> …`.
When a deployment is selected, its `DEPLOY_<NAME>_*` keys override the flat
`ELASTIC_*` / `KIBANA_*` / `FINOPS_PROFILE` / `VARIANT` values. Flat keys alone
still work for a single-target `.env` (backward compatible).
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

# Flat keys that can be provided per deployment as DEPLOY_<NAME>_<KEY>.
_DEPLOY_KEYS = (
    "ELASTIC_URL",
    "ELASTIC_API_KEY",
    "KIBANA_URL",
    "KIBANA_SPACE",
    "FINOPS_PROFILE",
    "VARIANT",  # maps → FINOPS_VARIANT
)

_DEPLOY_PREFIX_RE = re.compile(
    r"^DEPLOY_([A-Z0-9_]+)_(ELASTIC_URL|ELASTIC_API_KEY|KIBANA_URL|"
    r"KIBANA_SPACE|FINOPS_PROFILE|VARIANT)$"
)

ACTIVE_DEPLOYMENT: str | None = None


def _norm_deployment(name: str) -> str:
    return name.strip().lower().replace("-", "_")


def _deploy_prefix(name: str) -> str:
    return f"DEPLOY_{_norm_deployment(name).upper()}_"


def list_deployments() -> list[str]:
    """Deployment ids that define at least DEPLOY_<ID>_ELASTIC_URL."""
    found: set[str] = set()
    for key in os.environ:
        m = _DEPLOY_PREFIX_RE.match(key)
        if m and m.group(2) == "ELASTIC_URL":
            found.add(m.group(1).lower())
    return sorted(found)


_DEPLOY_VARIANT_ALIASES = {
    "vertexai": "gcp",
    "azure-openai": "azure",
    "azure_openai": "azure",
}
_KNOWN_VARIANTS = frozenset({
    "all", "aws", "gcp", "azure", "openai", "anthropic",
    "bedrock", "elastic-ai",
})


def _apply_deployment_env(name: str) -> None:
    """Copy DEPLOY_<NAME>_* into the flat connection env vars."""
    prefix = _deploy_prefix(name)
    # Drop prior deployment overlays so missing keys do not leak across targets.
    os.environ.pop("FINOPS_VARIANT", None)
    for key in ("KIBANA_URL", "KIBANA_SPACE", "FINOPS_PROFILE"):
        os.environ.pop(key, None)
    for key in _DEPLOY_KEYS:
        val = os.environ.get(f"{prefix}{key}")
        if val is None or val == "":
            continue
        if key == "VARIANT":
            os.environ["FINOPS_VARIANT"] = val.strip()
        else:
            os.environ[key] = val
    current = os.environ.get("FINOPS_VARIANT", "").strip()
    if current in _DEPLOY_VARIANT_ALIASES:
        os.environ["FINOPS_VARIANT"] = _DEPLOY_VARIANT_ALIASES[current]
    elif not current:
        # `--deployment gcp` without VARIANT should not fall back to aws
        # from config/active_variant.yaml.
        nid = _DEPLOY_VARIANT_ALIASES.get(
            _norm_deployment(name).replace("_", "-"),
            _norm_deployment(name).replace("_", "-"),
        )
        if nid in _KNOWN_VARIANTS:
            os.environ["FINOPS_VARIANT"] = nid


def _rebuild_connection() -> None:
    """Recompute module-level URL/header globals from os.environ."""
    global ELASTIC_URL, ELASTIC_API_KEY, KIBANA_SPACE, KIBANA_ROOT, KIBANA_URL
    global ES_HEADERS, KBN_HEADERS, ACTIVE_DEPLOYMENT

    if "ELASTIC_URL" not in os.environ or "ELASTIC_API_KEY" not in os.environ:
        known = ", ".join(list_deployments()) or "(none)"
        raise SystemExit(
            "Missing ELASTIC_URL / ELASTIC_API_KEY. Set flat keys in .env, or "
            f"set FINOPS_DEPLOYMENT to one of: {known}"
        )

    ELASTIC_URL = os.environ["ELASTIC_URL"].rstrip("/")
    ELASTIC_API_KEY = os.environ["ELASTIC_API_KEY"]
    KIBANA_SPACE = os.environ.get("KIBANA_SPACE", "").strip()
    _kibana_root = os.environ.get(
        "KIBANA_URL", ELASTIC_URL.replace(".es.", ".kb.").replace(":443", "")
    ).rstrip("/")
    KIBANA_ROOT = _kibana_root
    if KIBANA_SPACE and KIBANA_SPACE.lower() != "default":
        KIBANA_URL = f"{_kibana_root}/s/{KIBANA_SPACE}"
    else:
        KIBANA_URL = _kibana_root

    ES_HEADERS = {
        "Authorization": f"ApiKey {ELASTIC_API_KEY}",
        "Content-Type": "application/json",
    }
    KBN_HEADERS = {
        "Authorization": f"ApiKey {ELASTIC_API_KEY}",
        "kbn-xsrf": "true",
        "Content-Type": "application/json",
    }


def apply_deployment(name: str | None = None) -> str | None:
    """Select a named deployment and refresh connection globals.

    Returns the active deployment id (normalized) or None when using flat keys.
    """
    global ACTIVE_DEPLOYMENT

    raw = (name if name is not None else os.environ.get("FINOPS_DEPLOYMENT", "")).strip()
    if raw:
        nid = _norm_deployment(raw)
        if nid not in list_deployments() and f"{_deploy_prefix(nid)}ELASTIC_URL" not in os.environ:
            known = ", ".join(list_deployments()) or "(none defined)"
            raise SystemExit(
                f"Unknown deployment {raw!r}. Known DEPLOY_* targets: {known}"
            )
        os.environ["FINOPS_DEPLOYMENT"] = nid
        _apply_deployment_env(nid)
        ACTIVE_DEPLOYMENT = nid
    else:
        ACTIVE_DEPLOYMENT = None

    _rebuild_connection()

    # Variant / profile caches may have been built against a prior target.
    try:
        from src.variant import active_variant
        active_variant.cache_clear()
    except Exception:
        pass
    try:
        from src.profile import live_accounts
        live_accounts.cache_clear()
    except Exception:
        pass

    return ACTIVE_DEPLOYMENT


def deployment_summary() -> dict[str, str]:
    """Human-readable snapshot of the active Elastic target."""
    host = ELASTIC_URL.split("@")[-1] if "@" in ELASTIC_URL else ELASTIC_URL
    return {
        "deployment": ACTIVE_DEPLOYMENT or "(flat .env)",
        "elastic": host,
        "kibana": KIBANA_URL,
        "space": KIBANA_SPACE or "default",
        "profile": os.environ.get("FINOPS_PROFILE", "synthetic"),
        "variant": os.environ.get("FINOPS_VARIANT", "").strip() or "(active_variant.yaml)",
    }


# Resolve FINOPS_DEPLOYMENT (if any) on import.
apply_deployment()

WORLD_CONFIG = ROOT / "config" / "world.yaml"
