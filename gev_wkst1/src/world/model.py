"""Deterministic Elastic Co. world expansion."""
from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import yaml

from src.config import WORLD_CONFIG


def stable_hex(ns: str, key: str, n: int = 32) -> str:
    h = hashlib.sha256(f"{ns}:{key}".encode()).hexdigest()
    return h[:n]


def iso(ts: datetime) -> str:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


@dataclass
class Pod:
    name: str
    service: str
    namespace: str
    node: str
    version: str
    uid: str
    language: str = "go"
    kind: str = "app"
    mem_limit: int = 512 * 1024 * 1024


@dataclass
class HeroTrace:
    trace_id: str
    tenant_id: str
    ts: datetime
    order_id: str
    slow_db: bool


@dataclass
class World:
    cfg: dict
    rng: random.Random
    pods: list[Pod] = field(default_factory=list)

    @property
    def tenants(self) -> list[dict]:
        return self.cfg["tenants"]

    @property
    def blast_tenant(self) -> dict:
        return next(t for t in self.tenants if t.get("blast"))

    @property
    def healthy_tenants(self) -> list[dict]:
        return [t for t in self.tenants if not t.get("blast")]

    @property
    def cluster(self) -> dict:
        return self.cfg["cluster"]

    def service(self, name: str) -> dict:
        return next(s for s in self.cfg["services"] if s["name"] == name)

    def pods_for(self, service: str) -> list[Pod]:
        return [p for p in self.pods if p.service == service]

    def node_inventory(self) -> list[dict]:
        """Derived host identity for the 3 EKS worker nodes."""
        region = self.cluster.get("region", "us-east-1")
        out = []
        for i, n in enumerate(self.cluster["nodes"]):
            name = n["name"]
            host = name.split(".")[0]
            parts = host.split("-")
            ip = ".".join(parts[1:]) if len(parts) >= 4 else f"10.0.0.{10 + i}"
            out.append(
                {
                    "name": name,
                    "ip": ip,
                    "az": n.get("az") or f"{region}{chr(ord('a') + i)}",
                    "instance_id": n.get("instance_id") or f"i-{stable_hex('ec2', name, 17)}",
                    "machine_type": n.get("machine_type") or "m6i.2xlarge",
                    "cores": int(n.get("cores", 8)),
                    "memory_bytes": int(n.get("memory_bytes", 32 * 1024 * 1024 * 1024)),
                    "disk_bytes": int(n.get("disk_bytes", 200 * 1024 * 1024 * 1024)),
                }
            )
        return out

    def incident_window(self, anchor: datetime) -> tuple[datetime, datetime]:
        # Floor to the minute so backfill and verify share the same window.
        # Clamp to `anchor` (now) so 60-minute alerts and SLO burn still fire.
        anchor = anchor.astimezone(timezone.utc).replace(second=0, microsecond=0)
        inc = self.cfg["incident"]
        start = anchor - timedelta(minutes=inc["start_offset_minutes"])
        end = start + timedelta(minutes=inc["duration_minutes"])
        if end > anchor:
            end = anchor
        if end <= start:
            end = anchor
            start = end - timedelta(minutes=inc["duration_minutes"])
        return start, end

    def hero_traces(self, anchor: datetime) -> list[HeroTrace]:
        start, end = self.incident_window(anchor)
        n = int(self.cfg["incident"]["hero_trace_count"])
        seed = self.cfg.get("seed", 7)
        span = (end - start).total_seconds()
        traces = []
        for i in range(n):
            frac = (i + 1) / (n + 1)
            ts = start + timedelta(seconds=span * frac)
            # IDs are seed-stable so verify matches a prior backfill.
            tid = stable_hex("trace", f"hero-{seed}-{i}", 32)
            traces.append(
                HeroTrace(
                    trace_id=tid,
                    tenant_id=self.blast_tenant["id"],
                    ts=ts,
                    order_id=f"ord-{stable_hex('ord', tid, 8)}",
                    slow_db=True,
                )
            )
        return traces


def _default_replicas(svc: dict) -> int:
    if "replicas" in svc:
        return int(svc["replicas"])
    kind = svc.get("type")
    if kind in ("db", "airflow"):
        return 1
    if kind == "messaging":
        return 3
    if kind == "cache":
        return 2
    return 2


def load_world() -> World:
    with open(WORLD_CONFIG) as f:
        cfg = yaml.safe_load(f)
    rng = random.Random(cfg.get("seed", 7))
    world = World(cfg=cfg, rng=rng)
    nodes = world.cluster["nodes"]
    for svc in world.cfg["services"]:
        replicas = _default_replicas(svc)
        version = svc.get("deploy_good") or svc.get("version") or "1.0.0"
        mem_limit = int(svc.get("mem_limit_mi", 256)) * 1024 * 1024
        for i in range(replicas):
            # Keep checkout-api pod names stable (labs / prior backfills).
            key = str(i) if svc["name"] == "checkout-api" else f"{svc['name']}:{i}"
            name = f"{svc['name']}-{stable_hex('pod', key, 5)}-{stable_hex('rs', key, 5)}"
            world.pods.append(
                Pod(
                    name=name,
                    service=svc["name"],
                    namespace=svc["namespace"],
                    node=nodes[i % len(nodes)]["name"],
                    version=version,
                    uid=stable_hex("uid", name, 16),
                    language=svc.get("language", "go"),
                    kind=svc.get("type", "app"),
                    mem_limit=mem_limit,
                )
            )
    return world


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def rng_for(ns: str, key: str) -> random.Random:
    return random.Random(int(stable_hex(ns, key, 16), 16))
