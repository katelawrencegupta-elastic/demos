# ARCH-02 — Lifecycle, Governance & Standards

Hands-on companion to the SLB Architect enablement session (Wed Sep 23, 2026).
This workshop cluster is **Elastic Cloud Serverless** (`slbworkshoparch02`).

Deck: [SLB - Enablement - ARCH 02](https://docs.google.com/presentation/d/1fowlbV3TjGpYHDFuX1lVrsjyZmpJ8uC6/edit)

| | URL |
|---|---|
| Elasticsearch | `https://slbworkshoparch02-f3f54b.es.us-central1.gcp.elastic.cloud:443` |
| Kibana | `https://slbworkshoparch02-f3f54b.kb.us-central1.gcp.elastic.cloud` |

The deck is **80% design review, 20% product evidence**. These labs are the evidence. The deliverable is the six governance artifacts in `artifacts/`, not a click-by-click product tour.

## What you will decide

1. [Retention classes — policy first, mechanism second](labs/01-retention-classes.md) (~25 min)
2. [ECS vs OTel — aligned, not unified](labs/02-ecs-vs-otel.md) (~25 min)
3. [Dataset / namespace taxonomy and template ownership](labs/03-taxonomy-and-templates.md) (~20 min)
4. [Governance blueprint](labs/04-governance-blueprint.md) (~20 min) — fill the artifacts

Facilitator notes: [labs/facilitator.md](labs/facilitator.md)  
Talk track (60 min lecture, no labs): [labs/talk-track-60.md](labs/talk-track-60.md)

## Setup

```bash
cp .env.example .env   # then set ELASTIC_API_KEY
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python scripts/ping.py
.venv/bin/python scripts/apply.py
.venv/bin/python scripts/ingest.py
.venv/bin/python scripts/verify.py
.venv/bin/python scripts/compare_schema.py
.venv/bin/python scripts/create_kibana.py
```

Reset with `.venv/bin/python scripts/teardown.py`.

`.env` is gitignored. Required variables: `ELASTIC_URL`, `ELASTIC_API_KEY`, `KIBANA_URL`.

Kibana evidence is **Discover** data views (ECS vs OTel) plus `scripts/verify.py`. Dev Tools queries are in the labs.

## Design constraints on this cluster

| Capability | On this Serverless project |
|---|---|
| Data streams, index / component templates, ingest pipelines | Yes |
| Data stream lifecycle (`data_retention`) | Yes — this is the retention lever |
| ILM + hot/warm/cold/frozen data tiers | **No** — hosted/self-managed only; lab 1 maps classes to ILM |
| DLM frozen searchable snapshots (`frozen_after`, 9.5 GA) | **No** on Serverless |
| Fleet vs EDOT as an operating model | Design decision in lab 4; do not treat them as interchangeable |

## Docs from the deck

- [ECS ↔ OTel alignment overview](https://www.elastic.co/docs/reference/ecs/ecs-otel-alignment-overview)
- [Elastic Agent as OTel Collector](https://www.elastic.co/docs/reference/fleet/elastic-agent-as-otel-collector)
- [OTel data streams](https://www.elastic.co/docs/reference/opentelemetry/data-streams)
- [Index lifecycle management](https://www.elastic.co/docs/manage-data/lifecycle/index)
- [Data stream lifecycle](https://www.elastic.co/docs/manage-data/lifecycle/data-stream)
- [DLM searchable snapshots](https://www.elastic.co/docs/manage-data/lifecycle/data-stream/tutorial-migrate-ilm-managed-data-stream-to-data-stream-lifecycle)
