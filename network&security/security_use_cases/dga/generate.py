#!/usr/bin/env python3
"""Generate synthetic DGA DNS activity across syslog, NetFlow, and Snort outputs."""

import json
import os
import random
import socket
import struct
import sys
import time
from datetime import datetime, timezone

from dga import ALGORITHMS, generate_domain

BENIGN_DOMAINS = (
    "google.com",
    "microsoft.com",
    "amazon.com",
    "github.com",
    "elastic.co",
    "cloudflare.com",
    "stackoverflow.com",
    "wikipedia.org",
)

INFECTED_PREFIX = "10.0.50."
DNS_SERVER_PREFIX = "8.8.8."
DNS_PORT = 53
SYSLOG_PROGRAM = "dga-demo"

NETFLOW_VERSION = 9
TEMPLATE_ID = 256
TEMPLATE_FIELDS = [
    (8, 4),   # IPV4_SRC_ADDR
    (12, 4),  # IPV4_DST_ADDR
    (4, 1),   # PROTOCOL
    (7, 2),   # L4_SRC_PORT
    (11, 2),  # L4_DST_PORT
    (6, 1),   # TCP_FLAGS
    (1, 4),   # IN_BYTES
    (2, 4),   # IN_PKTS
    (10, 4),  # INPUT_SNMPINT
    (14, 4),  # OUTPUT_SNMPINT
    (55, 1),  # DST_TOS
    (58, 2),  # SRC_VLAN
    (59, 2),  # DST_VLAN
]
RECORD_SIZE = sum(length for _, length in TEMPLATE_FIELDS)

DGA_SNORT_SIGNATURES = [
    (2025888, 3, "ET MALWARE Possible DGA Domain (long random subdomain)", "A Network Trojan was detected", 1),
    (2025889, 2, "ET MALWARE DGA Domain Query NXDOMAIN Response", "A Network Trojan was detected", 1),
    (2031001, 1, "ET TROJAN DGA C2 Domain Lookup", "A Network Trojan was detected", 1),
    (2010935, 2, "ET DNS Query for a Suspicious Domain", "A Network Trojan was detected", 1),
]


def env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None:
        return default
    return int(value)


def env_float(name: str, default: float) -> float:
    value = os.environ.get(name)
    if value is None:
        return default
    return float(value)


def random_host(prefix: str) -> str:
    if prefix.endswith("."):
        return f"{prefix}{random.randint(1, 254)}"
    return prefix


def random_port() -> int:
    return random.randint(49152, 65535)


def bsd_syslog_timestamp(now: datetime) -> str:
    return now.strftime("%b %d %H:%M:%S").replace(" 0", "  ", 1)


def wrap_syslog(priority: int, hostname: str, message: str, now: datetime) -> bytes:
    timestamp = bsd_syslog_timestamp(now)
    return f"<{priority}>{timestamp} {hostname} {SYSLOG_PROGRAM}: {message}".encode("utf-8")


def ipv4_to_int(ip: str) -> int:
    return struct.unpack("!I", socket.inet_aton(ip))[0]


def pad_to_32bit(data: bytes) -> bytes:
    pad_len = (4 - (len(data) % 4)) % 4
    return data + (b"\x00" * pad_len)


def build_template_flowset() -> bytes:
    body = struct.pack("!HH", TEMPLATE_ID, len(TEMPLATE_FIELDS))
    for ie_id, length in TEMPLATE_FIELDS:
        body += struct.pack("!HH", ie_id, length)
    body = pad_to_32bit(body)
    return struct.pack("!HH", 0, 4 + len(body)) + body


def build_flow_record(
    *,
    src_ip: str,
    dst_ip: str,
    protocol: int,
    src_port: int,
    dst_port: int,
) -> bytes:
    packets = random.randint(1, 3)
    octets = packets * random.randint(64, 512)
    return struct.pack(
        "!IIBHHBIIIIBHH",
        ipv4_to_int(src_ip),
        ipv4_to_int(dst_ip),
        protocol,
        src_port,
        dst_port,
        0,
        octets,
        packets,
        1,
        1,
        0,
        500,
        0,
    )


def build_data_flowset(records: list[bytes]) -> bytes:
    body = pad_to_32bit(b"".join(records))
    return struct.pack("!HH", TEMPLATE_ID, 4 + len(body)) + body


def build_netflow_datagram(
    *,
    flow_sequence: int,
    sys_uptime_ms: int,
    unix_secs: int,
    src_ip: str,
    dst_ip: str,
    src_port: int,
) -> bytes:
    header = struct.pack(
        "!HHIIII",
        NETFLOW_VERSION,
        2,
        sys_uptime_ms,
        unix_secs,
        flow_sequence,
        0,
    )
    record = build_flow_record(
        src_ip=src_ip,
        dst_ip=dst_ip,
        protocol=17,
        src_port=src_port,
        dst_port=DNS_PORT,
    )
    return header + build_template_flowset() + build_data_flowset([record])


def build_dns_event(
    *,
    now: datetime,
    domain: str,
    algorithm: str,
    src_ip: str,
    dst_ip: str,
    src_port: int,
    is_dga: bool,
    response_code: str,
) -> dict:
    return {
        "@timestamp": now.isoformat(),
        "event": {
            "category": ["network"],
            "dataset": "dga.dns",
            "kind": "event",
            "type": ["connection", "protocol"],
            "action": "dns_query",
        },
        "tags": ["dga", "dns", algorithm] if is_dga else ["dns", "benign"],
        "network": {
            "transport": "udp",
            "protocol": "dns",
        },
        "source": {
            "ip": src_ip,
            "port": src_port,
        },
        "destination": {
            "ip": dst_ip,
            "port": DNS_PORT,
        },
        "dns": {
            "question": {
                "name": domain,
                "type": "A",
            },
            "response_code": response_code,
            "type": "query",
        },
        "dga": {
            "algorithm": algorithm if is_dga else "none",
            "suspicious": is_dga,
        },
    }


def build_snort_alert(
    *,
    now: datetime,
    sid: int,
    rev: int,
    msg: str,
    classification: str,
    priority: int,
    domain: str,
    algorithm: str,
    src_ip: str,
    dst_ip: str,
    src_port: int,
    alert_format: str,
    hostname: str,
) -> bytes:
    full_msg = f'{msg} ({domain}) [DGA:{algorithm}]'
    syslog_priority = 21 * 8 + 1

    if alert_format == "json":
        body = json.dumps(
            {
                "timestamp": now.strftime("%m/%d-%H:%M:%S.") + f"{now.microsecond:06d}",
                "proto": "UDP",
                "src_addr": src_ip,
                "src_port": src_port,
                "dst_addr": dst_ip,
                "dst_port": DNS_PORT,
                "rule": f"1:{sid}:{rev}",
                "action": "alert",
                "msg": full_msg,
                "class": classification,
                "priority": priority,
                "dns_query": domain,
                "dga_algorithm": algorithm,
            },
            separators=(",", ": "),
        )
        return wrap_syslog(syslog_priority, hostname, body, now)

    flow = f"{src_ip}:{src_port} -> {dst_ip}:{DNS_PORT}"
    if alert_format == "snort3":
        body = f'[1:{sid}:{rev}] "{full_msg}" {{UDP}} {flow}'
    else:
        body = (
            f"[1:{sid}:{rev}] {full_msg} "
            f"[Classification: {classification}] [Priority: {priority}] "
            f"{{UDP}} {flow}"
        )
    return wrap_syslog(syslog_priority, hostname, body, now)


class DgaSimulator:
    def __init__(self) -> None:
        self.output_mode = os.environ.get("DGA_OUTPUT_MODE", "all").lower()
        self.syslog_target = os.environ.get("DGA_SYSLOG_TARGET", "172.17.0.2")
        self.syslog_port = env_int("DGA_SYSLOG_PORT", 514)
        self.netflow_target = os.environ.get("DGA_NETFLOW_TARGET", "172.17.0.2")
        self.netflow_port = env_int("DGA_NETFLOW_PORT", 2055)
        self.interval = env_float("DGA_INTERVAL", 3.0)
        self.queries_per_burst = env_int("DGA_QUERIES_PER_BURST", 3)
        self.dga_ratio = env_float("DGA_RATIO", 0.7)
        self.nxdomain_ratio = env_float("DGA_NXDOMAIN_RATIO", 0.92)
        self.alert_format = os.environ.get("DGA_SNORT_FORMAT", "fast").lower()
        self.hostname = os.environ.get("DGA_HOSTNAME", "dga-demo")
        self.algorithm = os.environ.get("DGA_ALGORITHM", "").lower() or None
        self.infected_hosts = [
            random_host(INFECTED_PREFIX)
            for _ in range(env_int("DGA_INFECTED_HOSTS", 3))
        ]

        self.syslog_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.netflow_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.flow_sequence = random.randint(1, 1_000_000)
        self.start = time.monotonic()
        self.pkt_num = random.randint(1, 10_000)

        if self.output_mode not in {"all", "dns", "netflow", "snort"}:
            raise ValueError(f"Unsupported DGA_OUTPUT_MODE={self.output_mode!r}")
        if self.alert_format not in {"fast", "snort3", "json"}:
            raise ValueError(f"Unsupported DGA_SNORT_FORMAT={self.alert_format!r}")
        if self.algorithm and self.algorithm not in ALGORITHMS:
            raise ValueError(
                f"Unsupported DGA_ALGORITHM={self.algorithm!r}; "
                f"use one of {', '.join(sorted(ALGORITHMS))}"
            )

    def pick_query(self) -> tuple[str, str, bool]:
        if random.random() < self.dga_ratio:
            domain, algorithm = generate_domain(self.algorithm)
            return domain, algorithm, True
        domain = random.choice(BENIGN_DOMAINS)
        return domain, "benign", False

    def send_dns_event(self, event: dict, now: datetime) -> None:
        body = json.dumps(event, separators=(",", ":"))
        self.syslog_sock.sendto(
            wrap_syslog(21 * 8 + 6, self.hostname, body, now),
            (self.syslog_target, self.syslog_port),
        )

    def send_netflow(self, src_ip: str, dst_ip: str, src_port: int, now: datetime) -> None:
        sys_uptime_ms = int((time.monotonic() - self.start) * 1000) & 0xFFFFFFFF
        datagram = build_netflow_datagram(
            flow_sequence=self.flow_sequence,
            sys_uptime_ms=sys_uptime_ms,
            unix_secs=int(now.timestamp()),
            src_ip=src_ip,
            dst_ip=dst_ip,
            src_port=src_port,
        )
        self.netflow_sock.sendto(datagram, (self.netflow_target, self.netflow_port))
        self.flow_sequence = (self.flow_sequence + 1) & 0xFFFFFFFF

    def send_snort_alert(
        self,
        *,
        now: datetime,
        domain: str,
        algorithm: str,
        src_ip: str,
        dst_ip: str,
        src_port: int,
    ) -> None:
        sid, rev, msg, classification, priority = random.choice(DGA_SNORT_SIGNATURES)
        payload = build_snort_alert(
            now=now,
            sid=sid,
            rev=rev,
            msg=msg,
            classification=classification,
            priority=priority,
            domain=domain,
            algorithm=algorithm,
            src_ip=src_ip,
            dst_ip=dst_ip,
            src_port=src_port,
            alert_format=self.alert_format,
            hostname=self.hostname,
        )
        self.syslog_sock.sendto(payload, (self.syslog_target, self.syslog_port))
        self.pkt_num += 1

    def emit_query(self, now: datetime) -> None:
        domain, algorithm, is_dga = self.pick_query()
        src_ip = random.choice(self.infected_hosts)
        dst_ip = random_host(DNS_SERVER_PREFIX)
        src_port = random_port()
        response_code = "NXDOMAIN" if is_dga and random.random() < self.nxdomain_ratio else "NOERROR"

        if self.output_mode in {"all", "dns"}:
            self.send_dns_event(
                build_dns_event(
                    now=now,
                    domain=domain,
                    algorithm=algorithm,
                    src_ip=src_ip,
                    dst_ip=dst_ip,
                    src_port=src_port,
                    is_dga=is_dga,
                    response_code=response_code,
                ),
                now,
            )

        if self.output_mode in {"all", "netflow"}:
            self.send_netflow(src_ip, dst_ip, src_port, now)

        if self.output_mode in {"all", "snort"} and is_dga:
            self.send_snort_alert(
                now=now,
                domain=domain,
                algorithm=algorithm,
                src_ip=src_ip,
                dst_ip=dst_ip,
                src_port=src_port,
            )

    def run(self) -> None:
        print(
            f"Simulating DGA activity (mode={self.output_mode}) "
            f"syslog→{self.syslog_target}:{self.syslog_port} "
            f"netflow→{self.netflow_target}:{self.netflow_port} "
            f"every {self.interval}s from {len(self.infected_hosts)} infected hosts",
            flush=True,
        )
        if self.algorithm:
            print(f"  algorithm: {self.algorithm}", flush=True)
        else:
            print(f"  algorithms: {', '.join(sorted(ALGORITHMS))}", flush=True)

        while True:
            now = datetime.now(timezone.utc)
            burst = random.randint(1, max(1, self.queries_per_burst))
            for _ in range(burst):
                self.emit_query(now)
            time.sleep(self.interval)


def main() -> int:
    try:
        simulator = DgaSimulator()
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    try:
        simulator.run()
    except KeyboardInterrupt:
        print("\nStopped.", flush=True)
        return 0
    except OSError as exc:
        print(f"Error sending DGA traffic: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
