"""FinOps provision profile: synthetic (Meridian factory) vs live Verdian Dynamics."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml

from src.config import ROOT

ACTIVE_FILE = ROOT / "config" / "active_profile.yaml"
LIVE_DIR = ROOT / "config" / "live"


def finops_profile() -> str:
    env = os.environ.get("FINOPS_PROFILE", "").strip().lower()
    if env in ("live", "gev", "gev-live"):
        return "live"
    if env:
        return env
    if ACTIVE_FILE.is_file():
        data = yaml.safe_load(ACTIVE_FILE.read_text(encoding="utf-8")) or {}
        val = str(data.get("profile") or "synthetic").strip().lower()
        if val in ("live", "gev", "gev-live"):
            return "live"
        return val or "synthetic"
    return "synthetic"


def is_live() -> bool:
    return finops_profile() == "live"


@lru_cache(maxsize=1)
def live_accounts() -> dict:
    path = LIVE_DIR / "accounts.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.is_file() else {}
    stage = data.get("stage") or {}
    monitoring = data.get("monitoring") or {}
    esf = data.get("esf") or []
    esf0 = esf[0] if len(esf) > 0 else {}
    esf1 = esf[1] if len(esf) > 1 else {}
    return {
        "stage_account_id": str(stage.get("id") or ""),
        "stage_account_name": str(stage.get("name") or "stage"),
        "monitoring_account_id": str(monitoring.get("id") or ""),
        "monitoring_account_name": str(monitoring.get("name") or "monitoring"),
        "esf_account_a": str(esf0.get("id") or ""),
        "esf_account_b": str(esf1.get("id") or ""),
    }


def live_path(*parts: str) -> Path:
    return ROOT.joinpath(*parts)


# World account id → slot in the live Cost Explorer roster
# (stage, monitoring, ESF-a, ESF-b). Multiple world accounts can share a slot;
# CE docs still sum correctly by live account id.
_LIVE_SLOT = {
    "222222222222": 0,  # meridian-staging
    "333333333333": 0,  # meridian-dev
    "555555555555": 1,  # meridian-logging
    "444444444444": 1,  # meridian-security
    "111111111111": 2,  # meridian-prod
    "888888888888": 2,  # meridian-fintech-prod
    "777777777777": 3,  # meridian-mlops
    "666666666666": 3,  # meridian-sandbox
    "999999999999": 3,  # meridian-fintech-dev
}


def live_ce_roster() -> list[dict]:
    a = live_accounts()
    return [
        {"id": a["stage_account_id"], "name": a["stage_account_name"]},
        {"id": a["monitoring_account_id"], "name": a["monitoring_account_name"]},
        {"id": a["esf_account_a"], "name": a["esf_account_a"]},
        {"id": a["esf_account_b"], "name": a["esf_account_b"]},
    ]


def ce_account(acct: dict | None) -> dict | None:
    """Rewrite a world AWS account onto a live Cost Explorer linked-account id.

    Dashboards CASE on 12-digit account ids (not names). Synthetic world.yaml
    ids stay as-is when FINOPS_PROFILE is not live.
    """
    if not acct or not is_live():
        return acct
    roster = [r for r in live_ce_roster() if r.get("id")]
    if not roster:
        return acct
    slot = _LIVE_SLOT.get(str(acct.get("id")), 0) % len(roster)
    live = roster[slot]
    return {**acct, "id": live["id"], "name": live["name"]}
