#!/usr/bin/env python3
"""Fan the same logs/metrics/traces through a fleet of Elastic Agents.

Each agent is Elastic Agent in otel mode (see agents/docker-compose.otel.yml),
one per workshop host (aks-sre-01..03). The event shape matches edot/factory.py.

Usage (repo root, agent containers already running):

    .venv/bin/python agents/factory.py sample --count 60
    .venv/bin/python agents/factory.py stream --tick 2
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "edot"))

import factory as otel  # noqa: E402

AGENT_ENDPOINTS = (
    "http://127.0.0.1:14318",
    "http://127.0.0.1:15318",
    "http://127.0.0.1:16318",
)
AGENT_HOSTS = ("aks-sre-01", "aks-sre-02", "aks-sre-03")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("sample", "stream"))
    parser.add_argument("--count", type=int, default=60)
    parser.add_argument("--tick", type=float, default=2.0)
    parser.add_argument("--duration", type=float, default=None)
    parser.add_argument(
        "--syslog-ratio",
        type=float,
        default=otel.DEFAULT_SYSLOG_RATIO,
        help="fraction of events that are host syslog (ssh/sudo/useradd)",
    )
    parser.add_argument(
        "--endpoint",
        action="append",
        dest="endpoints",
        help="Override agent OTLP/HTTP URLs (repeat). Defaults to :14318,:15318,:16318",
    )
    args = parser.parse_args()
    endpoints = [e.rstrip("/") for e in (args.endpoints or AGENT_ENDPOINTS)]
    hosts = list(AGENT_HOSTS[: len(endpoints)])
    if args.mode == "sample":
        otel.sample(args.count, endpoints, hosts, syslog_ratio=args.syslog_ratio)
    else:
        otel.stream(args.tick, args.duration, endpoints, hosts, syslog_ratio=args.syslog_ratio)


if __name__ == "__main__":
    main()
