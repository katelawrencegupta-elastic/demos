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

    def incident_window(self, anchor: datetime) -> tuple[datetime, datetime]:
        # Floor to the minute so backfill and verify share the same window.
        anchor = anchor.astimezone(timezone.utc).replace(second=0, microsecond=0)
        inc = self.cfg["incident"]
        offset_start = anchor - timedelta(minutes=inc["start_offset_minutes"])
        offset_end = offset_start + timedelta(minutes=inc["duration_minutes"])
        if offset_end <= anchor:
            return offset_start, offset_end
        end = anchor - timedelta(minutes=15)
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


def load_world() -> World:
    with open(WORLD_CONFIG) as f:
        cfg = yaml.safe_load(f)
    rng = random.Random(cfg.get("seed", 7))
    world = World(cfg=cfg, rng=rng)
    svc = world.service("checkout-api")
    nodes = world.cluster["nodes"]
    replicas = int(svc.get("replicas", 3))
    for i in range(replicas):
        version = svc.get("deploy_good", "2.4.0")
        name = f"checkout-api-{stable_hex('pod', str(i), 5)}-{stable_hex('rs', str(i), 5)}"
        world.pods.append(
            Pod(
                name=name,
                service="checkout-api",
                namespace=svc["namespace"],
                node=nodes[i % len(nodes)]["name"],
                version=version,
                uid=stable_hex("uid", name, 16),
            )
        )
    return world


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def rng_for(ns: str, key: str) -> random.Random:
    return random.Random(int(stable_hex(ns, key, 16), 16))
