"""Object-only provision for the live ELK Co FinOps profile.

AWS live hub: Cost Explorer dashboards + rightsizing + workflows.
GCP / Azure live hubs: billing SLOs + agent + variant FinOps dashboards
(no rightsizing / workflows).
"""
from __future__ import annotations

import requests

from src.config import ELASTIC_URL, ES_HEADERS, KBN_HEADERS, KIBANA_ROOT
from src.profile import finops_profile, live_hub_caps, uses_live_aws_hub


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


def _run_aws_hub(*, fail_loud: bool) -> None:
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

    print("== ELK Co FinOps AI Assistant ==")
    from src.agent_builder import ensure_agent
    ensure_agent(fail_loud=fail_loud)

    from src.live_dashboards import publish
    publish()


def _run_billing_hub(*, fail_loud: bool) -> None:
    """GCP / Azure live billing hub — packages, budgets, agent, FinOps dashboards."""
    from src.setup_cmd import ensure_packages, patch_inference_token_usage_dashboard
    from src.variant import active_variant

    v = active_variant()
    print(f"== live billing hub ({v.id}) — no Cost Explorer / rightsizing / workflows ==")
    print("== Fleet packages ==")
    ensure_packages()
    _ensure_ess_billing_package(fail_loud=False)

    if v.setup_enabled("inference"):
        print("== GenAI Settings: token usage tracking ==")
        from src.genai_settings import ensure_genai_token_usage_tracking
        ensure_genai_token_usage_tracking(fail_loud=fail_loud)
        patch_inference_token_usage_dashboard()

    if v.setup_enabled("apm"):
        print("== APM gen_ai mappings + retention ==")
        from src.generators.llm_apm import ensure_apm_genai_mappings
        ensure_apm_genai_mappings(fail_loud=fail_loud)

    print("== FinOps spend SLOs + budget alerts ==")
    from src.budgets import ensure_budgets
    ensure_budgets(fail_loud=fail_loud)

    print("== ELK Co FinOps AI Assistant ==")
    from src.agent_builder import ensure_agent
    ensure_agent(fail_loud=fail_loud)

    print("== Variant FinOps dashboards (billing hub) ==")
    from src.dashboards import publish as dash_publish
    dash_publish(
        include_baseline=v.dashboards.get("baseline", True),
        include_classic=False,
        include_dynamic_alias=v.dashboards.get("dynamic", True),
        include_ai=v.dashboards.get("ai", True),
    )


def run(fail_loud: bool = False) -> None:
    caps = live_hub_caps()
    print(f"== profile: {finops_profile()} (objects only, no synthetic data) ==")
    if caps is None:
        raise SystemExit(
            "  [fail] live profile requires variant aws|gcp|azure "
            "(set FINOPS_VARIANT / DEPLOY_*_VARIANT)"
        )
    print(f"== live hub: {caps.cloud} "
          f"(ce={caps.cost_explorer} rs={caps.rightsizing} wf={caps.workflows}) ==")

    print("== checking Elasticsearch ==")
    r = requests.get(ELASTIC_URL, headers=ES_HEADERS, timeout=30)
    r.raise_for_status()
    info = r.json()
    print(f"  [ok] {info['version']['number']} ({info['version']['build_flavor']})")

    from src.spaces import ensure_space
    ensure_space(fail_loud=fail_loud)

    if uses_live_aws_hub():
        _run_aws_hub(fail_loud=fail_loud)
    else:
        _run_billing_hub(fail_loud=fail_loud)
    print("live setup complete.")


def verify() -> bool:
    caps = live_hub_caps()
    print(f"== profile: {finops_profile()} verify ==")
    if caps is None:
        print("  [fail] live hub not active (need variant aws|gcp|azure)")
        return False
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
        print(f"  [warn] ess_billing not installed ({r.status_code}) — optional for billing hub")

    if uses_live_aws_hub():
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
        from src.live_dashboards import verify_dashboards
        ok = verify_dashboards() and ok
    else:
        print(f"== billing hub ({caps.cloud}): skip rightsizing / workflows / CE dashboards ==")
        from src.variant import active_variant
        from src.variant_smoke import check_finops_dashboard
        v = active_variant()
        for which, flag in (("baseline", "baseline"), ("dynamic", "dynamic")):
            if not v.dashboards.get(flag):
                continue
            d_ok, d_msg = check_finops_dashboard(which, v)
            print(f"  [{'ok' if d_ok else 'fail'}] dashboard {which}: {d_msg}")
            ok = d_ok and ok

    from src.budgets import verify_budgets
    ok = verify_budgets() and ok
    from src.agent_builder import verify_agent
    ok = verify_agent() and ok
    return ok
