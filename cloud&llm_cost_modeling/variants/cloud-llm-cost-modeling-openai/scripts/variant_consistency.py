#!/usr/bin/env python3
"""Cross-variant consistency: packages, always-merge, budgets/SLOs.

Static config matrix for every workshop variant, plus live checks against
each named Elastic Cloud deployment (aws / azure / gcp).

Usage:
  .venv/bin/python scripts/variant_consistency.py
  .venv/bin/python scripts/variant_consistency.py --fix
  .venv/bin/python scripts/variant_consistency.py --json-out /tmp/consistency.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import requests
import yaml

from src.budgets import budgets_config_path
from src.config import (
    ELASTIC_URL,
    ES_HEADERS,
    KBN_HEADERS,
    KIBANA_ROOT,
    KIBANA_URL,
    apply_deployment,
    list_deployments,
)
from src.generators import NAMED
from src.setup_cmd import MANAGED_PACKAGES, _package_status
from src.variant import get_variant, list_variant_ids

# Index / field markers that imply a cloud/integration family.
_CLOUD_MARKERS = {
    "aws": (
        "metrics-aws",
        "aws_billing",
        "logs-aws",
        "aws.bedrock",
        "aws_bedrock",
    ),
    "gcp": (
        "metrics-gcp",
        "gcp.billing",
        "gcp_vertexai",
        "logs-gcp",
    ),
    "azure": (
        "metrics-azure",
        "azure.billing",
        "azure_openai",
        "logs-azure",
    ),
}

# Single-cloud variants must not reference other clouds' SLO indices.
# LLM packs (openai/elastic-ai) use scoped LLM budgets — no CUR.
# bedrock → aws and anthropic → gcp (see VARIANT_ALIASES).
_VARIANT_CLOUD = {
    "aws": "aws",
    "gcp": "gcp",
    "azure": "azure",
    "openai": None,
    "elastic-ai": None,
    "all": None,
}

_LLM_BUDGET_VARIANTS = frozenset({"openai", "elastic-ai"})
_CUR_INDEX_MARKERS = (
    "metrics-aws_billing",
    "aws_billing.cur",
    "metrics-gcp.billing",
    "metrics-azure.billing",
)

_ALWAYS_PACKAGES = ("ess_billing",)
_ALWAYS_SETUP = ("inference", "ess_billing")
_ALWAYS_DASH = ("ai",)
_ALWAYS_GENS = (
    "agent_builder_traces",
    "inference_token_usage",
    "ess_billing",
    "ess_billing_credits",
)


@dataclass
class Finding:
    ok: bool
    scope: str
    check: str
    detail: str


@dataclass
class Report:
    ok: bool = True
    findings: list[Finding] = field(default_factory=list)

    def add(self, ok: bool, scope: str, check: str, detail: str) -> None:
        self.findings.append(Finding(ok, scope, check, detail))
        if not ok:
            self.ok = False


def _load_budgets_file(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _index_cloud(index: str) -> str | None:
    idx = index or ""
    for cloud, markers in _CLOUD_MARKERS.items():
        if any(m in idx for m in markers):
            return cloud
    return None


def check_static_variant(report: Report, vid: str) -> None:
    v = get_variant(vid)
    scope = f"config:{vid}"

    # always merge
    for pkg in _ALWAYS_PACKAGES:
        ok = pkg in v.packages
        report.add(ok, scope, "always.package", f"{pkg}{' present' if ok else ' MISSING'}")
    for key in _ALWAYS_SETUP:
        ok = v.setup_enabled(key)
        report.add(ok, scope, "always.setup", f"{key}={'on' if ok else 'OFF'}")
    for key in _ALWAYS_DASH:
        ok = bool(v.dashboards.get(key))
        report.add(ok, scope, "always.dashboard", f"{key}={'on' if ok else 'OFF'}")
    if not v.is_all:
        missing_gens = [g for g in _ALWAYS_GENS if g not in v.generator_names]
        report.add(
            not missing_gens,
            scope,
            "always.generators",
            "ok" if not missing_gens else f"missing {missing_gens}",
        )

    # packages ↔ known registry + generators exist
    unknown = sorted(n for n in v.generator_names if n not in NAMED)
    report.add(
        not unknown,
        scope,
        "generators.registry",
        f"{len(v.generator_names)} gens" if not unknown else f"unknown {unknown}",
    )
    for pkg in v.packages:
        if pkg not in MANAGED_PACKAGES and pkg != "ess_billing":
            # still allowed (future packs) — warn as soft fail? treat as info ok
            report.add(True, scope, f"package.{pkg}", "declared (not in MANAGED_PACKAGES)")

    # budgets file + SLO index alignment
    for profile in ("synthetic", "live"):
        if profile == "live" and vid not in ("aws", "gcp", "azure"):
            continue
        path = budgets_config_path(variant_id=vid, profile=profile)
        exists = path.is_file()
        report.add(
            exists,
            scope,
            f"budgets.file[{profile}]",
            str(path.relative_to(ROOT)) if exists else f"MISSING {path}",
        )
        if not exists:
            continue
        cfg = _load_budgets_file(path)
        slos = cfg.get("slos") or []
        alerts = cfg.get("alerts") or []
        nums = cfg.get("budgets") or {}
        report.add(
            bool(slos),
            scope,
            f"budgets.slos[{profile}]",
            f"{len(slos)} SLOs" if slos else "no SLOs",
        )
        # ceiling keys resolve
        bad_ceil = [
            s["id"] for s in slos
            if s.get("ceiling_key") not in nums
        ]
        report.add(
            not bad_ceil,
            scope,
            f"budgets.ceiling_keys[{profile}]",
            "ok" if not bad_ceil else f"missing numbers for {bad_ceil}",
        )
        cloud = _VARIANT_CLOUD.get(vid)
        if cloud:
            foreign = []
            for s in slos:
                idx = s.get("index") or ""
                ic = _index_cloud(idx)
                if ic and ic != cloud:
                    # shared APM / inference are ok
                    if any(x in idx for x in ("traces-apm", "inference_token_usage", "ess_billing")):
                        continue
                    foreign.append(f"{s['id']}→{idx}")
            report.add(
                not foreign,
                scope,
                f"budgets.slo_cloud[{profile}]",
                "ok" if not foreign else f"foreign indices {foreign}",
            )
            # single-cloud must include that cloud's billing SLO when budgets enabled
            if v.setup_enabled("budgets") and profile == "synthetic":
                has_cloud_slo = any(
                    _index_cloud(s.get("index") or "") == cloud for s in slos
                )
                report.add(
                    has_cloud_slo,
                    scope,
                    f"budgets.native_slo[{profile}]",
                    f"has {cloud} billing SLO" if has_cloud_slo else f"no {cloud} billing SLO",
                )
        # shared always SLOs for workshop clouds
        if vid in ("azure", "gcp") and profile == "synthetic":
            ids = {s["id"] for s in slos}
            for need in ("elk-slo-llm-checkout-spend", "elk-slo-inference-daily-tokens"):
                report.add(
                    need in ids,
                    scope,
                    f"budgets.shared_slo[{profile}]",
                    f"{need} {'present' if need in ids else 'MISSING'}",
                )

        # LLM packs: no CUR / cloud-billing indices; require checkout + inference SLOs
        if vid in _LLM_BUDGET_VARIANTS and profile == "synthetic":
            ids = {s["id"] for s in slos}
            cur_hits = [
                f"{s['id']}→{s.get('index')}"
                for s in slos
                if any(m in (s.get("index") or "") for m in _CUR_INDEX_MARKERS)
            ]
            report.add(
                not cur_hits,
                scope,
                f"budgets.no_cur[{profile}]",
                "ok" if not cur_hits else f"CUR/cloud billing SLOs {cur_hits}",
            )
            for need in ("elk-slo-llm-checkout-spend", "elk-slo-inference-daily-tokens"):
                report.add(
                    need in ids,
                    scope,
                    f"budgets.llm_slo[{profile}]",
                    f"{need} {'present' if need in ids else 'MISSING'}",
                )

        if vid == "aws":
            # Bedrock is part of the AWS pack — budgets must carry the Bedrock SLO.
            slo_ids = {s["id"] for s in slos if s.get("id")}
            report.add(
                "elk-slo-bedrock-daily-spend" in slo_ids,
                scope,
                f"budgets.bedrock_slo[{profile}]",
                "elk-slo-bedrock-daily-spend present"
                if "elk-slo-bedrock-daily-spend" in slo_ids
                else "MISSING elk-slo-bedrock-daily-spend",
            )

        # alerts need kind or esql
        bad_alerts = [
            a.get("id") for a in alerts
            if not a.get("esql") and not a.get("kind") and a.get("id")
        ]
        # some alerts use kind via helper — kind required if no esql
        missing_kind = [
            a.get("id") for a in alerts
            if not (a.get("esql") or a.get("kind") or a.get("message") and "esql" in a)
            and not a.get("esql") and not a.get("kind")
        ]
        report.add(
            not missing_kind,
            scope,
            f"budgets.alerts[{profile}]",
            f"{len(alerts)} alerts" if not missing_kind else f"alerts missing kind/esql: {missing_kind}",
        )

    if vid == "aws":
        for need in ("bedrock_invocation", "bedrock_runtime", "bedrock_guardrails"):
            report.add(
                v.has_generator(need),
                scope,
                "generators.bedrock",
                f"{need} {'present' if v.has_generator(need) else 'MISSING'}",
            )
        report.add(
            v.setup_enabled("bedrock"),
            scope,
            "setup.bedrock",
            "on" if v.setup_enabled("bedrock") else "OFF",
        )
        report.add(
            any("Bedrock" in L for L in v.ootb_link_labels),
            scope,
            "ootb.bedrock",
            "bedrock ootb group present"
            if any("Bedrock" in L for L in v.ootb_link_labels)
            else "MISSING bedrock ootb labels",
        )

    # dashboard alias rule — synthetic variants must not enable both
    if v.dashboards.get("baseline") and v.dashboards.get("dynamic"):
        report.add(
            False,
            scope,
            "dashboards.dynamic_alias",
            "baseline+dynamic both true (publish skips -dynamic; set dynamic: false)",
        )
    else:
        report.add(
            True,
            scope,
            "dashboards.dynamic_alias",
            "ok",
        )


def check_live_deployment(report: Report, dep: str, *, fix: bool = False) -> None:
    apply_deployment(dep)
    # refresh module-level connection globals after deployment switch
    import importlib

    import src.config as cfg
    importlib.reload(cfg)
    import src.setup_cmd as setup_cmd
    importlib.reload(setup_cmd)
    from src.config import ELASTIC_URL as EU, ES_HEADERS as EH, KBN_HEADERS as KH
    from src.config import KIBANA_URL as KU
    from src.profile import finops_profile
    from src.setup_cmd import MANAGED_PACKAGES, _package_status, reconcile_packages
    from src.variant import active_variant
    # clear cached active_variant after FINOPS_VARIANT change
    from src import variant as variant_mod
    variant_mod.active_variant.cache_clear()

    v = active_variant()
    profile = finops_profile()
    scope = f"live:{dep}[{v.id}/{profile}]"

    # connectivity
    try:
        r = requests.get(f"{EU}/", headers=EH, timeout=30)
        report.add(r.status_code == 200, scope, "elasticsearch", f"{r.status_code}")
    except Exception as e:
        report.add(False, scope, "elasticsearch", str(e)[:200])
        return

    # packages wanted
    for pkg in v.packages:
        st, ver = _package_status(pkg)
        ok = st == "installed" or (pkg == "apm" and st == "not_installed")
        report.add(ok, scope, f"package.{pkg}", f"{st} {ver or ''}".strip())

    # foreign managed packs
    if not v.is_all:
        extras = []
        for pkg in MANAGED_PACKAGES:
            if pkg in v.packages:
                continue
            st, ver = _package_status(pkg)
            if st == "installed":
                extras.append(f"{pkg}@{ver}" if ver else pkg)
        if extras and fix:
            reconcile_packages()
            extras = []
            for pkg in MANAGED_PACKAGES:
                if pkg in v.packages:
                    continue
                st, ver = _package_status(pkg)
                if st == "installed":
                    extras.append(pkg)
        report.add(
            not extras,
            scope,
            "packages.scope",
            "match" if not extras else f"foreign still installed: {', '.join(extras)}",
        )

    # budgets / SLOs on cluster
    path = budgets_config_path(variant_id=v.id, profile=profile)
    cfg = _load_budgets_file(path)
    wanted = {s["id"] for s in (cfg.get("slos") or [])}
    r = requests.get(
        f"{KU}/api/observability/slos",
        headers=KH,
        params={"perPage": 100},
        timeout=60,
    )
    if r.status_code != 200:
        report.add(False, scope, "slos.list", f"GET {r.status_code}")
        return
    present = {}
    for s in r.json().get("results") or []:
        sid = s.get("id") or ""
        present[sid] = (s.get("summary") or {}).get("status")

    missing = sorted(wanted - set(present))
    if missing and fix:
        from src.budgets import ensure_budgets
        ensure_budgets(fail_loud=False)
        r = requests.get(
            f"{KU}/api/observability/slos",
            headers=KH,
            params={"perPage": 100},
            timeout=60,
        )
        present = {
            s.get("id"): (s.get("summary") or {}).get("status")
            for s in (r.json().get("results") or [])
            if s.get("id")
        }
        missing = sorted(wanted - set(present))
    report.add(
        not missing,
        scope,
        "slos.present",
        f"{len(wanted)} expected" if not missing else f"missing {missing}",
    )

    # orphan elk SLOs not in wanted (wrong cloud leftovers)
    orphans = sorted(
        sid for sid in present
        if sid.startswith("elk-") and sid not in wanted
    )
    if orphans and fix:
        for sid in orphans:
            requests.delete(f"{KU}/api/observability/slos/{sid}", headers=KH, timeout=60)
        r = requests.get(
            f"{KU}/api/observability/slos",
            headers=KH,
            params={"perPage": 100},
            timeout=60,
        )
        present = {
            s.get("id"): (s.get("summary") or {}).get("status")
            for s in (r.json().get("results") or [])
            if s.get("id")
        }
        orphans = sorted(
            sid for sid in present
            if sid.startswith("elk-") and sid not in wanted
        )
    report.add(
        not orphans,
        scope,
        "slos.orphans",
        "none" if not orphans else f"orphan {orphans}",
    )

    # expected SLOs should not all be NO_DATA
    nodata = [sid for sid in wanted if present.get(sid) in (None, "NO_DATA")]
    healthyish = [sid for sid in wanted if present.get(sid) not in (None, "NO_DATA")]
    report.add(
        bool(healthyish) or not wanted,
        scope,
        "slos.sli_data",
        f"{len(healthyish)}/{len(wanted)} with SLI"
        + (f"; still NO_DATA: {nodata}" if nodata else ""),
    )

    # posture index has non-NO_DATA elk rows when we expect SLOs
    if wanted:
        q = (
            "FROM .slo-observability.summary-v3.6\n"
            '| WHERE slo.id LIKE "elk-*" AND status != "NO_DATA"\n'
            "| KEEP slo.id, status\n| LIMIT 20"
        )
        rr = requests.post(
            f"{EU}/_query",
            headers={**EH, "Content-Type": "application/json"},
            json={"query": q},
            timeout=60,
        )
        rows = (rr.json().get("values") if rr.status_code == 200 else None) or []
        report.add(
            len(rows) > 0,
            scope,
            "slos.posture_table",
            f"{len(rows)} summary rows" if rows else "empty posture summary index",
        )


def main() -> int:
    p = argparse.ArgumentParser(description="Variant consistency: packages / budgets / SLOs")
    p.add_argument("--fix", action="store_true", help="remove foreign packages / orphan SLOs")
    p.add_argument("--json-out", default=None)
    p.add_argument(
        "--deployments",
        default="aws,azure,gcp",
        help="comma list of DEPLOY_* targets to live-check (default: aws,azure,gcp)",
    )
    p.add_argument("--skip-live", action="store_true")
    args = p.parse_args()

    report = Report()
    print("=" * 72)
    print("VARIANT CONSISTENCY — static config")
    print("=" * 72)
    for vid in list_variant_ids():
        check_static_variant(report, vid)

    # print static summary per variant
    by_scope: dict[str, list[Finding]] = {}
    for f in report.findings:
        by_scope.setdefault(f.scope, []).append(f)
    for scope in sorted(by_scope):
        if not scope.startswith("config:"):
            continue
        fails = [x for x in by_scope[scope] if not x.ok]
        status = "OK" if not fails else f"FAIL:{len(fails)}"
        print(f"  {scope[7:]:16}  {status}")
        for x in fails:
            print(f"    - {x.check}: {x.detail}")

    if not args.skip_live:
        print()
        print("=" * 72)
        print("VARIANT CONSISTENCY — live deployments")
        print("=" * 72)
        known = set(list_deployments())
        for dep in [d.strip() for d in args.deployments.split(",") if d.strip()]:
            if dep not in known and f"DEPLOY_{dep.upper()}_ELASTIC_URL" not in os.environ:
                report.add(False, f"live:{dep}", "deployment", "unknown DEPLOY_* target")
                print(f"  {dep:16}  FAIL: unknown deployment")
                continue
            before = len(report.findings)
            check_live_deployment(report, dep, fix=args.fix)
            chunk = report.findings[before:]
            fails = [x for x in chunk if not x.ok]
            status = "OK" if not fails else f"FAIL:{len(fails)}"
            print(f"  {dep:16}  {status}")
            for x in fails:
                print(f"    - {x.check}: {x.detail}")
            for x in chunk:
                if x.ok and x.check in (
                    "slos.present",
                    "slos.orphans",
                    "slos.sli_data",
                    "slos.posture_table",
                    "packages.scope",
                ):
                    print(f"    · {x.check}: {x.detail}")

    print()
    print("=" * 72)
    n_fail = sum(1 for f in report.findings if not f.ok)
    n_ok = sum(1 for f in report.findings if f.ok)
    print(f"OVERALL: {'SUCCESS' if report.ok else 'FAILURE'}  pass={n_ok} fail={n_fail}")
    print("=" * 72)

    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(
                {
                    "ok": report.ok,
                    "passed": n_ok,
                    "failed": n_fail,
                    "findings": [asdict(f) for f in report.findings],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"wrote {args.json_out}")
    return 0 if report.ok else 1


if __name__ == "__main__":
    # avoid proxy interference in sandboxes
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
        os.environ.pop(k, None)
    raise SystemExit(main())
