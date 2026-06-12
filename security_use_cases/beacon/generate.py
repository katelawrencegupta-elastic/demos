#!/usr/bin/env python3
"""Generate synthetic network beaconing activity across syslog, NetFlow, and Snort outputs."""

import json
import os
import random
import socket
import struct
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

INFECTED_PREFIX = "10.0.50."
C2_PREFIXES = (
    "185.220.101.",
    "45.33.32.",
    "104.244.42.",
    "91.219.236.",
)
C2_PORTS = (443, 8080, 8443, 4444)
INTERVAL_CHOICES = (60, 120, 300, 600)

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

BEACON_SNORT_SIGNATURES = [
    (2024898, 3, "ET TROJAN Possible C2 Beacon Traffic", "A Network Trojan was detected", 1),
    (2016149, 2, "ET MALWARE Periodic HTTP POST Request", "A Network Trojan was detected", 1),
    (2031002, 1, "ET TROJAN Outbound Periodic Connection to Rare Destination", "A Network Trojan was detected", 1),
    (2013414, 4, "ET INFO Suspicious Regular Outbound TCP Session", "Misc activity", 2),
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
    return f"<{priority}>{timestamp} {hostname} beacon-demo: {message}".encode("utf-8")


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
    src_port: int,
    dst_port: int,
    octets: int,
    packets: int,
) -> bytes:
    return struct.pack(
        "!IIBHHBIIIIBHH",
        ipv4_to_int(src_ip),
        ipv4_to_int(dst_ip),
        6,
        src_port,
        dst_port,
        0x18,
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
    dst_port: int,
    octets: int,
    packets: int,
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
        src_port=src_port,
        dst_port=dst_port,
        octets=octets,
        packets=packets,
    )
    return header + build_template_flowset() + build_data_flowset([record])


def host_name_from_ip(src_ip: str) -> str:
    suffix = src_ip.rsplit(".", 1)[-1]
    return f"infected-host-{suffix}"


def build_flow_event(
    *,
    now: datetime,
    src_ip: str,
    dst_ip: str,
    src_port: int,
    dst_port: int,
    interval: float,
    jitter: float,
    sequence: int,
    octets: int,
    packets: int,
    process_pid: int,
) -> dict:
    # Network Beaconing ML transform expects Elastic Defend-style disconnect events.
    src_bytes = max(octets // 2, 1)
    dst_bytes = max(octets - src_bytes, 1)
    host_name = host_name_from_ip(src_ip)
    return {
        "@timestamp": now.isoformat(),
        "event": {
            "category": ["network"],
            "dataset": "network_traffic.flow",
            "kind": "event",
            "type": ["end"],
            "action": "disconnect_received",
        },
        "host": {
            "name": host_name,
            "hostname": host_name,
        },
        "process": {
            "name": "beaconloader",
            "pid": process_pid,
        },
        "tags": ["beacon", "c2"],
        "network": {
            "transport": "tcp",
            "protocol": "tcp",
            "bytes": octets,
            "packets": packets,
        },
        "source": {
            "ip": src_ip,
            "port": src_port,
            "bytes": src_bytes,
        },
        "destination": {
            "ip": dst_ip,
            "port": dst_port,
            "bytes": dst_bytes,
        },
        "beacon": {
            "interval_seconds": interval,
            "jitter_ratio": jitter,
            "sequence": sequence,
            "suspicious": True,
            "pattern": "periodic_c2",
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
    src_ip: str,
    dst_ip: str,
    src_port: int,
    dst_port: int,
    interval: float,
    alert_format: str,
    hostname: str,
) -> bytes:
    full_msg = f"{msg} (interval={interval:.0f}s)"
    syslog_priority = 21 * 8 + 1

    if alert_format == "json":
        body = json.dumps(
            {
                "timestamp": now.strftime("%m/%d-%H:%M:%S.") + f"{now.microsecond:06d}",
                "proto": "TCP",
                "src_addr": src_ip,
                "src_port": src_port,
                "dst_addr": dst_ip,
                "dst_port": dst_port,
                "rule": f"1:{sid}:{rev}",
                "action": "alert",
                "msg": full_msg,
                "class": classification,
                "priority": priority,
                "beacon_interval": interval,
            },
            separators=(",", ": "),
        )
        return wrap_syslog(syslog_priority, hostname, body, now)

    flow = f"{src_ip}:{src_port} -> {dst_ip}:{dst_port}"
    if alert_format == "snort3":
        body = f'[1:{sid}:{rev}] "{full_msg}" {{TCP}} {flow}'
    else:
        body = (
            f"[1:{sid}:{rev}] {full_msg} "
            f"[Classification: {classification}] [Priority: {priority}] "
            f"{{TCP}} {flow}"
        )
    return wrap_syslog(syslog_priority, hostname, body, now)


@dataclass
class BeaconProfile:
    src_ip: str
    c2_ip: str
    c2_port: int
    interval: float
    jitter: float
    src_port: int
    octets: int
    packets: int
    process_pid: int
    sequence: int = 0
    next_beacon: float = field(default=0.0)

    def schedule_next(self, now: float) -> None:
        jitter_factor = 1.0 + random.uniform(-self.jitter, self.jitter)
        self.next_beacon = now + (self.interval * jitter_factor)


class BeaconSimulator:
    def __init__(self) -> None:
        self.output_mode = os.environ.get("BEACON_OUTPUT_MODE", "all").lower()
        self.syslog_target = os.environ.get("BEACON_SYSLOG_TARGET", "172.17.0.2")
        self.syslog_port = env_int("BEACON_SYSLOG_PORT", 514)
        self.netflow_target = os.environ.get("BEACON_NETFLOW_TARGET", "172.17.0.2")
        self.netflow_port = env_int("BEACON_NETFLOW_PORT", 2055)
        self.jitter = env_float("BEACON_JITTER", 0.05)
        self.alert_format = os.environ.get("BEACON_SNORT_FORMAT", "fast").lower()
        self.hostname = os.environ.get("BEACON_HOSTNAME", "beacon-demo")
        self.tick = env_float("BEACON_TICK", 0.5)
        self.alert_probability = env_float("BEACON_ALERT_PROBABILITY", 0.35)

        intervals = self._parse_intervals(os.environ.get("BEACON_INTERVALS", ""))
        host_count = env_int("BEACON_HOSTS", 3)
        c2_count = max(1, env_int("BEACON_C2_COUNT", 2))
        c2_targets = [
            (random_host(random.choice(C2_PREFIXES)), random.choice(C2_PORTS))
            for _ in range(c2_count)
        ]

        now = time.monotonic()
        self.profiles = []
        for index in range(host_count):
            c2_ip, c2_port = c2_targets[index % len(c2_targets)]
            interval = intervals[index % len(intervals)]
            profile = BeaconProfile(
                src_ip=random_host(INFECTED_PREFIX),
                c2_ip=c2_ip,
                c2_port=c2_port,
                interval=interval,
                jitter=self.jitter,
                src_port=random_port(),
                octets=random.choice((64, 96, 128, 192, 256)),
                packets=random.choice((1, 2, 3)),
                process_pid=random.randint(2000, 65000),
            )
            profile.schedule_next(now + random.uniform(0, interval))
            self.profiles.append(profile)

        self.syslog_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.netflow_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.flow_sequence = random.randint(1, 1_000_000)
        self.start = time.monotonic()
        self.pkt_num = random.randint(1, 10_000)

        if self.output_mode not in {"all", "flow", "netflow", "snort"}:
            raise ValueError(f"Unsupported BEACON_OUTPUT_MODE={self.output_mode!r}")
        if self.alert_format not in {"fast", "snort3", "json"}:
            raise ValueError(f"Unsupported BEACON_SNORT_FORMAT={self.alert_format!r}")

    @staticmethod
    def _parse_intervals(raw: str) -> list[float]:
        if raw.strip():
            return [float(value.strip()) for value in raw.split(",") if value.strip()]
        return [float(value) for value in INTERVAL_CHOICES]

    def send_flow_event(self, event: dict, now: datetime) -> None:
        body = json.dumps(event, separators=(",", ":"))
        self.syslog_sock.sendto(
            wrap_syslog(21 * 8 + 6, self.hostname, body, now),
            (self.syslog_target, self.syslog_port),
        )

    def send_netflow(self, profile: BeaconProfile, now: datetime) -> None:
        sys_uptime_ms = int((time.monotonic() - self.start) * 1000) & 0xFFFFFFFF
        datagram = build_netflow_datagram(
            flow_sequence=self.flow_sequence,
            sys_uptime_ms=sys_uptime_ms,
            unix_secs=int(now.timestamp()),
            src_ip=profile.src_ip,
            dst_ip=profile.c2_ip,
            src_port=profile.src_port,
            dst_port=profile.c2_port,
            octets=profile.octets,
            packets=profile.packets,
        )
        self.netflow_sock.sendto(datagram, (self.netflow_target, self.netflow_port))
        self.flow_sequence = (self.flow_sequence + 1) & 0xFFFFFFFF

    def send_snort_alert(self, profile: BeaconProfile, now: datetime) -> None:
        sid, rev, msg, classification, priority = random.choice(BEACON_SNORT_SIGNATURES)
        payload = build_snort_alert(
            now=now,
            sid=sid,
            rev=rev,
            msg=msg,
            classification=classification,
            priority=priority,
            src_ip=profile.src_ip,
            dst_ip=profile.c2_ip,
            src_port=profile.src_port,
            dst_port=profile.c2_port,
            interval=profile.interval,
            alert_format=self.alert_format,
            hostname=self.hostname,
        )
        self.syslog_sock.sendto(payload, (self.syslog_target, self.syslog_port))
        self.pkt_num += 1

    def emit_beacon(self, profile: BeaconProfile, now: datetime) -> None:
        profile.sequence += 1

        if self.output_mode in {"all", "flow"}:
            self.send_flow_event(
                build_flow_event(
                    now=now,
                    src_ip=profile.src_ip,
                    dst_ip=profile.c2_ip,
                    src_port=profile.src_port,
                    dst_port=profile.c2_port,
                    interval=profile.interval,
                    jitter=profile.jitter,
                    sequence=profile.sequence,
                    octets=profile.octets,
                    packets=profile.packets,
                    process_pid=profile.process_pid,
                ),
                now,
            )

        if self.output_mode in {"all", "netflow"}:
            self.send_netflow(profile, now)

        if self.output_mode in {"all", "snort"} and random.random() < self.alert_probability:
            self.send_snort_alert(profile, now)

    def backfill_flow_history(self) -> None:
        if self.output_mode not in {"all", "flow"}:
            return
        hours = env_float("BEACON_BACKFILL_HOURS", 6.0)
        if hours <= 0:
            return
        now = datetime.now(timezone.utc)
        start = now.timestamp() - (hours * 3600)
        sent = 0
        for profile in self.profiles:
            ts = start
            sequence = 0
            while ts <= now.timestamp():
                beacon_time = datetime.fromtimestamp(ts, tz=timezone.utc)
                sequence += 1
                self.send_flow_event(
                    build_flow_event(
                        now=beacon_time,
                        src_ip=profile.src_ip,
                        dst_ip=profile.c2_ip,
                        src_port=profile.src_port,
                        dst_port=profile.c2_port,
                        interval=profile.interval,
                        jitter=profile.jitter,
                        sequence=sequence,
                        octets=profile.octets,
                        packets=profile.packets,
                        process_pid=profile.process_pid,
                    ),
                    beacon_time,
                )
                sent += 1
                jitter_factor = 1.0 + random.uniform(-profile.jitter, profile.jitter)
                ts += profile.interval * jitter_factor
            profile.sequence = sequence
        print(
            f"Backfilled {sent} disconnect_received flow events over {hours:.0f}h "
            f"for ML beaconing transform",
            flush=True,
        )

    def run(self) -> None:
        print(
            f"Simulating network beaconing (mode={self.output_mode}) "
            f"syslog→{self.syslog_target}:{self.syslog_port} "
            f"netflow→{self.netflow_target}:{self.netflow_port} "
            f"from {len(self.profiles)} infected hosts",
            flush=True,
        )
        for profile in self.profiles:
            print(
                f"  {profile.src_ip} → {profile.c2_ip}:{profile.c2_port} "
                f"every {profile.interval:.0f}s (±{profile.jitter * 100:.0f}%)",
                flush=True,
            )

        self.backfill_flow_history()

        while True:
            now_mono = time.monotonic()
            now = datetime.now(timezone.utc)
            due = [profile for profile in self.profiles if now_mono >= profile.next_beacon]
            for profile in due:
                self.emit_beacon(profile, now)
                profile.schedule_next(now_mono)
            time.sleep(self.tick)


def main() -> int:
    try:
        simulator = BeaconSimulator()
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    try:
        simulator.run()
    except KeyboardInterrupt:
        print("\nStopped.", flush=True)
        return 0
    except OSError as exc:
        print(f"Error sending beacon traffic: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
