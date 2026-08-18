#!/usr/bin/env python3
"""Generate synthetic Snort IDS alerts and send them to a Logstash syslog input."""

import json
import os
import random
import socket
import sys
import time
from datetime import datetime, timezone

# (sid, rev, msg, classification, priority, proto, src_prefix, dst_prefix, dst_port)
SIGNATURES = [
    (1000015, 0, "Pinging...", "Misc activity", 3, "ICMP", "10.50.10.", "175.16.", 0),
    (2100498, 12, "GPL ATTACK_RESPONSE id check returned root", "Potentially Bad Traffic", 2, "TCP", "10.0.1.", "192.0.2.", 80),
    (2024897, 4, "ET POLICY HTTP request to a *.onion address", "Potential Corporate Privacy Violation", 1, "TCP", "10.0.2.", "93.184.216.", 80),
    (2013028, 3, "ET POLICY SSL/TLS Certificate Observed", "Not Suspicious Traffic", 3, "TCP", "10.0.1.", "142.250.80.", 443),
    (2001219, 19, "ET SCAN Potential SSH Scan", "Attempted Information Leak", 2, "TCP", "198.51.100.", "10.0.1.", 22),
    (2010935, 2, "ET DNS Query for a Suspicious Domain", "A Network Trojan was detected", 1, "UDP", "10.0.1.", "8.8.8.", 53),
    (1000001, 1, "ICMP PING", "Misc activity", 3, "ICMP", "10.0.3.", "10.0.1.", 0),
    (1000002, 1, "ICMP Destination Unreachable", "Misc activity", 3, "ICMP", "10.0.1.", "10.0.4.", 0),
    (2016149, 2, "ET TROJAN Possible Windows executable download", "A Network Trojan was detected", 1, "TCP", "185.220.101.", "10.0.1.", 8080),
    (2024364, 4, "ET INFO Executable and linking format (ELF) file download", "Not Suspicious Traffic", 3, "TCP", "10.0.5.", "203.0.113.", 443),
    (2402000, 1, "ET CINS Active Threat Intelligence Poor Reputation IP", "Misc Attack", 2, "TCP", "45.33.32.", "10.0.1.", 445),
    (2013414, 9, "ET POLICY RDP connection request", "Misc activity", 3, "TCP", "10.0.6.", "10.0.1.", 3389),
]


def env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None:
        return default
    return int(value)


def random_host(prefix: str) -> str:
    if prefix.endswith("."):
        return f"{prefix}{random.randint(1, 254)}"
    return prefix


def random_port() -> int:
    return random.randint(1024, 65535)


def bsd_syslog_timestamp(now: datetime) -> str:
    return now.strftime("%b %d %H:%M:%S").replace(" 0", "  ", 1)


def build_fast_alert(
    *,
    sid: int,
    rev: int,
    msg: str,
    classification: str,
    priority: int,
    proto: str,
    src_ip: str,
    dst_ip: str,
    src_port: int,
    dst_port: int,
) -> str:
    generator = 1
    if proto in ("TCP", "UDP"):
        flow = f"{src_ip}:{src_port} -> {dst_ip}:{dst_port}"
    else:
        flow = f"{src_ip} -> {dst_ip}"

    return (
        f"[{generator}:{sid}:{rev}] {msg} "
        f"[Classification: {classification}] [Priority: {priority}] "
        f"{{{proto}}} {flow}"
    )


def build_snort3_syslog_alert(
    *,
    sid: int,
    rev: int,
    msg: str,
    proto: str,
    src_ip: str,
    dst_ip: str,
    src_port: int,
    dst_port: int,
) -> str:
    generator = 1
    if proto in ("TCP", "UDP"):
        flow = f"{src_ip}:{src_port} -> {dst_ip}:{dst_port}"
    else:
        flow = f"{src_ip} -> {dst_ip}"

    return f'[{generator}:{sid}:{rev}] "{msg}" {{{proto}}} {flow}'


def build_json_alert(
    *,
    now: datetime,
    sid: int,
    rev: int,
    msg: str,
    classification: str,
    priority: int,
    proto: str,
    src_ip: str,
    dst_ip: str,
    src_port: int,
    dst_port: int,
    pkt_num: int,
) -> str:
    generator = 1
    direction = "C2S" if src_ip.startswith(("10.", "192.168.")) else "S2C"
    payload = {
        "timestamp": now.strftime("%m/%d-%H:%M:%S.") + f"{now.microsecond:06d}",
        "pkt_num": pkt_num,
        "proto": proto,
        "pkt_gen": f"stream_{proto.lower()}",
        "pkt_len": random.randint(64, 1500),
        "dir": direction,
        "src_addr": src_ip,
        "src_port": src_port,
        "dst_addr": dst_ip,
        "dst_port": dst_port,
        "rule": f"{generator}:{sid}:{rev}",
        "action": random.choice(["alert", "allow", "would_drop"]),
        "msg": msg,
        "class": classification,
        "priority": priority,
    }
    return json.dumps(payload, separators=(",", ": "))


def wrap_syslog(priority: int, hostname: str, message: str, now: datetime) -> str:
    timestamp = bsd_syslog_timestamp(now)
    return f"<{priority}>{timestamp} {hostname} snort: {message}"


def build_alert(signature: tuple, pkt_num: int, now: datetime, alert_format: str, hostname: str) -> str:
    sid, rev, msg, classification, priority, proto, src_prefix, dst_prefix, dst_port = signature
    src_ip = random_host(src_prefix)
    dst_ip = random_host(dst_prefix) if dst_port else random_host(dst_prefix)
    src_port = random_port() if proto in ("TCP", "UDP") else 0
    # local5 facility (21) + alert severity (1)
    syslog_priority = 21 * 8 + 1

    if alert_format == "json":
        body = build_json_alert(
            now=now,
            sid=sid,
            rev=rev,
            msg=msg,
            classification=classification,
            priority=priority,
            proto=proto,
            src_ip=src_ip,
            dst_ip=dst_ip,
            src_port=src_port,
            dst_port=dst_port,
            pkt_num=pkt_num,
        )
        return wrap_syslog(syslog_priority, hostname, body, now)

    if alert_format == "snort3":
        body = build_snort3_syslog_alert(
            sid=sid,
            rev=rev,
            msg=msg,
            proto=proto,
            src_ip=src_ip,
            dst_ip=dst_ip,
            src_port=src_port,
            dst_port=dst_port,
        )
        return wrap_syslog(syslog_priority, hostname, body, now)

    body = build_fast_alert(
        sid=sid,
        rev=rev,
        msg=msg,
        classification=classification,
        priority=priority,
        proto=proto,
        src_ip=src_ip,
        dst_ip=dst_ip,
        src_port=src_port,
        dst_port=dst_port,
    )
    return wrap_syslog(syslog_priority, hostname, body, now)


def main() -> int:
    target = os.environ.get("SNORT_TARGET", "logstash")
    port = env_int("SNORT_PORT", 514)
    interval = float(os.environ.get("SNORT_INTERVAL", "2"))
    alerts_per_burst = env_int("SNORT_ALERTS_PER_BURST", 1)
    alert_format = os.environ.get("SNORT_FORMAT", "fast").lower()
    hostname = os.environ.get("SNORT_HOSTNAME", "snort-demo")

    if alert_format not in {"fast", "snort3", "json"}:
        print(f"Unsupported SNORT_FORMAT={alert_format!r}; use fast, snort3, or json", file=sys.stderr)
        return 1

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    pkt_num = random.randint(1, 10_000)

    print(
        f"Sending synthetic Snort alerts ({alert_format}) to {target}:{port} "
        f"every {interval}s (Ctrl+C to stop)",
        flush=True,
    )

    try:
        while True:
            now = datetime.now(timezone.utc)
            burst = random.randint(1, max(1, alerts_per_burst))
            for _ in range(burst):
                signature = random.choice(SIGNATURES)
                message = build_alert(signature, pkt_num, now, alert_format, hostname)
                sock.sendto(message.encode("utf-8"), (target, port))
                pkt_num += 1
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nStopped.", flush=True)
        return 0
    except OSError as exc:
        print(f"Error sending Snort alerts: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
