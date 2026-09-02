"""ESS billing credits -> metrics-ess_billing.credits-default.

The OOTB [Metrics ESS Billing] Credits dashboard queries
`metrics-ess_billing.credits-*` for prepaid ECU balances. Fleet only
collects that stream for orgs on yearly/multi-year ECU contracts, so demo
clusters with pay-as-you-go Serverless billing have billing line items but
no credits — panels 3 and 5 on ess_billing-creditsdashboard error.

We synthesize one daily snapshot per contract line so ES|QL balance panels
render while real `metrics-ess_billing.billing-*` spend still drives the
cost charts.
"""
from datetime import datetime, timedelta, timezone

from src.generators.common import aligned, iso, isos, metric_doc
from src.world.scenarios import rng_for

DATA_STREAM = "metrics-ess_billing.credits-default"
DATASET = "ess_billing.credits"

# Matches the org on the live Serverless project (also in real billing docs).
ORG_ID = "1667763985"
ECU_QUANTITY = 1_500_000
DAILY_BURN_ECU = 43.0
CONTRACT_DAYS = 365


def _contract_bounds(anchor: datetime):
    end = datetime(anchor.year, 12, 31, 23, 59, 59, 999000, tzinfo=timezone.utc)
    start = end - timedelta(days=CONTRACT_DAYS - 1)
    start = start.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, end


def emit(world, t0, t1, anchor):
    start, end = _contract_bounds(anchor)
    for ts in aligned(t0, t1, 24 * 60):
        if ts < start or ts > end:
            continue
        day = ts.date()
        days_elapsed = (day - start.date()).days
        rng = rng_for("esscredits", day)
        burn = DAILY_BURN_ECU * (0.92 + rng.random() * 0.16)
        balance = max(int(ECU_QUANTITY - days_elapsed * burn), 0)
        doc = metric_doc(DATASET, ts, "credits", 24 * 3600 * 1000)
        doc["cloud"] = {
            "provider": "serverless",
            "account": {"id": ORG_ID},
            "region": "gcp-us-central1",
        }
        doc["ess"] = {"billing": {
            "active": True,
            "ecu_balance": balance,
            "ecu_quantity": ECU_QUANTITY,
            "organization_id": ORG_ID,
            "start": isos(start),
            "end": iso(end),
            "type": "prepaid_consumption",
        }}
        doc["event"]["dataset"] = DATASET
        doc["input"] = {"type": "cel"}
        doc["tags"] = ["billing", "synthetic"]
        yield doc
