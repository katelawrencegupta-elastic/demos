# Facilitator guide — Elastic Co. demo

## Use case map

| UC | Focus | Primary surfaces |
|----|--------|------------------|
| U1 | Orchestrator grok → Discover | Ingest pipeline · `elasticco-orchestrator` |
| U2 | Distributed traces · tenant · DB span | APM · `traces-apm-default` |
| U3 | EKS OOM restart → reason | K8s events · pod metrics · checkout logs |
| U4 | Noisy vs quality alerts · AI triage | Alerts · Cases · AI Assistant |
| U5 | App monitoring alert · RCA agent · approval · email | `cli incident` · `elasticco-incidents` |

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

## Environment

- Serverless Observability project; credentials in `.env`.
- Fictional EKS — no real cluster. Metrics/events are synthetic but ECS-shaped.
- Alert rule APIs differ slightly by stack version; if rule create warns, create manually from [../kibana/alert-rules.json](../kibana/alert-rules.json) and continue — talk-track still works on seeded data.
- **U5 email:** configure `KIBANA_EMAIL_CONNECTOR_ID` or SMTP in `.env` (see [../.env.example](../.env.example)); otherwise HTML is saved under `output/incident-emails/`.

## Pre-flight checklist

- [ ] `python -m src.cli setup` succeeds (pipelines + templates + alerts)
- [ ] `backfill --hours 6` indexes without FAILED lines
- [ ] `verify` all `[ok]` including hero trace correlation
- [ ] `verify --alerts` — quality rules active; Cases on slo-burn + eks-restarts
- [ ] Discover shows structured `tenant.id` on orchestrator (pipeline ran)
- [ ] APM shows `checkout-api` / DB spans
- [ ] AI Assistant connector configured on the project (LLM)
- [ ] **U5:** `python -m src.cli incident --dry-run` prints RCA without errors
- [ ] **U5:** email connector or SMTP configured (or accept HTML fallback)

## Failure modes

| Symptom | Fix |
|---------|-----|
| Orchestrator missing `tenant.id` | Re-run `setup`; confirm index template `default_pipeline`; re-backfill orchestrator scope |
| APM empty | `ensure_apm_mappings` + backfill `--scope apm`; check API key has write to `traces-apm-default` |
| Alert create 400 | Create `.es-query` rule manually with ES\|QL from `kibana/alert-rules.json` |
| AI vague | Use prompts in `kibana/ai-triage-prompts.md`; narrow time to Last 2 hours; mention `labels.demo: elastic-co` |
| U5 email not sent | Check connector/SMTP in `.env`; open `output/incident-emails/*.html` |
| U5 case not updated | Re-run `setup` for Cases action; use `--no-case` only for dry demos |

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
