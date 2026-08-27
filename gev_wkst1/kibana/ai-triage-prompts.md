# AI-assisted triage prompts — Elastic Co. demo (U4)

Use these after the **elasticco-checkout-slo-burn** alert fires (or against the last 2h of seeded data).
Prefer Observability AI Assistant / Agent Builder in Kibana. Paste prompts as-is.

## Contrast opener (noisy vs quality)

> Compare the alerts named `elasticco-noisy-node-cpu` and `elasticco-checkout-slo-burn`. Which one gives an on-call engineer enough context to start triage without opening five dashboards? What context is missing from the noisy rule?

## Primary RCA prompt

> An alert fired for checkout degradation affecting tenant `acme-retail` on cluster `eks-elastic-prod-usc1`. Using Elastic Co. telemetry (`labels.demo: elastic-co`), reconstruct the incident timeline for the last 2 hours. Correlate:
> 1. orchestrator logs in `logs-elasticco.orchestrator-*` (DAG `fulfillment.checkout`)
> 2. distributed traces in `traces-apm*` with `tenant.id: acme-retail` and any slow PostgreSQL spans
> 3. Kubernetes events / pod metrics for Deployment `checkout-api` (OOMKilled, restart count, memory vs limit)
>
> Return: blast radius (tenants/services), most likely root cause, and the single best next remediation step.

## Expected RCA (facilitator key)

Planted root cause the assistant should approximate:

1. `checkout-api` deployed **v2.4.1** with a memory leak (`CartCache.retainAll`)
2. Pods hit memory limit → **OOMKilled** / BackOff restart loop
3. Orchestrator retries amplify load on `orders` table
4. Slow `SELECT … FOR UPDATE` spans for `acme-retail`; other tenants mostly healthy

## Follow-ups

> Show me one `trace.id` that appears in both orchestrator logs and APM, and summarize the waterfall including the DB span duration.

> Write an ES|QL query that compares p95 transaction duration for `acme-retail` vs `globex-mart` over the last 2 hours.

> Draft a Slack message for #fulfillment-oncall that cites deploy version, OOM evidence, and the tenant SLO impact without dumping raw JSON.

## Knowledge-base note (optional lab)

Add to Observability AI knowledge base:

```
Elastic Co. runbook — checkout-api OOM
If OOMKilled on checkout-api after a deploy, check service.version.
v2.4.1 introduced CartCache.retainAll leak; roll back to 2.4.0.
Correlate orchestrator DAG fulfillment.checkout retries with postgres FOR UPDATE spans by trace.id / tenant.id.
```
