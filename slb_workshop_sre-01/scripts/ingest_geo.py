#!/usr/bin/env python3
"""Index workshop docs with public source.ip + geo into logs-elastic_agent-default.

Used so Kibana Maps can plot source.geo.location. IPs are well-known public
DNS / registry addresses, not attack traffic.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

from elasticsearch.helpers import bulk

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from client import get_client  # noqa: E402

STREAM = "logs-elastic_agent-default"
HOSTS = ("aks-sre-01", "aks-sre-02", "aks-sre-03")

# Public DNS / RIR anycast addresses that GeoIP usually locates.
PUBLIC_IPS = (
    "8.8.8.8",
    "8.8.4.4",
    "208.67.222.222",
    "94.140.14.14",
    "77.88.8.8",
    "168.95.1.1",
    "200.160.0.8",
    "196.216.2.1",
    "101.101.101.101",
    "80.67.169.12",
    "202.12.27.33",
    "139.130.4.5",
    "84.200.69.80",
    "4.2.2.1",
    "193.19.64.8",
    "41.204.63.58",
)


def enrich_geo(es, ips: tuple[str, ...]) -> list[dict]:
    sim = es.ingest.simulate(
        body={
            "pipeline": {
                "processors": [
                    {
                        "geoip": {
                            "field": "source.ip",
                            "target_field": "source.geo",
                            "ignore_missing": True,
                        }
                    }
                ]
            },
            "docs": [{"_source": {"source": {"ip": ip}}} for ip in ips],
        }
    )
    out: list[dict] = []
    for doc in sim.get("docs", []):
        src = (doc.get("doc") or {}).get("_source") or {}
        source = src.get("source") or {}
        geo = source.get("geo") or {}
        if "location" not in geo:
            continue
        out.append(source)
    return out


def build_docs(sources: list[dict]) -> list[dict]:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    docs: list[dict] = []
    for i, source in enumerate(sources):
        ip = source["ip"]
        host = HOSTS[i % len(HOSTS)]
        geo = source.get("geo") or {}
        country = geo.get("country_name") or geo.get("country_iso_code") or "unknown"
        docs.append(
            {
                "@timestamp": now,
                "message": (
                    f"workshop geo sample: outbound check to {ip} "
                    f"({country}) from {host}"
                ),
                "log": {"level": "info"},
                "data_stream": {
                    "type": "logs",
                    "dataset": "elastic_agent",
                    "namespace": "default",
                },
                "event": {
                    "dataset": "elastic_agent",
                    "kind": "event",
                    "category": ["network"],
                    "type": ["info"],
                },
                "host": {"name": host, "hostname": host},
                "agent": {"name": host, "type": "filebeat"},
                "source": source,
                "related": {"ip": [ip]},
                "labels": {"workshop": "sre-01", "purpose": "geo-map"},
            }
        )
    return docs


def main() -> None:
    es = get_client()
    sources = enrich_geo(es, PUBLIC_IPS)
    docs = build_docs(sources)
    if not docs:
        raise SystemExit("GeoIP returned no locations; nothing indexed")
    actions = (
        {"_op_type": "create", "_index": STREAM, "_source": doc} for doc in docs
    )
    ok, errors = bulk(es, actions, refresh="wait_for", raise_on_error=False)
    countries = sorted(
        {
            (d["source"].get("geo") or {}).get("country_iso_code")
            for d in docs
            if (d["source"].get("geo") or {}).get("country_iso_code")
        }
    )
    print(
        f"indexed={ok} errors={len(errors) if errors else 0} "
        f"stream={STREAM} countries={','.join(countries)}"
    )
    if errors:
        print(errors[:3])
        raise SystemExit(1)


if __name__ == "__main__":
    main()
