"""ESS billing line items -> metrics-ess_billing.billing-default.

Credits (prepaid ECU balance) stay in ess_billing_credits. This fills the OOTB
[Metrics ESS Billing] Billing dashboard and any live panel on
metrics-ess_billing.billing-*.
"""
from src.generators.common import aligned, isos, metric_doc
from src.generators.ess_billing_credits import DAILY_BURN_ECU, ORG_ID
from src.world.scenarios import rng_for

DATA_STREAM = "metrics-ess_billing.billing-default"
DATASET = "ess_billing.billing"

# Share of daily ECU burn across named line items (OOTB groups by ess.billing.name).
LINES = (
    ("elasticsearch", 0.46),
    ("kibana", 0.12),
    ("security", 0.10),
    ("observability", 0.14),
    ("serverless", 0.18),
)

_TEMPLATE_OK = False


def _ensure_template():
    global _TEMPLATE_OK
    if _TEMPLATE_OK:
        return
    from src.config import ELASTIC_URL, ES_HEADERS
    import requests
    body = {
        "index_patterns": ["metrics-ess_billing.billing-*"],
        "data_stream": {},
        "priority": 210,
        "template": {
            "mappings": {
                "properties": {
                    "@timestamp": {"type": "date"},
                    "ess": {"properties": {
                        "billing": {"properties": {
                            "name": {"type": "keyword"},
                            "type": {"type": "keyword"},
                            "organization_id": {"type": "keyword"},
                            "quantity": {"type": "double"},
                            "total_ecu": {"type": "double"},
                            "unit_price": {"type": "double"},
                        }},
                    }},
                    "cloud": {"properties": {
                        "account": {"properties": {
                            "id": {"type": "keyword"},
                        }},
                    }},
                }
            }
        },
    }
    r = requests.put(
        f"{ELASTIC_URL}/_index_template/meridian-ess-billing",
        headers=ES_HEADERS, json=body, timeout=30)
    if r.status_code >= 300:
        print(f"  [warn] ess billing template: {r.status_code} {r.text[:200]}")
    _TEMPLATE_OK = True


def emit(world, t0, t1, anchor):
    _ensure_template()
    for ts in aligned(t0, t1, 24 * 60):
        rng = rng_for("essbill", ts.date())
        burn = DAILY_BURN_ECU * (0.92 + rng.random() * 0.16)
        for name, share in LINES:
            ecu = round(burn * share, 3)
            doc = metric_doc(DATASET, ts, "billing", 24 * 3600 * 1000)
            doc["cloud"] = {
                "provider": "serverless",
                "account": {"id": ORG_ID},
                "region": "gcp-us-central1",
            }
            doc["ess"] = {"billing": {
                "name": name,
                "type": "usage",
                "organization_id": ORG_ID,
                "quantity": 1,
                "total_ecu": ecu,
                "unit_price": round(ecu, 3),
                "start": isos(ts),
            }}
            doc["event"]["dataset"] = DATASET
            doc["tags"] = ["billing", "synthetic"]
            yield doc
