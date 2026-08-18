#!/usr/bin/env python3
"""Generate synthetic NetFlow v9 datagrams and send them to a Logstash UDP input."""

import os
import random
import socket
import struct
import sys
import time
from datetime import datetime, timezone

NETFLOW_VERSION = 9
HEADER_SIZE = 20
TEMPLATE_ID = 256

# NetFlow v9 IE definitions: (ie_id, length)
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
    (21, 4),  # LAST_SWITCHED
    (22, 4),  # FIRST_SWITCHED
]

RECORD_SIZE = sum(length for _, length in TEMPLATE_FIELDS)

# (name, src_prefix, dst_prefix, protocol, dst_port, tcp_flags, src_vlan, dst_vlan)
TRAFFIC_PATTERNS = [
    ("http", "10.0.1.", "93.184.216.", 6, 80, 0x18, 100, 0),
    ("https", "10.0.1.", "142.250.80.", 6, 443, 0x18, 100, 0),
    ("dns", "10.0.1.", "8.8.8.", 17, 53, 0, 100, 0),
    ("ssh", "10.0.2.", "10.0.1.", 6, 22, 0x18, 200, 100),
    ("snmp", "10.0.3.", "10.0.1.", 17, 161, 0, 300, 100),
    ("mysql", "10.0.4.", "10.0.1.", 6, 3306, 0x18, 400, 100),
    ("ntp", "10.0.1.", "129.6.15.", 17, 123, 0, 100, 0),
    ("icmp", "10.0.1.", "10.0.2.", 1, 0, 0, 100, 200),
]


def env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None:
        return default
    return int(value)


def ipv4_to_int(ip: str) -> int:
    return struct.unpack("!I", socket.inet_aton(ip))[0]


def random_host(prefix: str) -> str:
    if prefix.endswith("."):
        return f"{prefix}{random.randint(1, 254)}"
    return prefix


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
    dst_port: int,
    tcp_flags: int,
    src_vlan: int,
    dst_vlan: int,
    sys_uptime_ms: int,
) -> bytes:
    src_port = random.randint(1024, 65535) if protocol in (6, 17) else 0
    packets = random.randint(1, 500)
    octets = packets * random.randint(64, 1500)
    flow_duration_ms = random.randint(1_000, 120_000)
    first_switched = (sys_uptime_ms - flow_duration_ms) & 0xFFFFFFFF
    last_switched = sys_uptime_ms & 0xFFFFFFFF

    return struct.pack(
        "!IIBHHBIIIIBHHII",
        ipv4_to_int(src_ip),
        ipv4_to_int(dst_ip),
        protocol,
        src_port,
        dst_port,
        tcp_flags,
        octets,
        packets,
        random.randint(1, 2),  # input snmp ifindex
        random.randint(1, 2),  # output snmp ifindex
        random.choice([0, 8, 16, 32, 64, 128]),  # tos/dscp
        src_vlan,
        dst_vlan,
        last_switched,
        first_switched,
    )


def build_data_flowset(records: list[bytes]) -> bytes:
    body = pad_to_32bit(b"".join(records))
    return struct.pack("!HH", TEMPLATE_ID, 4 + len(body)) + body


def build_datagram(flow_sequence: int, sys_uptime_ms: int, unix_secs: int) -> bytes:
    count = min(env_int("NETFLOW_FLOWS_PER_PACKET", 8), 30)
    patterns = random.sample(TRAFFIC_PATTERNS, k=min(count, len(TRAFFIC_PATTERNS)))
    while len(patterns) < count:
        patterns.append(random.choice(TRAFFIC_PATTERNS))

    header = struct.pack(
        "!HHIIII",
        NETFLOW_VERSION,
        2,  # template flowset + data flowset
        sys_uptime_ms,
        unix_secs,
        flow_sequence,
        0,  # source_id
    )

    records = []
    for _, src_prefix, dst_prefix, protocol, dst_port, tcp_flags, src_vlan, dst_vlan in patterns:
        records.append(
            build_flow_record(
                src_ip=random_host(src_prefix),
                dst_ip=random_host(dst_prefix),
                protocol=protocol,
                dst_port=dst_port,
                tcp_flags=tcp_flags,
                src_vlan=src_vlan,
                dst_vlan=dst_vlan,
                sys_uptime_ms=sys_uptime_ms,
            )
        )

    return header + build_template_flowset() + build_data_flowset(records)


def main() -> int:
    target = os.environ.get("NETFLOW_TARGET", "172.17.0.2")
    port = env_int("NETFLOW_PORT", 2055)
    interval = float(os.environ.get("NETFLOW_INTERVAL", "1"))

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    flow_sequence = random.randint(1, 1_000_000)
    start = time.monotonic()

    print(
        f"Sending synthetic NetFlow v9 to {target}:{port} "
        f"every {interval}s (Ctrl+C to stop)",
        flush=True,
    )

    try:
        while True:
            now = datetime.now(timezone.utc)
            sys_uptime_ms = int((time.monotonic() - start) * 1000) & 0xFFFFFFFF
            datagram = build_datagram(
                flow_sequence=flow_sequence,
                sys_uptime_ms=sys_uptime_ms,
                unix_secs=int(now.timestamp()),
            )
            sock.sendto(datagram, (target, port))
            flow_sequence = (flow_sequence + 1) & 0xFFFFFFFF
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nStopped.", flush=True)
        return 0
    except OSError as exc:
        print(f"Error sending NetFlow: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
