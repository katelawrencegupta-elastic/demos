"""Unstructured Airflow-style orchestrator logs (U1)."""
from datetime import timedelta

from src.config import DS_ORCHESTRATOR
from src.generators.common import base_labels, ds_meta, in_incident, iso
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


def emit(world: World, t0, t1, anchor):
    start, end = world.incident_window(anchor)
    heroes = {h.trace_id: h for h in world.hero_traces(anchor)}
    dag = world.cfg["orchestrator"]["dag_id"]
    tasks = world.cfg["orchestrator"]["task_ids"]
    rng = rng_for("orch", t0.isoformat())

    # Hero traces: one structured-looking unstructured line per task during incident
    for h in heroes.values():
        if not (t0 <= h.ts < t1):
            continue
        for i, task in enumerate(tasks):
            ts = h.ts + timedelta(seconds=i * 3)
            if task == "reserve_inventory":
                msg = SLOW_MSG.format(ms=rng.randint(2200, 4100))
                level = "WARNING"
            elif task == "charge_payment" and h.slow_db:
                msg = RETRY_MSG.format(attempt=rng.randint(2, 4))
                level = "ERROR"
            else:
                msg = TASK_MSGS[task].format(n=rng.randint(1, 8))
                level = "INFO"
            message = _raw_line(ts, dag, task, h.tenant_id, h.order_id, h.trace_id, level, msg)
            yield {
                "@timestamp": iso(ts),
                "data_stream": ds_meta("logs", DATASET),
                "message": message,
                "service": {"name": "orchestrator"},
                "host": {"name": "orchestrator-0.platform.svc"},
                "labels": base_labels(),
                "tags": ["synthetic", "orchestrator", "unstructured"],
            }

    # Background noise for healthy tenants (and blast outside hero set)
    step = timedelta(minutes=2)
    cur = t0
    while cur < t1:
        tenant = rng.choice(world.tenants)
        task = rng.choice(tasks)
        order = f"ord-{stable_hex('bg', f'{cur.isoformat()}{task}', 8)}"
        trace = stable_hex("bgtrace", f"{cur.isoformat()}{order}", 32)
        level = "INFO"
        msg = TASK_MSGS[task].format(n=rng.randint(1, 5))
        if in_incident(cur, start, end) and tenant.get("blast") and rng.random() < 0.35:
            level = "WARNING"
            msg = SLOW_MSG.format(ms=rng.randint(1800, 3500))
        message = _raw_line(cur, dag, task, tenant["id"], order, trace, level, msg)
        yield {
            "@timestamp": iso(cur),
            "data_stream": ds_meta("logs", DATASET),
            "message": message,
            "service": {"name": "orchestrator"},
            "host": {"name": "orchestrator-0.platform.svc"},
            "labels": base_labels(),
            "tags": ["synthetic", "orchestrator", "unstructured"],
        }
        cur += step
