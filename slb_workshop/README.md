# SRE-01 — Platform Operations Fundamentals

Hands-on companion to the SLB SRE enablement session (Wed Aug 19, 2026).
This workshop cluster is **Elastic Cloud Serverless** (`klgslbworkshopsre01`).

| | URL |
|---|---|
| Elasticsearch | `https://klgslbworkshopsre01-cecd27.es.us-central1.gcp.elastic.cloud:443` |
| Kibana | `https://klgslbworkshopsre01-cecd27.kb.us-central1.gcp.elastic.cloud` |
| Managed OTLP | `https://klgslbworkshopsre01-cecd27.ingest.us-central1.gcp.elastic.cloud` |

## What you will operate

Four control surfaces for telemetry in Elasticsearch, then two ingestion philosophies that both land in those surfaces:

1. [Data streams, templates, and ingest pipelines](labs/01-data-streams-templates-pipelines.md) (~35 min)
2. [Data tiers vs data stream lifecycle](labs/02-data-tiers-lifecycle.md) (~20 min)
3. [Fleet-managed Elastic Agent vs EDOT collector](labs/03-fleet-vs-edot.md) (~35 min)

Facilitator notes: [labs/facilitator.md](labs/facilitator.md)

## Setup

```bash
cp .env.example .env   # then set ELASTIC_API_KEY
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python scripts/ping.py
.venv/bin/python scripts/apply.py
.venv/bin/python scripts/simulate_pipeline.py
.venv/bin/python scripts/ingest.py
.venv/bin/python scripts/verify.py
.venv/bin/python scripts/create_kibana.py

# OTel path (one collector)
docker compose --env-file .env -f edot/docker-compose.yml up -d
.venv/bin/python edot/factory.py sample --count 40

# Elastic Agent path — Fleet-managed (policy sre-01-workshop)
.venv/bin/python agents/enroll.py
.venv/bin/python agents/syslog_factory.py sample --count 80

# Elastic Agent path — otel mode, same OTLP signals as EDOT
docker compose --env-file .env -f agents/docker-compose.otel.yml up -d
.venv/bin/python agents/factory.py sample --count 60
```

Reset the lab objects with `.venv/bin/python scripts/teardown.py`.

`.env` is gitignored. Required variables: `ELASTIC_URL`, `ELASTIC_API_KEY`, `KIBANA_URL`, `ELASTIC_OTLP_ENDPOINT`. Fleet enroll also needs `FLEET_URL` (in `.env.example`); `agents/enroll.py` fetches the enrollment token from Kibana.

## Kibana

- Discover: [Workshop platform logs](https://klgslbworkshopsre01-cecd27.kb.us-central1.gcp.elastic.cloud/app/discover#/?_a=(index:'workshop-platform-logs'))
- Dashboard: [SRE-01 Workshop — Platform logs](https://klgslbworkshopsre01-cecd27.kb.us-central1.gcp.elastic.cloud/app/dashboards#/view/bb3f65fa-c3d7-4b09-8295-b9645c789de9)
- Dashboard: [SRE-01 Workshop — Agents vs EDOT](https://klgslbworkshopsre01-cecd27.kb.us-central1.gcp.elastic.cloud/app/dashboards#/view/c8f4e1a2-9b3d-4e6f-a7c0-1d2e3f4a5b6c)

Recreate with `.venv/bin/python scripts/create_kibana.py`.

## Design constraints on this cluster

| Capability | On this Serverless project |
|---|---|
| Data streams, index / component templates, ingest pipelines | Yes |
| Data stream lifecycle (`data_retention`) | Yes — this is the retention lever |
| ILM + hot/warm/cold/frozen data tiers | **No** — hosted/self-managed only; lab 2 covers the mapping |
| Fleet + Elastic Agent integrations | Yes, in Kibana |
| EDOT Collector (Elastic Agent in `otel` mode) | Yes; supported intake is **Managed OTLP** or **Elastic Agent Gateway**, not APM Server OTLP |

## Docs

- [Data streams](https://www.elastic.co/docs/manage-data/data-store/data-streams)
- [Index and component templates](https://www.elastic.co/docs/manage-data/data-store/templates)
- [Ingest pipelines](https://www.elastic.co/docs/manage-data/ingest/transform-enrich/ingest-pipelines)
- [Data stream lifecycle](https://www.elastic.co/docs/manage-data/lifecycle/data-stream)
- [ILM](https://www.elastic.co/docs/manage-data/lifecycle/index-lifecycle-management) (hosted / self-managed)
- [Elastic OpenTelemetry / EDOT](https://www.elastic.co/docs/reference/opentelemetry)
- [Elastic Agent as OTel Collector](https://www.elastic.co/docs/reference/fleet/elastic-agent-as-otel-collector)
- [Managed OTLP Endpoint](https://www.elastic.co/docs/reference/opentelemetry/managed-inputs/managed-otlp-endpoint)
- [elastic/opentelemetry](https://github.com/elastic/opentelemetry)
