"""Azure billing usage details -> metrics-azure.billing-default.
Per-VM usage docs plus resource-group service docs, daily."""
from datetime import timedelta

from src.generators.common import aligned, iso, metric_doc
from src.world.costs import azure_service_daily_cost, azure_vm_daily_cost
from src.world.scenarios import rng_for

DATA_STREAM = "metrics-azure.billing-default"
DATASET = "azure.billing"

VM_PRODUCTS = {
    "Standard_B2s": "Virtual Machines BS Series - B2s",
    "Standard_D4s_v5": "Virtual Machines Dsv5 Series - D4s v5",
    "Standard_D8s_v5": "Virtual Machines Dsv5 Series - D8s v5",
    "Standard_E4s_v5": "Virtual Machines Esv5 Series - E4s v5",
}


def _base(world, ts, sub, day, cost):
    doc = metric_doc(DATASET, ts, "billing", 24 * 3600 * 1000)
    doc["cloud"] = {"provider": "azure", "region": world.cfg["azure"]["region"]}
    doc["azure"] = {
        "subscription_id": sub["id"],
        "billing": {
            "currency": "USD",
            "account_name": "Meridian Dynamics EA",
            "department_name": world.bu(sub["business_unit"])["name"],
            "billing_period_id": (f"/subscriptions/{sub['id']}/providers/"
                                  f"Microsoft.Billing/billingPeriods/{day.strftime('%Y%m')}01"),
            "usage_date": iso(day),
            "usage_start": iso(day),
            "usage_end": iso(day + timedelta(days=1)),
            "actual_cost": cost,
            "pretax_cost": cost,
        },
    }
    return doc


def emit(world, t0, t1, anchor):
    subs = world.cfg["azure"]["subscriptions"]
    for ts in aligned(t0, t1, 24 * 60):
        day = ts - timedelta(days=1)

        # per-VM usage details
        for vm in world.azure_vms:
            sub = vm["subscription"]
            cost = azure_vm_daily_cost(world, vm, day, anchor)
            doc = _base(world, ts, sub, day, cost)
            doc["azure"]["billing"]["product"] = VM_PRODUCTS[vm["size"]]
            doc["azure"]["resource"] = {
                "id": vm["id"], "name": vm["name"],
                "group": vm["resource_group"],
                "type": "Microsoft.Compute/virtualMachines",
            }
            if vm["tags"]:
                doc["azure"]["resource"]["tags"] = vm["tags"]
            doc["cloud"]["instance"] = {"id": vm["id"], "name": vm["name"]}
            yield doc

        # per resource-group service costs
        for sub in subs:
            for rg in sub["resource_groups"]:
                for svc in world.cfg["azure"]["services"]:
                    if svc == "Virtual Machines":
                        continue
                    cost = azure_service_daily_cost(world, sub, rg, svc, day, anchor)
                    if cost < 0.5:
                        continue
                    doc = _base(world, ts, sub, day, cost)
                    doc["azure"]["billing"]["product"] = svc
                    doc["azure"]["resource"] = {
                        "group": rg,
                        "type": "Microsoft.Resources/resourceGroups",
                    }
                    yield doc
