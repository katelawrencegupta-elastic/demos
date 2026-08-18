#!/usr/bin/env python3
"""Export ingest pipelines, transforms, and ML jobs from Elastic Cloud.

Writes JSON artifacts under artifacts/ and bundles them into
artifacts/elastic-demo-artifacts.zip for download.

Usage:
  cp logstash/.env.example logstash/.env   # set ELASTIC_HOSTS and ELASTIC_API_KEY
  python3 scripts/export-elastic-artifacts.py

Credentials are read from logstash/.env (or ELASTIC_HOSTS / ELASTIC_API_KEY env vars).
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib import error, request

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "artifacts"

# Pipelines referenced by logstash/pipeline/main.conf plus ML helpers.
INGEST_PIPELINE_IDS = [
    "logs-netflow.log-2.25.1-klg",
    "logs-network_traffic.flow-1.34.2",
    "logs-network_traffic.dns-1.34.2",
    "logs-network_traffic.http-1.34.2",
    "logs-network_traffic.tls-1.34.2",
    "logs-network_traffic.icmp-1.34.2",
    "logs-network_traffic.dhcpv4-1.34.2",
    "logs-network_traffic.amqp-1.34.2",
    "logs-network_traffic.cassandra-1.34.2",
    "logs-network_traffic.mysql-1.34.2",
    "logs-network_traffic.pgsql-1.34.2",
    "logs-network_traffic.redis-1.34.2",
    "logs-network_traffic.thrift-1.34.2",
    "logs-network_traffic.mongodb-1.34.2",
    "logs-network_traffic.memcached-1.34.2",
    "logs-network_traffic.nfs-1.34.2",
    "logs-network_traffic.sip-1.34.2",
    "logs-dga.dns-1.0.0",
    "logs-snort.log-1.21.2",
    "1.6.0-ml_beaconing_ingest_pipeline",
    "3.0.1-ml_dga_ingest_pipeline",
    "3.0.1-ml_dga_inference_pipeline",
]

TRANSFORM_IDS = [
    "logs-beaconing.pivot_transform-default-1.6.0",
]

ML_JOB_IDS = [
    "dga_high_sum_probability_ea",
    "high_count_network_events",
    "high_count_network_denies",
    "rare_destination_country",
]

TRAINED_MODEL_IDS = [
    "dga_1611725_2.0",
]


def load_env() -> tuple[str, str]:
    env_path = ROOT / "logstash" / ".env"
    if env_path.is_file():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            if key not in os.environ:
                os.environ[key] = value.strip().strip('"').strip("'")

    hosts = os.environ.get("ELASTIC_HOSTS", "").strip().rstrip("/")
    api_key = os.environ.get("ELASTIC_API_KEY", "").strip()
    if not hosts or not api_key:
        sys.exit("Set ELASTIC_HOSTS and ELASTIC_API_KEY in logstash/.env")
    return hosts, api_key


class Client:
    def __init__(self, hosts: str, api_key: str) -> None:
        self.hosts = hosts
        self.headers = {
            "Authorization": f"ApiKey {base64.b64encode(api_key.encode()).decode()}",
            "Content-Type": "application/json",
        }

    def request(self, method: str, path: str, body: dict | None = None) -> dict:
        data = json.dumps(body).encode() if body is not None else None
        req = request.Request(f"{self.hosts}{path}", data=data, headers=self.headers, method=method)
        try:
            with request.urlopen(req, timeout=120) as resp:
                raw = resp.read()
                return json.loads(raw) if raw else {}
        except error.HTTPError as exc:
            detail = exc.read().decode()
            return {"_error": exc.code, "_detail": detail[:1000]}


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n")


def export_ingest_pipelines(client: Client, manifest: dict) -> None:
    out_dir = ARTIFACTS / "ingest-pipelines"
    batch = client.request("GET", f"/_ingest/pipeline/{','.join(INGEST_PIPELINE_IDS)}")
    if "_error" in batch:
        manifest["errors"].append({"type": "ingest_pipelines_batch", **batch})
        return

    for pipeline_id, body in batch.items():
        rel = f"ingest-pipelines/{pipeline_id}.json"
        write_json(ARTIFACTS / rel, {pipeline_id: body})
        manifest["ingest_pipelines"].append(
            {
                "id": pipeline_id,
                "file": rel,
                "processors": len(body.get("processors", [])),
            }
        )


def export_transforms(client: Client, manifest: dict) -> None:
    for transform_id in TRANSFORM_IDS:
        payload = client.request("GET", f"/_transform/{transform_id}")
        if "_error" in payload:
            manifest["errors"].append({"type": "transform", "id": transform_id, **payload})
            continue

        rel = f"transforms/{transform_id}.json"
        write_json(ARTIFACTS / rel, payload)
        dest_index = None
        transforms = payload.get("transforms") or []
        if transforms:
            dest_index = transforms[0].get("dest", {}).get("index")
        manifest["transforms"].append(
            {"id": transform_id, "file": rel, "dest_index": dest_index}
        )


def export_ml_jobs(client: Client, manifest: dict) -> None:
    for job_id in ML_JOB_IDS:
        job = client.request("GET", f"/_ml/anomaly_detectors/{job_id}")
        if "_error" in job:
            manifest["errors"].append({"type": "ml_job", "id": job_id, **job})
            continue

        rel = f"ml-jobs/{job_id}.json"
        write_json(ARTIFACTS / rel, job)
        manifest["ml_jobs"].append({"id": job_id, "file": rel})

        datafeed_id = f"datafeed-{job_id}"
        datafeed = client.request("GET", f"/_ml/datafeeds/{datafeed_id}")
        if "_error" not in datafeed:
            df_rel = f"ml-datafeeds/{datafeed_id}.json"
            write_json(ARTIFACTS / df_rel, datafeed)
            manifest["ml_datafeeds"].append({"id": datafeed_id, "file": df_rel})


def export_trained_models(client: Client, manifest: dict) -> None:
    for model_id in TRAINED_MODEL_IDS:
        model = client.request("GET", f"/_ml/trained_models/{model_id}")
        if "_error" in model:
            manifest["errors"].append({"type": "trained_model", "id": model_id, **model})
            continue

        rel = f"ml-trained-models/{model_id}.json"
        write_json(ARTIFACTS / rel, model)
        manifest["ml_trained_models"].append({"id": model_id, "file": rel})


def create_zip(manifest: dict) -> Path:
    zip_path = ARTIFACTS / "elastic-demo-artifacts.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for section in (
            "ingest_pipelines",
            "transforms",
            "ml_jobs",
            "ml_datafeeds",
            "ml_trained_models",
        ):
            for item in manifest[section]:
                zf.write(ARTIFACTS / item["file"], item["file"])
        zf.write(ARTIFACTS / "manifest.json", "manifest.json")
    return zip_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--no-zip",
        action="store_true",
        help="Skip creating elastic-demo-artifacts.zip",
    )
    args = parser.parse_args()

    hosts, api_key = load_env()
    client = Client(hosts, api_key)

    manifest = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "source": "scripts/export-elastic-artifacts.py",
        "elastic_hosts": "${ELASTIC_HOSTS}",
        "ingest_pipelines": [],
        "transforms": [],
        "ml_jobs": [],
        "ml_datafeeds": [],
        "ml_trained_models": [],
        "errors": [],
    }

    export_ingest_pipelines(client, manifest)
    export_transforms(client, manifest)
    export_ml_jobs(client, manifest)
    export_trained_models(client, manifest)

    write_json(ARTIFACTS / "manifest.json", manifest)

    zip_path = None
    if not args.no_zip:
        zip_path = create_zip(manifest)

    print("Export complete:")
    print(f"  ingest pipelines: {len(manifest['ingest_pipelines'])}")
    print(f"  transforms:       {len(manifest['transforms'])}")
    print(f"  ml jobs:          {len(manifest['ml_jobs'])}")
    print(f"  ml datafeeds:     {len(manifest['ml_datafeeds'])}")
    print(f"  trained models:   {len(manifest['ml_trained_models'])}")
    print(f"  errors:           {len(manifest['errors'])}")
    print(f"  manifest:         {ARTIFACTS / 'manifest.json'}")
    if zip_path:
        print(f"  zip bundle:       {zip_path} ({zip_path.stat().st_size:,} bytes)")
    if manifest["errors"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
