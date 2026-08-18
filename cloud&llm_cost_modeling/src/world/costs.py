"""Daily cost model. Billing generators and dashboards share this so spend
lines up with the resource inventory and scenario timeline."""
from src.world.scenarios import (crypto_incident_active, genai_ramp_multiplier,
                                 growth, ml_burn_active, s3_exposure_active,
                                 sunday_batch_factor, rng_for)

AWS_SERVICE_BASES = {
    "AmazonS3": 60, "AmazonRDS": 180, "AWSLambda": 40, "AmazonEKS": 110,
    "AmazonCloudWatch": 55, "AWSDataTransfer": 90, "AmazonGuardDuty": 25,
}
GCP_SERVICE_BASES = {
    "BigQuery": 90, "Vertex AI": 120, "Cloud Storage": 35,
    "Cloud Logging": 22, "Cloud SQL": 48,
}
AZURE_SERVICE_BASES = {
    "Storage": 45, "Azure Kubernetes Service": 130, "Azure Monitor": 38,
    "Virtual Network": 25, "Azure Active Directory": 20,
}
ENV_FACTOR = {"prod": 1.0, "staging": 0.45, "dev": 0.3}


def _wk(day):
    return 0.9 if day.weekday() >= 5 else 1.0


def aws_daily_cost(world, acct, service, day, anchor) -> float:
    """USD spent by `acct` on `service` during the UTC day starting at `day`."""
    rng = rng_for("awscost", acct["id"], service, day.date())
    g = growth(world, day, anchor)
    noon = day.replace(hour=12)
    leak = world.scenarios["cost_leak"]

    if service == "AmazonEC2":
        cost = sum(i.hourly_usd * 24 for i in world.ec2_in_account(acct["id"]))
        cost *= 0.92 + rng.random() * 0.16
        sc = world.scenarios["crypto_incident"]
        if acct["id"] == sc["aws_account"] and crypto_incident_active(world, noon, anchor):
            cost += 8 * 0.526 * 24          # unauthorized g4dn.xlarge miners
        if acct["id"] == leak["aws_account"]:
            cost += leak["daily_cost_usd"] * 0.6   # orphaned instances
    else:
        cost = AWS_SERVICE_BASES[service] * ENV_FACTOR[acct["env"]]
        cost *= 0.85 + rng.random() * 0.3
        if acct["id"] == leak["aws_account"] and service == "AmazonRDS":
            cost += leak["daily_cost_usd"] * 0.4   # forgotten db cluster
        # S3 public exposure: egress spike on data transfer + S3
        exp = world.scenarios["s3_exposure"]
        if (acct["id"] == exp["aws_account"]
                and s3_exposure_active(world, noon, anchor)
                and service in ("AmazonS3", "AWSDataTransfer")):
            cost *= 4.5 if service == "AWSDataTransfer" else 2.2
    # Sunday ETL batch bumps Lambda / data transfer a bit
    cost *= sunday_batch_factor(noon)
    return round(cost * _wk(day) * g, 2)


def gcp_daily_cost(world, proj, service_desc, day, anchor) -> float:
    rng = rng_for("gcpcost", proj["id"], service_desc, day.date())
    g = growth(world, day, anchor)
    noon = day.replace(hour=12)
    if service_desc == "Compute Engine":
        cost = sum(i["hourly_usd"] * 24 for i in world.gce_instances
                   if i["project"]["id"] == proj["id"])
        cost *= 0.9 + rng.random() * 0.2
    else:
        cost = GCP_SERVICE_BASES[service_desc] * ENV_FACTOR[proj["env"]]
        if proj["id"] == "meridian-data-warehouse" and service_desc == "BigQuery":
            cost *= 3.2                      # the warehouse is BigQuery-heavy
        cost *= 0.85 + rng.random() * 0.3
    sc = world.scenarios["ml_burn"]
    if (proj["id"] == sc["gcp_project"]
            and service_desc in ("Compute Engine", "Vertex AI")
            and ml_burn_active(world, noon, anchor)):
        cost *= sc["cost_multiplier"]        # GPU training burn
    # GenAI shadow-IT ramp on the experiments project
    ramp = world.scenarios["genai_ramp"]
    if (proj["id"] == ramp["gcp_project"]
            and service_desc in ("Compute Engine", "Vertex AI")):
        cost *= genai_ramp_multiplier(world, noon, anchor)
    cost *= sunday_batch_factor(noon)
    return round(cost * _wk(day) * g, 2)


def azure_vm_daily_cost(world, vm, day, anchor) -> float:
    rng = rng_for("azvm", vm["id"], day.date())
    g = growth(world, day, anchor)
    noon = day.replace(hour=12)
    return round(vm["hourly_usd"] * 24 * (0.9 + rng.random() * 0.2)
                 * _wk(day) * sunday_batch_factor(noon) * g, 2)


def azure_service_daily_cost(world, sub, rg, service, day, anchor) -> float:
    rng = rng_for("azsvc", sub["id"], rg, service, day.date())
    g = growth(world, day, anchor)
    noon = day.replace(hour=12)
    cost = AZURE_SERVICE_BASES[service] * ENV_FACTOR[sub["env"]] / len(sub["resource_groups"])
    cost *= 0.85 + rng.random() * 0.3
    return round(cost * _wk(day) * sunday_batch_factor(noon) * g, 2)
