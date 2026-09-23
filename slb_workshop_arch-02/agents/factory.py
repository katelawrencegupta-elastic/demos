#!/usr/bin/env python3
"""Emit correlated OTel logs, metrics, and traces to ARCH-02 otel agents.

Usage (repo root, otel agents already running):

    .venv/bin/python agents/factory.py sample --count 40
    .venv/bin/python agents/factory.py stream --tick 2

Fan out across the three otel agents:

    .venv/bin/python agents/factory.py sample --count 60 \\
      --endpoint http://127.0.0.1:14318 --host aks-arch-edot-01 \\
      --endpoint http://127.0.0.1:15318 --host aks-arch-edot-02 \\
      --endpoint http://127.0.0.1:16318 --host aks-arch-edot-nonprod
"""

from __future__ import annotations

import argparse
import logging
import random
import signal
import time
from dataclasses import dataclass

from opentelemetry import metrics, trace
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

SERVICES = (
    "well-data-api",
    "reservoir-modeler",
    "survey-ingest",
)
HOSTS = ("aks-arch-edot-01", "aks-arch-edot-02", "aks-arch-edot-nonprod")
ENV_BY_HOST = {
    "aks-arch-edot-01": "prod",
    "aks-arch-edot-02": "prod",
    "aks-arch-edot-nonprod": "nonprod",
}
ROUTES = {
    "well-data-api": (("/v2/wells/{well}/surveys", "GET"), ("/v2/wells/{well}/logs", "GET")),
    "reservoir-modeler": (("/v1/models/{model}/run", "POST"), ("/v1/models/{model}", "GET")),
    "survey-ingest": (("/v1/ingest", "POST"), ("/health", "GET")),
}
DEFAULT_ENDPOINT = "http://127.0.0.1:14318"


@dataclass
class ServicePipeline:
    name: str
    host: str
    tracer: trace.Tracer
    logger: logging.Logger
    duration: metrics.Histogram
    requests: metrics.Counter
    errors: metrics.Counter
    tracer_provider: TracerProvider
    meter_provider: MeterProvider
    logger_provider: LoggerProvider

    def shutdown(self) -> None:
        self.tracer_provider.force_flush(10_000)
        self.meter_provider.force_flush(10_000)
        self.logger_provider.force_flush(10_000)
        self.tracer_provider.shutdown()
        self.meter_provider.shutdown()
        self.logger_provider.shutdown()


def _resource(service: str, host: str) -> Resource:
    return Resource.create(
        {
            "service.name": service,
            "service.version": "1.4.0",
            "deployment.environment": ENV_BY_HOST.get(host, "prod"),
            "host.name": host,
            "data_stream.dataset": "workshop.app.otel",
            "data_stream.namespace": ENV_BY_HOST.get(host, "prod"),
            "team": "reservoir-apps",
            "telemetry.workshop": "arch-02",
        }
    )


def build_pipeline(service: str, endpoint: str, host: str) -> ServicePipeline:
    resource = _resource(service, host)
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
    logger = logging.getLogger(f"arch02.{service}.{host}")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.propagate = False

    meter = meters.get_meter("arch-02-factory")
    return ServicePipeline(
        name=service,
        host=host,
        tracer=traces.get_tracer("arch-02-factory"),
        logger=logger,
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


def emit_one(
    pipelines: dict[tuple[str, str], ServicePipeline],
    rng: random.Random,
) -> str:
    key = rng.choice(list(pipelines))
    _host, service = key
    pipe = pipelines[key]
    route, method = rng.choice(ROUTES[service])
    well = 8000 + rng.randint(0, 200)
    path = route.format(well=well, model=rng.randint(10, 99))
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
        elif service == "reservoir-modeler" and rng.random() < 0.4:
            with pipe.tracer.start_as_current_span(
                "model.solve",
                kind=SpanKind.INTERNAL,
                attributes={"model.solver": "finite-difference"},
            ):
                time.sleep(min(latency / 2, 0.08))

        if status >= 500:
            span.set_status(Status(StatusCode.ERROR, "upstream timeout"))
            pipe.logger.error("request failed path=%s status=%s", path, status)
            pipe.errors.add(1, {"http.request.method": method, "url.path": path})
        elif status >= 400:
            pipe.logger.warning("client error path=%s status=%s", path, status)
        else:
            pipe.logger.info("request completed path=%s status=%s", path, status)

        pipe.duration.record(latency, attrs)
        pipe.requests.add(1, {"http.request.method": method, "http.response.status_code": status})
    return service


def build_pipelines(
    endpoints: list[str], hosts: list[str]
) -> dict[tuple[str, str], ServicePipeline]:
    if len(hosts) != len(endpoints):
        raise ValueError("hosts and endpoints must be the same length")
    pipelines: dict[tuple[str, str], ServicePipeline] = {}
    for host, endpoint in zip(hosts, endpoints):
        for service in SERVICES:
            pipelines[(host, service)] = build_pipeline(service, endpoint, host)
    return pipelines


def sample(count: int, endpoints: list[str], hosts: list[str]) -> None:
    pipelines = build_pipelines(endpoints, hosts)
    rng = random.Random()
    tallies: dict[str, int] = {name: 0 for name in SERVICES}
    try:
        for _ in range(count):
            tallies[emit_one(pipelines, rng)] += 1
    finally:
        for pipe in pipelines.values():
            pipe.shutdown()
    print(
        "sample "
        + " ".join(f"{name}={n}" for name, n in tallies.items())
        + f" endpoints={','.join(endpoints)}"
    )


def stream(
    tick: float,
    duration: float | None,
    endpoints: list[str],
    hosts: list[str],
) -> None:
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
    print(f"streaming to {','.join(endpoints)} tick={tick}s (Ctrl-C to stop)")
    try:
        while not stop:
            for _ in range(rng.randint(2, 6)):
                emit_one(pipelines, rng)
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
    parser.add_argument("mode", choices=("sample", "stream"))
    parser.add_argument("--count", type=int, default=40)
    parser.add_argument("--tick", type=float, default=2.0)
    parser.add_argument("--duration", type=float, default=None)
    parser.add_argument(
        "--endpoint",
        action="append",
        dest="endpoints",
        help="OTLP/HTTP base URL (repeat per agent). Default: first otel agent.",
    )
    parser.add_argument(
        "--host",
        action="append",
        dest="hosts",
        help="host.name for each --endpoint (same order)",
    )
    args = parser.parse_args()
    endpoints = [e.rstrip("/") for e in (args.endpoints or [DEFAULT_ENDPOINT])]
    hosts = args.hosts or [HOSTS[i % len(HOSTS)] for i in range(len(endpoints))]
    if len(hosts) != len(endpoints):
        raise SystemExit("provide the same number of --host and --endpoint values")
    if args.mode == "sample":
        sample(args.count, endpoints, hosts)
    else:
        stream(args.tick, args.duration, endpoints, hosts)


if __name__ == "__main__":
    main()
