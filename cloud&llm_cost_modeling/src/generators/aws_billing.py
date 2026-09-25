"""AWS billing -> metrics-aws.billing-default.

Two flavors, mirroring the real integration:
- CloudWatch EstimatedCharges (cumulative month-to-date), every 12h,
  per account and per account+service.
- Cost Explorer daily groups (UnblendedCost et al) by SERVICE,
  LINKED_ACCOUNT, INSTANCE_TYPE, AZ, and TAG cost_center.

SERVICE / INSTANCE_TYPE / AZ are slices of the same dollars as
LINKED_ACCOUNT — dashboards must not add those grains together.
"""
from datetime import timedelta

from src.generators.common import aligned, metric_doc
from src.profile import ce_account
from src.world.costs import aws_daily_cost
from src.world.scenarios import rng_for

_TEMPLATE_OK = False


def _ensure_ce_grain_template():
    """Map CE grains + group_definition key as keyword on every billing index.

    Without this, dynamic mapping makes ``group_definition.key`` a text field.
    Dashboard KQL / Lens term filters then fail or return empty on Serverless
    (non-aggregatable text); panels error with field / filter issues.
    """
    global _TEMPLATE_OK
    if _TEMPLATE_OK:
        return
    from src.config import ELASTIC_URL, ES_HEADERS
    import requests
    body = {
        "index_patterns": ["metrics-aws.billing-*"],
        "data_stream": {},
        "priority": 250,
        "template": {
            "mappings": {
                "properties": {
                    "data_stream": {"properties": {
                        "dataset": {"type": "keyword"},
                        "namespace": {"type": "keyword"},
                        "type": {"type": "keyword"},
                    }},
                    "cloud": {"properties": {
                        "account": {"properties": {
                            "id": {"type": "keyword"},
                            "name": {"type": "keyword"},
                        }},
                    }},
                    "aws": {"properties": {
                        "billing": {"properties": {
                            "group_definition": {"properties": {
                                "key": {"type": "keyword"},
                                "type": {"type": "keyword"},
                            }},
                            "group_by": {"properties": {
                                "INSTANCE_TYPE": {"type": "keyword"},
                                "AZ": {"type": "keyword"},
                                "SERVICE": {"type": "keyword"},
                                "LINKED_ACCOUNT": {"type": "keyword"},
                                "COST_CENTER": {"type": "keyword"},
                            }},
                        }},
                    }},
                }
            }
        },
    }
    r = requests.put(
        f"{ELASTIC_URL}/_index_template/elk-aws-billing-ce-grains",
        headers=ES_HEADERS, json=body, timeout=30)
    if r.status_code >= 300:
        print(f"  [warn] billing CE grain template: {r.status_code} {r.text[:200]}")
    _TEMPLATE_OK = True


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
    "AmazonMQ": "Amazon MQ",
}


def _base(world, ts, acct=None, period_h=12):
    doc = metric_doc(DATASET, ts, "billing", period_h * 3600 * 1000)
    doc["cloud"] = {"provider": "aws", "region": "us-east-1"}
    if acct:
        doc["cloud"]["account"] = {"id": acct["id"], "name": acct["name"]}
        doc["aws"] = {"linked_account": {"id": acct["id"], "name": acct["name"]}}
    else:
        payer = ce_account(world.aws_accounts[0])
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


def _allocate(total: float, weights: dict) -> dict:
    """Split `total` USD across keys proportional to weights; leftover to largest."""
    if not weights or total <= 0:
        return {}
    s = sum(weights.values())
    if s <= 0:
        return {}
    out = {k: round(total * w / s, 2) for k, w in weights.items()}
    drift = round(total - sum(out.values()), 2)
    if drift and out:
        k = max(out, key=out.get)
        out[k] = round(out[k] + drift, 2)
    return out


def _cost_explorer_doc(world, ts, day, group_key, group_type, group_value,
                       amount, rng, acct=None):
    doc = _base(world, ts, acct, period_h=24)
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
    _ensure_ce_grain_template()
    services = world.cfg["aws"]["services"]

    # ---- EstimatedCharges (every 12h, cumulative) --------------------------
    for ts in aligned(t0, t1, 12 * 60):
        for acct in world.aws_accounts:
            billed = ce_account(acct)
            combos = [None] + services
            for svc in combos:
                doc = _base(world, ts, billed)
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
        # Peel Amazon MQ from CloudWatch so SERVICE still equals LINKED_ACCOUNT.
        for acct in world.aws_accounts:
            cw = totals_by_acct[acct["id"]]["AmazonCloudWatch"]
            mq = round(cw * 0.16, 2)
            totals_by_acct[acct["id"]]["AmazonCloudWatch"] = round(cw - mq, 2)
            totals_by_acct[acct["id"]]["AmazonMQ"] = mq

        service_keys = list(services) + ["AmazonMQ"]

        for acct in world.aws_accounts:
            billed = ce_account(acct)
            by_svc = totals_by_acct[acct["id"]]

            for svc in service_keys:
                amount = round(by_svc[svc], 2)
                yield _cost_explorer_doc(
                    world, ts, day, "SERVICE", "DIMENSION",
                    SERVICE_LABELS[svc], amount, rng, billed)

            amount = round(sum(by_svc.values()), 2)
            yield _cost_explorer_doc(
                world, ts, day, "LINKED_ACCOUNT", "DIMENSION",
                billed["id"], amount, rng, billed)

            insts = world.ec2_in_account(acct["id"])
            type_w, az_w = {}, {}
            for inst in insts:
                type_w[inst.itype] = type_w.get(inst.itype, 0) + inst.hourly_usd
                az_w[inst.az] = az_w.get(inst.az, 0) + inst.hourly_usd

            ec2_cost = by_svc["AmazonEC2"]
            no_type = round(ec2_cost * 0.08, 2)
            for itype, amt in _allocate(round(ec2_cost - no_type, 2), type_w).items():
                yield _cost_explorer_doc(
                    world, ts, day, "INSTANCE_TYPE", "DIMENSION",
                    itype, amt, rng, billed)
            if no_type:
                yield _cost_explorer_doc(
                    world, ts, day, "INSTANCE_TYPE", "DIMENSION",
                    "NoInstanceType", no_type, rng, billed)

            az_pool = round(ec2_cost * 0.75 + by_svc["AmazonRDS"] * 0.5, 2)
            no_az = round(az_pool * 0.12, 2)
            for az, amt in _allocate(round(az_pool - no_az, 2), az_w).items():
                yield _cost_explorer_doc(
                    world, ts, day, "AZ", "DIMENSION", az, amt, rng, billed)
            if no_az:
                yield _cost_explorer_doc(
                    world, ts, day, "AZ", "DIMENSION", "NoAZ", no_az, rng, billed)

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
