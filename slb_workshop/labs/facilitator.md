# Facilitator notes — SRE-01 workshop

**Session:** Platform Operations Fundamentals  
**Audience:** SREs & Infrastructure Ops  
**Deck:** SLB Enablement SRE-01 (60 min classroom). This repo is the hands-on companion (about 90 minutes if all three labs run).

## Outcomes

Participants can:

- Explain how a data stream, index template, component template, and ingest pipeline compose.
- Set retention on **this** Serverless project with data stream lifecycle, and map that to ILM tiers on hosted clusters.
- Choose Fleet-managed Agent vs EDOT/`otel` mode using ownership and the EDOT SDK support boundary — not vendor preference.

## Timing

| Block | Classroom (60 min) | Hands-on (90 min) |
|---|---|---|
| Control surfaces (streams/templates/pipelines/tiers) | 15 min | Lab 1, 35 min |
| Two ingestion philosophies | 15 min | Lab 3 intro + Fleet UI, 15 min |
| Support boundary (EDOT ≠ APM OTLP) | 10 min | Stay on the slide; do not debate |
| Operational non-equivalence | 10 min | Lab 3 EDOT docker, 20 min |
| Lab 2 lifecycle | fold into block 1 | 20 min |
| Q&A | 10 min | remaining |

If time is short, **cut Docker** and keep Fleet UI + the support-boundary slide. Lab 1 `apply.py` / `ingest.py` is the must-run.

## Before the room

```bash
.venv/bin/python scripts/ping.py
.venv/bin/python scripts/teardown.py   # clean previous run
.venv/bin/python scripts/apply.py
.venv/bin/python scripts/ingest.py
.venv/bin/python scripts/verify.py
```

Confirm Kibana login and that Fleet is visible on the Serverless project. Managed OTLP is `https://klgslbworkshopsre01-cecd27.ingest.us-central1.gcp.elastic.cloud` (`ELASTIC_OTLP_ENDPOINT` in `.env`).

Dashboard: https://klgslbworkshopsre01-cecd27.kb.us-central1.gcp.elastic.cloud/app/dashboards#/view/bb3f65fa-c3d7-4b09-8295-b9645c789de9

Do not paste API keys into slides or chat transcripts.

## Talking points from the deck (do not skip)

1. Consistency across workstreams is the hard part, not the APIs.
2. Fleet vs OTel: both valid; expect coexistence.
3. EDOT SDKs + APM Server OTLP = unsupported even if it “works”.
4. Switching paths later is allowed and not free.

## Known gotchas on this cluster

- `GET _cluster/health` returns **410** in Serverless. Use `scripts/ping.py` / `GET /`.
- ILM APIs fail. Use `_data_stream/<name>/_lifecycle`.
- Do not set `number_of_shards` / `number_of_replicas` in templates here.
- OTel-native documents will **not** land in `logs-workshop.platform-default`. That is the lesson.

## Reset

```bash
.venv/bin/python scripts/teardown.py
docker compose -f edot/docker-compose.yml down
docker compose -f agents/docker-compose.yml down
docker compose -f agents/docker-compose.otel.yml down
```
