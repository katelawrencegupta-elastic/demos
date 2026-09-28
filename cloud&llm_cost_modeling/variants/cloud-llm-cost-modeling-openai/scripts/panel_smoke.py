#!/usr/bin/env python3
"""Deep smoke every ES|QL / data-view / options-list panel on FinOps dashboards.

Usage:
  .venv/bin/python scripts/panel_smoke.py --deployment azure
  .venv/bin/python scripts/panel_smoke.py --deployment aws --live
  .venv/bin/python scripts/panel_smoke.py --deployment gcp --json-out /tmp/gcp_panels.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _early_argv() -> None:
    argv = sys.argv[1:]
    for i, arg in enumerate(argv):
        if arg == "--deployment" and i + 1 < len(argv):
            os.environ["FINOPS_DEPLOYMENT"] = argv[i + 1]
            return
        if arg.startswith("--deployment="):
            os.environ["FINOPS_DEPLOYMENT"] = arg.split("=", 1)[1]
            return


_early_argv()

import requests

from src.config import ELASTIC_URL, ES_HEADERS, KBN_HEADERS, KIBANA_URL, apply_deployment
from src.live_dashboards import DASHBOARD_IDS, OOTB_HUB_TITLES, _resolve_hub_ids
from src.variant import active_variant
from src.variant_smoke import _FINOPS_DASH_BASES, _dash_id


def walk(ps, out):
    for p in ps or []:
        out.append(p)
        walk(p.get("panels"), out)


def subst_time(q: str, tstart: str, tend: str) -> str:
    return (
        q.replace("?_tstart", f'"{tstart}"')
        .replace("?_tend", f'"{tend}"')
        .replace("_tstart", f'"{tstart}"')
        .replace("_tend", f'"{tend}"')
    )


def find_queries(obj, found):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in ("query", "esql") and isinstance(v, str) and "FROM" in v.upper():
                found.append(v)
            else:
                find_queries(v, found)
    elif isinstance(obj, list):
        for v in obj:
            find_queries(v, found)


def data_view_ok(dvid: str):
    r = requests.get(
        f"{KIBANA_URL}/api/data_views/data_view/{dvid}",
        headers=KBN_HEADERS,
        timeout=30,
    )
    if r.status_code != 200:
        return False, f"GET {r.status_code}", None
    attrs = r.json().get("data_view") or r.json().get("dataView") or r.json()
    return True, attrs.get("title") or dvid, attrs


def target_dashboards(*, live: bool) -> list[str]:
    if live:
        mapping = _resolve_hub_ids()
        hub = [mapping[fid] for fid in OOTB_HUB_TITLES if fid in mapping]
        return list(dict.fromkeys(list(DASHBOARD_IDS) + hub))
    v = active_variant()
    ids = []
    dcfg = v.dashboards or {}
    # Match publish(): -dynamic is skipped when baseline is also on.
    publishable = dict(dcfg)
    if publishable.get("baseline") and publishable.get("dynamic"):
        publishable["dynamic"] = False
    for which, on in publishable.items():
        if on and which in _FINOPS_DASH_BASES:
            ids.append(_dash_id(which, v))
    return ids


def smoke_deployment(*, live: bool = False) -> dict:
    now = datetime.now(timezone.utc)
    tstart = (now - timedelta(days=120)).strftime("%Y-%m-%dT%H:%M:%SZ")
    tend = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    failures, passes, warnings = [], [], []
    dash_ids = target_dashboards(live=live)
    print(f"KIBANA {KIBANA_URL}")
    print(f"dashboards: {dash_ids}")
    print(f"window {tstart} .. {tend}")

    for did in dash_ids:
        r = requests.get(
            f"{KIBANA_URL}/api/dashboards/{did}",
            headers=KBN_HEADERS,
            timeout=60,
        )
        if r.status_code != 200:
            failures.append({"dash": did, "panel": "dashboard", "detail": f"GET {r.status_code}"})
            print(f"\n## {did} MISSING {r.status_code}")
            continue
        data = r.json().get("data") or {}
        title = data.get("title") or did
        panels = []
        walk(data.get("panels"), panels)
        walk(data.get("pinned_panels"), panels)
        print(f"\n## {title} ({did}) panels={len(panels)}")
        for p in panels:
            t = p.get("type") or "section"
            pid = p.get("id") or "?"
            cfgp = p.get("config") or {}
            pname = cfgp.get("title") or pid

            if t in ("section", "markdown", "slo_overview", "time_slider_control"):
                passes.append({"dash": did, "panel": pid, "detail": t})
                continue

            if t == "links":
                for link in cfgp.get("links") or []:
                    dest = link.get("destination") or ""
                    label = link.get("label") or "?"
                    ltype = link.get("type") or "dashboardLink"
                    if ltype == "externalLink" or str(dest).startswith("/"):
                        passes.append({"dash": did, "panel": pid, "detail": f"ext {label}"})
                        continue
                    rr = requests.get(
                        f"{KIBANA_URL}/api/dashboards/{dest}",
                        headers=KBN_HEADERS,
                        timeout=30,
                    )
                    if rr.status_code != 200:
                        failures.append({
                            "dash": did, "panel": pid,
                            "detail": f"link {label}->{dest} ({rr.status_code})",
                        })
                        print(f"  FAIL LINK {label}->{dest} ({rr.status_code})")
                    else:
                        passes.append({"dash": did, "panel": pid, "detail": f"link {label}"})
                continue

            if t == "options_list_control":
                dvid = cfgp.get("data_view_id")
                field = cfgp.get("field_name") or ""
                ok, dv_title, attrs = data_view_ok(dvid)
                if not ok:
                    failures.append({"dash": did, "panel": pid, "detail": f"ctrl dv missing {dvid}"})
                    print(f"  FAIL CTRL {pname}: dv missing")
                    continue
                if field.endswith(".keyword"):
                    failures.append({"dash": did, "panel": pid, "detail": f"ctrl uses {field}"})
                    print(f"  FAIL CTRL {pname}: {field}")
                    continue
                index = (attrs or {}).get("title") or dv_title
                sr = requests.post(
                    f"{ELASTIC_URL}/{index}/_search",
                    headers=ES_HEADERS,
                    json={
                        "size": 0,
                        "query": {"bool": {"filter": [{"range": {"@timestamp": {"gte": "now-120d"}}}]}},
                        "aggs": {"opts": {"terms": {"field": field, "size": 5}}},
                    },
                    timeout=60,
                )
                n = -1
                if sr.status_code == 200:
                    n = len((((sr.json().get("aggregations") or {}).get("opts") or {}).get("buckets")) or [])
                if sr.status_code != 200 or n == 0:
                    failures.append({
                        "dash": did, "panel": pid,
                        "detail": f"ctrl options n={n} status={sr.status_code}",
                    })
                    print(f"  FAIL CTRL {pname}: options n={n} status={sr.status_code}")
                else:
                    passes.append({"dash": did, "panel": pid, "detail": f"ctrl n={n}"})
                    print(f"  PASS CTRL {pname}: {field} n={n}")
                continue

            if t != "vis":
                warnings.append({"dash": did, "panel": pid, "detail": f"unknown type {t}"})
                print(f"  WARN {pname}: type={t}")
                continue

            ds = cfgp.get("data_source") or {}
            found = []
            if isinstance(ds.get("query"), str) and "FROM" in ds.get("query", "").upper():
                found.append(ds["query"])
            find_queries(cfgp, found)
            uniq = list(dict.fromkeys(found))
            if uniq:
                q = subst_time(uniq[0], tstart, tend)
                rr = requests.post(
                    f"{ELASTIC_URL}/_query",
                    headers={**ES_HEADERS, "Content-Type": "application/json"},
                    json={"query": q},
                    timeout=120,
                )
                if rr.status_code != 200:
                    err = rr.json().get("error") if rr.text else rr.text
                    if isinstance(err, dict):
                        err = err.get("reason") or err.get("message") or json.dumps(err)[:300]
                    failures.append({"dash": did, "panel": pid, "title": pname, "detail": f"ES|QL {rr.status_code}: {err}"})
                    print(f"  FAIL VIS {pname}: {str(err)[:220]}")
                else:
                    rows = len(rr.json().get("values") or [])
                    passes.append({"dash": did, "panel": pid, "detail": f"esql rows={rows}"})
                    print(f"  PASS VIS {pname}: rows={rows}")
                continue

            if ds.get("type") == "data_view_reference":
                dvid = ds.get("ref_id") or ds.get("id") or ds.get("data_view_id")
                ok, dv_title, _ = data_view_ok(dvid)
                if not ok:
                    failures.append({"dash": did, "panel": pid, "detail": f"dv missing {dvid}"})
                    print(f"  FAIL VIS {pname}: dv {dvid}")
                else:
                    passes.append({"dash": did, "panel": pid, "detail": f"dv {dv_title}"})
                    print(f"  PASS VIS {pname}: dv {dv_title}")
                continue

            warnings.append({"dash": did, "panel": pid, "detail": f"no executable query type={ds.get('type')}"})
            print(f"  SKIP VIS {pname}: no executable query")

    report = {
        "ok": not failures,
        "kibana": KIBANA_URL,
        "passed": len(passes),
        "failed": len(failures),
        "warnings": len(warnings),
        "failures": failures,
        "warning_details": warnings,
    }
    print("\n" + "=" * 72)
    print(f"PANEL SMOKE  pass={len(passes)} fail={len(failures)} warn={len(warnings)}")
    if failures:
        print("FAILURES:")
        for f in failures:
            print(f"  - {f.get('dash')} / {f.get('title') or f.get('panel')}: {f.get('detail')}")
    print("=" * 72)
    return report


def main() -> int:
    p = argparse.ArgumentParser(description="Panel-level FinOps dashboard smoke")
    p.add_argument("--deployment", required=True)
    p.add_argument("--live", action="store_true", help="smoke live AWS hub dashboard ids")
    p.add_argument("--json-out", default=None)
    args = p.parse_args()
    apply_deployment(args.deployment)
    report = smoke_deployment(live=args.live)
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"wrote {args.json_out}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
