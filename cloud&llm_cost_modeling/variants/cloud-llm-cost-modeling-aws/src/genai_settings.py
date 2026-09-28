"""Enable GenAI token usage tracking (Stack Management → GenAI Settings).

Mirrors turning on *Token usage tracking* in the GenAI Settings UI:
- sets advanced setting ``genAiSettings:tokenUsageTracking``
- installs the OOTB [Elastic] Inference Token Usage dashboard when possible

On Elastic Cloud Serverless the public ``/api/kibana/settings`` routes are
disabled; use ``/internal/kibana/settings`` with header
``x-elastic-internal-origin: kibana`` (required when restrictInternalApis is on).

Settings are applied on the Kibana *root* (default space) first — GenAI Settings
is a stack-level control — then on the active space when ``KIBANA_SPACE`` is set.
"""
from __future__ import annotations

import requests

from src.config import KBN_HEADERS, KIBANA_ROOT, KIBANA_URL

TOKEN_USAGE_SETTING = "genAiSettings:tokenUsageTracking"
INSTALL_DASHBOARD_PATH = "/internal/gen_ai_settings/install_token_usage_dashboard"


def _headers(*, internal: bool = False) -> dict:
    h = dict(KBN_HEADERS)
    if internal:
        h["x-elastic-internal-origin"] = "kibana"
    return h


def _bases() -> list[str]:
    """Default space first, then the active space (if different)."""
    out = [KIBANA_ROOT]
    if KIBANA_URL.rstrip("/") != KIBANA_ROOT.rstrip("/"):
        out.append(KIBANA_URL)
    return out


def _kbn(method: str, path: str, *, base: str | None = None,
         internal: bool = False, **kwargs) -> requests.Response:
    kwargs.setdefault("headers", _headers(internal=internal))
    kwargs.setdefault("timeout", 60)
    root = (base or KIBANA_ROOT).rstrip("/")
    return requests.request(method, f"{root}{path}", **kwargs)


def _user_value(settings: dict | None, key: str) -> bool | None:
    entry = (settings or {}).get(key)
    if not isinstance(entry, dict):
        return None
    if "userValue" in entry:
        return bool(entry["userValue"])
    return None


def _read_token_usage_enabled(base: str | None = None) -> bool | None:
    """Return True/False when readable; None if settings API is unavailable."""
    for internal in (True, False):
        path = "/internal/kibana/settings" if internal else "/api/kibana/settings"
        r = _kbn("GET", path, base=base, internal=internal)
        if r.status_code == 404:
            continue
        if r.status_code != 200:
            return None
        val = _user_value(r.json().get("settings"), TOKEN_USAGE_SETTING)
        return bool(val) if val is not None else False
    return None


def _set_token_usage_enabled(base: str | None = None) -> requests.Response | None:
    changes = {TOKEN_USAGE_SETTING: True}
    for internal in (True, False):
        path = "/internal/kibana/settings" if internal else "/api/kibana/settings"
        r = _kbn("POST", path, base=base, internal=internal, json={"changes": changes})
        if r.status_code == 404:
            continue
        return r
    return None


def _install_token_usage_dashboard(base: str | None = None) -> requests.Response:
    return _kbn(
        "POST", INSTALL_DASHBOARD_PATH, base=base, internal=True, json={}, timeout=120,
    )


def ensure_genai_token_usage_tracking(*, fail_loud: bool = False) -> bool:
    """Turn on GenAI token usage tracking and install the managed dashboard."""
    ok = True
    for base in _bases():
        label = "default" if base.rstrip("/") == KIBANA_ROOT.rstrip("/") else "space"
        current = _read_token_usage_enabled(base)
        if current is True:
            print(f"  [ok] {TOKEN_USAGE_SETTING} already enabled ({label})")
        else:
            r = _set_token_usage_enabled(base)
            if r is None:
                msg = (f"could not reach Kibana settings API on {label} "
                       "(tried /internal/kibana/settings and /api/kibana/settings)")
                if fail_loud:
                    raise RuntimeError(msg)
                print(f"  [warn] {msg}")
                ok = False
                continue
            if r.status_code >= 300:
                msg = (f"could not enable {TOKEN_USAGE_SETTING} ({label}): "
                       f"{r.status_code} {r.text[:400]}")
                if fail_loud:
                    raise RuntimeError(msg)
                print(f"  [warn] {msg}")
                ok = False
                continue
            enabled = _user_value(r.json().get("settings"), TOKEN_USAGE_SETTING)
            if enabled is not True:
                enabled = _read_token_usage_enabled(base)
            if enabled is not True:
                msg = f"{TOKEN_USAGE_SETTING} still disabled after settings update ({label})"
                if fail_loud:
                    raise RuntimeError(msg)
                print(f"  [warn] {msg}")
                ok = False
                continue
            print(f"  [ok] enabled {TOKEN_USAGE_SETTING} ({label})")

        r = _install_token_usage_dashboard(base)
        if r.status_code >= 300:
            msg = (f"token usage dashboard install ({label}): "
                   f"{r.status_code} {r.text[:400]} "
                   "(data view patch in setup may still apply)")
            if fail_loud and base.rstrip("/") == KIBANA_ROOT.rstrip("/"):
                raise RuntimeError(msg)
            print(f"  [warn] {msg}")
            continue
        body = r.json() if r.text else {}
        if body.get("installed"):
            print(f"  [ok] installed [Elastic] Inference Token Usage dashboard ({label})")
        else:
            print(f"  [ok] token usage dashboard already present ({label})")
    return ok
