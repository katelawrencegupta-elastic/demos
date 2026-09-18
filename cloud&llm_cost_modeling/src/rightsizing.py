"""Provision logs-finops.rightsizing data stream, transform, and optional seed."""
from __future__ import annotations

import json

import requests

from src.config import ELASTIC_URL, ES_HEADERS, ROOT

ES_DIR = ROOT / "elasticsearch" / "live"
PIPELINE_ID = "finops-rightsizing"
TEMPLATE_NAME = "logs-finops.rightsizing"
DEST_TEMPLATE_NAME = "finops-rightsizing-latest"
DATA_STREAM = "logs-finops.rightsizing-default"
TRANSFORM_ID = "finops-rightsizing-latest"
DEST_INDEX = "finops-rightsizing-latest"


def _es(method: str, path: str, **kwargs):
    kwargs.setdefault("headers", ES_HEADERS)
    kwargs.setdefault("timeout", 60)
    return requests.request(method, f"{ELASTIC_URL}{path}", **kwargs)


def _put_pipeline(fail_loud: bool) -> bool:
    body = json.loads((ES_DIR / "rightsizing-pipeline.json").read_text())
    r = _es("PUT", f"/_ingest/pipeline/{PIPELINE_ID}", json=body)
    if r.status_code >= 300:
        msg = f"  [fail] pipeline {PIPELINE_ID}: {r.status_code} {r.text[:300]}"
        if fail_loud:
            raise SystemExit(msg)
        print(msg.replace("[fail]", "[warn]"))
        return False
    print(f"  [ok] ingest pipeline {PIPELINE_ID}")
    return True


def _put_template(fail_loud: bool) -> bool:
    body = json.loads((ES_DIR / "rightsizing-index-template.json").read_text())
    r = _es("PUT", f"/_index_template/{TEMPLATE_NAME}", json=body)
    if r.status_code >= 300:
        msg = f"  [fail] index template {TEMPLATE_NAME}: {r.status_code} {r.text[:300]}"
        if fail_loud:
            raise SystemExit(msg)
        print(msg.replace("[fail]", "[warn]"))
        return False
    print(f"  [ok] index template {TEMPLATE_NAME}")
    return True


def _ensure_data_stream(fail_loud: bool) -> bool:
    r = _es("GET", f"/_data_stream/{DATA_STREAM}")
    if r.status_code == 200:
        print(f"  [ok] data stream {DATA_STREAM}")
        return True
    r = _es("PUT", f"/_data_stream/{DATA_STREAM}")
    if r.status_code >= 300:
        msg = f"  [fail] data stream {DATA_STREAM}: {r.status_code} {r.text[:300]}"
        if fail_loud:
            raise SystemExit(msg)
        print(msg.replace("[fail]", "[warn]"))
        return False
    print(f"  [ok] created data stream {DATA_STREAM}")
    return True


def _put_dest_template(fail_loud: bool) -> bool:
    body = json.loads((ES_DIR / "rightsizing-latest-index-template.json").read_text())
    r = _es("PUT", f"/_index_template/{DEST_TEMPLATE_NAME}", json=body)
    if r.status_code >= 300:
        msg = f"  [fail] index template {DEST_TEMPLATE_NAME}: {r.status_code} {r.text[:300]}"
        if fail_loud:
            raise SystemExit(msg)
        print(msg.replace("[fail]", "[warn]"))
        return False
    print(f"  [ok] index template {DEST_TEMPLATE_NAME}")
    return True


def _dest_mapping_ok() -> bool:
    r = _es("GET", f"/{DEST_INDEX}/_mapping")
    if r.status_code != 200:
        return False
    for body in (r.json() or {}).values():
        props = (body.get("mappings") or {}).get("properties") or {}
        status = (
            ((props.get("finops") or {}).get("properties") or {})
            .get("rightsizing", {})
            .get("properties", {})
            .get("status")
        )
        if status:
            return True
    return False


def _reset_transform_dest(fail_loud: bool, *, force: bool = False) -> bool:
    """Rebuild dest so ES|QL sees status/savings and picks up new seed docs.

    Latest transforms sync on ``@timestamp``. Re-seeding with historical
    timestamps does not advance the watermark, so *force* stop/reset/start
    after seed is required to refresh ``finops-rightsizing-latest``.
    """
    r = _es("GET", f"/_transform/{TRANSFORM_ID}")
    if r.status_code != 200:
        return True
    if not force and _dest_mapping_ok():
        print(f"  [ok] dest {DEST_INDEX} mapping already has finops.rightsizing.status")
        return True
    stop = _es(
        "POST",
        f"/_transform/{TRANSFORM_ID}/_stop",
        params={"wait_for_completion": "true", "force": "true", "timeout": "60s"},
    )
    if stop.status_code >= 300 and "not found" not in (stop.text or "").lower():
        print(f"  [warn] transform stop {TRANSFORM_ID}: {stop.status_code} {stop.text[:200]}")
    reset = _es("POST", f"/_transform/{TRANSFORM_ID}/_reset")
    if reset.status_code >= 300:
        msg = f"  [fail] transform reset {TRANSFORM_ID}: {reset.status_code} {reset.text[:300]}"
        if fail_loud:
            raise SystemExit(msg)
        print(msg.replace("[fail]", "[warn]"))
        _es("DELETE", f"/{DEST_INDEX}")
        return False
    print(f"  [ok] reset transform dest {DEST_INDEX}")
    return True


def _ensure_transform(fail_loud: bool) -> bool:
    body = json.loads((ES_DIR / "rightsizing-transform.json").read_text())
    r = _es("GET", f"/_transform/{TRANSFORM_ID}")
    if r.status_code == 200:
        print(f"  [ok] transform {TRANSFORM_ID} already exists")
    else:
        r = _es("PUT", f"/_transform/{TRANSFORM_ID}", json=body)
        if r.status_code >= 300:
            msg = f"  [fail] transform {TRANSFORM_ID}: {r.status_code} {r.text[:400]}"
            if fail_loud:
                raise SystemExit(msg)
            print(msg.replace("[fail]", "[warn]"))
            return False
        print(f"  [ok] transform created {TRANSFORM_ID}")
    r = _es("POST", f"/_transform/{TRANSFORM_ID}/_start")
    if r.status_code >= 300 and "already started" not in (r.text or "").lower():
        print(f"  [warn] transform start {TRANSFORM_ID}: {r.status_code} {r.text[:200]}")
    else:
        print(f"  [ok] transform started {TRANSFORM_ID}")
    return True


def _seed_docs(fail_loud: bool, *, force: bool = False) -> bool:
    """Seed expanded catalog into the data stream (create-only; DS rule).

    When *force*, deletes prior ``hidden_reason:seeded_sample`` docs first so
    create upserts cleanly. Otherwise skips if the stream already has ≥10 docs.
    """
    r = _es("GET", f"/{DATA_STREAM}/_count")
    count = 0
    if r.status_code == 200:
        count = int((r.json() or {}).get("count") or 0)
    if count >= 10 and not force:
        print(f"  [ok] rightsizing docs already present ({count})")
        return True

    seed = ES_DIR / "rightsizing-seed.ndjson"
    if not seed.is_file():
        from scripts.generate_rightsizing_seed import write_seed
        write_seed(seed)
    else:
        # Regenerate so action catalog stays in sync with the script.
        from scripts.generate_rightsizing_seed import write_seed
        write_seed(seed)

    if force or count > 0:
        # Data streams reject bulk "index"; wipe prior seeds then create.
        dr = _es(
            "POST",
            f"/{DATA_STREAM}/_delete_by_query?conflicts=proceed&refresh=true",
            json={"query": {"term": {"finops.rightsizing.hidden_reason": "seeded_sample"}}},
        )
        if dr.status_code < 300:
            deleted = int((dr.json() or {}).get("deleted") or 0)
            print(f"  [ok] removed {deleted} prior seeded_sample docs")
        else:
            print(f"  [warn] seed cleanup: {dr.status_code} {dr.text[:200]}")

    r = _es(
        "POST",
        "/_bulk?refresh=true",
        data=seed.read_text(encoding="utf-8"),
        headers={**ES_HEADERS, "Content-Type": "application/x-ndjson"},
    )
    if r.status_code >= 300:
        msg = f"  [fail] rightsizing seed: {r.status_code} {r.text[:300]}"
        if fail_loud:
            raise SystemExit(msg)
        print(msg.replace("[fail]", "[warn]"))
        return False
    body = r.json() if r.text else {}
    items = body.get("items") or []
    n_ok = 0
    n_conflict = 0
    for it in items:
        res = it.get("create") or it.get("index") or {}
        st = res.get("status", 500)
        if st < 300:
            n_ok += 1
        elif st == 409:
            n_conflict += 1
        else:
            err = (res.get("error") or {}).get("reason", "")[:160]
            print(f"  [warn] seed item {res.get('_id')}: {st} {err}")
    print(f"  [ok] seeded {n_ok} rightsizing docs"
          + (f" ({n_conflict} already existed)" if n_conflict else ""))
    return True


def ensure_rightsizing(fail_loud: bool = False, seed: bool = True, force_seed: bool = False) -> bool:
    print("== FinOps rightsizing stream ==")
    ok = True
    ok = _put_pipeline(fail_loud) and ok
    ok = _put_template(fail_loud) and ok
    ok = _put_dest_template(fail_loud) and ok
    ok = _ensure_data_stream(fail_loud) and ok
    ok = _reset_transform_dest(fail_loud) and ok
    ok = _ensure_transform(fail_loud) and ok
    if seed:
        ok = _seed_docs(fail_loud, force=force_seed) and ok
        # Latest syncs on @timestamp; historical seed docs need a full reset
        # so finops-rightsizing-latest picks up the expanded catalog.
        if force_seed:
            ok = _reset_transform_dest(fail_loud, force=True) and ok
            ok = _ensure_transform(fail_loud) and ok
    return ok


def verify_rightsizing() -> bool:
    print("== FinOps rightsizing ==")
    r = _es("GET", f"/_data_stream/{DATA_STREAM}")
    if r.status_code != 200:
        print(f"  [fail] data stream {DATA_STREAM}: {r.status_code}")
        return False
    print(f"  [ok] data stream {DATA_STREAM}")
    r = _es("GET", f"/_transform/{TRANSFORM_ID}")
    if r.status_code != 200:
        print(f"  [fail] transform {TRANSFORM_ID}: {r.status_code}")
        return False
    print(f"  [ok] transform {TRANSFORM_ID}")
    return True
