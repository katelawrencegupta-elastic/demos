"""AWS Cost and Usage Report (CUR 2.0) -> metrics-aws_billing.cur-default.

Daily line items covering compute + Bedrock LLM spend so dashboards that join
cloud + LLM cost have CUR-shaped docs (in addition to metrics-aws.billing).
"""
from datetime import timedelta

from src.generators.common import aligned, iso, metric_doc
from src.world.costs import aws_daily_cost
from src.world.llm_traffic import iter_events
from src.world.model import stable_uuid

DATA_STREAM = "metrics-aws_billing.cur-default"
DATASET = "aws_billing.cur"
SCOPE = "cloud"  # also emitted under llm backfill via select()


def _line(world, ts, day, acct, product_code, usage_type, description,
          amount, usage_amount, resource_id=None, tags=None):
    payer = world.aws_accounts[0]
    doc = metric_doc(DATASET, ts, "cur", 24 * 3600 * 1000)
    doc["cloud"] = {"provider": "aws", "region": "us-east-1",
                   "account": {"id": acct["id"], "name": acct["name"]}}
    doc["aws_billing"] = {"cur": {
        "identity": {
            "line_item_id": stable_uuid("cur", acct["id"], product_code, day.date(),
                                        usage_type),
            "time_interval": f"{day.strftime('%Y-%m-%d')}T00:00:00Z/"
                             f"{(day + timedelta(days=1)).strftime('%Y-%m-%d')}T00:00:00Z",
        },
        "bill": {
            "billing_entity": "AWS",
            "billing_period_start_date": day.replace(day=1).strftime("%Y-%m-%dT00:00:00Z"),
            "billing_period_end_date": ts.strftime("%Y-%m-%dT00:00:00Z"),
            "payer_account_id": payer["id"],
            "payer_account_name": payer["name"],
            "type": "Anniversary",
        },
        "line_item": {
            "usage_account_id": acct["id"],
            "usage_account_name": acct["name"],
            "product_code": product_code,
            "usage_type": usage_type,
            "operation": "RunInstances" if product_code == "AmazonEC2" else "InvokeModel",
            "description": description,
            "usage_amount": usage_amount,
            "usage_start_date": iso(day),
            "usage_end_date": iso(ts),
            "unblended_cost": amount,
            "blended_cost": amount,
            "net_unblended_cost": amount,
            "currency_code": "USD",
            "type": "Usage",
            "resource_id": resource_id,
        },
        "product": {
            "product": product_code,
            "servicecode": product_code,
            "region_code": "us-east-1",
            "location": "US East (N. Virginia)",
        },
        "pricing": {"currency": "USD", "term": "OnDemand", "unit": "Hrs"
                    if product_code == "AmazonEC2" else "Tokens"},
        "cost": {"amortized_cost": amount, "net_amortized_cost": amount},
        "resource_tags": [f"{k}={v}" for k, v in (tags or {}).items()],
    }}
    doc["tags"] = ["synthetic", "aws_billing"]
    return doc


def emit(world, t0, t1, anchor):
    for ts in aligned(t0, t1, 24 * 60):
        day = ts - timedelta(days=1)

        # Classic service spend as CUR lines (subset of accounts for volume)
        for acct in world.aws_accounts:
            for svc in ("AmazonEC2", "AmazonS3", "AmazonRDS", "AmazonEKS"):
                amount = aws_daily_cost(world, acct, svc, day, anchor)
                if amount < 1:
                    continue
                yield _line(
                    world, ts, day, acct, svc,
                    f"BoxUsage:m5.large" if svc == "AmazonEC2" else f"{svc}-Usage",
                    f"{svc} usage for {acct['name']}",
                    amount, round(amount / 0.1, 2),
                    tags={"user:team": acct["business_unit"],
                          "user:env": acct["env"]},
                )

        # Bedrock LLM spend rolled from traffic engine
        bedrock_by_model = {}
        hour = day
        while hour < ts:
            from datetime import timedelta as td
            nxt = min(hour + td(hours=1), ts)
            for ev in iter_events(world, hour, nxt, anchor):
                if ev.model["provider"] != "aws_bedrock":
                    continue
                b = bedrock_by_model.setdefault(ev.model["id"],
                                                {"cost": 0.0, "tokens": 0})
                b["cost"] += ev.cost_usd
                b["tokens"] += ev.input_tokens + ev.output_tokens
            hour = nxt

        acct = next((a for a in world.aws_accounts if a["name"] == "meridian-mlops"),
                    world.aws_accounts[0])
        for model_id, b in bedrock_by_model.items():
            if b["cost"] < 0.01:
                continue
            yield _line(
                world, ts, day, acct, "AmazonBedrock",
                f"US-ModelInference-{model_id}",
                f"Bedrock model inference {model_id}",
                round(b["cost"], 4), float(b["tokens"]),
                resource_id=model_id,
                tags={"user:team": "mlplatform", "user:app": "fraud-nlp"},
            )
