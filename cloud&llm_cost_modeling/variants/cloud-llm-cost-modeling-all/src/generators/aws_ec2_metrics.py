"""EC2 CloudWatch-style metrics -> metrics-aws.ec2_metrics-default (5-min period)."""
from src.generators.common import aligned, metric_doc
from src.world.model import stable_uuid
from src.world.scenarios import (compromised_instance, crypto_incident_active,
                                 diurnal, rng_for)

DATA_STREAM = "metrics-aws.ec2_metrics-default"
DATASET = "aws.ec2_metrics"
PERIOD_MIN = 5

CORES = {"t3.medium": 2, "m5.large": 2, "m5.xlarge": 4, "c5.2xlarge": 8,
         "r5.large": 2, "g4dn.xlarge": 4}


def _cpu(world, inst, ts, anchor):
    rng = rng_for("cpu", inst.instance_id, int(ts.timestamp()))
    base = 8 + (hash(inst.instance_id) % 23)
    val = base * (0.55 + 0.9 * diurnal(ts)) * (0.85 + rng.random() * 0.3)
    if crypto_incident_active(world, ts, anchor) and \
            inst.instance_id == compromised_instance(world).instance_id:
        return rng.randint(96, 99)
    return int(max(1, min(94, val)))


def emit(world, t0, t1, anchor):
    marks = aligned(t0, t1, PERIOD_MIN)
    if not marks:
        return
    monitored = [i for i in world.ec2_instances if i.monitored]
    for ts in marks:
        for inst in monitored:
            rng = rng_for("ec2m", inst.instance_id, int(ts.timestamp()))
            cpu = _cpu(world, inst, ts, anchor)
            net_in = int(cpu * rng.randint(400_000, 900_000))
            net_out = int(net_in * (0.4 + rng.random() * 0.5))
            doc = metric_doc(DATASET, ts, "ec2", PERIOD_MIN * 60 * 1000)
            doc["cloud"] = {
                "provider": "aws", "region": inst.region,
                "availability_zone": inst.az,
                "account": {"id": inst.account["id"], "name": inst.account["name"]},
                "instance": {"id": inst.instance_id, "name": inst.name},
                "machine": {"type": inst.itype},
            }
            doc["host"] = {"name": inst.name}
            doc["aws"] = {
                "cloudwatch": {"namespace": "AWS/EC2"},
                "dimensions": {"InstanceId": inst.instance_id},
                "tags": inst.tags or None,
                "ec2": {
                    "instance": {
                        "core": {"count": CORES[inst.itype]},
                        "threads_per_core": 2,
                        "image": {"id": "ami-0" + stable_uuid("ami", inst.account["id"])[:8]},
                        "monitoring": {"state": "enabled"},
                        "state": {"name": "running", "code": 16},
                        "private": {"ip": inst.private_ip,
                                    "dns_name": f"ip-{inst.private_ip.replace('.', '-')}.ec2.internal"},
                        "public": {"ip": inst.public_ip,
                                   "dns_name": f"ec2-{inst.public_ip.replace('.', '-')}.compute-1.amazonaws.com"},
                    },
                    "metrics": {
                        "CPUUtilization": {"avg": cpu},
                        "NetworkIn": {"sum": net_in, "rate": net_in // (PERIOD_MIN * 60)},
                        "NetworkOut": {"sum": net_out, "rate": net_out // (PERIOD_MIN * 60)},
                        "NetworkPacketsIn": {"sum": net_in // 900},
                        "NetworkPacketsOut": {"sum": net_out // 900},
                        "DiskReadBytes": {"sum": rng.randint(0, 5_000_000)},
                        "DiskWriteBytes": {"sum": rng.randint(0, 9_000_000)},
                        "DiskReadOps": {"sum": rng.randint(0, 800)},
                        "DiskWriteOps": {"sum": rng.randint(0, 1200)},
                        "StatusCheckFailed": {"avg": 0},
                        "StatusCheckFailed_Instance": {"avg": 0},
                        "StatusCheckFailed_System": {"avg": 0},
                    },
                },
            }
            if doc["aws"]["tags"] is None:
                del doc["aws"]["tags"]
            yield doc
