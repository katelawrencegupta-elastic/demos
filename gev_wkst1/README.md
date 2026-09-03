# Elastic Co. — Elastic Observability Demo

Synthetic multi-tenant fulfillment SaaS demo for Elastic Cloud Serverless. One correlated checkout incident drives U1–U6; U7 is a sibling log-volume scenario; U8 is a sibling log-telemetry gap.

## Use cases

| # | Story | Kibana / CLI |
|---|--------|----------------|
| U1 | Unstructured orchestrator logs → structured, searchable, correlated | Discover · ingest pipeline |
| U2 | End-to-end distributed trace (7 hops) with tenant context and DB deep dive | APM waterfall · E2E tracing dashboard |
| U3 | EKS/pod incident root cause — restart to reason | K8s events · pod metrics · EKS Restarts dashboard |
| U4 | Noisy vs native SLO vs correlated RCA | Alerts · SLOs · Cases · AI Assistant (opener) |
| U5 | Agent Builder RCA → approve rollback into the case | Agent Builder `elasticco-rca-agent` · Cases |
| U6 | Detect → remediate (automated stitch) | Kibana Workflow `elasticco-detect-remediate` |
| U7 | Log rate analysis — verbose logger vs outage | AIOps Labs · dashboard `elasticco-log-rate` |
| U8 | Log telemetry fails — silence vs live APM | Alert `elasticco-log-telemetry-gap` · dashboard `elasticco-telemetry-gap` |

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
.venv/bin/python -m src.cli verify --alerts   # rules firing + Cases + Workflows + SLO + agent
.venv/bin/python -m src.cli dashboards   # deep links + re-import assets
.venv/bin/python -m src.cli agent --verify-only
.venv/bin/python -m src.cli workflow --verify-only
```

U4, U5, U8, or the 25-minute arc — start a live tick in a **side terminal** before the room (`--live-incident` is the default):

```bash
.venv/bin/python -m src.cli stream --tick 60
```

U1–U3 historical Discover/APM/dashboards do not need the stream. Use `--no-live-incident` only if you want healthy recovery ticks.

Narrow a reload with `--scope` (`orchestrator` | `apm` | `apm_deps` | `traces` | `k8s` | `infra` | `app_logs`). `k8s` includes pod metrics plus host/node/APM-internal (`infra`). `app_logs` is the U7 inventory DEBUG flood plus U8 notification-service silence.

## Incident (planted)

**Tenant `acme-retail` checkout degradation** (last ~60 minutes **through now**, so 60-minute alerts fire and the native SLO shows error-budget impact):

- `checkout-api` **v2.4.1** memory leak → **OOMKilled** / restart loop on `eks-elastic-prod-usc1`
- Orchestrator DAG `fulfillment.checkout` retries
- Slow PostgreSQL `SELECT … FOR UPDATE` spans for `acme-retail`
- Hero `trace.id` values join orchestrator logs ↔ APM waterfall ↔ checkout logs

Telemetry covers **12 services / 23 pods / 3 EKS nodes**. OOM remains checkout-only; other services emit healthy host, node, pod, and APM runtime metrics.

**U7 (separate scenario):** `inventory-service` canary **v4.0.9** left `SkuCache` at DEBUG for the last ~35 minutes. Log volume cliffs; inventory APM stays healthy. Restore INFO — do not treat this as the checkout rollback.

**U8 (separate scenario):** `notification-service` logs go silent for the last ~20 minutes while APM and pod metrics continue. Alert `elasticco-log-telemetry-gap` opens a case. Restart agent / check ingest — do not rollback checkout-api, do not restore INFO, do not start `elasticco-detect-remediate`.

Seven-hop checkout path: `edge-gateway` → `identity-service` → `checkout-api` → inventory / fraud / payments → postgres + redis + kafka → `notification-service`. Smoking gun: `SELECT … FOR UPDATE` on `orders` for `acme-retail`.

## Alerts, SLO, Agent Builder, Workflow

| Object | Role |
|--------|------|
| `elasticco-noisy-node-cpu` | Anti-pattern — CPU threshold, no tenant/service |
| `elasticco-slo-checkout-availability` | **Native SLO** — what you page on (`checkout-api` + `acme-retail`) |
| `elasticco-checkout-correlated-rca` | ES\|QL **correlation** (OOM + slow DB + OOM logs) — RCA starter, not an SLO; Cases + **Run Workflow** |
| `elasticco-eks-pod-restarts` | Restart loop + Cases + **Run Workflow** |
| `elasticco-app-checkout-error-rate` | App error rate > 10% (U5 entry). Per-row `service.name` so APM inventory / Service map badge checkout-api |
| `elasticco-rca-agent` | Agent Builder U5 close — ES\|QL tools, approve rollback into the case |
| `elasticco-detect-remediate` | Kibana Workflow — Alerting → ES\|QL → Agent Builder → Cases (rollback **comment**, not kubectl) |
| Inventory DEBUG flood | U7 — `logs-elasticco.inventory-default`; Log Rate Analysis names SkuCache / debug / 4.0.9 |
| `elasticco-log-telemetry-gap` | U8 — no notification-service logs in 15m while a 2h baseline exists; Cases; **no** Run Workflow |

Kibana: **SLOs**, **Agent Builder** (`/app/agent_builder/chat`), **Workflows** (`/app/workflows`). Universal Profiling is talk-only after `CartCache.retainAll`; Synthetics is not in this demo.

`logs-elasticco.incident-default` is written by the **facilitator CLI** (`incident`), not by Agent Builder or the workflow. The customer audit is the Observability **case** thread.

## Data streams

| Stream | Role |
|--------|------|
| `logs-elasticco.orchestrator-default` | Raw Airflow-style lines + grok pipeline |
| `logs-elasticco.checkout-default` | App / OOM container logs |
| `logs-elasticco.inventory-default` | U7 SkuCache DEBUG flood + quiet INFO baseline |
| `logs-elasticco.notification-default` | U8 notification-service heartbeat logs (silent last ~20 min) |
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
| `elasticco-log-rate` | Elastic Co. — Log Rate | U7 DEBUG flood vs INFO |
| `elasticco-telemetry-gap` | Elastic Co. — Log Telemetry Gap | U8 logs silent vs APM live |

## Demo materials

- SE talk-track (25 min): [labs/talk-track-25.md](labs/talk-track-25.md)
- SE talk-tracks (5 min, per use case): [labs/talk-track-5.md](labs/talk-track-5.md)
- Facilitator notes: [labs/facilitator.md](labs/facilitator.md)
- Scenario walkthrough (start → finish): [presentations/scenario-walkthrough.html](presentations/scenario-walkthrough.html)
- Combined U2 + U5 lab: [labs/02-05-trace-rca.md](labs/02-05-trace-rca.md) · [presentations/scenario-u2-u5.html](presentations/scenario-u2-u5.html)
- Combined U7 + SLO lab: [labs/07-slo-log-rate.md](labs/07-slo-log-rate.md) · [presentations/scenario-u7-slo.html](presentations/scenario-u7-slo.html)
- Labs 01–05 (U1–U5): [labs/](labs/) · U5 walkthrough: [labs/05-app-monitoring-rca.md](labs/05-app-monitoring-rca.md)
- Detect → remediate workflow: [labs/06-detect-remediate.md](labs/06-detect-remediate.md)
- Log rate analysis (U7): [labs/07-log-rate-analysis.md](labs/07-log-rate-analysis.md)
- Log telemetry gap (U8): [labs/08-log-telemetry-gap.md](labs/08-log-telemetry-gap.md)
- AI / Agent Builder prompts: [kibana/ai-triage-prompts.md](kibana/ai-triage-prompts.md)
- Agent Builder config: [config/rca_agent.yaml](config/rca_agent.yaml)
- Workflow YAML: [kibana/workflow-detect-remediate.yaml](kibana/workflow-detect-remediate.yaml)
- U4 knowledge base export: [kibana/knowledge-base-checkout-oom.md](kibana/knowledge-base-checkout-oom.md)

HTML presentations (open in a browser; ← → navigate, F fullscreen):

| UC | Deck |
|----|------|
| Full arc | [presentations/scenario-walkthrough.html](presentations/scenario-walkthrough.html) |
| U2 + U5 | [presentations/scenario-u2-u5.html](presentations/scenario-u2-u5.html) |
| U7 + SLO | [presentations/scenario-u7-slo.html](presentations/scenario-u7-slo.html) |
| U1 | [presentations/u1-elastic-components.html](presentations/u1-elastic-components.html) |
| U2 | [presentations/u2-distributed-traces.html](presentations/u2-distributed-traces.html) |
| U3 | [presentations/u3-eks-restart-rca.html](presentations/u3-eks-restart-rca.html) |
| U4 | [presentations/u4-alerting-ai-triage.html](presentations/u4-alerting-ai-triage.html) |
| U5 | [presentations/u5-app-monitoring-rca.html](presentations/u5-app-monitoring-rca.html) |
| U6 | [presentations/u6-detect-to-remediate.html](presentations/u6-detect-to-remediate.html) |
| U7 | [presentations/u7-log-rate-analysis.html](presentations/u7-log-rate-analysis.html) |
| U8 | [presentations/u8-log-telemetry-gap.html](presentations/u8-log-telemetry-gap.html) |

## CLI

| Command | Purpose |
|---------|---------|
| `setup` | Pipelines, templates, data views, native SLO, Agent Builder, Workflow, alerts |
| `sample` | Pipeline simulate / one-doc write check |
| `backfill --hours N` | Plant history + incident (`--scope` to reload one stream family) |
| `stream --tick N` | Live synthetic tick (`--live-incident` default pins the window through now; `--no-live-incident` for healthy recovery) |
| `verify` | Assert fields + `trace.id` correlation (`--alerts` for rules/SLO/agent/workflow) |
| `dashboards` | Re-import Kibana assets + print links |
| `agent` | Upsert Agent Builder RCA agent + ES\|QL tools (U5 close) |
| `workflow` | Upsert Kibana Workflow `elasticco-detect-remediate` |
| `incident` | Facilitator backup: CLI RCA, case, email (not the customer close) |
