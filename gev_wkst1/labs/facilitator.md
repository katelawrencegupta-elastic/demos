# Facilitator guide — Elastic Co. demo

## Use case map

| UC | Focus | Primary surfaces |
|----|--------|------------------|
| U1 | Orchestrator grok → Discover | Ingest pipeline · `elasticco-orchestrator` |
| U2 | Seven-hop traces · tenant · `FOR UPDATE` | APM · **End-to-End Tracing** dashboard |
| U3 | EKS OOM restart → reason (+ Inventory 30s) | K8s events · pod metrics · checkout logs |
| U4 | Noisy vs **native SLO** vs correlated RCA | Alerts · SLOs · Cases · AI Assistant (opener) |
| U5 | Agent Builder RCA → case / email | Agent Builder `elasticco-rca-agent` · Cases |

## Story key (do not show early)

| Fact | Value |
|------|--------|
| Blast tenant | `acme-retail` |
| Healthy tenants | `globex-mart`, `initech-b2b` |
| Cluster | `eks-elastic-prod-usc1` |
| Bad deploy | `checkout-api` **v2.4.1** |
| Good deploy | **v2.4.0** |
| Leak hint | `CartCache.retainAll` |
| DAG | `fulfillment.checkout` |
| DB smoking gun | `SELECT … FOR UPDATE` on `orders`, span ~2–4s |
| Correlation key | `trace.id` (+ `tenant.id`, `order.id`) |
| Native SLO | `elasticco-slo-checkout-availability` (page on this) |
| Correlation alert | `elasticco-checkout-correlated-rca` (RCA starter, **not** an SLO) |

## Environment

- Serverless Observability project; credentials in `.env`.
- Fictional EKS — no real cluster. Metrics/events are synthetic but ECS-shaped.
- Alert rule APIs differ slightly by stack version; if rule create warns, create manually from [../kibana/alert-rules.json](../kibana/alert-rules.json) and continue — talk-track still works on seeded data.
- **Agent Builder write path:** `enable_elastic_capabilities: true` on `elasticco-rca-agent`. If Cases / email tools appear, “approve rollback” can comment the case. If capabilities stay read-only, paste the agent’s comment into the case the alert already opened.
- **CLI backup:** `python -m src.cli incident --dry-run` (lab 05). Do not claim “without leaving Elastic” on a terminal path. Never have the chat agent silently call `src.cli incident`.
- **U5 email (CLI only):** `KIBANA_EMAIL_CONNECTOR_ID` or SMTP in `.env`; otherwise HTML under `output/incident-emails/`.

## Pre-flight checklist

- [ ] `python -m src.cli setup` succeeds (pipelines + templates + alerts + native SLO + Agent Builder)
- [ ] `backfill --hours 6` indexes without FAILED lines
- [ ] `verify` all `[ok]` including hero trace correlation
- [ ] `verify --alerts` — rules **exist, enabled, Cases on correlation + eks-restarts, firing**; native SLO present; Agent Builder tools + `elasticco-rca-agent`
- [ ] Retired name `elasticco-checkout-slo-burn` is **disabled** (renamed to `elasticco-checkout-correlated-rca`)
- [ ] Discover shows structured `tenant.id` on orchestrator (pipeline ran)
- [ ] APM / E2E dashboard shows seven hops + DB spans
- [ ] Agent Builder chat opens; a test prompt returns **non-zero** acme-retail errors / slow DB (not 0%)
- [ ] **U4 / U5 / 25-min:** `stream --tick 60` running in a side terminal (`--live-incident` is the default). U1–U3 historical path does not need it.
- [ ] **Facilitator only:** `python -m src.cli incident --dry-run` prints RCA (fails if evidence is weak)

## Failure modes

| Symptom | Fix |
|---------|-----|
| Orchestrator missing `tenant.id` | Re-run `setup`; confirm index template `default_pipeline`; re-backfill orchestrator scope |
| APM empty | `ensure_apm_mappings` + backfill `--scope apm`; check API key has write to `traces-apm-default` |
| Alerts not firing / RCA 0% errors | Incident window must cover **now**. Re-backfill; start `stream --tick 60` (live-incident default). `verify --alerts` checks last-60m hits |
| Alert create 400 | Create `.es-query` rule manually with ES\|QL from `kibana/alert-rules.json` |
| Native SLO 403 | Soft-fail is OK; still teach SLO vs correlation using the SLO app if the object exists, or say “we provision via `/api/observability/slos`” |
| Agent Builder empty / 0% errors | Do not invent. Skip to open case + `elasticco-checkout-correlated-rca`. Re-backfill. |
| Agent Builder 403 | `python -m src.cli agent` after confirming Agent Builder is enabled on the project |
| Inventory empty | Custom `metrics-elasticco.host-*` may not light Inventory. Skip the 30s beat; stay on EKS Restarts |
| AI vague (U4 opener) | Use prompts in `kibana/ai-triage-prompts.md`; Last 2 hours; `labels.demo: elastic-co` |
| CLI email not sent | Lab-only path — check connector/SMTP; open `output/incident-emails/*.html` |

## Product surfaces we do **not** fake

| Surface | Stance |
|---------|--------|
| Universal Profiling | Talk only after `CartCache.retainAll`. Do not synthesize `profiling-*` streams. |
| Synthetics | Skip. No sixth use case; a full browser monitor is a large fake. |

## Lab flow (optional after SE path)

Run labs **01→05** in order. Each assumes backfill already loaded.

| Lab | Use case |
|-----|----------|
| [01-orchestrator-structuring.md](01-orchestrator-structuring.md) | U1 |
| [02-trace-tenant-db.md](02-trace-tenant-db.md) | U2 |
| [03-eks-restart-rca.md](03-eks-restart-rca.md) | U3 |
| [04-alerting-ai-triage.md](04-alerting-ai-triage.md) | U4 |
| [05-app-monitoring-rca.md](05-app-monitoring-rca.md) | U5 |

## Talk-tracks

- Full arc (~25 min): [talk-track-25.md](talk-track-25.md)
- One use case (~5 min each): [talk-track-5.md](talk-track-5.md)

## HTML presentations

- U1: [../presentations/u1-elastic-components.html](../presentations/u1-elastic-components.html)
- U2: [../presentations/u2-distributed-traces.html](../presentations/u2-distributed-traces.html)
- U3: [../presentations/u3-eks-restart-rca.html](../presentations/u3-eks-restart-rca.html)
- U4: [../presentations/u4-alerting-ai-triage.html](../presentations/u4-alerting-ai-triage.html)
- U5: [../presentations/u5-app-monitoring-rca.html](../presentations/u5-app-monitoring-rca.html)

## Reset

Delete data streams if you need a clean slate:

```
logs-elasticco.orchestrator-default
logs-elasticco.checkout-default
logs-elasticco.k8s.event-default
logs-elasticco.incident-default
metrics-elasticco.k8s.pod-default
```

Then `setup` + `backfill` again. Avoid deleting `traces-apm-default` on shared projects — filter with `labels.demo: elastic-co` instead.
