"""Synthetic EKS pod metrics, events, and checkout container logs (U3)."""
from datetime import timedelta

from src.config import DS_CHECKOUT, DS_K8S_EVENT, DS_K8S_POD
from src.generators.common import base_labels, ds_meta, in_incident, iso
from src.world.model import World, rng_for

SCOPE = "all"
MEM_LIMIT = 512 * 1024 * 1024  # 512Mi


def emit_pod_metrics(world: World, t0, t1, anchor):
    start, end = world.incident_window(anchor)
    checkout = world.service("checkout-api")
    bad_ver = checkout.get("deploy_bad", "2.4.1")
    good_ver = checkout.get("deploy_good", "2.4.0")
    cluster = world.cluster["name"]
    rng = rng_for("k8smet", t0.isoformat())

    step = timedelta(minutes=1)
    cur = t0
    # restart counters climb during incident
    restarts = {p.name: 0 for p in world.pods}
    while cur < t1:
        incident = in_incident(cur, start, end)
        progress = 0.0
        if incident:
            progress = (cur - start).total_seconds() / max((end - start).total_seconds(), 1)
        for i, pod in enumerate(world.pods):
            version = bad_ver if incident else good_ver
            if incident:
                # Rising RSS toward OOM; pod 0 dies first
                base = 180 + progress * 360 + i * 20
                mem = int(min(MEM_LIMIT * 0.98, (base + rng.randint(-10, 15)) * 1024 * 1024))
                if progress > 0.35 + i * 0.12 and rng.random() < 0.15:
                    restarts[pod.name] += 1
                    mem = int(80 * 1024 * 1024)  # post-restart dip
            else:
                mem = int((140 + rng.randint(-20, 30)) * 1024 * 1024)
            cpu = int((50_000_000 + rng.randint(0, 40_000_000)) * (1.6 if incident else 1.0))
            yield DS_K8S_POD, {
                "@timestamp": iso(cur),
                "data_stream": ds_meta("metrics", "elasticco.k8s.pod"),
                "metricset": {"name": "pod"},
                "service": {"name": "checkout-api", "version": version},
                "orchestrator": {"cluster": {"name": cluster}},
                "kubernetes": {
                    "namespace": pod.namespace,
                    "deployment": {"name": "checkout-api"},
                    "pod": {
                        "name": pod.name,
                        "uid": pod.uid,
                        "memory": {"usage": {"bytes": mem}, "limit": {"bytes": MEM_LIMIT}},
                        "cpu": {"usage": {"nanocores": cpu}},
                        "restart": {"count": restarts[pod.name]},
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
    # Emit OOMKilled + BackOff events inside the incident for each pod
    for i, pod in enumerate(world.pods):
        oom_ts = start + timedelta(minutes=12 + i * 8)
        if not (t0 <= oom_ts < t1):
            continue
        yield DS_K8S_EVENT, {
            "@timestamp": iso(oom_ts),
            "data_stream": ds_meta("logs", "elasticco.k8s.event"),
            "event": {"kind": "event", "category": ["process"], "type": ["info"]},
            "orchestrator": {"cluster": {"name": cluster}},
            "kubernetes": {
                "namespace": pod.namespace,
                "pod": {"name": pod.name, "uid": pod.uid},
                "event": {
                    "reason": "OOMKilled",
                    "type": "Warning",
                    "message": f"Container checkout-api in pod {pod.name} killed due to memory limit",
                },
            },
            "message": f"OOMKilled: {pod.name} checkout-api exceeded memory limit {MEM_LIMIT}",
            "service": {"name": "checkout-api", "version": world.service("checkout-api").get("deploy_bad")},
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
                "kubernetes": {
                    "namespace": pod.namespace,
                    "pod": {"name": pod.name, "uid": pod.uid},
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
    bad_ver = world.service("checkout-api").get("deploy_bad", "2.4.1")
    heroes = {h.trace_id: h for h in world.hero_traces(anchor)}
    rng = rng_for("coLogs", t0.isoformat())

    for h in heroes.values():
        if not (t0 <= h.ts < t1):
            continue
        pod = world.pods[rng.randrange(len(world.pods))]
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
                "namespace": pod.namespace,
                "deployment": {"name": "checkout-api"},
                "pod": {"name": pod.name},
                "container": {"name": "checkout-api"},
            },
            "labels": base_labels(),
            "tags": ["synthetic", "checkout"],
        }

    # Pre-OOM last lines
    for i, pod in enumerate(world.pods):
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
