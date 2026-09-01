"""Enable GenAI token usage tracking (Stack Management → GenAI Settings).

Mirrors turning on *Token usage tracking* in the GenAI Settings UI:
- sets advanced setting ``genAiSettings:tokenUsageTracking``
- installs the OOTB [Elastic] Inference Token Usage dashboard when possible

On Elastic Cloud Serverless the public ``/api/kibana/settings`` routes are
disabled; use ``/internal/kibana/settings`` with header
``x-elastic-internal-origin: kibana`` (required when restrictInternalApis is on).
"""
from __future__ import annotations

import requests

from src.config import KBN_HEADERS, KIBANA_URL

TOKEN_USAGE_SETTING = "genAiSettings:tokenUsageTracking"
INSTALL_DASHBOARD_PATH = "/internal/gen_ai_settings/install_token_usage_dashboard"


def _headers(*, internal: bool = False) -> dict:
    h = dict(KBN_HEADERS)
    if internal:
        h["x-elastic-internal-origin"] = "kibana"
    return h


def _kbn(method: str, path: str, *, internal: bool = False, **kwargs) -> requests.Response:
    kwargs.setdefault("headers", _headers(internal=internal))
    kwargs.setdefault("timeout", 60)
    return requests.request(method, f"{KIBANA_URL}{path}", **kwargs)


def _user_value(settings: dict | None, key: str) -> bool | None:
    entry = (settings or {}).get(key)
    if not isinstance(entry, dict):
        return None
    if "userValue" in entry:
        return bool(entry["userValue"])
    return None


def _read_token_usage_enabled() -> bool | None:
    """Return True/False when readable; None if settings API is unavailable."""
    for internal in (True, False):
        path = "/internal/kibana/settings" if internal else "/api/kibana/settings"
        r = _kbn("GET", path, internal=internal)
        if r.status_code == 404:
            continue
        if r.status_code != 200:
            return None
        val = _user_value(r.json().get("settings"), TOKEN_USAGE_SETTING)
        return bool(val) if val is not None else False
    return None


def _set_token_usage_enabled() -> requests.Response | None:
    changes = {TOKEN_USAGE_SETTING: True}
    for internal in (True, False):
        path = "/internal/kibana/settings" if internal else "/api/kibana/settings"
        r = _kbn("POST", path, internal=internal, json={"changes": changes})
        if r.status_code == 404:
            continue
        return r
    return None


def _install_token_usage_dashboard() -> requests.Response:
    return _kbn("POST", INSTALL_DASHBOARD_PATH, internal=True, json={}, timeout=120)


def ensure_genai_token_usage_tracking(*, fail_loud: bool = False) -> bool:
    """Turn on GenAI token usage tracking and install the managed dashboard."""
    current = _read_token_usage_enabled()
    if current is True:
        print(f"  [ok] {TOKEN_USAGE_SETTING} already enabled")
    else:
        r = _set_token_usage_enabled()
        if r is None:
            msg = ("could not reach Kibana settings API "
                   "(tried /internal/kibana/settings and /api/kibana/settings)")
            if fail_loud:
                raise RuntimeError(msg)
            print(f"  [warn] {msg}")
            return False
        if r.status_code >= 300:
            msg = f"could not enable {TOKEN_USAGE_SETTING}: {r.status_code} {r.text[:400]}"
            if fail_loud:
                raise RuntimeError(msg)
            print(f"  [warn] {msg}")
            return False
        enabled = _user_value(r.json().get("settings"), TOKEN_USAGE_SETTING)
        if enabled is not True:
            # setMany succeeded but value not echoed — re-read.
            enabled = _read_token_usage_enabled()
        if enabled is not True:
            msg = f"{TOKEN_USAGE_SETTING} still disabled after settings update"
            if fail_loud:
                raise RuntimeError(msg)
            print(f"  [warn] {msg}")
            return False
        print(f"  [ok] enabled {TOKEN_USAGE_SETTING}")

    r = _install_token_usage_dashboard()
    if r.status_code >= 300:
        msg = (f"token usage dashboard install: {r.status_code} {r.text[:400]} "
               "(data view patch in setup may still apply)")
        if fail_loud:
            raise RuntimeError(msg)
        print(f"  [warn] {msg}")
        return True
    body = r.json() if r.text else {}
    if body.get("installed"):
        print("  [ok] installed [Elastic] Inference Token Usage dashboard")
    else:
        print("  [ok] token usage dashboard already present (or install skipped)")
    return True
