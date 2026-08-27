# Elastic Co. — Elastic Observability Demo

Synthetic multi-tenant fulfillment SaaS demo for Elastic Cloud Serverless. One correlated incident drives four SE use cases in ~20–25 minutes, with optional labs.

## Use cases

1. **Unstructured orchestrator logs → structured, searchable, correlated**
2. **End-to-end distributed trace with tenant context and DB deep dive**
3. **EKS/pod incident root cause — restart to reason**
4. **Alerting quality + AI-assisted triage**

## Prerequisites

- Elastic Observability project (Serverless) with API key write access
- Python 3.11+

`.env` (gitignored):

```
ELASTIC_URL=https://….es.…elastic.cloud:443
ELASTIC_API_KEY=…
KIBANA_URL=https://….kb.…elastic.cloud
```

## Quick start

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

.venv/bin/python -m src.cli setup
.venv/bin/python -m src.cli backfill --hours 6
.venv/bin/python -m src.cli verify
.venv/bin/python -m src.cli dashboards   # deep links + re-import assets
```

Optional live tick during a customer session:

```bash
.venv/bin/python -m src.cli stream --tick 60
```

## Incident (planted)

**Tenant `acme-retail` checkout degradation** (~last 90 minutes of backfill):

- `checkout-api` **v2.4.1** memory leak → **OOMKilled** / restart loop on `eks-elastic-prod-usc1`
- Orchestrator DAG `fulfillment.checkout` retries
- Slow PostgreSQL `SELECT … FOR UPDATE` spans for `acme-retail`
- Hero `trace.id` values join orchestrator logs ↔ APM waterfall ↔ checkout logs

## Data streams

| Stream | Role |
|--------|------|
| `logs-elasticco.orchestrator-default` | Raw Airflow-style lines + grok pipeline |
| `logs-elasticco.checkout-default` | App / OOM container logs |
| `logs-elasticco.k8s.event-default` | OOMKilled / BackOff events |
| `metrics-elasticco.k8s.pod-default` | Pod memory / CPU / restart count |
| `traces-apm-default` | Multi-service traces + DB spans + `tenant.id` |

## Demo materials

- SE talk-track: [labs/talk-track-25.md](labs/talk-track-25.md)
- Facilitator notes: [labs/facilitator.md](labs/facilitator.md)
- Labs 01–04: [labs/](labs/)
- AI triage prompts: [kibana/ai-triage-prompts.md](kibana/ai-triage-prompts.md)

## CLI

| Command | Purpose |
|---------|---------|
| `setup` | Pipelines, templates, data views, alerts, saved objects |
| `sample` | Pipeline simulate / one-doc write check |
| `backfill --hours N` | Plant history + incident |
| `stream --tick N` | Live synthetic tick |
| `verify` | Assert fields + `trace.id` correlation |
| `dashboards` | Re-import Kibana assets + print links |
