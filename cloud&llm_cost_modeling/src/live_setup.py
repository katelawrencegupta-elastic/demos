"""Object-only provision for the live Verdian Dynamics FinOps profile."""
from __future__ import annotations

import requests

from src.config import ELASTIC_URL, ES_HEADERS, KBN_HEADERS, KIBANA_ROOT
from src.profile import finops_profile


def _ensure_ess_billing_package(*, fail_loud: bool = False) -> bool:
    """Install the Elastic (ESS) Billing Fleet integration if missing."""
    print("== Elastic Billing integration (ess_billing) ==")
    r = requests.get(
        f"{KIBANA_ROOT}/api/fleet/epm/packages/ess_billing",
        headers=KBN_HEADERS,
        timeout=60,
    )
    if r.status_code >= 300:
        msg = f"ess_billing package lookup: {r.status_code} {r.text[:300]}"
        if fail_loud:
            raise SystemExit(f"  [fail] {msg}")
        print(f"  [warn] {msg}")
        return False
    item = r.json().get("item") or {}
    if item.get("status") == "installed":
        print(f"  [ok] package ess_billing {item.get('version')} already installed")
        return True
    print("  installing package ess_billing ...")
    r = requests.post(
        f"{KIBANA_ROOT}/api/fleet/epm/packages/ess_billing",
        headers=KBN_HEADERS,
        json={},
        timeout=600,
    )
    if r.status_code >= 300:
        msg = f"ess_billing install: {r.status_code} {r.text[:300]}"
        if fail_loud:
            raise SystemExit(f"  [fail] {msg}")
        print(f"  [warn] {msg}")
        return False
    print("  [ok] package ess_billing installed")
    return True


def run(fail_loud: bool = False) -> None:
    print(f"== profile: {finops_profile()} (objects only, no synthetic data) ==")
    print("== checking Elasticsearch ==")
    r = requests.get(ELASTIC_URL, headers=ES_HEADERS, timeout=30)
    r.raise_for_status()
    info = r.json()
    print(f"  [ok] {info['version']['number']} ({info['version']['build_flavor']})")

    from src.spaces import ensure_space
    ensure_space(fail_loud=fail_loud)

    from src.setup_cmd import (
        ensure_packages,
        patch_inference_token_usage_dashboard,
        patch_tsds_templates,
        pin_ess_billing_dashboards,
    )
    print("== Fleet packages + TSDS patch (usage-vs-cost streams) ==")
    ensure_packages()
    _ensure_ess_billing_package(fail_loud=fail_loud)
    patch_tsds_templates()
    from src.ess_billing_health import ensure_ess_billing_field_health
    ensure_ess_billing_field_health(fail_loud=fail_loud)
    pin_ess_billing_dashboards()
    from src.generators.aws_ec2_metrics import ensure_cpu_restore_pipeline
    ensure_cpu_restore_pipeline()

    print("== GenAI Settings: token usage tracking ==")
    from src.genai_settings import ensure_genai_token_usage_tracking
    ensure_genai_token_usage_tracking(fail_loud=fail_loud)
    print("== OOTB Inference Token Usage dashboard (data view + time range) ==")
    patch_inference_token_usage_dashboard()

    from src.rightsizing import ensure_rightsizing
    ensure_rightsizing(fail_loud=fail_loud, force_seed=True)

    from src.workflows import ensure_workflows
    ensure_workflows(fail_loud=fail_loud)

    print("== FinOps spend SLOs + budget alerts ==")
    from src.budgets import ensure_budgets
    ensure_budgets(fail_loud=fail_loud)

    print("== Verdian Dynamics FinOps AI Assistant ==")
    from src.agent_builder import ensure_agent
    ensure_agent(fail_loud=fail_loud)

    from src.live_dashboards import publish
    publish()
    print("live setup complete.")


def verify() -> bool:
    print(f"== profile: {finops_profile()} verify ==")
    ok = True

    print("== Elastic Billing integration ==")
    r = requests.get(
        f"{KIBANA_ROOT}/api/fleet/epm/packages/ess_billing",
        headers=KBN_HEADERS,
        timeout=60,
    )
    if r.status_code == 200 and (r.json().get("item") or {}).get("status") == "installed":
        ver = (r.json().get("item") or {}).get("version")
        print(f"  [ok] package ess_billing {ver} installed")
    else:
        print(f"  [fail] ess_billing not installed ({r.status_code})")
        ok = False
    from src.ess_billing_health import ensure_ess_billing_field_health
    ok = ensure_ess_billing_field_health(fail_loud=False) and ok

    print("== GenAI token usage tracking ==")
    from src.genai_settings import _read_token_usage_enabled
    enabled = _read_token_usage_enabled()
    if enabled is True:
        print("  [ok] genAiSettings:tokenUsageTracking enabled")
    else:
        print(f"  [fail] genAiSettings:tokenUsageTracking not enabled ({enabled!r})")
        ok = False

    from src.rightsizing import verify_rightsizing
    ok = verify_rightsizing() and ok
    from src.workflows import verify_workflows
    ok = verify_workflows() and ok
    from src.budgets import verify_budgets
    ok = verify_budgets() and ok
    from src.agent_builder import verify_agent
    ok = verify_agent() and ok
    from src.live_dashboards import verify_dashboards
    ok = verify_dashboards() and ok
    return ok
