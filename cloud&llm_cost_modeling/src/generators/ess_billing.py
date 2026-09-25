"""ESS billing line items -> metrics-ess_billing.billing-default.

Credits (prepaid ECU balance) stay in ess_billing_credits. This fills the OOTB
[Metrics ESS Billing] Billing dashboard and any live panel on
metrics-ess_billing.billing-*.

Documents must match the Fleet `metrics-ess_billing.billing@package` mapping:
deployment_* and sku are keyword; quantity is {value}; do not set
ess.billing.cloud as a string (package maps it as an object with
service.type / machine.type).
"""
from datetime import timedelta

from src.generators.common import aligned, iso, isos, metric_doc
from src.generators.ess_billing_credits import DAILY_BURN_ECU, ORG_ID
from src.world.scenarios import rng_for

DATA_STREAM = "metrics-ess_billing.billing-default"
DATASET = "ess_billing.billing"

# (deployment_type, deployment_name, deployment_id, sku, billing.type, name,
#  cloud.service.type, cloud.machine.type|None, share)
# deployment_type "deployment" = Elastic Cloud Hosted; others = Serverless projects.
# cloud.service.type feeds OOTB "Serverless features per service types".
# cloud.machine.type (ECH capacity) feeds "ECH Capacity Costs per instance flavors"
# (Lens uses top-level cloud.machine.type + ess.billing.cloud.machine.type).
LINES = (
    ("elasticsearch", "klgfinopsdemo", "proj_es_finops",
     "elasticsearch.search_gcp-us-central1", "usage", "elasticsearch",
     "search", None, 0.30),
    ("observability", "klg-obs-prod", "proj_obs_prod",
     "observability.ingest_gcp-us-central1", "usage", "observability",
     "observability", None, 0.16),
    ("security", "klg-sec-prod", "proj_sec_prod",
     "security.ingest_gcp-us-central1", "usage", "security",
     "security", None, 0.12),
    ("deployment", "elk-ech-prod", "dep_ech_prod",
     "gcp.n2.gcp-us-central1_4096_2", "capacity", "elasticsearch",
     "elasticsearch", "gcp.n2.4096_2", 0.14),
    ("deployment", "elk-ech-prod", "dep_ech_prod",
     "gcp.kibana.gcp-us-central1", "usage", "kibana",
     "kibana", None, 0.08),
    # Ingress / egress panels filter ess.billing.type : data_in / data_out.
    ("elasticsearch", "klgfinopsdemo", "proj_es_finops",
     "elasticsearch.data_in_gcp-us-central1", "data_in", "elasticsearch",
     "search", None, 0.10),
    ("elasticsearch", "klgfinopsdemo", "proj_es_finops",
     "elasticsearch.data_out_gcp-us-central1", "data_out", "elasticsearch",
     "search", None, 0.10),
)


def emit(world, t0, t1, anchor):
    # Rely on Fleet package index template (priority 200). Never reintroduce
    # elk-ess-billing — it shadows package keyword mappings and breaks
    # OOTB Lens ("Could not locate field" on deployment_*).
    from src.ess_billing_health import remove_shadowing_template
    remove_shadowing_template()
    for ts in aligned(t0, t1, 24 * 60):
        rng = rng_for("essbill", ts.date())
        burn = DAILY_BURN_ECU * (0.92 + rng.random() * 0.16)
        day_start = ts.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1) - timedelta(milliseconds=1)
        for (dep_type, dep_name, dep_id, sku, bill_type, name,
             svc_type, machine_type, share) in LINES:
            ecu = round(burn * share, 3)
            # data_in / data_out quantity is GB transferred that day.
            if bill_type in ("data_in", "data_out"):
                qty = round(8.0 + rng.random() * 24.0, 3)
            else:
                qty = 1.0
            doc = metric_doc(DATASET, ts, "billing", 24 * 3600 * 1000)
            provider = "serverless" if dep_type != "deployment" else "gcp"
            cloud = {
                "provider": provider,
                "account": {"id": ORG_ID},
                "region": "gcp-us-central1",
                "instance": {"id": dep_id, "name": dep_name},
            }
            if machine_type:
                cloud["machine"] = {"type": machine_type}
            doc["cloud"] = cloud
            # Object shape required by package mapping (never a string).
            billing_cloud = {"service": {"type": svc_type}}
            if machine_type:
                billing_cloud["machine"] = {"type": machine_type}
            doc["ess"] = {"billing": {
                "name": name,
                "type": bill_type,
                "organization_id": ORG_ID,
                "deployment_id": dep_id,
                "deployment_name": dep_name,
                "deployment_type": dep_type,
                "sku": sku,
                "quantity": {
                    "value": qty,
                    "formatted_value": str(int(qty) if qty == int(qty) else qty),
                },
                "total_ecu": ecu,
                "from": isos(day_start),
                "to": iso(day_end),
                "cloud": billing_cloud,
            }}
            doc["event"]["dataset"] = DATASET
            doc["tags"] = ["billing", "synthetic"]
            yield doc
