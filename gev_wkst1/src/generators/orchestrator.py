"""Unstructured Airflow-style orchestrator logs (U1 + U7 beat 2)."""
from datetime import timedelta

from src.config import DS_ORCHESTRATOR
from src.generators.common import base_labels, ds_meta, iso
from src.world.model import World, rng_for, stable_hex

SCOPE = "all"
DATA_STREAM = DS_ORCHESTRATOR
DATASET = "elasticco.orchestrator"

TASK_MSGS = {
    "validate_cart": "Cart validation complete items={n}",
    "reserve_inventory": "Reserved SKU batch warehouse=usc1-a",
    "charge_payment": "Payment intent submitted provider=stripe",
    "emit_fulfillment": "Fulfillment event published topic=orders.fulfilled",
}

RETRY_MSG = (
    "Task failed after checkout-api timeout; scheduling retry attempt={attempt} "
    "reason=upstream_5xx"
)
SLOW_MSG = (
    "Downstream latency elevated checkout_p95_ms={ms}; holding DAG run"
)


def _raw_line(ts, dag, task, tenant, order, trace, level, msg) -> str:
    # Intentionally unstructured — pipeline grok extracts fields.
    # Trailing Z helps TIMESTAMP_ISO8601 / date processors reliably.
    stamp = ts.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    return (
        f"{stamp} [{dag}] {task} "
        f"tenant={tenant} order={order} trace_id={trace} {level}: {msg}"
    )


def _doc(ts, message, tags):
    return {
        "@timestamp": iso(ts),
        "data_stream": ds_meta("logs", DATASET),
        "message": message,
        "service": {"name": "orchestrator"},
        "host": {"name": "orchestrator-0.platform.svc"},
        "labels": base_labels(),
        "tags": tags,
    }


def emit(world: World, t0, t1, anchor):
    start, end = world.incident_window(anchor)
    heroes = {h.trace_id: h for h in world.hero_traces(anchor)}
    dag = world.cfg["orchestrator"]["dag_id"]
    tasks = world.cfg["orchestrator"]["task_ids"]
    rng = rng_for("orch", t0.isoformat())
    blast = world.blast_tenant["id"]

    # Hero traces: one unstructured line per task during incident
    for h in heroes.values():
        if not (t0 <= h.ts < t1):
            continue
        for i, task in enumerate(tasks):
            ts = h.ts + timedelta(seconds=i * 3)
            if task == "reserve_inventory":
                msg = SLOW_MSG.format(ms=rng.randint(3000, 3200))
                level = "WARNING"
            elif task == "charge_payment" and h.slow_db:
                msg = RETRY_MSG.format(attempt=rng.randint(2, 4))
                level = "ERROR"
            else:
                msg = TASK_MSGS[task].format(n=rng.randint(1, 8))
                level = "INFO"
            message = _raw_line(ts, dag, task, h.tenant_id, h.order_id, h.trace_id, level, msg)
            yield _doc(ts, message, ["synthetic", "orchestrator", "unstructured"])

    # Quiet INFO baseline (all tenants) so Log Rate Analysis has a contrast class
    step = timedelta(minutes=2)
    cur = t0
    while cur < t1:
        tenant = rng.choice(world.tenants)
        task = rng.choice(tasks)
        order = f"ord-{stable_hex('bg', f'{cur.isoformat()}{task}', 8)}"
        trace = stable_hex("bgtrace", f"{cur.isoformat()}{order}", 32)
        msg = TASK_MSGS[task].format(n=rng.randint(1, 5))
        message = _raw_line(cur, dag, task, tenant["id"], order, trace, "INFO", msg)
        yield _doc(cur, message, ["synthetic", "orchestrator", "unstructured"])
        cur += step

    # U7 beat 2: acme-retail ERROR retry storm inside the checkout incident window.
    # Log Rate Analysis on Elastic Co. Orchestrator Logs should name tenant.id + log.level.
    storm = world.cfg["orchestrator"].get("retry_storm") or {}
    interval = int(storm.get("interval_seconds", 4))
    task = storm.get("task_id", "charge_payment")
    flood_t0 = max(t0, start)
    flood_t1 = min(t1, end)
    if flood_t1 <= flood_t0:
        return
    ts = flood_t0
    i = 0
    while ts < flood_t1:
        order = f"ord-{stable_hex('rstorm', f'{ts.isoformat()}{i}', 8)}"
        trace = stable_hex("rstormt", f"{order}{i}", 32)
        msg = RETRY_MSG.format(attempt=2 + (i % 3))
        message = _raw_line(ts, dag, task, blast, order, trace, "ERROR", msg)
        yield _doc(ts, message, ["synthetic", "orchestrator", "unstructured", "retry-storm"])
        ts += timedelta(seconds=interval)
        i += 1
