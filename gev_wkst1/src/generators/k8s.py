"""Synthetic EKS pod metrics, events, and checkout container logs (U3)."""
from datetime import timedelta

from src.config import DS_CHECKOUT, DS_K8S_EVENT, DS_K8S_POD
from src.generators.common import base_labels, ds_meta, in_incident, iso
from src.world.model import World, rng_for

SCOPE = "all"
CLUSTER_CLOUD = "aws"


def _pod_resources(world: World, pod, cur, start, end, incident, progress, rng, restarts):
    """Memory/CPU for one pod. Only checkout-api OOMs during the incident."""
    checkout = world.service("checkout-api")
    bad_ver = checkout.get("deploy_bad", "2.4.1")
    good_ver = checkout.get("deploy_good", "2.4.0")
    limit = pod.mem_limit
    version = pod.version
    checkout_pods = [p.name for p in world.pods_for("checkout-api")]
    checkout_idx = checkout_pods.index(pod.name) if pod.name in checkout_pods else 0

    if pod.service == "checkout-api":
        version = bad_ver if incident else good_ver
        if incident:
            base_mi = 180 + progress * 360 + checkout_idx * 20
            mem = int(min(limit * 0.98, (base_mi + rng.randint(-10, 15)) * 1024 * 1024))
            if progress > 0.35 + checkout_idx * 0.12 and rng.random() < 0.15:
                restarts[pod.name] += 1
                mem = int(80 * 1024 * 1024)
            cpu = int((50_000_000 + rng.randint(0, 40_000_000)) * 1.6)
        else:
            mem = int((140 + rng.randint(-20, 30)) * 1024 * 1024)
            cpu = int(50_000_000 + rng.randint(0, 40_000_000))
        return version, mem, cpu

    # Related infra heats up with checkout retries; everything else stays healthy.
    load = 1.0
    if incident and pod.service in ("orders-db", "edge-gateway", "payments-api", "orchestrator"):
        load = 1.35 + progress * 0.4
    elif incident and pod.service in ("inventory-service", "inventory-db", "kafka"):
        load = 1.15
    rss_frac = {"db": 0.45, "cache": 0.40, "messaging": 0.35, "airflow": 0.30}.get(pod.kind, 0.28)
    mem = int(limit * rss_frac * load + rng.randint(-8, 12) * 1024 * 1024)
    mem = max(32 * 1024 * 1024, min(int(limit * 0.92), mem))
    cpu = int((18_000_000 + rng.randint(0, 25_000_000)) * load)
    return version, mem, cpu


def emit_pod_metrics(world: World, t0, t1, anchor):
    start, end = world.incident_window(anchor)
    cluster = world.cluster["name"]
    region = world.cluster.get("region", "us-east-1")
    rng = rng_for("k8smet", t0.isoformat())
    node_by_name = {n["name"]: n for n in world.node_inventory()}
    net_rx = {p.name: rng.randint(1, 8) * 10**8 for p in world.pods}
    net_tx = {p.name: rng.randint(1, 6) * 10**8 for p in world.pods}

    step = timedelta(minutes=1)
    cur = t0
    restarts = {p.name: 0 for p in world.pods}
    while cur < t1:
        incident = in_incident(cur, start, end)
        progress = 0.0
        if incident:
            progress = (cur - start).total_seconds() / max((end - start).total_seconds(), 1)
        for pod in world.pods:
            version, mem, cpu = _pod_resources(
                world, pod, cur, start, end, incident, progress, rng, restarts
            )
            node = node_by_name.get(pod.node) or {
                "name": pod.node,
                "ip": "10.0.0.1",
                "instance_id": pod.node,
                "cores": 8,
                "memory_bytes": 32 * 1024 * 1024 * 1024,
            }
            cores_nano = int(node.get("cores", 8)) * 1_000_000_000
            node_mem = int(node.get("memory_bytes", 32 * 1024 * 1024 * 1024))
            cpu_limit_nano = 1_000_000_000
            net_rx[pod.name] += rng.randint(50, 400) * 1024
            net_tx[pod.name] += rng.randint(40, 350) * 1024
            pod_ip = (
                f"10.{20 + (hash(pod.namespace) % 10)}."
                f"{hash(pod.name) % 200}.{10 + (hash(pod.uid) % 200)}"
            )
            yield DS_K8S_POD, {
                "@timestamp": iso(cur),
                "data_stream": ds_meta("metrics", "elasticco.k8s.pod"),
                "metricset": {"name": "pod"},
                "event": {"dataset": "kubernetes.pod", "module": "kubernetes"},
                "service": {"name": pod.service, "version": version},
                "orchestrator": {"cluster": {"name": cluster}, "type": "kubernetes"},
                "cloud": {"provider": CLUSTER_CLOUD, "region": region},
                "host": {
                    "name": pod.node,
                    "hostname": pod.node,
                    "id": node.get("instance_id"),
                    "ip": node.get("ip"),
                },
                "container": {"id": pod.uid, "name": pod.service},
                "kubernetes": {
                    "cluster": {"name": cluster},
                    "namespace": pod.namespace,
                    "deployment": {"name": pod.service},
                    "pod": {
                        "name": pod.name,
                        "uid": pod.uid,
                        "ip": pod_ip,
                        "memory": {
                            "usage": {
                                "bytes": mem,
                                "node": {"pct": round(mem / node_mem, 6)},
                                "limit": {"pct": round(mem / max(pod.mem_limit, 1), 4)},
                            },
                            "limit": {"bytes": pod.mem_limit},
                            "working_set": {"bytes": mem},
                        },
                        "cpu": {
                            "usage": {
                                "nanocores": cpu,
                                "node": {"pct": round(cpu / cores_nano, 6)},
                                "limit": {"pct": round(cpu / cpu_limit_nano, 4)},
                            }
                        },
                        "restart": {"count": restarts[pod.name]},
                        "network": {
                            "rx": {"bytes": net_rx[pod.name]},
                            "tx": {"bytes": net_tx[pod.name]},
                        },
                    },
                    "container": {
                        "name": pod.service,
                        "memory": {"usage": {"bytes": mem}},
                        "cpu": {"usage": {"nanocores": cpu}},
                    },
                    "node": {"name": pod.node},
                },
                "labels": base_labels(),
                "tags": ["synthetic", "kubernetes"],
            }
        cur += step


def emit_k8s_events(world: World, t0, t1, anchor):
    start, end = world.incident_window(anchor)
    cluster = world.cluster["name"]
    for i, pod in enumerate(world.pods_for("checkout-api")):
        oom_ts = start + timedelta(minutes=12 + i * 8)
        if not (t0 <= oom_ts < t1):
            continue
        yield DS_K8S_EVENT, {
            "@timestamp": iso(oom_ts),
            "data_stream": ds_meta("logs", "elasticco.k8s.event"),
            "event": {"kind": "event", "category": ["process"], "type": ["info"]},
            "orchestrator": {"cluster": {"name": cluster}},
            "host": {"name": pod.node, "hostname": pod.node},
            "kubernetes": {
                "cluster": {"name": cluster},
                "namespace": pod.namespace,
                "pod": {"name": pod.name, "uid": pod.uid},
                "node": {"name": pod.node},
                "event": {
                    "reason": "OOMKilled",
                    "type": "Warning",
                    "message": f"Container checkout-api in pod {pod.name} killed due to memory limit",
                },
            },
            "message": f"OOMKilled: {pod.name} checkout-api exceeded memory limit {pod.mem_limit}",
            "service": {
                "name": "checkout-api",
                "version": world.service("checkout-api").get("deploy_bad"),
            },
            "labels": base_labels(),
            "tags": ["synthetic", "kubernetes", "oom"],
        }
        backoff_ts = oom_ts + timedelta(seconds=45)
        if t0 <= backoff_ts < t1:
            yield DS_K8S_EVENT, {
                "@timestamp": iso(backoff_ts),
                "data_stream": ds_meta("logs", "elasticco.k8s.event"),
                "event": {"kind": "event", "category": ["process"], "type": ["info"]},
            "orchestrator": {"cluster": {"name": cluster}},
            "host": {"name": pod.node, "hostname": pod.node},
            "kubernetes": {
                "cluster": {"name": cluster},
                "namespace": pod.namespace,
                "pod": {"name": pod.name, "uid": pod.uid},
                "node": {"name": pod.node},
                "event": {
                    "reason": "BackOff",
                        "type": "Warning",
                        "message": f"Back-off restarting failed container checkout-api in pod {pod.name}",
                    },
                },
                "message": f"BackOff restarting container checkout-api in {pod.name}",
                "service": {"name": "checkout-api"},
                "labels": base_labels(),
                "tags": ["synthetic", "kubernetes"],
            }


def emit_checkout_logs(world: World, t0, t1, anchor):
    start, end = world.incident_window(anchor)
    cluster = world.cluster["name"]
    bad_ver = world.service("checkout-api").get("deploy_bad", "2.4.1")
    heroes = {h.trace_id: h for h in world.hero_traces(anchor)}
    rng = rng_for("coLogs", t0.isoformat())
    checkout_pods = world.pods_for("checkout-api")

    for h in heroes.values():
        if not (t0 <= h.ts < t1):
            continue
        pod = checkout_pods[rng.randrange(len(checkout_pods))]
        yield DS_CHECKOUT, {
            "@timestamp": iso(h.ts),
            "data_stream": ds_meta("logs", "elasticco.checkout"),
            "message": (
                f"order={h.order_id} tenant={h.tenant_id} trace_id={h.trace_id} "
                f"db_wait_ms={rng.randint(2400, 3800)} status=slow_query"
            ),
            "log": {"level": "error"},
            "service": {"name": "checkout-api", "version": bad_ver},
            "tenant": {"id": h.tenant_id},
            "trace": {"id": h.trace_id},
            "order": {"id": h.order_id},
            "kubernetes": {
                "cluster": {"name": cluster},
                "namespace": pod.namespace,
                "deployment": {"name": "checkout-api"},
                "pod": {"name": pod.name},
                "container": {"name": "checkout-api"},
            },
            "labels": base_labels(),
            "tags": ["synthetic", "checkout"],
        }

    for i, pod in enumerate(checkout_pods):
        ts = start + timedelta(minutes=11 + i * 8)
        if not (t0 <= ts < t1):
            continue
        yield DS_CHECKOUT, {
            "@timestamp": iso(ts),
            "data_stream": ds_meta("logs", "elasticco.checkout"),
            "message": (
                f"FATAL java.lang.OutOfMemoryError: Java heap space "
                f"deploy={bad_ver} pod={pod.name} suspected_leak=CartCache.retainAll"
            ),
            "log": {"level": "fatal"},
            "service": {"name": "checkout-api", "version": bad_ver},
            "kubernetes": {
                "cluster": {"name": cluster},
                "namespace": pod.namespace,
                "deployment": {"name": "checkout-api"},
                "pod": {"name": pod.name},
                "container": {"name": "checkout-api"},
            },
            "labels": base_labels(),
            "tags": ["synthetic", "checkout", "oom"],
        }


def emit(world: World, t0, t1, anchor):
    """Yield (data_stream, doc) pairs — k8s generator is multi-stream."""
    yield from emit_pod_metrics(world, t0, t1, anchor)
    yield from emit_k8s_events(world, t0, t1, anchor)
    yield from emit_checkout_logs(world, t0, t1, anchor)
