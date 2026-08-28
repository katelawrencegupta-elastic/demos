"""Rich multi-service APM traces with nested spans + tenant context (U2).

Trace topology (one checkout request):

  edge-gateway
    ├─ identity-service   (auth)
    └─ checkout-api
         ├─ redis-cart
         ├─ inventory-service → inventory-db
         ├─ orders-db (postgres FOR UPDATE)   ← slow on blast tenant
         ├─ fraud-service → redis
         ├─ payments-api → stripe + ledger-db
         └─ kafka → notification-service
"""
from __future__ import annotations

from datetime import datetime, timedelta

from src.config import DS_TRACES
from src.generators.common import base_labels, ds_meta, in_incident, iso
from src.world.model import HeroTrace, World, rng_for, stable_hex

SCOPE = "all"
DATA_STREAM = DS_TRACES
DATASET = "apm"

APM_CUSTOM = "traces-apm@elasticco"
APM_PROPERTIES = {
    "tenant.id": {"type": "keyword"},
    "labels.tenant.id": {"type": "keyword"},
    "labels.order.id": {"type": "keyword"},
    "labels.demo": {"type": "keyword"},
    "span.subtype": {"type": "keyword"},
    "span.type": {"type": "keyword"},
    "span.name": {"type": "keyword"},
    "span.action": {"type": "keyword"},
    "span.id": {"type": "keyword"},
    "event.outcome": {"type": "keyword"},
    "service.name": {"type": "keyword"},
    "service.environment": {"type": "keyword"},
    "service.version": {"type": "keyword"},
    "trace.id": {"type": "keyword"},
    "transaction.name": {"type": "keyword"},
    "transaction.type": {"type": "keyword"},
    "parent.id": {"type": "keyword"},
    "span.db.statement": {"type": "wildcard"},
    "span.db.type": {"type": "keyword"},
    "span.destination.service.resource": {"type": "keyword"},
    "span.destination.service.type": {"type": "keyword"},
    "span.destination.service.name": {"type": "keyword"},
    "destination.service.resource": {"type": "keyword"},
    "destination.service.type": {"type": "keyword"},
    "destination.service.name": {"type": "keyword"},
    "service.target.type": {"type": "keyword"},
    "service.target.name": {"type": "keyword"},
    "messaging.destination.name": {"type": "keyword"},
}

_AGENT = {
    "edge-gateway": ("go", "go"),
    "identity-service": ("go", "go"),
    "checkout-api": ("java", "java"),
    "inventory-service": ("go", "go"),
    "fraud-service": ("python", "python"),
    "payments-api": ("go", "go"),
    "notification-service": ("go", "go"),
}

_VERSION = {
    "edge-gateway": "1.9.2",
    "identity-service": "2.3.1",
    "inventory-service": "4.0.8",
    "fraud-service": "1.7.0",
    "payments-api": "3.1.0",
    "notification-service": "1.4.2",
}

_TEMPLATE_OK = False


def ensure_apm_mappings():
    global _TEMPLATE_OK
    if _TEMPLATE_OK:
        return
    import requests
    from src.config import ELASTIC_URL, ES_HEADERS

    body = {
        "template": {
            "lifecycle": {"data_retention": "30d"},
            "mappings": {"properties": APM_PROPERTIES},
        },
        "_meta": {"description": "Elastic Co. tenant + distributed span fields", "demo": "elastic-co"},
    }
    r = requests.put(
        f"{ELASTIC_URL}/_component_template/{APM_CUSTOM}",
        headers=ES_HEADERS,
        json=body,
        timeout=30,
    )
    if r.status_code >= 300:
        print(f"  [warn] {APM_CUSTOM}: {r.status_code} {r.text[:200]}")
    else:
        print(f"  [ok] component template {APM_CUSTOM}")

    r = requests.put(
        f"{ELASTIC_URL}/{DATA_STREAM}/_mapping",
        headers=ES_HEADERS,
        timeout=30,
        json={"properties": APM_PROPERTIES},
    )
    if r.status_code >= 300:
        print(f"  [warn] {DATA_STREAM} mapping: {r.status_code} {r.text[:200]}")
    else:
        print(f"  [ok] {DATA_STREAM} mapping updated")
    _TEMPLATE_OK = True


def _agent(service: str) -> tuple[str, str]:
    return _AGENT.get(service, ("go", "go"))


def _ver(service: str, checkout_version: str | None = None) -> str:
    if service == "checkout-api" and checkout_version:
        return checkout_version
    return _VERSION.get(service, "1.0.0")


def _tx(
    ts: datetime,
    service: str,
    tx_id: str,
    trace_id: str,
    name: str,
    duration_us: int,
    outcome: str,
    tenant: str,
    order: str,
    *,
    parent_id: str | None = None,
    tx_type: str = "request",
    checkout_version: str | None = None,
):
    agent_name, lang = _agent(service)
    doc = {
        "@timestamp": iso(ts),
        "data_stream": ds_meta("traces", "apm"),
        "processor": {"event": "transaction", "name": "transaction"},
        "observer": {"type": "apm-server", "version": "9.2.0"},
        "agent": {"name": agent_name, "version": "1.0.0"},
        "service": {
            "name": service,
            "environment": "production",
            "version": _ver(service, checkout_version),
            "language": {"name": lang},
        },
        "transaction": {
            "id": tx_id,
            "name": name,
            "type": tx_type,
            "duration": {"us": duration_us},
            "result": "HTTP 2xx" if outcome == "success" else "HTTP 5xx",
            "sampled": True,
        },
        "event": {"outcome": outcome},
        "trace": {"id": trace_id},
        "timestamp": {"us": int(ts.timestamp() * 1_000_000)},
        "tenant": {"id": tenant},
        "labels": {**base_labels(), "tenant.id": tenant, "order.id": order},
        "tags": ["synthetic", "elasticco", "distributed"],
    }
    if parent_id:
        doc["parent"] = {"id": parent_id}
    return doc


def _span(
    ts: datetime,
    service: str,
    span_id: str,
    parent_id: str,
    tx_id: str,
    trace_id: str,
    name: str,
    span_type: str,
    subtype: str,
    duration_us: int,
    outcome: str,
    tenant: str,
    order: str,
    *,
    dest: str | None = None,
    db: dict | None = None,
    messaging_dest: str | None = None,
    checkout_version: str | None = None,
    target_type: str | None = None,
    target_name: str | None = None,
):
    """Emit an APM span.

    Service-map edges require *exit* spans with:
      - span.destination.service.resource  (not root destination.*)
      - service.target.{type,name}
      - span.type in {external, db, messaging, ...} — not ``app``
    """
    agent_name, lang = _agent(service)
    span_body: dict = {
        "id": span_id,
        "name": name,
        "type": span_type,
        "subtype": subtype,
        "action": subtype,
        "duration": {"us": duration_us},
    }
    dest_root = None
    if dest:
        dest_svc = {
            "resource": dest,
            "type": span_type,
            "name": dest,
        }
        # Service map uses span.destination.*; ES|QL dashboards query destination.*
        span_body["destination"] = {"service": dest_svc}
        dest_root = {"service": dest_svc}
    if db:
        span_body["db"] = db

    svc: dict = {
        "name": service,
        "environment": "production",
        "version": _ver(service, checkout_version),
        "language": {"name": lang},
    }
    # Modern service-map field (APM Server 8.3+)
    if target_name or dest:
        svc["target"] = {
            "type": target_type or subtype or span_type,
            "name": target_name or dest,
        }

    doc = {
        "@timestamp": iso(ts),
        "data_stream": ds_meta("traces", "apm"),
        "processor": {"event": "span", "name": "transaction"},
        "observer": {"type": "apm-server", "version": "9.2.0"},
        "agent": {"name": agent_name, "version": "1.0.0"},
        "service": svc,
        "span": span_body,
        "parent": {"id": parent_id},
        "transaction": {"id": tx_id},
        "event": {"outcome": outcome},
        "trace": {"id": trace_id},
        "timestamp": {"us": int(ts.timestamp() * 1_000_000)},
        "tenant": {"id": tenant},
        "labels": {**base_labels(), "tenant.id": tenant, "order.id": order},
        "tags": ["synthetic", "elasticco", "distributed"],
    }
    if dest_root:
        doc["destination"] = dest_root
    if messaging_dest:
        doc["messaging"] = {"destination": {"name": messaging_dest}}
    return doc


def _sid(trace_id: str, key: str) -> str:
    return stable_hex("sp", f"{trace_id}:{key}", 16)


def _tid(trace_id: str, key: str) -> str:
    return stable_hex("tx", f"{trace_id}:{key}", 16)


def _emit_checkout_trace(world: World, h: HeroTrace, checkout_version: str, slow: bool):
    """Full distributed checkout waterfall with parent/child linking."""
    rng = rng_for("trace", h.trace_id)
    tenant, order, tid = h.tenant_id, h.order_id, h.trace_id
    ts = h.ts
    cv = checkout_version

    # Durations (µs)
    auth_us = rng.randint(8, 25) * 1000
    redis_us = rng.randint(2, 12) * 1000
    inv_db_us = rng.randint(15, 60) * 1000
    inv_us = inv_db_us + rng.randint(10, 30) * 1000
    db_us = (rng.randint(2400, 3800) * 1000) if slow else (rng.randint(20, 90) * 1000)
    fraud_redis_us = rng.randint(3, 15) * 1000
    fraud_us = fraud_redis_us + rng.randint(20, 80) * 1000
    stripe_us = rng.randint(40, 140) * 1000
    ledger_us = rng.randint(10, 40) * 1000
    pay_us = stripe_us + ledger_us + rng.randint(15, 40) * 1000
    kafka_us = rng.randint(5, 20) * 1000
    notif_us = rng.randint(15, 50) * 1000

    # Checkout owns inventory + db + fraud + payments + kafka (mostly sequential)
    co_us = redis_us + inv_us + db_us + fraud_us + pay_us + kafka_us + 40_000
    gw_us = auth_us + co_us + 12_000

    outcome = "failure" if slow and rng.random() < 0.22 else "success"
    fraud_outcome = "success"
    if slow and rng.random() < 0.15:
        fraud_outcome = "failure"

    # --- IDs (exit span id becomes remote transaction parent) ---
    gw_tx = _tid(tid, "gw")
    id_tx = _tid(tid, "id")
    co_tx = _tid(tid, "co")
    inv_tx = _tid(tid, "inv")
    fraud_tx = _tid(tid, "fraud")
    pay_tx = _tid(tid, "pay")
    notif_tx = _tid(tid, "notif")

    sp_gw_auth = _sid(tid, "gw-auth")
    sp_gw_co = _sid(tid, "gw-co")
    sp_co_redis = _sid(tid, "co-redis")
    sp_co_inv = _sid(tid, "co-inv")
    sp_inv_db = _sid(tid, "inv-db")
    sp_co_db = _sid(tid, "co-db")
    sp_co_fraud = _sid(tid, "co-fraud")
    sp_fraud_redis = _sid(tid, "fraud-redis")
    sp_co_pay = _sid(tid, "co-pay")
    sp_pay_stripe = _sid(tid, "pay-stripe")
    sp_pay_ledger = _sid(tid, "pay-ledger")
    sp_co_kafka = _sid(tid, "co-kafka")
    sp_notif_kafka = _sid(tid, "notif-kafka")

    t = ts

    # 1) edge-gateway
    yield _tx(t, "edge-gateway", gw_tx, tid, "POST /checkout", gw_us, outcome, tenant, order)
    yield _span(
        t + timedelta(milliseconds=1),
        "edge-gateway",
        sp_gw_auth,
        gw_tx,
        gw_tx,
        tid,
        "identity-service",
        "external",
        "http",
        auth_us,
        "success",
        tenant,
        order,
        dest="identity-service",
    )
    yield _tx(
        t + timedelta(milliseconds=1),
        "identity-service",
        id_tx,
        tid,
        "POST /v1/token/introspect",
        auth_us,
        "success",
        tenant,
        order,
        parent_id=sp_gw_auth,
    )

    t_co = t + timedelta(milliseconds=2) + timedelta(microseconds=auth_us)
    yield _span(
        t_co,
        "edge-gateway",
        sp_gw_co,
        gw_tx,
        gw_tx,
        tid,
        "checkout-api",
        "external",
        "http",
        co_us,
        outcome,
        tenant,
        order,
        dest="checkout-api",
    )

    # 2) checkout-api
    yield _tx(
        t_co + timedelta(milliseconds=1),
        "checkout-api",
        co_tx,
        tid,
        "POST /v1/orders",
        co_us,
        outcome,
        tenant,
        order,
        parent_id=sp_gw_co,
        checkout_version=cv,
    )

    t1 = t_co + timedelta(milliseconds=2)
    yield _span(
        t1,
        "checkout-api",
        sp_co_redis,
        co_tx,
        co_tx,
        tid,
        "GET cart",
        "db",
        "redis",
        redis_us,
        "success",
        tenant,
        order,
        dest="redis",
        checkout_version=cv,
    )

    t2 = t1 + timedelta(microseconds=redis_us)
    yield _span(
        t2,
        "checkout-api",
        sp_co_inv,
        co_tx,
        co_tx,
        tid,
        "inventory-service",
        "external",
        "http",
        inv_us,
        "success",
        tenant,
        order,
        dest="inventory-service",
        checkout_version=cv,
    )
    yield _tx(
        t2 + timedelta(milliseconds=1),
        "inventory-service",
        inv_tx,
        tid,
        "POST /v1/reserve",
        inv_us,
        "success",
        tenant,
        order,
        parent_id=sp_co_inv,
    )
    yield _span(
        t2 + timedelta(milliseconds=2),
        "inventory-service",
        sp_inv_db,
        inv_tx,
        inv_tx,
        tid,
        "UPDATE inventory SET reserved",
        "db",
        "postgresql",
        inv_db_us,
        "success",
        tenant,
        order,
        dest="postgresql",
        db={
            "type": "postgresql",
            "statement": (
                f"UPDATE inventory SET reserved=reserved+1 "
                f"WHERE sku IN (...) AND tenant_id='{tenant}'"
            ),
        },
    )

    t3 = t2 + timedelta(microseconds=inv_us)
    yield _span(
        t3,
        "checkout-api",
        sp_co_db,
        co_tx,
        co_tx,
        tid,
        "SELECT … FOR UPDATE orders",
        "db",
        "postgresql",
        db_us,
        outcome,
        tenant,
        order,
        dest="postgresql",
        checkout_version=cv,
        db={
            "type": "postgresql",
            "statement": (
                f"SELECT id, status FROM orders WHERE tenant_id='{tenant}' "
                f"AND id='{order}' FOR UPDATE"
            ),
        },
    )

    t4 = t3 + timedelta(microseconds=db_us)
    yield _span(
        t4,
        "checkout-api",
        sp_co_fraud,
        co_tx,
        co_tx,
        tid,
        "fraud-service",
        "external",
        "http",
        fraud_us,
        fraud_outcome,
        tenant,
        order,
        dest="fraud-service",
        checkout_version=cv,
    )
    yield _tx(
        t4 + timedelta(milliseconds=1),
        "fraud-service",
        fraud_tx,
        tid,
        "POST /v1/score",
        fraud_us,
        fraud_outcome,
        tenant,
        order,
        parent_id=sp_co_fraud,
    )
    yield _span(
        t4 + timedelta(milliseconds=2),
        "fraud-service",
        sp_fraud_redis,
        fraud_tx,
        fraud_tx,
        tid,
        "GET risk:features",
        "db",
        "redis",
        fraud_redis_us,
        "success",
        tenant,
        order,
        dest="redis",
    )

    t5 = t4 + timedelta(microseconds=fraud_us)
    yield _span(
        t5,
        "checkout-api",
        sp_co_pay,
        co_tx,
        co_tx,
        tid,
        "payments-api",
        "external",
        "http",
        pay_us,
        "success" if outcome == "success" else outcome,
        tenant,
        order,
        dest="payments-api",
        checkout_version=cv,
    )
    yield _tx(
        t5 + timedelta(milliseconds=1),
        "payments-api",
        pay_tx,
        tid,
        "POST /v1/charge",
        pay_us,
        "success" if outcome == "success" else outcome,
        tenant,
        order,
        parent_id=sp_co_pay,
    )
    yield _span(
        t5 + timedelta(milliseconds=2),
        "payments-api",
        sp_pay_stripe,
        pay_tx,
        pay_tx,
        tid,
        "POST https://api.stripe.com/v1/charges",
        "external",
        "http",
        stripe_us,
        "success",
        tenant,
        order,
        dest="api.stripe.com",
    )
    yield _span(
        t5 + timedelta(milliseconds=2) + timedelta(microseconds=stripe_us),
        "payments-api",
        sp_pay_ledger,
        pay_tx,
        pay_tx,
        tid,
        "INSERT INTO ledger",
        "db",
        "postgresql",
        ledger_us,
        "success",
        tenant,
        order,
        dest="postgresql",
        db={
            "type": "postgresql",
            "statement": f"INSERT INTO ledger (order_id, tenant_id) VALUES ('{order}', '{tenant}')",
        },
    )

    t6 = t5 + timedelta(microseconds=pay_us)
    yield _span(
        t6,
        "checkout-api",
        sp_co_kafka,
        co_tx,
        co_tx,
        tid,
        "publish fulfillment.events",
        "messaging",
        "kafka",
        kafka_us,
        "success",
        tenant,
        order,
        dest="kafka",
        messaging_dest="fulfillment.events",
        checkout_version=cv,
    )

    # Async consumer continues the same trace.id
    t7 = t6 + timedelta(microseconds=kafka_us + 5_000)
    yield _tx(
        t7,
        "notification-service",
        notif_tx,
        tid,
        "TOPIC fulfillment.events",
        notif_us,
        "success",
        tenant,
        order,
        parent_id=sp_co_kafka,
        tx_type="messaging",
    )
    yield _span(
        t7 + timedelta(milliseconds=1),
        "notification-service",
        sp_notif_kafka,
        notif_tx,
        notif_tx,
        tid,
        "consume fulfillment.events",
        "messaging",
        "kafka",
        notif_us - 5_000,
        "success",
        tenant,
        order,
        dest="kafka",
        messaging_dest="fulfillment.events",
    )


def emit(world: World, t0, t1, anchor):
    ensure_apm_mappings()
    start, end = world.incident_window(anchor)
    checkout = world.service("checkout-api")
    bad_ver = checkout.get("deploy_bad", "2.4.1")
    good_ver = checkout.get("deploy_good", "2.4.0")
    rng = rng_for("apm", t0.isoformat())

    for h in world.hero_traces(anchor):
        if t0 <= h.ts < t1:
            yield from _emit_checkout_trace(world, h, bad_ver, slow=True)

    # One trace per tenant every 20s so treemaps, heatmaps, and time series fill.
    # Blast tenant gets extra traces during the incident (slow DB + failures).
    step = timedelta(seconds=20)
    cur = t0
    seq = 0
    while cur < t1:
        incident = in_incident(cur, start, end)
        version = bad_ver if incident else good_ver
        for tenant in world.tenants:
            copies = 3 if (incident and tenant.get("blast")) else 1
            for k in range(copies):
                slow = bool(
                    incident and tenant.get("blast") and rng.random() < (0.6 if k else 0.4)
                )
                jitter_ms = rng.randint(0, 12_000) + k * 250
                ts = cur + timedelta(milliseconds=jitter_ms)
                if ts >= t1:
                    continue
                key = f"{cur.isoformat()}:{tenant['id']}:{k}:{seq}"
                h = HeroTrace(
                    trace_id=stable_hex("bgapm", key, 32),
                    tenant_id=tenant["id"],
                    ts=ts,
                    order_id=f"ord-{stable_hex('bgord', key, 8)}",
                    slow_db=slow,
                )
                yield from _emit_checkout_trace(world, h, version, slow=slow)
                seq += 1
        cur += step
