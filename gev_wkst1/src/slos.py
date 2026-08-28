"""Provision native Observability SLOs for the Elastic Co. checkout incident."""
from __future__ import annotations

import uuid

import requests

from src.config import KBN_HEADERS, KIBANA_URL

SLO_API = f"{KIBANA_URL}/api/observability/slos"
RULE_API = f"{KIBANA_URL}/api/alerting/rule"

SLO_ID = "elasticco-slo-checkout-availability"
SLO_NAME = "Elastic Co. — checkout-api availability (acme-retail)"
BURN_RULE_ID = "elasticco-slo-checkout-availability-burn"
TAGS = ["elastic-co", "demo", "checkout-api", "acme-retail"]


def _kbn(method: str, url: str, **kwargs):
    kwargs.setdefault("headers", KBN_HEADERS)
    kwargs.setdefault("timeout", 60)
    return requests.request(method, url, **kwargs)


def _kql_slo_body() -> dict:
    """Custom KQL SLO — works with synthetic APM + tenant.id (not only Elastic Agent APM)."""
    return {
        "name": SLO_NAME,
        "description": (
            "Availability of checkout-api transactions for tenant acme-retail "
            "(labels.demo: elastic-co). Native SLO — not the ES|QL correlation alert."
        ),
        "indicator": {
            "type": "sli.kql.custom",
            "params": {
                "index": "traces-apm-default",
                "filter": (
                    'processor.event: transaction and service.name: "checkout-api" '
                    'and labels.demo: "elastic-co" and tenant.id: "acme-retail"'
                ),
                "good": 'not event.outcome: failure',
                "total": "*",
                "timestampField": "@timestamp",
            },
        },
        "budgetingMethod": "occurrences",
        "timeWindow": {"duration": "7d", "type": "rolling"},
        "objective": {"target": 0.99},
        "tags": TAGS,
    }


def _apm_slo_body() -> dict:
    return {
        "name": SLO_NAME,
        "description": (
            "APM error-rate SLO for checkout-api / acme-retail. "
            "Prefer this when the project accepts sli.apm.transactionErrorRate."
        ),
        "indicator": {
            "type": "sli.apm.transactionErrorRate",
            "params": {
                "service": "checkout-api",
                "environment": "ENVIRONMENT_ALL",
                "transactionType": "request",
                "transactionName": "*",
                "index": "traces-apm*",
                "filter": 'labels.demo: "elastic-co" and tenant.id: "acme-retail"',
            },
        },
        "budgetingMethod": "occurrences",
        "timeWindow": {"duration": "7d", "type": "rolling"},
        "objective": {"target": 0.99},
        "tags": TAGS,
    }


def _upsert_slo(body: dict, fail_loud: bool) -> bool:
    r = _kbn("GET", f"{SLO_API}/{SLO_ID}")
    if r.status_code == 200:
        r = _kbn("PUT", f"{SLO_API}/{SLO_ID}", json=body)
        action = "updated"
    elif r.status_code == 404:
        r = _kbn("POST", SLO_API, json={**body, "id": SLO_ID})
        action = "created"
    else:
        msg = f"  [fail] SLO GET {SLO_ID}: {r.status_code} {r.text[:240]}"
        if fail_loud:
            raise SystemExit(msg)
        print(msg.replace("[fail]", "[warn]"))
        return False

    if r.status_code >= 300:
        msg = f"  [fail] SLO {action} {SLO_ID}: {r.status_code} {r.text[:400]}"
        if r.status_code in (403, 404) and not fail_loud:
            print(msg.replace("[fail]", "[warn]"))
            return False
        if fail_loud:
            raise SystemExit(msg)
        print(msg.replace("[fail]", "[warn]"))
        return False
    print(f"  [ok] SLO {action}: {SLO_ID}")
    return True


def _burn_rate_body() -> dict:
    windows = [
        {
            "id": str(uuid.uuid4()),
            "burnRateThreshold": 14.4,
            "maxBurnRateThreshold": 1000,
            "longWindow": {"value": 1, "unit": "h"},
            "shortWindow": {"value": 5, "unit": "m"},
            "actionGroup": "slo.burnRate.high",
        },
        {
            "id": str(uuid.uuid4()),
            "burnRateThreshold": 6.0,
            "maxBurnRateThreshold": 1000,
            "longWindow": {"value": 6, "unit": "h"},
            "shortWindow": {"value": 30, "unit": "m"},
            "actionGroup": "slo.burnRate.medium",
        },
    ]
    return {
        "name": "Elastic Co. — checkout SLO burn (acme-retail)",
        "tags": TAGS,
        "rule_type_id": "slo.rules.burnRate",
        "consumer": "slo",
        "enabled": True,
        "schedule": {"interval": "1m"},
        "actions": [],
        "params": {
            "sloId": SLO_ID,
            "windows": windows,
            "dependencies": [],
        },
    }


def _upsert_burn_rule(fail_loud: bool) -> bool:
    body = _burn_rate_body()
    r = _kbn("GET", f"{RULE_API}/{BURN_RULE_ID}")
    if r.status_code == 200:
        update = {k: body[k] for k in ("name", "tags", "schedule", "params", "actions") if k in body}
        r = _kbn("PUT", f"{RULE_API}/{BURN_RULE_ID}", json=update)
        action = "updated"
    elif r.status_code == 404:
        r = _kbn("POST", f"{RULE_API}/{BURN_RULE_ID}", json=body)
        action = "created"
    else:
        msg = f"  [fail] burn-rate GET: {r.status_code} {r.text[:200]}"
        if fail_loud:
            raise SystemExit(msg)
        print(msg.replace("[fail]", "[warn]"))
        return False
    if r.status_code >= 300:
        msg = f"  [fail] burn-rate {action}: {r.status_code} {r.text[:300]}"
        if fail_loud:
            raise SystemExit(msg)
        print(msg.replace("[fail]", "[warn]"))
        return False
    print(f"  [ok] burn-rate rule {action}: {BURN_RULE_ID}")
    return True


def ensure_slos(fail_loud: bool = False) -> bool:
    """Create the native checkout availability SLO. Prefers APM indicator, falls back to KQL."""
    ok = _upsert_slo(_apm_slo_body(), fail_loud=False)
    if not ok:
        print("  [info] APM SLO indicator rejected; trying custom KQL SLO")
        ok = _upsert_slo(_kql_slo_body(), fail_loud)
    if ok:
        _upsert_burn_rule(fail_loud=False)
    return ok
