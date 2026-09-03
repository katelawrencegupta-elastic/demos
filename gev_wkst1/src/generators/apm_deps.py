"""APM aggregated metrics that power Dependencies, Service map, and Traces.

Bulk-indexed spans alone are not enough on modern Elastic APM:

* Dependencies / Service map → ``metricset.name: service_destination``
* Traces list → ``metricset.name: transaction`` with ``transaction.root: true``

When any ``transaction.duration.histogram`` metrics exist, Kibana prefers the
aggregated Traces path and will show an empty list without root transaction
metrics — even if ``traces-apm-*`` is full of sampled transactions.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from src.generators.common import base_labels, ds_meta, in_incident, iso
from src.generators.apm import _AGENT, _VERSION
from src.world.model import World, rng_for

SCOPE = "all"
DS_DEST = "metrics-apm.service_destination.1m-default"
DS_SUMMARY = "metrics-apm.service_summary.1m-default"
DS_TX = "metrics-apm.service_transaction.1m-default"
DS_TXN = "metrics-apm.transaction.1m-default"

# Root / entry transactions that should appear on Applications → Traces.
# Only docs with transaction.root:true populate that list once metrics exist.
ROOT_TRANSACTIONS = [
    ("edge-gateway", "POST /checkout", "request"),
]

# Non-root transaction groups (service detail pages / throughput).
SERVICE_TRANSACTIONS = [
    ("identity-service", "POST /v1/token/introspect", "request"),
    ("checkout-api", "POST /v1/orders", "request"),
    ("inventory-service", "POST /v1/reserve", "request"),
    ("fraud-service", "POST /v1/score", "request"),
    ("payments-api", "POST /v1/charge", "request"),
    ("notification-service", "TOPIC fulfillment.events", "messaging"),
]

# (caller, resource, target_type, target_name, span_name, base_latency_ms)
# resource is what Service map / Dependencies use as the edge key.
EDGES = [
    ("edge-gateway", "identity-service", "http", "identity-service", "POST /v1/token/introspect", 15),
    ("edge-gateway", "checkout-api", "http", "checkout-api", "POST /v1/orders", 400),
    ("checkout-api", "redis", "redis", "redis", "GET cart", 6),
    ("checkout-api", "inventory-service", "http", "inventory-service", "POST /v1/reserve", 45),
    ("checkout-api", "postgresql", "postgresql", "orders", "SELECT … FOR UPDATE orders", 80),
    ("checkout-api", "fraud-service", "http", "fraud-service", "POST /v1/score", 55),
    ("checkout-api", "payments-api", "http", "payments-api", "POST /v1/charge", 120),
    ("checkout-api", "kafka", "kafka", "fulfillment.events", "publish fulfillment.events", 12),
    ("inventory-service", "postgresql", "postgresql", "inventory", "UPDATE inventory SET reserved", 35),
    ("fraud-service", "redis", "redis", "redis", "GET risk:features", 8),
    ("payments-api", "api.stripe.com", "http", "api.stripe.com", "POST /v1/charges", 90),
    ("payments-api", "postgresql", "postgresql", "ledger", "INSERT INTO ledger", 25),
    ("notification-service", "kafka", "kafka", "fulfillment.events", "consume fulfillment.events", 20),
]

SERVICES = [
    "edge-gateway",
    "identity-service",
    "checkout-api",
    "inventory-service",
    "fraud-service",
    "payments-api",
    "notification-service",
]


def _agent_name(service: str) -> str:
    return _AGENT.get(service, ("go", "go"))[0]


def _lang(service: str) -> str:
    return _AGENT.get(service, ("go", "go"))[1]


def _version(service: str, checkout_ver: str) -> str:
    if service == "checkout-api":
        return checkout_ver
    return _VERSION.get(service, "1.0.0")


def _dest_doc(
    ts: datetime,
    service: str,
    resource: str,
    target_type: str,
    target_name: str,
    span_name: str,
    count: int,
    sum_us: int,
    outcome: str,
    checkout_ver: str,
) -> tuple[str, dict]:
    return DS_DEST, {
        "@timestamp": iso(ts.replace(second=0, microsecond=0)),
        "data_stream": ds_meta("metrics", "apm.service_destination.1m"),
        "processor": {"event": "metric", "name": "metric"},
        "metricset": {"name": "service_destination", "interval": "1m"},
        "observer": {"type": "apm-server", "version": "9.2.0"},
        "agent": {"name": _agent_name(service)},
        "service": {
            "name": service,
            "environment": "production",
            "language": {"name": _lang(service)},
            "version": _version(service, checkout_ver),
            "target": {"type": target_type, "name": target_name},
        },
        "span": {
            "name": span_name,
            "destination": {
                "service": {
                    "resource": resource,
                    "response_time": {
                        "count": count,
                        "sum": {"us": sum_us},
                    },
                }
            },
        },
        "event": {"outcome": outcome},
        "labels": base_labels(),
        "tags": ["synthetic", "elasticco", "service-destination"],
        "_doc_count": count,
    }


def _summary_doc(ts: datetime, service: str, checkout_ver: str) -> tuple[str, dict]:
    return DS_SUMMARY, {
        "@timestamp": iso(ts.replace(second=0, microsecond=0)),
        "data_stream": ds_meta("metrics", "apm.service_summary.1m"),
        "processor": {"event": "metric", "name": "metric"},
        "metricset": {"name": "service_summary", "interval": "1m"},
        "observer": {"type": "apm-server", "version": "9.2.0"},
        "agent": {"name": _agent_name(service)},
        "service": {
            "name": service,
            "environment": "production",
            "language": {"name": _lang(service)},
            "version": _version(service, checkout_ver),
        },
        "labels": base_labels(),
        "tags": ["synthetic", "elasticco", "service-summary"],
    }


def _tx_metric_doc(
    ts: datetime,
    service: str,
    count: int,
    sum_us: int,
    success: int,
    checkout_ver: str,
) -> tuple[str, dict]:
    # Rough histogram: single bucket at average latency
    avg = max(int(sum_us / max(count, 1)), 1)
    return DS_TX, {
        "@timestamp": iso(ts.replace(second=0, microsecond=0)),
        "data_stream": ds_meta("metrics", "apm.service_transaction.1m"),
        "processor": {"event": "metric", "name": "metric"},
        "metricset": {"name": "service_transaction", "interval": "1m"},
        "observer": {"type": "apm-server", "version": "9.2.0"},
        "agent": {"name": _agent_name(service)},
        "service": {
            "name": service,
            "environment": "production",
            "language": {"name": _lang(service)},
            "version": _version(service, checkout_ver),
        },
        "transaction": {
            "type": "request",
            "duration": {
                "summary": {"sum": sum_us, "value_count": count},
                "histogram": {"values": [avg], "counts": [count]},
            },
        },
        "event": {
            "outcome": "success" if success == count else "failure",
            "success_count": {"sum": success, "value_count": count},
        },
        "labels": base_labels(),
        "tags": ["synthetic", "elasticco", "service-transaction"],
        "_doc_count": count,
    }


def _txn_agg_doc(
    ts: datetime,
    service: str,
    tx_name: str,
    tx_type: str,
    count: int,
    sum_us: int,
    success: int,
    checkout_ver: str,
    *,
    root: bool,
) -> tuple[str, dict]:
    """Per-transaction-name metrics; root=True feeds Applications → Traces."""
    avg = max(int(sum_us / max(count, 1)), 1)
    return DS_TXN, {
        "@timestamp": iso(ts.replace(second=0, microsecond=0)),
        "data_stream": ds_meta("metrics", "apm.transaction.1m"),
        "processor": {"event": "metric", "name": "metric"},
        "metricset": {"name": "transaction", "interval": "1m"},
        "observer": {"type": "apm-server", "version": "9.2.0"},
        "agent": {"name": _agent_name(service)},
        "service": {
            "name": service,
            "environment": "production",
            "language": {"name": _lang(service)},
            "version": _version(service, checkout_ver),
        },
        "transaction": {
            "name": tx_name,
            "type": tx_type,
            "root": root,
            "result": "HTTP 2xx" if success == count else "HTTP 5xx",
            "duration": {
                "summary": {"sum": sum_us, "value_count": count},
                "histogram": {"values": [avg], "counts": [count]},
            },
        },
        "event": {
            "outcome": "success" if success == count else "failure",
            "success_count": {"sum": success, "value_count": count},
        },
        "labels": base_labels(),
        "tags": ["synthetic", "elasticco", "transaction-metric"],
        "_doc_count": count,
    }


def emit(world: World, t0: datetime, t1: datetime, anchor: datetime):
    """Yield (data_stream, doc) dependency + summary metrics per minute."""
    start, end = world.incident_window(anchor)
    checkout = world.service("checkout-api")
    bad_ver = checkout.get("deploy_bad", "2.4.1")
    good_ver = checkout.get("deploy_good", "2.4.0")
    rng = rng_for("deps", t0.isoformat())

    cur = t0.replace(second=0, microsecond=0)
    if cur < t0:
        cur += timedelta(minutes=1)

    while cur < t1:
        incident = in_incident(cur, start, end)
        checkout_ver = bad_ver if incident else good_ver
        # Match denser span traffic: ~9 traces/min baseline, more during incident
        base_calls = 9 + (18 if incident else 0)

        for service in SERVICES:
            yield _summary_doc(cur, service, checkout_ver)
            # Gateway + checkout carry most traffic
            weight = 1.0
            if service in ("edge-gateway", "checkout-api"):
                weight = 1.0
            elif service == "notification-service":
                weight = 0.9
            else:
                weight = 0.85
            n = max(1, int(base_calls * weight + rng.randint(0, 2)))
            # Latency: checkout spikes during incident
            if service == "checkout-api" and incident:
                avg_ms = rng.randint(3000, 3200)
                fails = max(0, int(n * 0.15))
            elif service == "edge-gateway" and incident:
                avg_ms = rng.randint(3050, 3250)
                fails = max(0, int(n * 0.12))
            else:
                avg_ms = rng.randint(40, 180)
                fails = 0
            sum_us = n * avg_ms * 1000
            yield _tx_metric_doc(cur, service, n, sum_us, n - fails, checkout_ver)

        # Aggregated transaction metrics (Traces list requires root:true)
        for service, tx_name, tx_type in ROOT_TRANSACTIONS + SERVICE_TRANSACTIONS:
            root = (service, tx_name, tx_type) in ROOT_TRANSACTIONS
            if service == "checkout-api" and incident:
                avg_ms = rng.randint(2400, 3600)
                n = max(1, base_calls + rng.randint(0, 2))
                fails = max(0, int(n * 0.15))
            elif service == "edge-gateway" and incident:
                avg_ms = rng.randint(2500, 3700)
                n = max(1, base_calls + rng.randint(0, 2))
                fails = max(0, int(n * 0.12))
            else:
                avg_ms = rng.randint(40, 220)
                n = max(1, int(base_calls * (1.0 if root else 0.9)) + rng.randint(0, 1))
                fails = 0
            yield _txn_agg_doc(
                cur,
                service,
                tx_name,
                tx_type,
                n,
                n * avg_ms * 1000,
                n - fails,
                checkout_ver,
                root=root,
            )

        for caller, resource, ttype, tname, span_name, base_ms in EDGES:
            n = max(1, base_calls + rng.randint(0, 2))
            lat = base_ms
            if incident and caller == "checkout-api" and resource == "postgresql":
                lat = rng.randint(2700, 2900)
                outcome = "failure" if rng.random() < 0.2 else "success"
            elif incident and caller in ("edge-gateway", "checkout-api") and resource in (
                "checkout-api",
                "payments-api",
            ):
                lat = int(base_ms * rng.uniform(4.0, 8.0))
                outcome = "failure" if rng.random() < 0.15 else "success"
            else:
                lat = int(base_ms * rng.uniform(0.8, 1.3))
                outcome = "success"
            sum_us = n * lat * 1000
            yield _dest_doc(
                cur,
                caller,
                resource,
                ttype,
                tname,
                span_name,
                n,
                sum_us,
                outcome,
                checkout_ver,
            )

        cur += timedelta(minutes=1)
