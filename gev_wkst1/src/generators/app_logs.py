"""App logs: U7 inventory DEBUG flood + U8 notification-service log silence."""
from datetime import timedelta

from src.config import DS_INVENTORY, DS_NOTIFICATION
from src.generators.common import base_labels, ds_meta, in_incident, iso
from src.world.model import World, rng_for, stable_hex

SCOPE = "app_logs"
DATA_STREAM = DS_INVENTORY
DATASET = "elasticco.inventory"

DEBUG_MSGS = (
    "SkuCache lookup sku={sku} tenant={tenant} hit=false ttl_ms=0",
    "SkuCache refresh warehouse=usc1-a sku={sku} keys={n}",
    "SkuCache debug dump partition={p} size={n}",
)
INFO_MSG = "reserved sku={sku} warehouse=usc1-a tenant={tenant} ok=true"
NOTIFY_MSG = (
    "published topic=fulfillment.events tenant={tenant} order={order} "
    "channel=email status=accepted"
)


def _inv_doc(world: World, ts, pod, level: str, logger: str, version: str, message: str, tenant: str):
    cluster = world.cluster["name"]
    return {
        "@timestamp": iso(ts),
        "data_stream": ds_meta("logs", DATASET),
        "event": {"dataset": DATASET},
        "message": message,
        "log": {"level": level, "logger": logger},
        "service": {"name": "inventory-service", "version": version},
        "tenant": {"id": tenant},
        "host": {"name": pod.node},
        "kubernetes": {
            "cluster": {"name": cluster},
            "namespace": pod.namespace,
            "deployment": {"name": "inventory-service"},
            "pod": {"name": pod.name},
            "container": {"name": "inventory-service"},
        },
        "labels": base_labels(),
        "tags": ["synthetic", "inventory", "log-rate"],
    }


def _notify_doc(world: World, ts, pod, tenant: str, order: str):
    cluster = world.cluster["name"]
    svc = world.service("notification-service")
    return {
        "@timestamp": iso(ts),
        "data_stream": ds_meta("logs", "elasticco.notification"),
        "event": {"dataset": "elasticco.notification"},
        "message": NOTIFY_MSG.format(tenant=tenant, order=order),
        "log": {"level": "info", "logger": "com.elasticco.notify.Publisher"},
        "service": {"name": "notification-service", "version": svc.get("version", "1.4.2")},
        "tenant": {"id": tenant},
        "host": {"name": pod.node},
        "kubernetes": {
            "cluster": {"name": cluster},
            "namespace": pod.namespace,
            "deployment": {"name": "notification-service"},
            "pod": {"name": pod.name},
            "container": {"name": "notification-service"},
        },
        "labels": base_labels(),
        "tags": ["synthetic", "notification", "telemetry-gap"],
    }


def emit_inventory(world: World, t0, t1, anchor):
    lr = world.cfg.get("log_rate") or {}
    window = world.log_rate_window(anchor)
    pods = world.pods_for("inventory-service")
    if not pods:
        return
    tenants = [t["id"] for t in world.tenants]
    logger = lr.get("logger", "com.elasticco.inventory.SkuCache")
    verbose = lr.get("verbose_version", "4.0.9")
    good = lr.get("good_version", "4.0.8")
    rng = rng_for("invLogs", t0.isoformat())

    cur = t0.replace(second=0, microsecond=0)
    if cur < t0:
        cur += timedelta(minutes=2)
    while cur < t1:
        pod = pods[rng.randrange(len(pods))]
        tenant = rng.choice(tenants)
        sku = f"sku-{stable_hex('sku', f'{cur.isoformat()}{tenant}', 6)}"
        yield DS_INVENTORY, _inv_doc(
            world,
            cur,
            pod,
            "info",
            "com.elasticco.inventory.Reserve",
            good,
            INFO_MSG.format(sku=sku, tenant=tenant),
            tenant,
        )
        cur += timedelta(minutes=2)

    if not window:
        return
    start, end = window
    flood_t0 = max(t0, start)
    flood_t1 = min(t1, end)
    if flood_t1 <= flood_t0:
        return
    ts = flood_t0
    step = timedelta(seconds=2)
    i = 0
    while ts < flood_t1:
        pod = pods[i % len(pods)]
        tenant = tenants[i % len(tenants)]
        sku = f"sku-{stable_hex('dsku', f'{ts.isoformat()}{i}', 6)}"
        tmpl = DEBUG_MSGS[i % len(DEBUG_MSGS)]
        msg = tmpl.format(sku=sku, tenant=tenant, n=rng.randint(8, 40), p=i % 16)
        yield DS_INVENTORY, _inv_doc(world, ts, pod, "debug", logger, verbose, msg, tenant)
        ts += step
        i += 1


def emit_notification(world: World, t0, t1, anchor):
    """Heartbeat logs that go silent in the U8 telemetry-gap window."""
    pods = world.pods_for("notification-service")
    if not pods:
        return
    tenants = [t["id"] for t in world.tenants]
    gap = world.telemetry_gap_window(anchor)
    cur = t0.replace(second=0, microsecond=0)
    step = timedelta(seconds=30)
    if cur < t0:
        cur += step
    i = 0
    while cur < t1:
        if gap and in_incident(cur, gap[0], gap[1]):
            cur += step
            i += 1
            continue
        pod = pods[i % len(pods)]
        tenant = tenants[i % len(tenants)]
        order = f"ord-{stable_hex('ntfy', f'{cur.isoformat()}{i}', 8)}"
        yield DS_NOTIFICATION, _notify_doc(world, cur, pod, tenant, order)
        cur += step
        i += 1


def emit(world: World, t0, t1, anchor):
    yield from emit_inventory(world, t0, t1, anchor)
    yield from emit_notification(world, t0, t1, anchor)
