"""Object-only provision for the live Verdian Dynamics FinOps profile."""
from __future__ import annotations

import requests

from src.config import ELASTIC_URL, ES_HEADERS
from src.profile import finops_profile


def run(fail_loud: bool = False) -> None:
    print(f"== profile: {finops_profile()} (objects only, no synthetic data) ==")
    print("== checking Elasticsearch ==")
    r = requests.get(ELASTIC_URL, headers=ES_HEADERS, timeout=30)
    r.raise_for_status()
    info = r.json()
    print(f"  [ok] {info['version']['number']} ({info['version']['build_flavor']})")

    from src.spaces import ensure_space
    ensure_space(fail_loud=fail_loud)

    from src.setup_cmd import ensure_packages, patch_tsds_templates
    print("== Fleet packages + TSDS patch (usage-vs-cost streams) ==")
    ensure_packages()
    patch_tsds_templates()
    from src.generators.aws_ec2_metrics import ensure_cpu_restore_pipeline
    ensure_cpu_restore_pipeline()

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
