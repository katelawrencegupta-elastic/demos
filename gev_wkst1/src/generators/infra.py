"""Host, Kubernetes node, and APM runtime metrics for every service."""
from __future__ import annotations

from datetime import timedelta

from src.config import DS_APM_INTERNAL, DS_HOST, DS_K8S_NODE
from src.generators.apm import _AGENT
from src.generators.common import base_labels, ds_meta, in_incident, iso
from src.world.model import World, rng_for

SCOPE = "all"


def _agent_for(pod) -> tuple[str, str]:
    if pod.language == "java":
        return "java", "java"
    if pod.language == "python":
        return "python", "python"
    if pod.language == "go":
        return "go", "go"
    return _AGENT.get(pod.service, ("go", "go"))


def emit_host_metrics(world: World, t0, t1, anchor):
    start, end = world.incident_window(anchor)
    cluster = world.cluster["name"]
    region = world.cluster.get("region", "us-east-1")
    rng = rng_for("hostmet", t0.isoformat())
    nodes = world.node_inventory()
    step = timedelta(minutes=1)
    cur = t0
    net_in = {n["name"]: rng.randint(8, 20) * 10**9 for n in nodes}
    net_out = {n["name"]: rng.randint(6, 16) * 10**9 for n in nodes}

    checkout_nodes = {p.node for p in world.pods_for("checkout-api")}

    while cur < t1:
        incident = in_incident(cur, start, end)
        progress = 0.0
        if incident:
            progress = (cur - start).total_seconds() / max((end - start).total_seconds(), 1)
        for node in nodes:
            name = node["name"]
            hot = incident and name in checkout_nodes
            cpu_pct = (0.62 + progress * 0.22 if hot else 0.28) + rng.uniform(-0.04, 0.05)
            cpu_pct = min(0.92, max(0.08, cpu_pct))
            mem_pct = (0.74 + progress * 0.16 if hot else 0.48) + rng.uniform(-0.03, 0.03)
            mem_pct = min(0.94, max(0.20, mem_pct))
            used = int(node["memory_bytes"] * mem_pct)
            actual_used = int(used * 0.92)
            disk_pct = 0.41 + (0.08 if hot else 0.0) + rng.uniform(-0.01, 0.02)
            net_in[name] += rng.randint(8, 40) * 1024 * 1024
            net_out[name] += rng.randint(6, 32) * 1024 * 1024
            load1 = round(node["cores"] * cpu_pct * rng.uniform(0.9, 1.15), 2)
            yield DS_HOST, {
                "@timestamp": iso(cur),
                "data_stream": ds_meta("metrics", "elasticco.host"),
                "metricset": {"name": "host", "period": 60000},
                "event": {"dataset": "system.cpu", "module": "system"},
                "host": {
                    "name": name,
                    "hostname": name,
                    "id": node["instance_id"],
                    "ip": node["ip"],
                    "architecture": "x86_64",
                    "os": {
                        "name": "Amazon Linux",
                        "platform": "linux",
                        "type": "linux",
                        "version": "2023",
                    },
                    "cpu": {"usage": round(cpu_pct, 4)},
                    "memory": {"used": {"pct": round(mem_pct, 4)}},
                },
                "system": {
                    "cpu": {
                        "cores": node["cores"],
                        "total": {
                            "norm": {"pct": round(cpu_pct, 4)},
                            "pct": round(cpu_pct * node["cores"], 4),
                        },
                        "user": {
                            "norm": {"pct": round(cpu_pct * 0.72, 4)},
                            "pct": round(cpu_pct * 0.72 * node["cores"], 4),
                        },
                        "system": {
                            "norm": {"pct": round(cpu_pct * 0.22, 4)},
                            "pct": round(cpu_pct * 0.22 * node["cores"], 4),
                        },
                    },
                    "memory": {
                        "total": node["memory_bytes"],
                        "used": {
                            "bytes": used,
                            "pct": round(mem_pct, 4),
                        },
                        "actual": {
                            "used": {
                                "bytes": actual_used,
                                "pct": round(actual_used / node["memory_bytes"], 4),
                            },
                            "free": node["memory_bytes"] - actual_used,
                        },
                    },
                    "load": {
                        "1": load1,
                        "5": round(load1 * 0.88, 2),
                        "15": round(load1 * 0.76, 2),
                    },
                    "filesystem": {
                        "used": {"pct": round(disk_pct, 4)},
                        "total": node["disk_bytes"],
                    },
                    "network": {
                        "in": {"bytes": net_in[name]},
                        "out": {"bytes": net_out[name]},
                    },
                },
                "cloud": {
                    "provider": "aws",
                    "region": region,
                    "availability_zone": node["az"],
                    "instance": {"id": node["instance_id"], "name": name},
                    "machine": {"type": node["machine_type"]},
                },
                "orchestrator": {"cluster": {"name": cluster}, "type": "kubernetes"},
                "labels": base_labels(),
                "tags": ["synthetic", "infrastructure", "host"],
            }
        cur += step


def emit_node_metrics(world: World, t0, t1, anchor):
    start, end = world.incident_window(anchor)
    cluster = world.cluster["name"]
    region = world.cluster.get("region", "us-east-1")
    rng = rng_for("nodemet", t0.isoformat())
    nodes = world.node_inventory()
    pods_by_node: dict[str, int] = {}
    for p in world.pods:
        pods_by_node[p.node] = pods_by_node.get(p.node, 0) + 1
    checkout_nodes = {p.node for p in world.pods_for("checkout-api")}

    step = timedelta(minutes=1)
    cur = t0
    while cur < t1:
        incident = in_incident(cur, start, end)
        progress = 0.0
        if incident:
            progress = (cur - start).total_seconds() / max((end - start).total_seconds(), 1)
        for node in nodes:
            name = node["name"]
            hot = incident and name in checkout_nodes
            cpu_pct = (0.58 + progress * 0.24 if hot else 0.26) + rng.uniform(-0.03, 0.04)
            cpu_pct = min(0.90, max(0.08, cpu_pct))
            mem_pct = (0.72 + progress * 0.18 if hot else 0.46) + rng.uniform(-0.03, 0.03)
            mem_pct = min(0.93, max(0.20, mem_pct))
            disk_pct = 0.40 + (0.07 if hot else 0.0)
            yield DS_K8S_NODE, {
                "@timestamp": iso(cur),
                "data_stream": ds_meta("metrics", "elasticco.k8s.node"),
                "metricset": {"name": "node"},
                "event": {"dataset": "kubernetes.node", "module": "kubernetes"},
                "orchestrator": {"cluster": {"name": cluster}, "type": "kubernetes"},
                "cloud": {
                    "provider": "aws",
                    "region": region,
                    "availability_zone": node["az"],
                    "instance": {"id": node["instance_id"]},
                },
                "host": {"name": name, "hostname": name, "id": node["instance_id"]},
                "kubernetes": {
                    "node": {
                        "name": name,
                        "cpu": {
                            "usage": {
                                "nanocores": int(cpu_pct * node["cores"] * 1_000_000_000),
                                "pct": round(cpu_pct, 4),
                            },
                            "capacity": {"cores": node["cores"]},
                        },
                        "memory": {
                            "usage": {
                                "bytes": int(node["memory_bytes"] * mem_pct),
                                "pct": round(mem_pct, 4),
                            },
                            "available": {"bytes": int(node["memory_bytes"] * (1 - mem_pct))},
                            "capacity": {"bytes": node["memory_bytes"]},
                        },
                        "fs": {
                            "used": {"bytes": int(node["disk_bytes"] * disk_pct)},
                            "capacity": {"bytes": node["disk_bytes"]},
                        },
                        "pod": {"count": pods_by_node.get(name, 0)},
                    }
                },
                "labels": base_labels(),
                "tags": ["synthetic", "kubernetes", "node"],
            }
        cur += step


def emit_apm_internal(world: World, t0, t1, anchor):
    """Per-pod process/JVM/Go metrics into metrics-apm.internal (APM Metrics tab)."""
    start, end = world.incident_window(anchor)
    cluster = world.cluster["name"]
    region = world.cluster.get("region", "us-east-1")
    rng = rng_for("apmint", t0.isoformat())
    checkout = world.service("checkout-api")
    bad_ver = checkout.get("deploy_bad", "2.4.1")
    good_ver = checkout.get("deploy_good", "2.4.0")
    instrumented = [p for p in world.pods if p.language in ("java", "go", "python")]

    step = timedelta(minutes=1)
    cur = t0
    while cur < t1:
        incident = in_incident(cur, start, end)
        progress = 0.0
        if incident:
            progress = (cur - start).total_seconds() / max((end - start).total_seconds(), 1)
        for pod in instrumented:
            version = pod.version
            load = 1.0
            if pod.service == "checkout-api":
                version = bad_ver if incident else good_ver
                load = (1.7 + progress * 1.4) if incident else 1.0
            elif incident and pod.service in (
                "edge-gateway",
                "payments-api",
                "orchestrator",
                "inventory-service",
            ):
                load = 1.25
            proc_cpu = min(0.95, max(0.02, (0.06 + rng.uniform(0, 0.05)) * load))
            sys_cpu = min(0.90, proc_cpu * rng.uniform(1.6, 2.4))
            rss = int(pod.mem_limit * (0.22 + 0.08 * load) + rng.randint(-4, 8) * 1024 * 1024)
            rss = max(24 * 1024 * 1024, min(int(pod.mem_limit * 0.96), rss))
            agent_name, lang = _agent_for(pod)
            doc = {
                "@timestamp": iso(cur),
                "data_stream": ds_meta("metrics", "apm.internal"),
                "processor": {"event": "metric", "name": "metric"},
                "observer": {"type": "apm-server", "version": "9.2.0"},
                "metricset": {"name": "app", "interval": "1m"},
                "agent": {"name": agent_name, "version": "1.0.0"},
                "service": {
                    "name": pod.service,
                    "environment": "production",
                    "version": version,
                    "language": {"name": lang},
                    "node": {"name": pod.name},
                },
                "host": {
                    "name": pod.node,
                    "hostname": pod.node,
                    "architecture": "x86_64",
                    "os": {"platform": "linux", "type": "linux"},
                },
                "cloud": {"provider": "aws", "region": region},
                "container": {"id": pod.uid, "name": pod.service},
                "kubernetes": {
                    "namespace": pod.namespace,
                    "pod": {"name": pod.name, "uid": pod.uid},
                    "node": {"name": pod.node},
                    "deployment": {"name": pod.service},
                },
                "orchestrator": {"cluster": {"name": cluster}},
                "system": {
                    "cpu": {"total": {"norm": {"pct": round(sys_cpu, 4)}}},
                    "memory": {
                        "total": 32 * 1024 * 1024 * 1024,
                        "actual": {"free": int(32 * 1024 * 1024 * 1024 * (0.42 if incident else 0.55))},
                    },
                    "process": {
                        "cpu": {"total": {"norm": {"pct": round(proc_cpu, 4)}}},
                        "memory": {"size": rss},
                    },
                },
                "process": {
                    "pid": int(pod.uid[:8], 16) % 30_000 + 100,
                    "cpu": {"pct": round(proc_cpu, 4)},
                    "memory": {"size": rss},
                },
                "labels": base_labels(),
                "tags": ["synthetic", "elasticco", "apm-internal"],
            }
            if lang == "java":
                heap_max = pod.mem_limit
                heap_used = int(rss * (0.88 if incident and pod.service == "checkout-api" else 0.55))
                heap_used = min(int(heap_max * 0.97), heap_used)
                young_count = rng.randint(2, 12) + (int(progress * 20) if incident else 0)
                young_time = rng.randint(8, 40) + (int(progress * 80) if incident else 0)
                old_count = rng.randint(0, 2) + (int(progress * 6) if incident else 0)
                old_time = rng.randint(5, 25) + (int(progress * 120) if incident else 0)
                doc["jvm"] = {
                    "memory": {
                        "heap": {
                            "used": heap_used,
                            "committed": min(heap_max, int(heap_used * 1.15)),
                            "max": heap_max,
                        },
                        "non_heap": {"used": 48 * 1024 * 1024, "committed": 64 * 1024 * 1024},
                    },
                    "thread": {"count": 40 + int(20 * load) + rng.randint(-4, 6)},
                    "gc": {
                        "count": young_count + old_count,
                        "time": young_time + old_time,
                    },
                }
                yield DS_APM_INTERNAL, doc
                # APM GC charts terms-agg on labels.name + jvm.gc.{count,time}
                for gc_name, gc_count, gc_time in (
                    ("G1 Young Generation", young_count, young_time),
                    ("G1 Old Generation", old_count, old_time),
                ):
                    gc_doc = {
                        **doc,
                        "jvm": {"gc": {"count": gc_count, "time": gc_time}},
                        "labels": {**base_labels(), "name": gc_name},
                    }
                    yield DS_APM_INTERNAL, gc_doc
                continue
            elif lang == "go":
                doc["golang"] = {
                    "goroutines": int(60 * load) + rng.randint(-8, 12),
                    "heap": {
                        "allocations": {
                            "mallocs": rng.randint(10_000, 80_000),
                            "frees": rng.randint(8_000, 70_000),
                            "heap": {
                                "sys": {"bytes": rss},
                                "in_use": {"bytes": int(rss * 0.7)},
                                "idle": {"bytes": int(rss * 0.2)},
                            },
                        }
                    },
                }
            yield DS_APM_INTERNAL, doc
        cur += step


def emit(world: World, t0, t1, anchor):
    yield from emit_host_metrics(world, t0, t1, anchor)
    yield from emit_node_metrics(world, t0, t1, anchor)
    yield from emit_apm_internal(world, t0, t1, anchor)
