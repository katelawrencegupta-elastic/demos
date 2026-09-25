"""Variant-scoped Meridian smoke checks driven by config/variants.yaml.

Usage (via CLI):
  .venv/bin/python -m src.cli smoke --variant aws
  .venv/bin/python -m src.cli smoke --all-variants
  .venv/bin/python -m src.cli smoke --all-variants --json-out /tmp/matrix.json
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

import requests

from src.config import KBN_HEADERS, KIBANA_ROOT, KIBANA_URL, ELASTIC_URL
from src.live_smoke import (
    CheckResult,
    SmokeReport,
    _check,
    _kbn_get,
    check_dashboard,
    check_es_connectivity,
    check_kibana_connectivity,
    check_stream_docs,
)
from src.variant import Variant, get_variant, list_variant_ids


_MERIDIAN_DASH_BASES = {
    "baseline": "meridian-finops-llm-observability",
    "classic": "meridian-finops-llm-observability-classic",
    "dynamic": "meridian-finops-llm-observability-dynamic",
    "ai": "meridian-ai-assistant-inference-usage",
}


def _dash_id(which: str, variant: Variant) -> str:
    return _MERIDIAN_DASH_BASES[which] + variant.dash_suffix()


def _generator_streams(variant: Variant) -> list[tuple[str, str]]:
    """Unique (generator_name, data_stream) pairs for the variant."""
    from src.generators import NAMED

    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    names = sorted(variant.generator_names)
    for name in names:
        mod = NAMED.get(name)
        if mod is None:
            continue
        ds = getattr(mod, "DATA_STREAM", None)
        if not ds or ds in seen:
            continue
        seen.add(ds)
        out.append((name, ds))
    return out


def check_fleet_package(pkg: str) -> tuple[bool, str]:
    r = requests.get(
        f"{KIBANA_ROOT}/api/fleet/epm/packages/{pkg}",
        headers=KBN_HEADERS,
        timeout=60,
    )
    if r.status_code == 404:
        return False, "not installed"
    if r.status_code != 200:
        return False, f"GET {r.status_code}"
    body = r.json()
    item = body.get("item") or body.get("response") or body
    status = str(item.get("status") or item.get("installationStatus") or "?")
    ver = item.get("version") or item.get("installed_version") or "?"
    if status.lower() in ("installed", "install_failed"):
        if status.lower() == "install_failed":
            return False, f"{status} v{ver}"
        return True, f"v{ver} ({status})"
    # Serverless / managed projects often ship APM without a Fleet install.
    if pkg == "apm" and status.lower() == "not_installed":
        ok, detail = check_stream_docs("traces-apm-*", 1)
        if ok:
            return True, f"v{ver} (not_installed; {detail})"
        return False, f"{status} v{ver}; no APM traces"
    if status.lower() == "not_installed":
        return False, f"{status} v{ver}"
    return True, f"v{ver} ({status})"


def check_ootb_dashboard(label: str, saved_id: str) -> tuple[bool, str]:
    """OOTB Fleet dashboards live in the default space; hub copies may be remapped."""
    for base, tag in ((KIBANA_URL, "space"), (KIBANA_ROOT, "default")):
        r = requests.get(
            f"{base}/api/dashboards/{saved_id}",
            headers=KBN_HEADERS,
            timeout=60,
        )
        if r.status_code == 200:
            title = (r.json().get("data") or {}).get("title") or label
            return True, f"{title} [{tag}]"
    # APM overview id drifts across versions; accept traces as evidence.
    if "APM" in label.upper():
        ok, detail = check_stream_docs("traces-apm-*", 1)
        if ok:
            return True, f"id missing; {detail}"
    return False, f"missing id={saved_id} (space+default)"


def check_meridian_dashboard(which: str, variant: Variant) -> tuple[bool, str]:
    """Resolve Meridian layout id for a variant; tolerate live hub aliases."""
    from src.profile import is_live

    candidates = [_dash_id(which, variant)]
    base = _MERIDIAN_DASH_BASES[which]
    if not variant.is_all and base not in candidates:
        candidates.append(base)
    # Live Verdian AWS hub uses the dynamic-aws id primarily.
    if is_live() and variant.id == "aws" and which == "dynamic":
        live_id = "meridian-finops-llm-observability-dynamic-aws"
        if live_id not in candidates:
            candidates.insert(0, live_id)
    if is_live() and variant.id == "aws" and which in ("baseline", "classic"):
        # Live FinOps publishes a focused hub set rather than full Meridian layouts.
        return True, f"skipped on live (layout={which}; hub uses dynamic-aws)"
    if is_live() and which == "ai":
        # Live ships the Elastic inference usage dashboard (not variant-suffixed).
        for extra in ("kibana-inference-token-usage", "meridian-ai-assistant-inference-usage"):
            if extra not in candidates:
                candidates.append(extra)

    tried = []
    for did in candidates:
        # Inference usage is published in the default space on live.
        if did.startswith("kibana-"):
            for base_url, tag in ((KIBANA_URL, "space"), (KIBANA_ROOT, "default")):
                r = requests.get(
                    f"{base_url}/api/dashboards/{did}",
                    headers=KBN_HEADERS,
                    timeout=60,
                )
                if r.status_code == 200:
                    title = (r.json().get("data") or {}).get("title") or did
                    return True, f"{title} ({did} [{tag}])"
                tried.append(f"{did}@{tag}:{r.status_code}")
            continue
        ok, detail = check_dashboard(did)
        if ok:
            return True, f"{detail} ({did})"
        tried.append(f"{did}:{detail}")
    return False, "; ".join(tried)


def check_variant_agent(variant: Variant) -> tuple[bool, str]:
    if not variant.setup_enabled("agent"):
        return True, "skipped (setup.agent=false)"
    from src.agent_builder import AGENTS_API, _kbn, agent_id

    aid = agent_id()
    r = _kbn("GET", f"{AGENTS_API}/{aid}")
    if r.status_code != 200:
        return False, f"agent {aid}: {r.status_code}"
    return True, f"agent {aid}"


def check_variant_budgets(variant: Variant) -> tuple[bool, str]:
    if not variant.setup_enabled("budgets"):
        return True, "skipped (setup.budgets=false)"
    from src.budgets import load_budgets

    cfg = load_budgets()
    slos = cfg.get("slos") or []
    if not slos:
        return False, "no SLOs in budgets config"
    missing = []
    for spec in slos:
        r = _kbn_get(f"/api/observability/slos/{spec['id']}")
        if r.status_code != 200:
            missing.append(spec["id"])
    if missing:
        return False, f"missing SLOs {missing[:5]}"
    return True, f"{len(slos)} SLOs present"


def check_apm_genai_fields(variant: Variant) -> tuple[bool, str]:
    if not variant.has_generator("llm_apm"):
        return True, "skipped (no llm_apm)"
    from src.config import ES_HEADERS

    need = ("span.subtype", "gen_ai.usage.total_tokens", "labels.llm_cost_usd")
    r = requests.post(
        f"{ELASTIC_URL}/traces-apm-default/_field_caps",
        headers=ES_HEADERS,
        timeout=60,
        json={"fields": list(need)},
    )
    if r.status_code >= 300:
        return False, f"field_caps {r.status_code}"
    fields = r.json().get("fields") or {}
    missing = [f for f in need if f not in fields]
    if missing:
        return False, f"missing {missing}"
    return True, "gen_ai columns present"


def run_variant_smoke(variant_id: str, *, fix: bool = False) -> SmokeReport:
    """Smoke-test one workshop variant against the configured cluster."""
    from src.dashboards import OOTB
    from src.profile import finops_profile

    variant = get_variant(variant_id)
    report = SmokeReport(
        started_at=datetime.now(timezone.utc).isoformat(),
        profile=finops_profile(),
        suite=f"variant:{variant.id}",
        variant=variant.id,
        kibana=KIBANA_URL,
        elastic=ELASTIC_URL.split("@")[-1] if "@" in ELASTIC_URL else ELASTIC_URL,
    )
    results: list[CheckResult] = []

    _check(results, "es", "Elasticsearch connectivity", check_es_connectivity, do_fix=False)
    _check(results, "kibana", "Kibana connectivity", check_kibana_connectivity, do_fix=False)

    # Registry sanity: every declared generator exists
    from src.generators import NAMED

    unknown = sorted(n for n in variant.generator_names if n not in NAMED)
    _check(
        results,
        "registry",
        f"Variant {variant.id} generator registry",
        lambda: (
            (False, f"unknown generators {unknown}")
            if unknown
            else (True, f"{len(variant.generator_names)} generators")
        ),
        do_fix=False,
    )

    for pkg in variant.packages:
        _check(
            results,
            f"pkg_{pkg}",
            f"Fleet package {pkg}",
            lambda p=pkg: check_fleet_package(p),
            do_fix=False,
        )

    for gen_name, stream in _generator_streams(variant):
        _check(
            results,
            f"ds_{gen_name}",
            f"Data: {stream}",
            lambda s=stream: check_stream_docs(s, 1),
            do_fix=False,
        )

    for which, enabled in (variant.dashboards or {}).items():
        if not enabled:
            continue
        if which not in _MERIDIAN_DASH_BASES:
            continue
        _check(
            results,
            f"dash_{which}",
            f"Meridian dashboard {which}",
            lambda w=which, v=variant: check_meridian_dashboard(w, v),
            do_fix=False,
        )

    for label in sorted(variant.ootb_link_labels):
        saved = OOTB.get(label)
        if not saved:
            _check(
                results,
                f"ootb_{label[:24]}",
                f"OOTB {label}",
                lambda: (False, "no id mapping in dashboards.OOTB"),
                do_fix=False,
            )
            continue
        _check(
            results,
            f"ootb_{saved}",
            f"OOTB {label}",
            lambda lab=label, sid=saved: check_ootb_dashboard(lab, sid),
            do_fix=False,
        )

    _check(
        results,
        "apm_fields",
        "APM gen_ai field caps",
        lambda: check_apm_genai_fields(variant),
        do_fix=False,
    )
    _check(
        results,
        "budgets",
        "Spend budgets / SLOs",
        lambda: check_variant_budgets(variant),
        do_fix=False,
    )
    _check(
        results,
        "agent",
        "FinOps AI Assistant",
        lambda: check_variant_agent(variant),
        do_fix=False,
    )

    report.checks = results
    report.passed = sum(1 for c in results if c.ok)
    report.failed = sum(1 for c in results if not c.ok)
    report.fixed = sum(1 for c in results if c.fixed)
    report.finished_at = datetime.now(timezone.utc).isoformat()
    return report


def run_all_variants_smoke(
    *,
    variant_ids: Iterable[str] | None = None,
    include_live: bool = False,
    fix: bool = False,
    deep: bool = False,
) -> list[SmokeReport]:
    """Run smoke for each workshop variant; optionally prepend live FinOps suite."""
    reports: list[SmokeReport] = []
    if include_live:
        from src.live_smoke import run_smoke

        reports.append(run_smoke(fix=fix, deep=deep))
    ids = list(variant_ids) if variant_ids is not None else list_variant_ids()
    for vid in ids:
        reports.append(run_variant_smoke(vid, fix=fix))
    return reports


def print_matrix(reports: list[SmokeReport]) -> None:
    from src.live_smoke import print_report

    print()
    print("=" * 72)
    print("VARIANT SMOKE MATRIX")
    print("=" * 72)
    for r in reports:
        label = r.variant or r.suite
        status = "SUCCESS" if r.ok else "FAILURE"
        print(
            f"  {label:24}  {status:7}  "
            f"passed={r.passed:3} failed={r.failed:3} total={len(r.checks)}"
        )
    print("-" * 72)
    overall = all(r.ok for r in reports)
    print(f"OVERALL: {'SUCCESS' if overall else 'FAILURE'}  suites={len(reports)}")
    print("=" * 72)
    # Full detail only for failures (keeps matrix runs readable)
    for r in reports:
        if not r.ok:
            print_report(r)
    if overall:
        print("\n(all suites passed — skip per-check detail; re-run --variant X for detail)")


def matrix_ok(reports: list[SmokeReport]) -> bool:
    return all(r.ok for r in reports)


def write_matrix_json(reports: list[SmokeReport], path: str) -> None:
    import json
    from dataclasses import asdict

    payload = {
        "ok": matrix_ok(reports),
        "suites": len(reports),
        "reports": [asdict(r) for r in reports],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    print(f"wrote {path}")
