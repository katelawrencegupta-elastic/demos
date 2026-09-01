"""AWS billing -> metrics-aws.billing-default.

Two flavors, mirroring the real integration:
- CloudWatch EstimatedCharges (cumulative month-to-date), every 12h,
  per account and per account+service.
- Cost Explorer daily groups (UnblendedCost et al) by SERVICE,
  LINKED_ACCOUNT, and TAG cost_center.
"""
from datetime import timedelta

from src.generators.common import aligned, metric_doc
from src.world.costs import aws_daily_cost
from src.world.scenarios import rng_for

DATA_STREAM = "metrics-aws.billing-default"
DATASET = "aws.billing"

SERVICE_LABELS = {
    "AmazonEC2": "Amazon Elastic Compute Cloud - Compute",
    "AmazonS3": "Amazon Simple Storage Service",
    "AmazonRDS": "Amazon Relational Database Service",
    "AWSLambda": "AWS Lambda",
    "AmazonEKS": "Amazon Elastic Container Service for Kubernetes",
    "AmazonCloudWatch": "AmazonCloudWatch",
    "AWSDataTransfer": "AWS Data Transfer",
    "AmazonGuardDuty": "Amazon GuardDuty",
}


def _base(world, ts, acct=None, period_h=12):
    doc = metric_doc(DATASET, ts, "billing", period_h * 3600 * 1000)
    doc["cloud"] = {"provider": "aws", "region": "us-east-1"}
    if acct:
        doc["cloud"]["account"] = {"id": acct["id"], "name": acct["name"]}
        doc["aws"] = {"linked_account": {"id": acct["id"], "name": acct["name"]}}
    else:
        payer = world.aws_accounts[0]
        doc["cloud"]["account"] = {"id": payer["id"], "name": payer["name"]}
        doc["aws"] = {}
    return doc


def _month_to_date(world, acct, service, ts, anchor):
    """Cumulative spend for the invoice month up to ts."""
    day = ts.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    total = 0.0
    while day < ts:
        frac = min(1.0, (ts - day).total_seconds() / 86400)
        if service is None:
            daily = sum(aws_daily_cost(world, acct, s, day, anchor)
                        for s in world.cfg["aws"]["services"])
        else:
            daily = aws_daily_cost(world, acct, service, day, anchor)
        total += daily * frac
        day += timedelta(days=1)
    return round(total, 2)


def _cost_explorer_doc(world, ts, day, group_key, group_type, group_value,
                       amount, rng):
    doc = _base(world, ts, period_h=24)
    doc["aws"]["billing"] = {
        "start_date": day.strftime("%Y-%m-%d"),
        "end_date": (day + timedelta(days=1)).strftime("%Y-%m-%d"),
        "group_definition": {"key": group_key, "type": group_type},
        "group_by": {group_key: group_value},
        "Currency": "USD",
        "UnblendedCost": {"amount": amount, "unit": "USD"},
        "AmortizedCost": {"amount": amount, "unit": "USD"},
        "BlendedCost": {"amount": round(amount * (0.98 + rng.random() * 0.04), 2), "unit": "USD"},
        "NormalizedUsageAmount": {"amount": round(amount * rng.uniform(4, 9), 1), "unit": "N/A"},
        "UsageQuantity": {"amount": round(amount * rng.uniform(2, 6), 1), "unit": "N/A"},
    }
    return doc


def emit(world, t0, t1, anchor):
    services = world.cfg["aws"]["services"]

    # ---- EstimatedCharges (every 12h, cumulative) --------------------------
    for ts in aligned(t0, t1, 12 * 60):
        for acct in world.aws_accounts:
            combos = [None] + services
            for svc in combos:
                doc = _base(world, ts, acct)
                billing = {
                    "Currency": "USD",
                    "EstimatedCharges": int(_month_to_date(world, acct, svc, ts, anchor)),
                }
                if svc:
                    billing["ServiceName"] = svc
                doc["aws"]["billing"] = billing
                doc["aws"]["cloudwatch"] = {"namespace": "AWS/Billing"}
                yield doc

    # ---- Cost Explorer daily groups (at each midnight, for previous day) ---
    for ts in aligned(t0, t1, 24 * 60):
        day = ts - timedelta(days=1)
        rng = rng_for("ce", day.date())

        totals_by_acct = {
            a["id"]: {s: aws_daily_cost(world, a, s, day, anchor) for s in services}
            for a in world.aws_accounts
        }

        for svc in services:
            amount = round(sum(t[svc] for t in totals_by_acct.values()), 2)
            yield _cost_explorer_doc(world, ts, day, "SERVICE", "DIMENSION",
                                     SERVICE_LABELS[svc], amount, rng)

        for acct in world.aws_accounts:
            amount = round(sum(totals_by_acct[acct["id"]].values()), 2)
            yield _cost_explorer_doc(world, ts, day, "LINKED_ACCOUNT", "DIMENSION",
                                     acct["name"], amount, rng)

        # TAG cost_center attribution incl. the untagged bucket
        by_cc = {}
        for acct in world.aws_accounts:
            total = sum(totals_by_acct[acct["id"]].values())
            cc = world.bu(acct["business_unit"])["cost_center"]
            if cc is None:
                by_cc["cost_center$"] = by_cc.get("cost_center$", 0) + total
            else:
                tagged = total * 0.85       # tag drift: ~15% unattributed
                by_cc[f"cost_center${cc}"] = by_cc.get(f"cost_center${cc}", 0) + tagged
                by_cc["cost_center$"] = by_cc.get("cost_center$", 0) + (total - tagged)
        for tag_value, amount in by_cc.items():
            yield _cost_explorer_doc(world, ts, day, "COST_CENTER", "TAG",
                                     tag_value, round(amount, 2), rng)
