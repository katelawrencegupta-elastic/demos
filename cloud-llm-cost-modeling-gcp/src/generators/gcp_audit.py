"""GCP audit logs -> logs-gcp.audit-default. Raw LogEntry JSON in `message`."""
import json

from src.generators.common import log_doc, poisson_count, spread
from src.world.model import stable_uuid
from src.world.scenarios import (activity_multiplier, genai_ramp_active,
                                 ml_burn_active, rng_for)

DATA_STREAM = "logs-gcp.audit-default"
DATASET = "gcp.audit"
BASE_RATE_PER_HOUR = 55

METHODS = [
    (10, "compute.googleapis.com", "v1.compute.instances.start", "compute.instances.start"),
    (8, "compute.googleapis.com", "v1.compute.instances.stop", "compute.instances.stop"),
    (5, "compute.googleapis.com", "v1.compute.instances.insert", "compute.instances.create"),
    (3, "compute.googleapis.com", "v1.compute.instances.delete", "compute.instances.delete"),
    (6, "compute.googleapis.com", "v1.compute.instances.setMetadata", "compute.instances.setMetadata"),
    (12, "bigquery.googleapis.com", "google.cloud.bigquery.v2.JobService.InsertJob", "bigquery.jobs.create"),
    (2, "cloudresourcemanager.googleapis.com", "SetIamPolicy", "resourcemanager.projects.setIamPolicy"),
    (5, "storage.googleapis.com", "storage.buckets.get", "storage.buckets.get"),
    (4, "aiplatform.googleapis.com", "google.cloud.aiplatform.v1.PredictionService.Predict",
     "aiplatform.endpoints.predict"),
    (3, "aiplatform.googleapis.com", "google.cloud.aiplatform.v1.JobService.CreateCustomJob",
     "aiplatform.customJobs.create"),
]


def _entry(world, rng, ts, proj, service, method, permission, principal, caller_ip):
    if service == "compute.googleapis.com":
        pool = [i for i in world.gce_instances if i["project"]["id"] == proj["id"]]
        inst = rng.choice(pool) if pool else None
        resource_name = (f"projects/{proj['id']}/zones/{inst['zone']}/instances/{inst['name']}"
                         if inst else f"projects/{proj['id']}")
        resource = {"type": "gce_instance",
                    "labels": {"instance_id": inst["id"] if inst else "0",
                               "project_id": proj["id"],
                               "zone": inst["zone"] if inst else "us-central1-a"}}
    elif service == "bigquery.googleapis.com":
        resource_name = f"projects/{proj['id']}/jobs/job_{stable_uuid('bq', ts.isoformat(), rng.random())[:12]}"
        resource = {"type": "bigquery_project",
                    "labels": {"project_id": proj["id"], "location": "US"}}
    else:
        resource_name = f"projects/{proj['id']}"
        resource = {"type": "project", "labels": {"project_id": proj["id"]}}

    tstr = ts.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    return {
        "insertId": stable_uuid("gcplog", ts.isoformat(), rng.random())[:20],
        "logName": f"projects/{proj['id']}/logs/cloudaudit.googleapis.com%2Factivity",
        "protoPayload": {
            "@type": "type.googleapis.com/google.cloud.audit.AuditLog",
            "authenticationInfo": {"principalEmail": principal},
            "authorizationInfo": [{"granted": True, "permission": permission,
                                   "resourceAttributes": {}}],
            "methodName": method,
            "requestMetadata": {
                "callerIp": caller_ip,
                "callerSuppliedUserAgent": "google-cloud-sdk gcloud/488.0.0",
            },
            "resourceName": resource_name,
            "serviceName": service,
            "status": {},
        },
        "receiveTimestamp": tstr,
        "resource": resource,
        "severity": "NOTICE",
        "timestamp": tstr,
    }


def _principal(world, rng, proj):
    if rng.random() < 0.35:
        sa = rng.choice([i for i in world.identities if i.is_service])
        return f"{sa.user}@{proj['id']}.iam.gserviceaccount.com", sa.source_ips[0]
    humans = world.humans_in_bu(proj["business_unit"]) or world.humans_in_bu("mlplatform")
    h = rng.choice(humans)
    return h.email, rng.choice(h.source_ips)


def emit(world, t0, t1, anchor):
    rng = rng_for("gcpaudit", t0.isoformat())
    hours = (t1 - t0).total_seconds() / 3600
    mult = activity_multiplier(world, t0, anchor)
    projects = world.cfg["gcp"]["projects"]
    proj_weights = []
    for p in projects:
        if p["id"] == "meridian-ml-prod":
            proj_weights.append(4)
        elif p["id"] == "meridian-data-warehouse":
            proj_weights.append(3)
        elif p["id"] == "meridian-genai-poc":
            proj_weights.append(2)
        else:
            proj_weights.append(1.5)

    for _ in range(poisson_count(rng, BASE_RATE_PER_HOUR * mult * hours)):
        ts = spread(rng, t0, t1)
        proj = rng.choices(projects, weights=proj_weights)[0]
        _, service, method, perm = rng.choices(METHODS, weights=[m[0] for m in METHODS])[0]
        principal, ip = _principal(world, rng, proj)
        yield log_doc(DATASET, ts, json.dumps(
            _entry(world, rng, ts, proj, service, method, perm, principal, ip)))

    # ML training burn: churn of GPU instances + BQ jobs in ml-prod
    mid = t0 + (t1 - t0) / 2
    if ml_burn_active(world, mid, anchor):
        proj = next(p for p in projects
                    if p["id"] == world.scenarios["ml_burn"]["gcp_project"])
        burn_methods = [
            ("compute.googleapis.com", "v1.compute.instances.insert", "compute.instances.create"),
            ("compute.googleapis.com", "v1.compute.instances.delete", "compute.instances.delete"),
            ("bigquery.googleapis.com", "google.cloud.bigquery.v2.JobService.InsertJob", "bigquery.jobs.create"),
        ]
        for _ in range(poisson_count(rng, 28 * hours)):
            ts = spread(rng, t0, t1)
            service, method, perm = rng.choice(burn_methods)
            principal, ip = _principal(world, rng, proj)
            yield log_doc(DATASET, ts, json.dumps(
                _entry(world, rng, ts, proj, service, method, perm, principal, ip)))

    # GenAI shadow-IT ramp: Vertex AI predict + custom jobs
    if genai_ramp_active(world, mid, anchor):
        proj = next(p for p in projects
                    if p["id"] == world.scenarios["genai_ramp"]["gcp_project"])
        genai_methods = [
            ("aiplatform.googleapis.com",
             "google.cloud.aiplatform.v1.PredictionService.Predict",
             "aiplatform.endpoints.predict"),
            ("aiplatform.googleapis.com",
             "google.cloud.aiplatform.v1.JobService.CreateCustomJob",
             "aiplatform.customJobs.create"),
            ("compute.googleapis.com", "v1.compute.instances.insert",
             "compute.instances.create"),
        ]
        for _ in range(poisson_count(rng, 14 * hours)):
            ts = spread(rng, t0, t1)
            service, method, perm = rng.choice(genai_methods)
            principal, ip = _principal(world, rng, proj)
            yield log_doc(DATASET, ts, json.dumps(
                _entry(world, rng, ts, proj, service, method, perm, principal, ip)))
