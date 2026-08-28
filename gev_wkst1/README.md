# Elastic Co. — Elastic Observability Demo

Synthetic multi-tenant fulfillment SaaS demo for Elastic Cloud Serverless. One correlated incident drives five SE use cases in ~25–30 minutes, with optional labs.

## Use cases

| # | Story | Kibana / CLI |
|---|--------|----------------|
| U1 | Unstructured orchestrator logs → structured, searchable, correlated | Discover · ingest pipeline |
| U2 | End-to-end distributed trace (7 hops) with tenant context and DB deep dive | APM waterfall · E2E tracing dashboard |
| U3 | EKS/pod incident root cause — restart to reason | K8s events · pod metrics · Inventory (30s) |
| U4 | Noisy vs native SLO vs correlated RCA | Alerts · SLOs · Cases · AI Assistant (opener) |
| U5 | Agent Builder RCA → approve rollback into the case | Agent Builder `elasticco-rca-agent` · Cases |

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
.venv/bin/python -m src.cli verify --alerts   # rules firing + Cases + native SLO + Agent Builder
.venv/bin/python -m src.cli dashboards   # deep links + re-import assets
.venv/bin/python -m src.cli agent --verify-only
```

U4, U5, or the 25-minute arc — start a live tick in a **side terminal** before the room (`--live-incident` is the default):

```bash
.venv/bin/python -m src.cli stream --tick 60
```

U1–U3 historical Discover/APM/dashboards do not need the stream. Use `--no-live-incident` only if you want healthy recovery ticks.

Narrow a reload with `--scope` (`orchestrator` | `apm` | `apm_deps` | `traces` | `k8s` | `infra`). `k8s` includes pod metrics plus host/node/APM-internal (`infra`).

## Incident (planted)

**Tenant `acme-retail` checkout degradation** (last ~60 minutes **through now**, so 60-minute alerts and SLO burn fire):

- `checkout-api` **v2.4.1** memory leak → **OOMKilled** / restart loop on `eks-elastic-prod-usc1`
- Orchestrator DAG `fulfillment.checkout` retries
- Slow PostgreSQL `SELECT … FOR UPDATE` spans for `acme-retail`
- Hero `trace.id` values join orchestrator logs ↔ APM waterfall ↔ checkout logs

Telemetry covers **12 services / 23 pods / 3 EKS nodes**. OOM remains checkout-only; other services emit healthy host, node, pod, and APM runtime metrics.

Seven-hop checkout path: `edge-gateway` → `identity-service` → `checkout-api` → inventory / fraud / payments → postgres + redis + kafka → `notification-service`. Smoking gun: `SELECT … FOR UPDATE` on `orders` for `acme-retail`.

## Alerts, SLO, Agent Builder

| Object | Role |
|--------|------|
| `elasticco-noisy-node-cpu` | Anti-pattern — CPU threshold, no tenant/service |
| `elasticco-slo-checkout-availability` | **Native SLO** — what you page on (`checkout-api` + `acme-retail`) |
| `elasticco-checkout-correlated-rca` | ES\|QL **correlation** (OOM + slow DB + OOM logs) — RCA starter, not an SLO |
| `elasticco-eks-pod-restarts` | Restart loop + Cases |
| `elasticco-app-checkout-error-rate` | App error rate > 10% (U5 entry) |
| `elasticco-rca-agent` | Agent Builder U5 close — ES\|QL tools, approve rollback into the case |

Kibana: **SLOs**, **Agent Builder** (`/app/agent_builder/chat`), **Inventory** (U3 30s — skip if hosts do not render). Universal Profiling is talk-only after `CartCache.retainAll`; Synthetics is not in this demo.

`logs-elasticco.incident-default` is written by the **facilitator CLI** (`incident`), not by Agent Builder. The customer audit is the Observability **case** thread.

## Data streams

| Stream | Role |
|--------|------|
| `logs-elasticco.orchestrator-default` | Raw Airflow-style lines + grok pipeline |
| `logs-elasticco.checkout-default` | App / OOM container logs |
| `logs-elasticco.k8s.event-default` | OOMKilled / BackOff events |
| `metrics-elasticco.k8s.pod-default` | Pod memory / CPU / restart count (all services) |
| `metrics-elasticco.k8s.node-default` | EKS node CPU / memory / network |
| `metrics-elasticco.host-default` | Host inventory (`system.cpu` / `system.memory`) |
| `metrics-apm.internal-default` | APM runtime / JVM metrics by service |
| `traces-apm-default` | Multi-service traces + DB spans + `tenant.id` |
| `metrics-apm.service_destination.1m-default` | Service-map / Dependencies edges |
| `metrics-apm.transaction.1m-default` | Root transaction aggregations |
| `logs-elasticco.incident-default` | CLI lab audit trail only (`cli incident`) |

Filter everywhere with `labels.demo: elastic-co`.

## Dashboards

Published by `setup` / `dashboards` (`src/dashboards.py`):

| Id | Title | Use case |
|----|--------|----------|
| `elasticco-incident-overview` | Elastic Co. — Incident Overview | Talk-track home |
| `elasticco-distributed-traces` | Elastic Co. — Distributed Traces | U2 volume / gauges |
| `elasticco-e2e-tracing` | Elastic Co. — End-to-End Tracing | U2 hop latency, tenant p95, slow `trace.id` |
| `elasticco-eks-restarts` | Elastic Co. — EKS Restarts | U3 OOM / restart RCA |

## Demo materials

- SE talk-track (25 min): [labs/talk-track-25.md](labs/talk-track-25.md)
- SE talk-tracks (5 min, per use case): [labs/talk-track-5.md](labs/talk-track-5.md)
- Facilitator notes: [labs/facilitator.md](labs/facilitator.md)
- Labs 01–05 (U1–U5): [labs/](labs/) · U5 walkthrough: [labs/05-app-monitoring-rca.md](labs/05-app-monitoring-rca.md)
- AI / Agent Builder prompts: [kibana/ai-triage-prompts.md](kibana/ai-triage-prompts.md)
- Agent Builder config: [config/rca_agent.yaml](config/rca_agent.yaml)
- U4 knowledge base export: [kibana/knowledge-base-checkout-oom.md](kibana/knowledge-base-checkout-oom.md)

HTML presentations (open in a browser; ← → navigate, F fullscreen):

| UC | Deck |
|----|------|
| U1 | [presentations/u1-elastic-components.html](presentations/u1-elastic-components.html) |
| U2 | [presentations/u2-distributed-traces.html](presentations/u2-distributed-traces.html) |
| U3 | [presentations/u3-eks-restart-rca.html](presentations/u3-eks-restart-rca.html) |
| U4 | [presentations/u4-alerting-ai-triage.html](presentations/u4-alerting-ai-triage.html) |
| U5 | [presentations/u5-app-monitoring-rca.html](presentations/u5-app-monitoring-rca.html) |

## CLI

| Command | Purpose |
|---------|---------|
| `setup` | Pipelines, templates, data views, alerts, native SLO, Agent Builder |
| `sample` | Pipeline simulate / one-doc write check |
| `backfill --hours N` | Plant history + incident (`--scope` to reload one stream family) |
| `stream --tick N` | Live synthetic tick (`--live-incident` default pins the window through now; `--no-live-incident` for healthy recovery) |
| `verify` | Assert fields + `trace.id` correlation (`--alerts` for rules/SLO/agent) |
| `dashboards` | Re-import Kibana assets + print links |
| `agent` | Upsert Agent Builder RCA agent + ES\|QL tools (U5 close) |
| `incident` | Facilitator backup: CLI RCA, case, email (not the customer close) |
