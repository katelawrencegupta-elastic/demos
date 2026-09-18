"""Generate FinOps rightsizing seed docs (expanded action catalog).

Writes elasticsearch/live/rightsizing-seed.ndjson for bulk ingest.
Stable document ids so re-seeding upserts rather than duplicating.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "elasticsearch" / "live" / "rightsizing-seed.ndjson"

TS = "2026-09-09T16:00:00.000Z"
REGION = "us-west-2"

ACCOUNTS = {
    "apm-dev": {"id": "041298796264", "name": "apm-dev"},
    "apm-stage": {"id": "985408759551", "name": "apm-stage"},
    "esf-a": {"id": "439106060789", "name": "ESF"},
    "esf-b": {"id": "119672459156", "name": "ESF"},
}


def _id(*parts: str) -> str:
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode()).digest()[:18].hex()


def _doc(
    *,
    account_key: str,
    action: str,
    finding: str,
    resource_type: str,
    resource_name: str,
    resource_arn: str,
    current_type: str,
    recommended_type: str,
    status: str,
    savings: float,
    risk: str = "Low",
    owner: str = "platform",
    source: str = "compute_optimizer",
    lookback_days: int = 14,
    realized: float | None = None,
    instance_id: str | None = None,
    machine: str | None = None,
    hidden_reason: str = "seeded_sample",
    case_id: str | None = None,
) -> dict:
    acct = ACCOUNTS[account_key]
    cloud: dict = {
        "provider": "aws",
        "region": REGION,
        "account": {"id": acct["id"], "name": acct["name"]},
    }
    if instance_id:
        cloud["instance"] = {"id": instance_id, "name": resource_name}
    if machine:
        cloud["machine"] = {"type": machine}
    rs = {
        "id": _id(resource_arn, finding, recommended_type, action),
        "action": action,
        "finding": finding,
        "resource_type": resource_type,
        "resource_arn": resource_arn,
        "resource_name": resource_name,
        "current_type": current_type,
        "recommended_type": recommended_type,
        "status": status,
        "estimated_monthly_savings": savings,
        "performance_risk": risk,
        "lookback_days": lookback_days,
        "owner": owner,
        "source": source,
        "currency": "USD",
        "hidden_reason": hidden_reason,
    }
    if realized is not None:
        rs["realized_savings"] = realized
    if case_id:
        rs["case_id"] = case_id
    return {
        "@timestamp": TS,
        "cloud": cloud,
        "data_stream": {
            "type": "logs",
            "dataset": "finops.rightsizing",
            "namespace": "default",
        },
        "event": {"dataset": "finops.rightsizing", "kind": "event"},
        "finops": {"rightsizing": rs},
    }


def seed_docs() -> list[dict]:
    """Diverse open / in_progress / done / hidden recs across action types."""
    docs = [
        # --- downsize (classic CO) ---
        _doc(
            account_key="apm-dev",
            action="downsize",
            finding="OVER_PROVISIONED",
            resource_type="ec2",
            resource_name="actions-runner",
            resource_arn="arn:aws:ec2:us-west-2:041298796264:instance/i-09c920d4ff962442f",
            current_type="m5.large",
            recommended_type="t3.medium",
            status="in_progress",
            savings=38.4,
            owner="platform",
            instance_id="i-09c920d4ff962442f",
            machine="m5.large",
            case_id="case-rs-actions-runner",
        ),
        _doc(
            account_key="apm-stage",
            action="downsize",
            finding="OVER_PROVISIONED",
            resource_type="ec2",
            resource_name="ai-bridge",
            resource_arn="arn:aws:ec2:us-west-2:985408759551:instance/i-046010bf81f3e6e54",
            current_type="c6i.xlarge",
            recommended_type="c6i.large",
            status="open",
            savings=61.2,
            owner="apm",
            instance_id="i-046010bf81f3e6e54",
            machine="c6i.xlarge",
        ),
        _doc(
            account_key="apm-stage",
            action="downsize",
            finding="OVER_PROVISIONED",
            resource_type="ec2",
            resource_name="apm-stage-sample-worker",
            resource_arn="arn:aws:ec2:us-west-2:985408759551:instance/i-0sampledone01",
            current_type="c5.xlarge",
            recommended_type="c5.large",
            status="done",
            savings=62.1,
            realized=58.4,
            owner="apm",
            instance_id="i-0sampledone01",
            machine="c5.xlarge",
        ),
        _doc(
            account_key="apm-stage",
            action="downsize",
            finding="OVER_PROVISIONED",
            resource_type="rds",
            resource_name="apm-stage-postgres",
            resource_arn="arn:aws:rds:us-west-2:985408759551:db:apm-stage-postgres",
            current_type="db.r6g.xlarge",
            recommended_type="db.r6g.large",
            status="open",
            savings=94.0,
            owner="apm",
            risk="Medium",
        ),
        # --- upsize ---
        _doc(
            account_key="apm-stage",
            action="upsize",
            finding="UNDER_PROVISIONED",
            resource_type="ec2",
            resource_name="checkout-api",
            resource_arn="arn:aws:ec2:us-west-2:985408759551:instance/i-0upsize001",
            current_type="t3.small",
            recommended_type="t3.medium",
            status="open",
            savings=0.0,  # cost increase — still a rec
            risk="High",
            owner="checkout",
            instance_id="i-0upsize001",
            machine="t3.small",
        ),
        _doc(
            account_key="esf-a",
            action="upsize",
            finding="UNDER_PROVISIONED",
            resource_type="rds",
            resource_name="esf-metrics-db",
            resource_arn="arn:aws:rds:us-west-2:439106060789:db:esf-metrics-db",
            current_type="db.t3.medium",
            recommended_type="db.r6g.large",
            status="open",
            savings=0.0,
            risk="High",
            owner="esf",
        ),
        # --- stop_idle (workflow + CO) ---
        _doc(
            account_key="apm-dev",
            action="stop_idle",
            finding="IDLE",
            resource_type="ec2",
            resource_name="legacy-batch",
            resource_arn="arn:aws:ec2:us-west-2:041298796264:instance/i-0idleec201",
            current_type="m5.xlarge",
            recommended_type="review",
            status="open",
            savings=0.0,  # workflow-invented: do not invent USD
            source="spend_spike_workflow",
            owner="finops-workflow",
            instance_id="i-0idleec201",
            machine="m5.xlarge",
            case_id="case-spike-legacy-batch",
        ),
        _doc(
            account_key="apm-stage",
            action="stop_idle",
            finding="IDLE",
            resource_type="rds",
            resource_name="apm-stage-devtools",
            resource_arn="arn:aws:rds:us-west-2:985408759551:db:apm-stage-devtools",
            current_type="rds",
            recommended_type="review",
            status="open",
            savings=0.0,
            source="spend_spike_workflow",
            owner="finops-workflow",
            case_id="case-spike-devtools-rds",
        ),
        # --- delete_volume / unattached EBS ---
        _doc(
            account_key="apm-dev",
            action="delete_volume",
            finding="UNATTACHED",
            resource_type="ebs",
            resource_name="orphaned-gp3",
            resource_arn="arn:aws:ec2:us-west-2:041298796264:volume/vol-0samplehide01",
            current_type="gp3",
            recommended_type="delete",
            status="hidden",
            savings=32.0,
            risk="High",
            owner="platform",
        ),
        _doc(
            account_key="apm-stage",
            action="delete_volume",
            finding="UNATTACHED",
            resource_type="ebs",
            resource_name="old-snapshot-vol",
            resource_arn="arn:aws:ec2:us-west-2:985408759551:volume/vol-0unattached02",
            current_type="gp2",
            recommended_type="delete",
            status="open",
            savings=18.5,
            owner="apm",
        ),
        # --- migrate_generation ---
        _doc(
            account_key="apm-stage",
            action="migrate_generation",
            finding="OVER_PROVISIONED",
            resource_type="ec2",
            resource_name="ingest-worker",
            resource_arn="arn:aws:ec2:us-west-2:985408759551:instance/i-0migragen01",
            current_type="m5.2xlarge",
            recommended_type="m7g.xlarge",
            status="open",
            savings=112.0,
            owner="platform",
            instance_id="i-0migragen01",
            machine="m5.2xlarge",
        ),
        _doc(
            account_key="esf-a",
            action="migrate_generation",
            finding="OVER_PROVISIONED",
            resource_type="ec2",
            resource_name="esf-compute-a",
            resource_arn="arn:aws:ec2:us-west-2:439106060789:instance/i-0migragen02",
            current_type="c5.4xlarge",
            recommended_type="c7g.2xlarge",
            status="in_progress",
            savings=186.4,
            owner="esf",
            risk="Medium",
            instance_id="i-0migragen02",
            machine="c5.4xlarge",
            case_id="case-rs-esf-compute",
        ),
        # --- gp2_to_gp3 ---
        _doc(
            account_key="apm-dev",
            action="gp2_to_gp3",
            finding="OVER_PROVISIONED",
            resource_type="ebs",
            resource_name="actions-runner-root",
            resource_arn="arn:aws:ec2:us-west-2:041298796264:volume/vol-0gp2mig01",
            current_type="gp2",
            recommended_type="gp3",
            status="open",
            savings=9.6,
            owner="platform",
        ),
        _doc(
            account_key="apm-stage",
            action="gp2_to_gp3",
            finding="OVER_PROVISIONED",
            resource_type="ebs",
            resource_name="ai-bridge-data",
            resource_arn="arn:aws:ec2:us-west-2:985408759551:volume/vol-0gp2mig02",
            current_type="gp2",
            recommended_type="gp3",
            status="open",
            savings=14.2,
            owner="apm",
        ),
        # --- purchase_ri_sp ---
        _doc(
            account_key="apm-stage",
            action="purchase_ri_sp",
            finding="OPTIMIZE_PURCHASE",
            resource_type="ec2",
            resource_name="stable-fleet-coverage-gap",
            resource_arn="arn:aws:ec2:us-west-2:985408759551:instance/i-0rispcover01",
            current_type="on_demand",
            recommended_type="compute_sp_1y_no_upfront",
            status="open",
            savings=240.0,
            risk="Low",
            owner="finops",
            lookback_days=30,
            instance_id="i-0rispcover01",
            machine="m6i.large",
            source="billing_derived",
        ),
        _doc(
            account_key="esf-b",
            action="purchase_ri_sp",
            finding="OPTIMIZE_PURCHASE",
            resource_type="ec2",
            resource_name="esf-steady-workers",
            resource_arn="arn:aws:ec2:us-west-2:119672459156:instance/i-0rispcover02",
            current_type="on_demand",
            recommended_type="ec2_ri_1y_partial",
            status="open",
            savings=310.0,
            owner="finops",
            lookback_days=30,
            instance_id="i-0rispcover02",
            machine="c6i.xlarge",
            source="billing_derived",
        ),
        # --- schedule_offhours ---
        _doc(
            account_key="apm-dev",
            action="schedule_offhours",
            finding="IDLE",
            resource_type="ec2",
            resource_name="dev-sandbox-ui",
            resource_arn="arn:aws:ec2:us-west-2:041298796264:instance/i-0offhours01",
            current_type="always_on",
            recommended_type="weekday_9_to_7",
            status="open",
            savings=48.0,
            owner="platform",
            lookback_days=21,
            instance_id="i-0offhours01",
            machine="t3.large",
            source="metrics_derived",
        ),
        _doc(
            account_key="apm-stage",
            action="schedule_offhours",
            finding="IDLE",
            resource_type="ec2",
            resource_name="loadtest-harness",
            resource_arn="arn:aws:ec2:us-west-2:985408759551:instance/i-0offhours02",
            current_type="always_on",
            recommended_type="weekday_business_hours",
            status="in_progress",
            savings=72.5,
            owner="qa",
            lookback_days=21,
            instance_id="i-0offhours02",
            machine="c6i.2xlarge",
            source="metrics_derived",
            case_id="case-rs-loadtest-schedule",
        ),
        # --- rightsize_lambda ---
        _doc(
            account_key="apm-stage",
            action="rightsize_lambda",
            finding="OVER_PROVISIONED",
            resource_type="lambda",
            resource_name="checkout-token-mint",
            resource_arn="arn:aws:lambda:us-west-2:985408759551:function:checkout-token-mint",
            current_type="1024MB",
            recommended_type="512MB",
            status="open",
            savings=22.0,
            owner="checkout",
            lookback_days=14,
            source="compute_optimizer",
        ),
        _doc(
            account_key="apm-dev",
            action="rightsize_lambda",
            finding="OVER_PROVISIONED",
            resource_type="lambda",
            resource_name="log-shipper",
            resource_arn="arn:aws:lambda:us-west-2:041298796264:function:log-shipper",
            current_type="2048MB",
            recommended_type="1024MB",
            status="open",
            savings=11.4,
            owner="platform",
            source="compute_optimizer",
        ),
        # --- parked / false positive ---
        _doc(
            account_key="apm-stage",
            action="downsize",
            finding="OVER_PROVISIONED",
            resource_type="ec2",
            resource_name="burst-cache",
            resource_arn="arn:aws:ec2:us-west-2:985408759551:instance/i-0parked01",
            current_type="r6g.xlarge",
            recommended_type="r6g.large",
            status="hidden",
            savings=55.0,
            risk="High",
            owner="apm",
            hidden_reason="park_infeasible",
            instance_id="i-0parked01",
            machine="r6g.xlarge",
        ),
    ]
    return docs


def write_seed(path: Path = OUT) -> int:
    docs = seed_docs()
    lines: list[str] = []
    for doc in docs:
        rid = doc["finops"]["rightsizing"]["id"]
        lines.append(json.dumps({"create": {"_index": "logs-finops.rightsizing-default", "_id": rid}}))
        lines.append(json.dumps(doc, separators=(",", ":")))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(docs)


if __name__ == "__main__":
    n = write_seed()
    print(f"wrote {n} rightsizing seed docs -> {OUT}")
