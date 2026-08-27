# Facilitator guide — Elastic Co. demo

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

## Pre-flight checklist

- [ ] `python -m src.cli setup` succeeds (pipelines + templates)
- [ ] `backfill --hours 6` indexes without FAILED lines
- [ ] `verify` all `[ok]` including hero trace correlation
- [ ] Discover shows structured `tenant.id` on orchestrator (pipeline ran)
- [ ] APM shows `checkout-api` / DB spans
- [ ] AI Assistant connector configured on the project (LLM)

## Failure modes

| Symptom | Fix |
|---------|-----|
| Orchestrator missing `tenant.id` | Re-run `setup`; confirm index template `default_pipeline`; re-backfill orchestrator scope |
| APM empty | `ensure_apm_mappings` + backfill `--scope apm`; check API key has write to `traces-apm-default` |
| Alert create 400 | Create `.es-query` rule manually with ES\|QL from `kibana/alert-rules.json` |
| AI vague | Use prompts in `kibana/ai-triage-prompts.md`; narrow time to Last 2 hours; mention `labels.demo: elastic-co` |

## Lab flow (optional after SE path)

Run labs 01→04 in order. Each assumes backfill already loaded. Labs are read-mostly except 01 (simulate) and 04 (optional KB note).

## Reset

Delete data streams if you need a clean slate:

```
logs-elasticco.orchestrator-default
logs-elasticco.checkout-default
logs-elasticco.k8s.event-default
metrics-elasticco.k8s.pod-default
```

Then `setup` + `backfill` again. Avoid deleting `traces-apm-default` on shared projects — filter with `labels.demo: elastic-co` instead.
