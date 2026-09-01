"""GCP billing (BigQuery billing export style) -> metrics-gcp.billing-default.
One doc per project x service per day."""
from datetime import timedelta

from src.generators.common import aligned, iso, metric_doc
from src.world.costs import gcp_daily_cost
from src.world.scenarios import rng_for

DATA_STREAM = "metrics-gcp.billing-default"
DATASET = "gcp.billing"

SKUS = {
    "Compute Engine": ("9C9C-9C9C-0001", "N2 Instance Core running in Americas"),
    "BigQuery": ("24E6-0002-38E5", "Analysis (US)"),
    "Vertex AI": ("C3BE-0003-0975", "A2 accelerator-optimized training (us-central1)"),
    "Cloud Storage": ("95FF-0004-5EA1", "Standard Storage US Multi-region"),
    "Cloud Logging": ("58CD-0005-72CA", "Log Volume"),
    "Cloud SQL": ("9662-0006-5089", "Cloud SQL for PostgreSQL: Zonal - vCPU"),
}


def emit(world, t0, t1, anchor):
    cfg = world.cfg["gcp"]
    for ts in aligned(t0, t1, 24 * 60):
        day = ts - timedelta(days=1)
        rng = rng_for("gcpbill", day.date())
        for proj in cfg["projects"]:
            for svc in cfg["services"]:
                desc = svc["description"]
                total = gcp_daily_cost(world, proj, desc, day, anchor)
                if total < 0.5:
                    continue
                sku_id, sku_desc = SKUS[desc]
                doc = metric_doc(DATASET, ts, "billing", 24 * 3600 * 1000)
                doc["cloud"] = {
                    "provider": "gcp",
                    "account": {"id": cfg["billing_account_id"],
                                "name": "Meridian Dynamics Billing"},
                    "project": {"id": proj["id"], "name": proj["id"]},
                    "region": cfg["regions"][0],
                }
                doc["gcp"] = {"billing": {
                    "billing_account_id": cfg["billing_account_id"],
                    "cost_type": "regular",
                    "invoice_month": day.strftime("%Y%m"),
                    "project_id": proj["id"],
                    "project_name": proj["id"],
                    "service_id": svc["id"],
                    "service_description": desc,
                    "sku_id": sku_id,
                    "sku_description": sku_desc,
                    "total": total,
                    "effective_price": round(rng.uniform(0.01, 3.9), 4),
                    "usage_start_time": iso(day),
                    "usage_end_time": iso(ts),
                    "location": {"country": "US", "region": cfg["regions"][0]},
                }}
                yield doc
