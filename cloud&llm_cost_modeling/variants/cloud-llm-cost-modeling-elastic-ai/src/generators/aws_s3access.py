"""S3 server access logs -> logs-aws.s3access-default. Classic space-delimited line in `message`."""
from src.generators.common import log_doc, poisson_count, spread
from src.world.model import stable_uuid
from src.world.scenarios import (activity_multiplier, crypto_incident_active,
                                 s3_exposure_active, rng_for)

DATA_STREAM = "logs-aws.s3access-default"
DATASET = "aws.s3access"
BASE_RATE_PER_HOUR = 280

OPS = [
    (62, "REST.GET.OBJECT", "GET"),
    (16, "REST.PUT.OBJECT", "PUT"),
    (10, "REST.HEAD.OBJECT", "HEAD"),
    (8, "REST.GET.BUCKET", "GET"),
    (4, "REST.DELETE.OBJECT", "DELETE"),
]
KEY_POOL = ["media/img_{n}.png", "assets/app-{n}.js", "orders/2026/08/order-{n}.json",
            "backups/db-{n}.tar.gz", "models/checkpoint-{n}.pt", "logs/app-{n}.log",
            "exports/report-{n}.csv"]
UAS = ["aws-sdk-java/1.12.261 Linux/5.15", "Boto3/1.34.11 Python/3.11.4",
       "aws-cli/2.15.10 Python/3.11.6", "S3Console/0.4"]


def _bucket_region(world, bucket):
    for acct in world.aws_accounts:
        if bucket in acct.get("s3_buckets", []):
            return acct
    return world.aws_accounts[0]


def _line(world, rng, ts, bucket, acct, op, verb, key, requester_arn,
          remote_ip, status, bytes_sent, object_size, user_agent):
    owner = stable_uuid("owner", acct["id"]).replace("-", "") * 2
    owner = owner[:64]
    tstr = ts.strftime("[%d/%b/%Y:%H:%M:%S +0000]")
    req_id = stable_uuid("s3req", ts.isoformat(), rng.random()).replace("-", "")[:16].upper()
    uri = f"{verb} /{key if key != '-' else ''} HTTP/1.1"
    error_code = "-" if status < 400 else ("AccessDenied" if status == 403 else "NoSuchKey")
    region = "us-east-1"
    total_ms = rng.randint(8, 300)
    host_id = stable_uuid("host", bucket).replace("-", "") + "="
    return (
        f"{owner} {bucket} {tstr} {remote_ip} {requester_arn} {req_id} {op} "
        f"{key} \"{uri}\" {status} {error_code} "
        f"{bytes_sent if bytes_sent else '-'} {object_size if object_size else '-'} "
        f"{total_ms} {max(1, total_ms - 4)} \"-\" \"{user_agent}\" - "
        f"{host_id} SigV4 ECDHE-RSA-AES128-GCM-SHA256 AuthHeader "
        f"{bucket}.s3.{region}.amazonaws.com TLSv1.2"
    )


def emit(world, t0, t1, anchor):
    rng = rng_for("s3access", t0.isoformat())
    hours = (t1 - t0).total_seconds() / 3600
    mult = activity_multiplier(world, t0, anchor)
    buckets = [b for a in world.aws_accounts for b in a.get("s3_buckets", [])]
    weights = [4 if "prod" in b else 1 for b in buckets]

    for _ in range(poisson_count(rng, BASE_RATE_PER_HOUR * mult * hours)):
        ts = spread(rng, t0, t1)
        bucket = rng.choices(buckets, weights=weights)[0]
        acct = _bucket_region(world, bucket)
        _, op, verb = rng.choices(OPS, weights=[o[0] for o in OPS])[0]
        key = "-" if op == "REST.GET.BUCKET" else rng.choice(KEY_POOL).format(n=rng.randint(1, 500))
        ident = rng.choice(world.identities)
        anonymous = rng.random() < 0.04
        requester = "-" if anonymous else f"arn:aws:iam::{acct['id']}:user/{ident.user}"
        status = 200
        r = rng.random()
        if anonymous and r < 0.6:
            status = 403
        elif r < 0.03:
            status = 404
        size = rng.randint(2_000, 40_000_000) if "GET" in op or "PUT" in op else None
        sent = size if (status == 200 and verb == "GET") else None
        remote_ip = rng.choice(ident.source_ips) if not anonymous else \
            f"198.51.100.{rng.randint(2, 250)}"
        yield log_doc(DATASET, ts, _line(
            world, rng, ts, bucket, acct, op, verb, key, requester,
            remote_ip, status, sent, size, rng.choice(UAS)))

    # crypto incident: bulk exfil-style GETs from the attacker IP
    mid = t0 + (t1 - t0) / 2
    if crypto_incident_active(world, mid, anchor):
        sc = world.scenarios["crypto_incident"]
        acct = world.aws_account(sc["aws_account"])
        victim = world.humans_in_bu(acct["business_unit"])[2]
        for _ in range(poisson_count(rng, 40 * hours)):
            ts = spread(rng, t0, t1)
            bucket = rng.choice(acct["s3_buckets"])
            key = rng.choice(KEY_POOL).format(n=rng.randint(1, 500))
            size = rng.randint(5_000_000, 900_000_000)
            yield log_doc(DATASET, ts, _line(
                world, rng, ts, bucket, acct, "REST.GET.OBJECT", "GET", key,
                f"arn:aws:iam::{acct['id']}:user/{victim.user}",
                world.attacker_ip, 200, size, size,
                "Boto3/1.34.11 Python/3.11.4"))

    # S3 public exposure: anonymous GETs flood the fintech exports bucket
    if s3_exposure_active(world, mid, anchor):
        exp = world.scenarios["s3_exposure"]
        acct = world.aws_account(exp["aws_account"])
        for _ in range(poisson_count(rng, 55 * hours)):
            ts = spread(rng, t0, t1)
            key = f"exports/customer-{rng.randint(1000, 9999)}.csv"
            size = rng.randint(50_000, 8_000_000)
            yield log_doc(DATASET, ts, _line(
                world, rng, ts, exp["bucket"], acct, "REST.GET.OBJECT", "GET",
                key, "-", f"198.51.100.{rng.randint(2, 250)}", 200, size, size,
                "curl/8.5.0"))
