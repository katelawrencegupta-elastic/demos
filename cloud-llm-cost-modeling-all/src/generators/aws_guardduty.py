"""GuardDuty findings -> logs-aws.guardduty-default. Raw finding JSON in `message`."""
import json

from src.generators.common import isos, log_doc, poisson_count, spread
from src.world.model import stable_uuid
from src.world.scenarios import (compromised_instance, crypto_incident_active,
                                 s3_exposure_active, rng_for)

DATA_STREAM = "logs-aws.guardduty-default"
DATASET = "aws.guardduty"
BASELINE_PER_DAY = 18.0

BASELINE_TYPES = [
    ("Recon:EC2/PortProbeUnprotectedPort", 2.0,
     "EC2 instance has an unprotected port which is being probed by a known malicious host."),
    ("UnauthorizedAccess:EC2/SSHBruteForce", 4.0,
     "EC2 instance is being probed for SSH weak passwords."),
    ("Persistence:IAMUser/AnomalousBehavior", 5.0,
     "An API commonly used to maintain persistence was invoked in an anomalous way."),
    ("Discovery:S3/AnomalousBehavior", 3.0,
     "An S3 API commonly used to discover resources was invoked in an anomalous way."),
    ("Stealth:S3/ServerAccessLoggingDisabled", 4.0,
     "S3 server access logging was disabled on a bucket."),
    ("Policy:IAMUser/RootCredentialUsage", 6.0,
     "Root credentials were used to make an AWS API call."),
]


def _finding(world, rng, ts, acct, ftype, severity, title_desc, inst=None,
             action=None, first_seen=None, count=1):
    region = inst.region if inst else rng.choice(world.cfg["aws"]["regions"])
    detector = stable_uuid("detector", acct["id"]).replace("-", "")[:32]
    fid = stable_uuid("finding", ts.isoformat(), rng.random()).replace("-", "")
    inst = inst or (world.ec2_in_account(acct["id"]) or [None])[0]
    inst_details = {}
    if inst:
        inst_details = {
            "instanceId": inst.instance_id,
            "instanceType": inst.itype,
            "launchTime": "2026-05-01T09:00:00Z",
            "instanceState": "running",
            "availabilityZone": inst.az,
            "tags": [{"key": k, "value": v} for k, v in inst.tags.items()],
            "networkInterfaces": [{"privateIpAddress": inst.private_ip,
                                   "publicIp": inst.public_ip}],
        }
    return {
        "schemaVersion": "2.0",
        "accountId": acct["id"],
        "region": region,
        "partition": "aws",
        "id": fid,
        "arn": f"arn:aws:guardduty:{region}:{acct['id']}:detector/{detector}/finding/{fid}",
        "type": ftype,
        "resource": {"resourceType": "Instance", "instanceDetails": inst_details},
        "service": {
            "serviceName": "guardduty",
            "detectorId": detector,
            "action": action or {
                "actionType": "NETWORK_CONNECTION",
                "networkConnectionAction": {
                    "connectionDirection": "INBOUND",
                    "protocol": "TCP",
                    "blocked": False,
                    "localPortDetails": {"port": 22, "portName": "SSH"},
                    "remoteIpDetails": {
                        "ipAddressV4": f"91.240.{rng.randint(1, 254)}.{rng.randint(1, 254)}",
                        "organization": {"asn": "9009", "asnOrg": "M247 Ltd"},
                        "country": {"countryName": "Romania"},
                    },
                },
            },
            "archived": False,
            "count": count,
            "eventFirstSeen": isos(first_seen or ts),
            "eventLastSeen": isos(ts),
            "resourceRole": "TARGET",
        },
        "severity": severity,
        "createdAt": isos(first_seen or ts),
        "updatedAt": isos(ts),
        "title": title_desc.split(".")[0] + ".",
        "description": title_desc,
    }


def emit(world, t0, t1, anchor):
    rng = rng_for("guardduty", t0.isoformat())
    hours = (t1 - t0).total_seconds() / 3600

    for _ in range(poisson_count(rng, BASELINE_PER_DAY / 24 * hours)):
        ts = spread(rng, t0, t1)
        acct = rng.choice(world.aws_accounts)
        ftype, sev, desc = rng.choice(BASELINE_TYPES)
        yield log_doc(DATASET, ts, json.dumps(
            _finding(world, rng, ts, acct, ftype, sev, desc)))

    mid = t0 + (t1 - t0) / 2
    if crypto_incident_active(world, mid, anchor):
        sc = world.scenarios["crypto_incident"]
        acct = world.aws_account(sc["aws_account"])
        inst = compromised_instance(world)
        window_start_ts = anchor.timestamp() + sc["start_day"] * 86400
        from datetime import datetime, timezone
        first_seen = datetime.fromtimestamp(window_start_ts + 1800, tz=timezone.utc)
        hours_in = max(1.0, (t0.timestamp() - window_start_ts) / 3600)
        for _ in range(poisson_count(rng, 2.5 * hours)):
            ts = spread(rng, t0, t1)
            action = {
                "actionType": "NETWORK_CONNECTION",
                "networkConnectionAction": {
                    "connectionDirection": "OUTBOUND",
                    "protocol": "TCP",
                    "blocked": False,
                    "localIpDetails": {"ipAddressV4": inst.private_ip},
                    "remotePortDetails": {"port": 3333, "portName": "Unknown"},
                    "remoteIpDetails": {
                        "ipAddressV4": world.mining_pool_ip,
                        "organization": {"asn": "202425", "asnOrg": "IP Volume inc"},
                        "country": {"countryName": "Netherlands"},
                    },
                },
            }
            yield log_doc(DATASET, ts, json.dumps(_finding(
                world, rng, ts, acct,
                "CryptoCurrency:EC2/BitcoinTool.B", 8.0,
                f"EC2 instance {inst.instance_id} is querying an IP address that is "
                "associated with cryptocurrency-related activity.",
                inst=inst, action=action, first_seen=first_seen,
                count=int(hours_in * 4))))

    if s3_exposure_active(world, mid, anchor):
        exp = world.scenarios["s3_exposure"]
        acct = world.aws_account(exp["aws_account"])
        for _ in range(poisson_count(rng, 1.8 * hours)):
            ts = spread(rng, t0, t1)
            action = {
                "actionType": "AWS_API_CALL",
                "awsApiCallAction": {
                    "api": "GetObject",
                    "serviceName": "s3.amazonaws.com",
                    "callerType": "Remote IP",
                    "remoteIpDetails": {
                        "ipAddressV4": f"198.51.100.{rng.randint(2, 250)}",
                        "organization": {"asn": "16509", "asnOrg": "AMAZON-02"},
                        "country": {"countryName": "United States"},
                    },
                },
            }
            yield log_doc(DATASET, ts, json.dumps(_finding(
                world, rng, ts, acct,
                "Policy:S3/BucketAnonymousAccessGranted", 8.0,
                f"The S3 bucket {exp['bucket']} was granted public (anonymous) access.",
                action=action, count=rng.randint(20, 200))))
