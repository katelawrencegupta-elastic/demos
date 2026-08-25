#!/usr/bin/env python3
"""Emit correlated logs, metrics, and traces to the local EDOT collector.

Usage (repo root, collector already running):

    .venv/bin/python edot/factory.py sample --count 40
    .venv/bin/python edot/factory.py stream --tick 2
    .venv/bin/python edot/factory.py stream --tick 1 --duration 60
"""

from __future__ import annotations

import argparse
import logging
import random
import signal
import time
from dataclasses import dataclass

from opentelemetry import metrics, trace
from opentelemetry._logs import Logger
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import SpanKind, Status, StatusCode

from syslog_events import next_event as next_syslog_event

SERVICES = (
    "well-data-api",
    "telemetry-gateway",
    "identity-service",
    "rig-scheduler",
)
HOSTS = ("aks-sre-01", "aks-sre-02", "aks-sre-03")
HOST_IPS = {
    "aks-sre-01": "8.8.8.8",
    "aks-sre-02": "80.67.169.12",
    "aks-sre-03": "202.12.27.33",
}
ROUTES = {
    "well-data-api": (("/v2/wells/{well}/surveys", "GET"), ("/v2/wells/{well}/logs", "GET")),
    "telemetry-gateway": (("/v1/ingest", "POST"), ("/health", "GET")),
    "identity-service": (("/v1/auth/token", "POST"), ("/v1/auth/jwks", "GET")),
    "rig-scheduler": (("/v1/jobs/schedule", "POST"), ("/v1/jobs/{job}", "GET")),
}
TEAMS = {
    "well-data-api": "drilling-apps",
    "telemetry-gateway": "platform",
    "identity-service": "identity",
    "rig-scheduler": "platform",
    "rsyslog": "platform",
}

SYSLOG_SERVICE = "rsyslog"
SYSLOG_DATASET = "system.auth"
DEFAULT_SYSLOG_RATIO = 0.35
DEFAULT_ENDPOINT = "http://127.0.0.1:4318"


@dataclass
class ServicePipeline:
    name: str
    host: str
    tracer: trace.Tracer
    logger: logging.Logger
    otel_logger: Logger
    duration: metrics.Histogram
    requests: metrics.Counter
    errors: metrics.Counter
    tracer_provider: TracerProvider
    meter_provider: MeterProvider
    logger_provider: LoggerProvider

    def flush(self, timeout_millis: int = 10_000) -> None:
        self.tracer_provider.force_flush(timeout_millis)
        self.meter_provider.force_flush(timeout_millis)
        self.logger_provider.force_flush(timeout_millis)

    def shutdown(self) -> None:
        self.flush()
        self.tracer_provider.shutdown()
        self.meter_provider.shutdown()
        self.logger_provider.shutdown()


def _resource(service: str, host: str | None = None, dataset: str = "workshop.otel") -> Resource:
    resolved_host = host or random.choice(HOSTS)
    return Resource.create(
        {
            "service.name": service,
            "service.version": "8.2312.0" if service == SYSLOG_SERVICE else "1.8.2",
            "deployment.environment": "workshop",
            "host.name": resolved_host,
            "host.ip": HOST_IPS.get(resolved_host, "8.8.8.8"),
            "data_stream.dataset": dataset,
            "data_stream.namespace": "default",
            "team": TEAMS[service],
        }
    )


def build_pipeline(
    service: str,
    endpoint: str,
    host: str | None = None,
    dataset: str = "workshop.otel",
) -> ServicePipeline:
    resource = _resource(service, host, dataset=dataset)
    resolved_host = str(resource.attributes["host.name"])
    traces = TracerProvider(resource=resource)
    traces.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces"))
    )
    meters = MeterProvider(
        resource=resource,
        metric_readers=[
            PeriodicExportingMetricReader(
                OTLPMetricExporter(endpoint=f"{endpoint}/v1/metrics"),
                export_interval_millis=5_000,
            )
        ],
    )
    logs = LoggerProvider(resource=resource)
    logs.add_log_record_processor(
        BatchLogRecordProcessor(OTLPLogExporter(endpoint=f"{endpoint}/v1/logs"))
    )
    handler = LoggingHandler(level=logging.INFO, logger_provider=logs)
    logger = logging.getLogger(f"workshop.{service}")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.propagate = False

    meter = meters.get_meter("sre-01-factory")
    return ServicePipeline(
        name=service,
        host=resolved_host,
        tracer=traces.get_tracer("sre-01-factory"),
        logger=logger,
        otel_logger=logs.get_logger("sre-01-syslog" if service == SYSLOG_SERVICE else "sre-01-factory"),
        duration=meter.create_histogram(
            "http.server.request.duration",
            unit="s",
            description="HTTP server request duration",
        ),
        requests=meter.create_counter(
            "http.server.request.total",
            unit="{request}",
            description="HTTP server requests",
        ),
        errors=meter.create_counter(
            "http.server.errors",
            unit="{error}",
            description="HTTP server 5xx responses",
        ),
        tracer_provider=traces,
        meter_provider=meters,
        logger_provider=logs,
    )


def _status() -> int:
    roll = random.random()
    if roll < 0.08:
        return 500
    if roll < 0.14:
        return 404
    if roll < 0.22:
        return 201
    return 200


def emit_syslog(pipe: ServicePipeline, rng: random.Random) -> str:
    body, attrs, severity = next_syslog_event(pipe.host, rng)
    pipe.otel_logger.emit(
        body=body,
        severity_number=severity,
        severity_text=severity.name,
        attributes=attrs,
    )
    return SYSLOG_SERVICE


def emit_one(
    pipelines: dict[tuple[str | None, str], ServicePipeline],
    rng: random.Random,
    syslog_ratio: float = DEFAULT_SYSLOG_RATIO,
) -> str:
    syslog_keys = [k for k in pipelines if k[1] == SYSLOG_SERVICE]
    http_keys = [k for k in pipelines if k[1] != SYSLOG_SERVICE]
    if syslog_keys and rng.random() < syslog_ratio:
        key = rng.choice(syslog_keys)
        return emit_syslog(pipelines[key], rng)
    key = rng.choice(http_keys or list(pipelines))
    _host, service = key
    pipe = pipelines[key]
    route, method = rng.choice(ROUTES[service])
    well = 8000 + rng.randint(0, 200)
    path = route.format(well=well, job=rng.randint(100, 999))
    status = _status()
    latency = max(0.008, rng.gauss(0.12 if status < 500 else 1.4, 0.05))
    attrs = {
        "http.request.method": method,
        "url.path": path,
        "http.route": route,
        "http.response.status_code": status,
        "server.address": pipe.name,
    }

    with pipe.tracer.start_as_current_span(
        f"{method} {route}",
        kind=SpanKind.SERVER,
        attributes=attrs,
    ) as span:
        if service == "well-data-api":
            with pipe.tracer.start_as_current_span(
                "postgres.query",
                kind=SpanKind.CLIENT,
                attributes={"db.system": "postgresql", "db.operation": "SELECT"},
            ) as child:
                time.sleep(min(latency / 3, 0.05))
                if status >= 500:
                    child.set_status(Status(StatusCode.ERROR, "upstream timeout"))
        elif service == "telemetry-gateway" and rng.random() < 0.35:
            with pipe.tracer.start_as_current_span(
                "kafka.produce",
                kind=SpanKind.PRODUCER,
                attributes={
                    "messaging.system": "kafka",
                    "messaging.destination.name": "rig.metrics",
                },
            ):
                time.sleep(min(latency / 4, 0.03))

        if status >= 500:
            span.set_status(Status(StatusCode.ERROR, "survey lookup failed: upstream timeout"))
            pipe.logger.error(
                "survey lookup failed: upstream timeout path=%s status=%s",
                path,
                status,
            )
            pipe.errors.add(1, {"http.request.method": method, "url.path": path})
        elif status >= 400:
            pipe.logger.warning("well not found path=%s status=%s", path, status)
        else:
            pipe.logger.info("request completed path=%s status=%s", path, status)

        pipe.duration.record(latency, attrs)
        pipe.requests.add(1, {"http.request.method": method, "http.response.status_code": status})
    return service


def _add_syslog_pipelines(
    pipelines: dict[tuple[str | None, str], ServicePipeline],
    endpoint: str,
    hosts: list[str],
) -> None:
    for host in hosts:
        pipelines[(host, SYSLOG_SERVICE)] = build_pipeline(
            SYSLOG_SERVICE,
            endpoint,
            host=host,
            dataset=SYSLOG_DATASET,
        )


def build_pipelines(
    endpoints: list[str], hosts: list[str] | None = None
) -> dict[tuple[str | None, str], ServicePipeline]:
    pipelines: dict[tuple[str | None, str], ServicePipeline] = {}
    if len(endpoints) == 1:
        for service in SERVICES:
            pipelines[(None, service)] = build_pipeline(service, endpoints[0])
        _add_syslog_pipelines(pipelines, endpoints[0], list(HOSTS))
        return pipelines
    named_hosts = hosts or list(HOSTS)
    if len(named_hosts) != len(endpoints):
        raise ValueError("hosts and endpoints must be the same length")
    for host, endpoint in zip(named_hosts, endpoints):
        for service in SERVICES:
            pipelines[(host, service)] = build_pipeline(service, endpoint, host=host)
        _add_syslog_pipelines(pipelines, endpoint, [host])
    return pipelines


def sample(
    count: int,
    endpoint: str | list[str],
    hosts: list[str] | None = None,
    syslog_ratio: float = DEFAULT_SYSLOG_RATIO,
) -> None:
    endpoints = [endpoint] if isinstance(endpoint, str) else list(endpoint)
    pipelines = build_pipelines(endpoints, hosts)
    rng = random.Random()
    tallies: dict[str, int] = {name: 0 for name in (*SERVICES, SYSLOG_SERVICE)}
    try:
        for _ in range(count):
            tallies[emit_one(pipelines, rng, syslog_ratio=syslog_ratio)] += 1
    finally:
        for pipe in pipelines.values():
            pipe.shutdown()
    dest = ",".join(endpoints)
    print(
        "sample "
        + " ".join(f"{name}={n}" for name, n in tallies.items())
        + f" endpoint={dest}"
    )


def stream(
    tick: float,
    duration: float | None,
    endpoint: str | list[str],
    hosts: list[str] | None = None,
    syslog_ratio: float = DEFAULT_SYSLOG_RATIO,
) -> None:
    endpoints = [endpoint] if isinstance(endpoint, str) else list(endpoint)
    pipelines = build_pipelines(endpoints, hosts)
    rng = random.Random()
    stop = False

    def _stop(*_args: object) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    started = time.time()
    emitted = 0
    dest = ",".join(endpoints)
    print(f"streaming to {dest} tick={tick}s syslog_ratio={syslog_ratio} (Ctrl-C to stop)")
    try:
        while not stop:
            burst = rng.randint(2, 6)
            for _ in range(burst):
                emit_one(pipelines, rng, syslog_ratio=syslog_ratio)
                emitted += 1
            if duration is not None and time.time() - started >= duration:
                break
            time.sleep(tick)
    finally:
        for pipe in pipelines.values():
            pipe.shutdown()
    print(f"stream complete emitted={emitted}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "mode",
        choices=("sample", "stream"),
        help="sample = finite burst; stream = continuous until Ctrl-C or --duration",
    )
    parser.add_argument("--count", type=int, default=40, help="events for sample mode")
    parser.add_argument("--tick", type=float, default=2.0, help="seconds between stream bursts")
    parser.add_argument("--duration", type=float, default=None, help="stream for N seconds")
    parser.add_argument(
        "--syslog-ratio",
        type=float,
        default=DEFAULT_SYSLOG_RATIO,
        help="fraction of events that are host syslog (ssh/sudo/useradd). 1.0 = syslog only",
    )
    parser.add_argument(
        "--endpoint",
        action="append",
        dest="endpoints",
        help="OTLP/HTTP base URL (repeat for a fleet). Default: http://127.0.0.1:4318",
    )
    parser.add_argument(
        "--host",
        action="append",
        dest="hosts",
        help="host.name for each --endpoint (same order). Used with an agent fleet.",
    )
    args = parser.parse_args()
    endpoints = [e.rstrip("/") for e in (args.endpoints or [DEFAULT_ENDPOINT])]
    if args.mode == "sample":
        sample(args.count, endpoints, args.hosts, syslog_ratio=args.syslog_ratio)
    else:
        stream(args.tick, args.duration, endpoints, args.hosts, syslog_ratio=args.syslog_ratio)


if __name__ == "__main__":
    main()
