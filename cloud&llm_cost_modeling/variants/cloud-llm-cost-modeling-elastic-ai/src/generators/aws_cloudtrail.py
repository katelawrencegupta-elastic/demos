"""CloudTrail management events -> logs-aws.cloudtrail-default.

Emits raw CloudTrail record JSON in `message`; the integration pipeline
parses it into ECS + aws.cloudtrail.* fields.
"""
import json

from src.generators.common import isos, iso, log_doc, poisson_count, spread
from src.world.model import stable_uuid
from src.world.scenarios import (activity_multiplier, crypto_incident_active,
                                 compromised_instance, s3_exposure_active, rng_for)

DATA_STREAM = "logs-aws.cloudtrail-default"
DATASET = "aws.cloudtrail"
BASE_RATE_PER_HOUR = 140

# weight, eventSource-prefix, eventName, readOnly, actor kind
CATALOG = [
    (22, "sts", "AssumeRole", True, "svc"),
    (16, "ec2", "DescribeInstances", True, "any"),
    (5, "ec2", "StartInstances", False, "human"),
    (5, "ec2", "StopInstances", False, "human"),
    (3, "ec2", "RunInstances", False, "human"),
    (2, "ec2", "TerminateInstances", False, "human"),
    (7, "s3", "ListBuckets", True, "any"),
    (2, "s3", "CreateBucket", False, "human"),
    (3, "s3", "GetBucketAcl", True, "any"),
    (2, "s3", "PutBucketPolicy", False, "human"),
    (2, "s3", "PutBucketPublicAccessBlock", False, "human"),
    (6, "signin", "ConsoleLogin", False, "human"),
    (4, "iam", "ListUsers", True, "human"),
    (1, "iam", "CreateAccessKey", False, "human"),
    (1, "iam", "AttachUserPolicy", False, "human"),
    (3, "lambda", "UpdateFunctionCode", False, "any"),
    (3, "rds", "DescribeDBInstances", True, "any"),
    (2, "eks", "DescribeCluster", True, "any"),
    (3, "cloudwatch", "PutMetricAlarm", False, "svc"),
]
ACCT_WEIGHTS = {
    "meridian-prod": 5, "meridian-staging": 2, "meridian-dev": 2,
    "meridian-security": 1, "meridian-logging": 1, "meridian-sandbox": 1.5,
    "meridian-mlops": 3, "meridian-fintech-prod": 3.5, "meridian-fintech-dev": 1.5,
}
SDK_UA = "aws-sdk-go/1.44.289 (go1.21.4; linux; amd64)"
CONSOLE_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"
ATTACKER_UA = "Boto3/1.34.11 md/Botocore#1.34.11 ua/2.0 os/linux#5.15.0 lang/python#3.11.4"


def _principal_id(ident):
    return "AIDA" + stable_uuid("principal", ident.user).replace("-", "")[:17].upper()


def _user_identity(ident, acct_id):
    return {
        "type": "IAMUser",
        "principalId": _principal_id(ident),
        "arn": f"arn:aws:iam::{acct_id}:user/{ident.user}",
        "accountId": acct_id,
        "accessKeyId": ident.aws_access_key,
        "userName": ident.user,
    }


def _record(world, rng, ts, ident, acct, source, name, read_only,
            source_ip=None, user_agent=None, request_params=None,
            response_elements=None, region=None):
    region = region or rng.choices(world.cfg["aws"]["regions"], weights=[5, 3, 2])[0]
    is_signin = source == "signin"
    rec = {
        "eventVersion": "1.08",
        "userIdentity": _user_identity(ident, acct["id"]),
        "eventTime": isos(ts),
        "eventSource": f"{source}.amazonaws.com",
        "eventName": name,
        "awsRegion": "us-east-1" if is_signin else region,
        "sourceIPAddress": source_ip or rng.choice(ident.source_ips),
        "userAgent": user_agent or (CONSOLE_UA if is_signin else SDK_UA),
        "requestParameters": request_params,
        "responseElements": response_elements,
        "requestID": stable_uuid("req", ts.isoformat(), rng.random()),
        "eventID": stable_uuid("evt", ts.isoformat(), rng.random()),
        "readOnly": read_only,
        "eventType": "AwsConsoleSignIn" if is_signin else "AwsApiCall",
        "managementEvent": True,
        "recipientAccountId": acct["id"],
        "eventCategory": "Management",
    }
    return rec


def _pick_actor(world, rng, acct, kind):
    bu = acct["business_unit"]
    humans = world.humans_in_bu(bu) or world.humans_in_bu("corpit")
    svcs = [i for i in world.identities if i.is_service]
    if kind == "human":
        return rng.choice(humans)
    if kind == "svc":
        return rng.choice(svcs)
    return rng.choice(humans if rng.random() < 0.6 else svcs)


def _request_params(rng, source, name, world, acct):
    if name == "RunInstances":
        return {"instancesSet": {"items": [{"imageId": "ami-0" + stable_uuid("ami", acct["id"])[:8],
                                            "instanceType": rng.choice(["m5.large", "c5.2xlarge", "t3.medium"]),
                                            "minCount": 1, "maxCount": rng.randint(1, 3)}]}}
    if name in ("StartInstances", "StopInstances", "TerminateInstances"):
        pool = world.ec2_in_account(acct["id"])
        if pool:
            return {"instancesSet": {"items": [{"instanceId": rng.choice(pool).instance_id}]}}
    if name in ("CreateBucket", "GetBucketAcl", "PutBucketPolicy",
                "PutBucketPublicAccessBlock"):
        if acct.get("s3_buckets"):
            return {"bucketName": rng.choice(acct["s3_buckets"])}
    if name == "AssumeRole":
        return {"roleArn": f"arn:aws:iam::{acct['id']}:role/{rng.choice(['deploy', 'read-only', 'admin', 'ci'])}-role",
                "roleSessionName": "session-" + str(rng.randint(1000, 9999))}
    return None


def emit(world, t0, t1, anchor):
    rng = rng_for("cloudtrail", t0.isoformat())
    hours = (t1 - t0).total_seconds() / 3600
    mult = activity_multiplier(world, t0, anchor)
    n = poisson_count(rng, BASE_RATE_PER_HOUR * mult * hours)
    accounts = world.aws_accounts
    weights = [ACCT_WEIGHTS[a["name"]] for a in accounts]

    for _ in range(n):
        ts = spread(rng, t0, t1)
        acct = rng.choices(accounts, weights=weights)[0]
        _, source, name, read_only, kind = rng.choices(
            CATALOG, weights=[c[0] for c in CATALOG])[0]
        ident = _pick_actor(world, rng, acct, kind)
        resp = None
        if name == "ConsoleLogin":
            ok = rng.random() > 0.06
            resp = {"ConsoleLogin": "Success" if ok else "Failure"}
        rec = _record(world, rng, ts, ident, acct, source, name, read_only,
                      request_params=_request_params(rng, source, name, world, acct),
                      response_elements=resp)
        yield log_doc(DATASET, ts, json.dumps(rec))

    # --- crypto incident: attacker activity from a compromised IAM user ----
    mid = t0 + (t1 - t0) / 2
    if crypto_incident_active(world, mid, anchor):
        sc = world.scenarios["crypto_incident"]
        acct = world.aws_account(sc["aws_account"])
        victim = world.humans_in_bu(acct["business_unit"])[2]
        inst = compromised_instance(world)
        window_start = anchor.timestamp() + sc["start_day"] * 86400
        in_first_two_hours = t0.timestamp() - window_start < 7200

        if in_first_two_hours:
            # brute-force console logins, then a success
            for k in range(poisson_count(rng, 8 * hours)):
                ts = spread(rng, t0, t1)
                rec = _record(world, rng, ts, victim, acct, "signin", "ConsoleLogin",
                              False, source_ip=world.attacker_ip, user_agent=CONSOLE_UA,
                              response_elements={"ConsoleLogin": "Failure"})
                yield log_doc(DATASET, ts, json.dumps(rec))

        attacker_events = [
            ("ec2", "DescribeInstances", True, None),
            ("sts", "GetCallerIdentity", True, None),
            ("s3", "ListBuckets", True, None),
            ("ec2", "RunInstances", False,
             {"instancesSet": {"items": [{"imageId": "ami-0feedbeefcafe01",
                                          "instanceType": "g4dn.xlarge",
                                          "minCount": 2, "maxCount": 4}]}}),
            ("iam", "CreateAccessKey", False, {"userName": victim.user}),
        ]
        for _ in range(poisson_count(rng, 10 * hours)):
            ts = spread(rng, t0, t1)
            source, name, ro, params = rng.choice(attacker_events)
            rec = _record(world, rng, ts, victim, acct, source, name, ro,
                          source_ip=world.attacker_ip, user_agent=ATTACKER_UA,
                          request_params=params, region=inst.region)
            yield log_doc(DATASET, ts, json.dumps(rec))

    # --- S3 public exposure: PutBucketPolicy that opens the fintech exports bucket
    if s3_exposure_active(world, mid, anchor):
        exp = world.scenarios["s3_exposure"]
        acct = world.aws_account(exp["aws_account"])
        actor = world.humans_in_bu(acct["business_unit"])[0]
        window_start = anchor.timestamp() + exp["start_day"] * 86400
        # Misconfig at the start of the window, then discovery / scramble later
        if t0.timestamp() - window_start < 3600:
            ts = spread(rng, t0, t1)
            rec = _record(
                world, rng, ts, actor, acct, "s3", "PutBucketPolicy", False,
                request_params={
                    "bucketName": exp["bucket"],
                    "bucketPolicy": {
                        "Version": "2012-10-17",
                        "Statement": [{"Effect": "Allow", "Principal": "*",
                                       "Action": "s3:GetObject",
                                       "Resource": f"arn:aws:s3:::{exp['bucket']}/*"}],
                    },
                })
            yield log_doc(DATASET, ts, json.dumps(rec))
        for _ in range(poisson_count(rng, 4 * hours)):
            ts = spread(rng, t0, t1)
            name = rng.choice(["GetBucketAcl", "GetBucketPolicy",
                               "PutBucketPublicAccessBlock"])
            rec = _record(world, rng, ts, actor, acct, "s3", name, name.startswith("Get"),
                          request_params={"bucketName": exp["bucket"]})
            yield log_doc(DATASET, ts, json.dumps(rec))
