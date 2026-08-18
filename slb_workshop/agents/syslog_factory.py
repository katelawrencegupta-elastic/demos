#!/usr/bin/env python3
"""Write ssh/sudo/useradd syslog lines into each Fleet agent's log files.

The System integration tails /var/log/secure (auth) and /var/log/messages
(syslog) inside the RHEL agent containers.

Usage (repo root, Fleet agents already running with log mounts):

    .venv/bin/python agents/syslog_factory.py sample --count 80
    .venv/bin/python agents/syslog_factory.py stream --tick 2
"""

from __future__ import annotations

import argparse
import random
import signal
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "edot"))

from syslog_events import next_event  # noqa: E402

HOSTS = ("aks-sre-01", "aks-sre-02", "aks-sre-03")
LOG_ROOT = Path(__file__).resolve().parent / "logs"
AUTH_FILES = ("secure",)
SYSLOG_FILES = ("messages",)


def host_dir(host: str) -> Path:
    return LOG_ROOT / host


def ensure_log_files(hosts: tuple[str, ...] = HOSTS) -> None:
    """Create empty log files so Docker file mounts are files, not directories."""
    for host in hosts:
        directory = host_dir(host)
        directory.mkdir(parents=True, exist_ok=True)
        for name in (*AUTH_FILES, *SYSLOG_FILES):
            path = directory / name
            if not path.exists():
                path.write_text("")


def _append(host: str, line: str) -> None:
    payload = line.rstrip("\n") + "\n"
    directory = host_dir(host)
    for name in (*AUTH_FILES, *SYSLOG_FILES):
        with (directory / name).open("a", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()


def emit_one(rng: random.Random, hosts: tuple[str, ...] = HOSTS) -> str:
    host = rng.choice(hosts)
    body, _attrs, _severity = next_event(host, rng)
    _append(host, body)
    return host


def sample(count: int, hosts: tuple[str, ...] = HOSTS) -> None:
    ensure_log_files(hosts)
    rng = random.Random()
    tallies = {host: 0 for host in hosts}
    for _ in range(count):
        tallies[emit_one(rng, hosts)] += 1
    print(
        "syslog sample "
        + " ".join(f"{host}={n}" for host, n in tallies.items())
        + f" dir={LOG_ROOT}"
    )


def stream(tick: float, duration: float | None, hosts: tuple[str, ...] = HOSTS) -> None:
    ensure_log_files(hosts)
    rng = random.Random()
    stop = False

    def _stop(*_args: object) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    started = time.time()
    emitted = 0
    print(f"streaming syslog to {LOG_ROOT} tick={tick}s (Ctrl-C to stop)")
    try:
        while not stop:
            burst = rng.randint(2, 6)
            for _ in range(burst):
                emit_one(rng, hosts)
                emitted += 1
            if duration is not None and time.time() - started >= duration:
                break
            time.sleep(tick)
    finally:
        print(f"stream complete emitted={emitted}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("sample", "stream", "init"))
    parser.add_argument("--count", type=int, default=80)
    parser.add_argument("--tick", type=float, default=2.0)
    parser.add_argument("--duration", type=float, default=None)
    args = parser.parse_args()
    if args.mode == "init":
        ensure_log_files()
        print(f"initialized {LOG_ROOT}")
        return
    if args.mode == "sample":
        sample(args.count)
    else:
        stream(args.tick, args.duration)


if __name__ == "__main__":
    main()
