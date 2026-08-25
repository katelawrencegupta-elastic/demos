"""Setup: install Elastic integration packages via Fleet, patch TSDS
templates so 30-day metric backfill is accepted, and smoke-test write access."""
import json

import requests

from src.config import ELASTIC_URL, ES_HEADERS, KBN_HEADERS, KIBANA_URL

PACKAGES = [
    "aws", "gcp", "azure", "azure_billing",
    "openai", "anthropic", "anthropic_metrics",
    "azure_openai", "aws_bedrock", "gcp_vertexai",
    "aws_billing", "apm",
]

# TSDS index templates that would reject backfilled timestamps
TSDS_PATCH = ["metrics-aws.ec2_metrics", "metrics-aws_bedrock.runtime"]

TEMPLATE_KEYS = ("index_patterns", "template", "composed_of", "priority",
                 "data_stream", "_meta", "ignore_missing_component_templates",
                 "allow_auto_create")


def ensure_packages():
    for pkg in PACKAGES:
        r = requests.get(f"{KIBANA_URL}/api/fleet/epm/packages/{pkg}",
                         headers=KBN_HEADERS, timeout=60)
        r.raise_for_status()
        item = r.json()["item"]
        if item.get("status") == "installed":
            print(f"  [ok] package {pkg} {item['version']} already installed")
            continue
        print(f"  installing package {pkg} ...")
        r = requests.post(f"{KIBANA_URL}/api/fleet/epm/packages/{pkg}",
                          headers=KBN_HEADERS, json={}, timeout=600)
        r.raise_for_status()
        print(f"  [ok] package {pkg} installed")


def patch_tsds_templates():
    for name in TSDS_PATCH:
        r = requests.get(f"{ELASTIC_URL}/_index_template/{name}",
                         headers=ES_HEADERS, timeout=60)
        r.raise_for_status()
        tpl = r.json()["index_templates"][0]["index_template"]
        idx = tpl.get("template", {}).get("settings", {}).get("index", {})
        if idx.get("mode") != "time_series":
            print(f"  [ok] {name} already standard mode")
            continue
        idx.pop("mode", None)
        idx.pop("routing_path", None)
        idx.pop("look_ahead_time", None)
        idx.pop("look_back_time", None)
        body = {k: tpl[k] for k in TEMPLATE_KEYS if k in tpl}
        r = requests.put(f"{ELASTIC_URL}/_index_template/{name}",
                         headers=ES_HEADERS, json=body, timeout=60)
        if r.status_code >= 300:
            print(f"  [warn] could not patch {name}: {r.status_code} {r.text[:300]}")
            continue
        print(f"  [ok] {name}: time_series mode removed (backfill enabled)")
        # if the data stream already exists it was created TSDS; recreate it
        ds = f"{name}-default"
        r = requests.get(f"{ELASTIC_URL}/_data_stream/{ds}", headers=ES_HEADERS)
        if r.status_code == 200:
            requests.delete(f"{ELASTIC_URL}/_data_stream/{ds}", headers=ES_HEADERS)
            print(f"  [ok] deleted pre-existing data stream {ds} so the patch applies")


def check_write_access():
    """Bulk-index one probe doc into a throwaway index and remove it."""
    probe = "logs-synthetic-probe"
    r = requests.post(f"{ELASTIC_URL}/{probe}/_doc", headers=ES_HEADERS,
                      json={"@timestamp": "2026-01-01T00:00:00Z", "message": "probe"},
                      timeout=30)
    if r.status_code >= 300:
        raise SystemExit(f"  [fail] cannot write to {probe}: {r.status_code} {r.text[:300]}")
    requests.delete(f"{ELASTIC_URL}/{probe}", headers=ES_HEADERS)
    print("  [ok] API key can create indices and write documents")


CUR_ALIAS = "aws_billing.cur_latest"
CUR_DATA_VIEW_ID = "aws-billing-cur-latest"
# Packaged OOTB controls reference this ad-hoc ES|QL data-view hash, which
# Fleet never materializes as a saved index-pattern on Serverless.
CUR_PACKAGED_DATA_VIEW_ID = "e65c8b0bfe6b4a0aebad76d709d8666b7812bb7a07da7ac7ce8d2af692bce544"
AWS_BILLING_DASHBOARDS = (
    "aws_billing-01aace34-9219-4c6c-80a9-b903af48950f",  # Current month
    "aws_billing-fa467f8d-50d9-4cb0-ae88-94ef24e9941a",  # Last month
    "aws_billing-a716ad8e-0f77-4592-b497-6c841447efd2",  # Last 3 months
    "aws_billing-fb79da15-4c4c-453f-9d3d-b792ce2482ff",  # Last 6 months
    "aws_billing-81918d21-70c6-4bc0-a03e-9e298460a525",  # All time
)


def ensure_cur_latest_alias():
    """OOTB aws_billing CUR dashboards query aws_billing.cur_latest.

    Fleet's transform that should create that alias fails on Serverless
    (kibana service account lacks create_index on aws_billing.cur-v1).
    Point the alias at the native CUR data stream instead.
    """
    target = "metrics-aws_billing.cur-default"
    r = requests.get(f"{ELASTIC_URL}/_alias/{CUR_ALIAS}", headers=ES_HEADERS, timeout=30)
    if r.status_code == 200:
        print(f"  [ok] alias {CUR_ALIAS} already exists")
        return
    r = requests.post(f"{ELASTIC_URL}/_aliases", headers=ES_HEADERS, timeout=30, json={
        "actions": [{"add": {"index": target, "alias": CUR_ALIAS}}],
    })
    if r.status_code >= 300:
        print(f"  [warn] could not create {CUR_ALIAS}: {r.status_code} {r.text[:300]}")
        return
    print(f"  [ok] alias {CUR_ALIAS} -> {target}")


def ensure_cur_data_view():
    """Options-list controls (Payer / Linked Account ID) need a classic
    index-pattern data view. The packaged dashboards point at an ES|QL
    ad-hoc data view that does not exist as a saved object.
    """
    r = requests.get(f"{KIBANA_URL}/api/data_views/data_view/{CUR_DATA_VIEW_ID}",
                     headers=KBN_HEADERS, timeout=30)
    if r.status_code == 200:
        print(f"  [ok] data view {CUR_DATA_VIEW_ID} already exists")
        return
    r = requests.post(f"{KIBANA_URL}/api/data_views/data_view",
                      headers=KBN_HEADERS, timeout=30, json={
                          "data_view": {
                              "id": CUR_DATA_VIEW_ID,
                              "title": CUR_ALIAS,
                              "name": "AWS CUR latest",
                              "timeFieldName": "@timestamp",
                              "allowNoIndex": True,
                          },
                          "override": True,
                      })
    if r.status_code >= 300:
        print(f"  [warn] could not create data view: {r.status_code} {r.text[:300]}")
        return
    print(f"  [ok] data view {CUR_DATA_VIEW_ID} -> {CUR_ALIAS}")


def patch_aws_billing_dashboards():
    """Point Payer / Linked Account ID controls at the real CUR data view."""
    for did in AWS_BILLING_DASHBOARDS:
        r = requests.get(f"{KIBANA_URL}/api/dashboards/{did}",
                         headers=KBN_HEADERS, timeout=30)
        if r.status_code != 200:
            print(f"  [warn] dashboard {did}: {r.status_code}")
            continue
        body = r.json()["data"]
        changed = 0
        for panel in body.get("pinned_panels") or []:
            cfg = panel.get("config") or {}
            if cfg.get("data_view_id") == CUR_PACKAGED_DATA_VIEW_ID:
                cfg["data_view_id"] = CUR_DATA_VIEW_ID
                changed += 1
        if not changed:
            print(f"  [ok] {body.get('title')}: controls already patched")
            continue
        r = requests.put(f"{KIBANA_URL}/api/dashboards/{did}",
                         headers=KBN_HEADERS, json=body, timeout=60)
        if r.status_code >= 300:
            print(f"  [warn] could not patch {did}: {r.status_code} {r.text[:300]}")
            continue
        print(f"  [ok] retargeted {changed} controls on {body.get('title')}")


BACKFILL_TIME_RANGE = {
    "from": "2026-07-14T00:00:00.000Z",
    "to": "2026-08-18T00:00:00.000Z",
}


def patch_openai_usage_dashboard():
    """OOTB OpenAI Usage dashboard filters on event.dataset, which the
    Fleet openai pipeline never writes. Point filters at data_stream.dataset
    (constant_keyword on the streams) and pin the backfill time window.
    """
    did = "openai-651bb059-f606-44fc-b704-2078d0af26da"
    r = requests.get(f"{KIBANA_URL}/api/dashboards/{did}",
                     headers=KBN_HEADERS, timeout=30)
    if r.status_code != 200:
        print(f"  [warn] dashboard {did}: {r.status_code}")
        return
    body = json.loads(
        json.dumps(r.json()["data"]).replace(
            "event.dataset", "data_stream.dataset")
    )
    body["time_range"] = dict(BACKFILL_TIME_RANGE)
    r = requests.put(f"{KIBANA_URL}/api/dashboards/{did}",
                     headers=KBN_HEADERS, json=body, timeout=60)
    if r.status_code >= 300:
        print(f"  [warn] could not patch dashboard: {r.status_code} {r.text[:400]}")
        return
    print(f"  [ok] patched filters + time range on {body.get('title')}")


def _pin_dashboard_time_range(dash_id):
    r = requests.get(f"{KIBANA_URL}/api/dashboards/{dash_id}",
                     headers=KBN_HEADERS, timeout=30)
    if r.status_code != 200:
        print(f"  [warn] dashboard {dash_id}: {r.status_code}")
        return
    body = r.json()["data"]
    body["time_range"] = dict(BACKFILL_TIME_RANGE)
    r = requests.put(f"{KIBANA_URL}/api/dashboards/{dash_id}",
                     headers=KBN_HEADERS, json=body, timeout=60)
    if r.status_code >= 300:
        print(f"  [warn] could not pin time range: {r.status_code} {r.text[:300]}")
        return
    print(f"  [ok] pinned time range on {body.get('title')}")


AZURE_OPENAI_DASHBOARDS = (
    "azure_openai-f5bbc591-5e6b-4af7-b6c5-b02065a06455",  # Billing
    "azure_openai-83bbaa98-7f44-4785-8774-15e0de9f74fa",  # PTU Deployments
    "azure_openai-8b09a72a-8317-4ec5-aafe-4b7d3833dcc0",  # Content Filtering
    "azure_openai-21d9a0d0-e6a0-4b34-bc6d-ce6560a1dab3",  # Overview
)


def pin_azure_openai_dashboards():
    """Store the backfill window on OOTB Azure OpenAI dashboards.

    Fleet assets ship with timeRestore false, so without this the picker
    stays on 'Last 15 minutes' and the 30-day backfill never appears.
    """
    for did in AZURE_OPENAI_DASHBOARDS:
        _pin_dashboard_time_range(did)


INFERENCE_TOKEN_USAGE_DATA_VIEW_ID = "kibana-inference-token-usage"
INFERENCE_TOKEN_USAGE_DASHBOARD_ID = "kibana-inference-token-usage"
INFERENCE_TOKEN_USAGE_INDEX = "logs-elastic.inference_token_usage-default"


def patch_inference_token_usage_dashboard():
    """OOTB [Elastic] Inference Token Usage dashboard.

    Kibana installs a data view titled `.kibana-inference-token-usage` (hidden
    stream). On Serverless users cannot create dot-prefixed indices, the stream
    never materializes, and the data view has empty fields — every Lens panel
    errors. Point the same data-view id at the demo stream that already has
    the token_usage / model / inference mappings.
    """
    r = requests.get(
        f"{KIBANA_URL}/api/data_views/data_view/{INFERENCE_TOKEN_USAGE_DATA_VIEW_ID}",
        headers=KBN_HEADERS, timeout=30)
    if r.status_code != 200:
        print(f"  [warn] data view {INFERENCE_TOKEN_USAGE_DATA_VIEW_ID}: {r.status_code}")
        return
    current = r.json()["data_view"]
    title = current.get("title")
    fields = current.get("fields") or {}
    n_fields = len(fields) if isinstance(fields, dict) else 0
    already = (title == INFERENCE_TOKEN_USAGE_INDEX and n_fields > 0)
    if already:
        print(f"  [ok] data view already -> {INFERENCE_TOKEN_USAGE_INDEX} ({n_fields} fields)")
    else:
        r = requests.post(
            f"{KIBANA_URL}/api/data_views/data_view/{INFERENCE_TOKEN_USAGE_DATA_VIEW_ID}",
            headers=KBN_HEADERS, timeout=30, json={
                "refresh_fields": True,
                "data_view": {
                    "title": INFERENCE_TOKEN_USAGE_INDEX,
                    "name": "Inference Token Usage",
                    "timeFieldName": "@timestamp",
                    "allowNoIndex": True,
                },
            })
        if r.status_code >= 300:
            print(f"  [warn] could not retarget data view: {r.status_code} {r.text[:400]}")
            return
        updated = r.json().get("data_view") or r.json()
        n_fields = len(updated.get("fields") or {})
        print(f"  [ok] data view {INFERENCE_TOKEN_USAGE_DATA_VIEW_ID} -> "
              f"{INFERENCE_TOKEN_USAGE_INDEX} ({n_fields} fields)")
    print("== checking Elasticsearch ==")
    r = requests.get(ELASTIC_URL, headers=ES_HEADERS, timeout=30)
    r.raise_for_status()
    info = r.json()
    print(f"  [ok] {info['version']['number']} ({info['version']['build_flavor']})")
    print("== installing integration packages (Fleet) ==")
    ensure_packages()
    print("== patching TSDS templates for backfill ==")
    patch_tsds_templates()
    print("== CUR latest alias (OOTB aws_billing dashboards) ==")
    ensure_cur_latest_alias()
    print("== CUR data view + Payer/Linked Account controls ==")
    ensure_cur_data_view()
    patch_aws_billing_dashboards()
    print("== OpenAI Usage dashboard (data_stream.dataset + time range) ==")
    patch_openai_usage_dashboard()
    print("== Azure OpenAI dashboards (time range) ==")
    pin_azure_openai_dashboards()
    print("== checking write access ==")
    check_write_access()
    print("== APM gen_ai mappings + retention (ES|QL) ==")
    from src.generators.llm_apm import ensure_apm_genai_mappings
    ensure_apm_genai_mappings()
    print("== inference token-usage template ==")
    from src.generators.elastic_ai import _ensure_template
    _ensure_template()
    print("  [ok] logs-elastic.inference_token_usage-*")
    print("== OOTB Inference Token Usage dashboard (data view + time range) ==")
    patch_inference_token_usage_dashboard()
    print("setup complete.")
