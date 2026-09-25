"""Usage-vs-cost stubs for the live FinOps overview.

Streams match the dashboard ES|QL (RDS DBLoad/connections, S3 StandardStorage,
Lambda invocations, Amazon MQ broker CPU, CloudWatch FilterLogEvents, EKS
kubelet pod CPU). Volume is hourly or daily so 120d backfill stays small.
"""
from src.generators.common import aligned, metric_doc
from src.profile import ce_account
from src.world.model import stable_uuid
from src.world.scenarios import diurnal, rng_for, usage_multiplier

PERIOD_H = 60


def _cloud(acct, region, **extra):
    billed = ce_account(acct)
    cloud = {
        "provider": "aws",
        "region": region,
        "account": {"id": billed["id"], "name": billed["name"]},
    }
    cloud.update(extra)
    return cloud


def _rds_instances(world):
    regions = world.cfg["aws"]["regions"]
    out = []
    for acct in world.aws_accounts:
        n = 2 if acct["env"] == "prod" else 1
        for i in range(n):
            out.append({
                "id": f"{acct['name']}-pg-{i:02d}",
                "account": acct,
                "region": regions[i % len(regions)],
                "idle": i == n - 1 and acct["env"] != "prod",
            })
    return out


class AwsRds:
    DATA_STREAM = "metrics-aws.rds-default"
    DATASET = "aws.rds"

    def emit(self, world, t0, t1, anchor):
        for ts in aligned(t0, t1, PERIOD_H):
            for db in _rds_instances(world):
                rng = rng_for("rds", db["id"], int(ts.timestamp()))
                load = (0.04 + rng.random() * 0.06) if db["idle"] else (
                    0.18 + 0.45 * diurnal(ts) * usage_multiplier(world, ts, anchor)
                    + rng.random() * 0.08)
                conns = 2 + rng.randint(0, 4) if db["idle"] else int(
                    18 + 40 * diurnal(ts) + rng.randint(0, 12))
                doc = metric_doc(self.DATASET, ts, "rds", PERIOD_H * 60 * 1000)
                doc["cloud"] = _cloud(db["account"], db["region"])
                doc["aws"] = {
                    "cloudwatch": {"namespace": "AWS/RDS"},
                    "dimensions": {"DBInstanceIdentifier": db["id"]},
                    "rds": {"metrics": {
                        "DBLoad": {"avg": round(load, 4)},
                        "DatabaseConnections": {"avg": conns},
                    }},
                }
                yield doc


class AwsS3DailyStorage:
    DATA_STREAM = "metrics-aws.s3_daily_storage-default"
    DATASET = "aws.s3_daily_storage"

    def emit(self, world, t0, t1, anchor):
        for ts in aligned(t0, t1, 24 * 60):
            for acct in world.aws_accounts:
                for bucket in acct.get("s3_buckets") or []:
                    rng = rng_for("s3sz", bucket, ts.date())
                    gib = 80 + (hash(bucket) % 900) + rng.randint(0, 40)
                    gib *= usage_multiplier(world, ts, anchor)
                    doc = metric_doc(self.DATASET, ts, "s3_daily_storage",
                                     24 * 3600 * 1000)
                    doc["cloud"] = _cloud(acct, "us-east-1")
                    doc["aws"] = {
                        "cloudwatch": {"namespace": "AWS/S3"},
                        "dimensions": {
                            "BucketName": bucket,
                            "StorageType": "StandardStorage",
                        },
                        "s3": {"metrics": {
                            "BucketSizeBytes": {"avg": int(gib * 1024 ** 3)},
                            "NumberOfObjects": {"avg": int(gib * 120)},
                        }},
                    }
                    yield doc


class AwsLambda:
    DATA_STREAM = "metrics-aws.lambda-default"
    DATASET = "aws.lambda"

    def emit(self, world, t0, t1, anchor):
        for ts in aligned(t0, t1, PERIOD_H):
            for acct in world.aws_accounts:
                rng = rng_for("lambda", acct["id"], int(ts.timestamp()))
                inv = int(40 * usage_multiplier(world, ts, anchor)
                          * (0.7 + rng.random() * 0.6)
                          * (0.35 if acct["env"] == "dev" else 1.0))
                fn = f"{acct['name']}-api"
                doc = metric_doc(self.DATASET, ts, "lambda", PERIOD_H * 60 * 1000)
                doc["cloud"] = _cloud(acct, "us-east-1")
                doc["aws"] = {
                    "cloudwatch": {"namespace": "AWS/Lambda"},
                    "dimensions": {"FunctionName": fn},
                    "lambda": {"metrics": {
                        "Invocations": {"sum": max(1, inv)},
                        "Errors": {"sum": int(inv * 0.01)},
                        "Duration": {"avg": round(80 + rng.random() * 40, 1)},
                    }},
                }
                yield doc


class AwsMqActive:
    DATA_STREAM = "metrics-aws_mq.activemq_metrics-default"
    DATASET = "aws_mq.activemq_metrics"

    def emit(self, world, t0, t1, anchor):
        acct = world.aws_accounts[0]
        for ts in aligned(t0, t1, PERIOD_H):
            rng = rng_for("amq", int(ts.timestamp()))
            cpu = 12 + 25 * diurnal(ts) + rng.random() * 8
            doc = metric_doc(self.DATASET, ts, "activemq_metrics",
                             PERIOD_H * 60 * 1000)
            doc["cloud"] = _cloud(acct, "us-east-1")
            doc["aws"] = {"amazonmq": {"metrics": {"activemq": {"broker": {
                "CpuUtilization": {"avg": round(cpu, 2)},
            }}}}}
            yield doc


class AwsMqRabbit:
    DATA_STREAM = "metrics-aws_mq.rabbitmq_metrics-default"
    DATASET = "aws_mq.rabbitmq_metrics"

    def emit(self, world, t0, t1, anchor):
        acct = world.aws_accounts[1] if len(world.aws_accounts) > 1 else world.aws_accounts[0]
        for ts in aligned(t0, t1, PERIOD_H):
            rng = rng_for("rmq", int(ts.timestamp()))
            cpu = 8 + 18 * diurnal(ts) + rng.random() * 6
            doc = metric_doc(self.DATASET, ts, "rabbitmq_metrics",
                             PERIOD_H * 60 * 1000)
            doc["cloud"] = _cloud(acct, "us-east-1")
            doc["aws"] = {"amazonmq": {"metrics": {"rabbitmq": {"broker": {
                "SystemCpuUtilization": {"max": round(cpu, 2)},
            }}}}}
            yield doc


class AwsCloudwatchUsage:
    DATA_STREAM = "metrics-aws.cloudwatch_metrics-default"
    DATASET = "aws.cloudwatch_metrics"

    def emit(self, world, t0, t1, anchor):
        for ts in aligned(t0, t1, PERIOD_H):
            for acct in world.aws_accounts:
                rng = rng_for("cwuse", acct["id"], int(ts.timestamp()))
                calls = int(800 * usage_multiplier(world, ts, anchor)
                            * (0.8 + rng.random() * 0.4))
                doc = metric_doc(self.DATASET, ts, "cloudwatch",
                                 PERIOD_H * 60 * 1000)
                doc["cloud"] = _cloud(acct, "us-east-1")
                doc["aws"] = {
                    "cloudwatch": {"namespace": "AWS/Usage"},
                    "dimensions": {
                        "Resource": "FilterLogEvents",
                        "Service": "CloudWatch Logs",
                        "Type": "API",
                    },
                    "usage": {"metrics": {"CallCount": {"sum": max(10, calls)}}},
                }
                yield doc


class Kubeletstats:
    DATA_STREAM = "metrics-kubeletstatsreceiver.otel-default"
    DATASET = "kubeletstatsreceiver.otel"

    def emit(self, world, t0, t1, anchor):
        _ensure_kubelet_template()
        pods = []
        for acct in world.aws_accounts[:4]:
            pods.append((acct, f"{acct['name']}-checkout"))
            pods.append((acct, f"{acct['name']}-api"))
        for ts in aligned(t0, t1, PERIOD_H):
            for acct, pod in pods:
                rng = rng_for("k8s", pod, int(ts.timestamp()))
                cpu = 0.04 + 0.22 * diurnal(ts) * usage_multiplier(world, ts, anchor)
                cpu += rng.random() * 0.03
                doc = metric_doc(self.DATASET, ts, "kubeletstats",
                                 PERIOD_H * 60 * 1000)
                billed = ce_account(acct)
                doc["cloud"] = {
                    "provider": "aws",
                    "region": "us-west-2",
                    "account": {"id": billed["id"], "name": billed["name"]},
                }
                doc["k8s"] = {"pod": {"name": pod, "uid": stable_uuid("pod", pod)}}
                doc["metrics"] = {"k8s": {"pod": {"cpu": {"usage": round(cpu, 5)}}}}
                yield doc


_KUBELET_OK = False


def _ensure_kubelet_template():
    global _KUBELET_OK
    if _KUBELET_OK:
        return
    from src.config import ELASTIC_URL, ES_HEADERS
    import requests
    body = {
        "index_patterns": ["metrics-kubeletstatsreceiver.otel-*"],
        "data_stream": {},
        "priority": 210,
        "template": {
            "mappings": {
                "properties": {
                    "@timestamp": {"type": "date"},
                    "metrics": {"properties": {
                        "k8s": {"properties": {
                            "pod": {"properties": {
                                "cpu": {"properties": {
                                    "usage": {"type": "double"},
                                }},
                            }},
                        }},
                    }},
                    "k8s": {"properties": {
                        "pod": {"properties": {
                            "name": {"type": "keyword"},
                            "uid": {"type": "keyword"},
                        }},
                    }},
                    "cloud": {"properties": {
                        "account": {"properties": {
                            "id": {"type": "keyword"},
                            "name": {"type": "keyword"},
                        }},
                    }},
                }
            }
        },
    }
    r = requests.put(
        f"{ELASTIC_URL}/_index_template/elk-kubeletstats",
        headers=ES_HEADERS, json=body, timeout=30)
    if r.status_code >= 300:
        print(f"  [warn] kubeletstats template: {r.status_code} {r.text[:200]}")
    _KUBELET_OK = True


aws_rds = AwsRds()
aws_s3_daily_storage = AwsS3DailyStorage()
aws_lambda = AwsLambda()
aws_mq_activemq = AwsMqActive()
aws_mq_rabbitmq = AwsMqRabbit()
aws_cloudwatch_usage = AwsCloudwatchUsage()
kubeletstats = Kubeletstats()
