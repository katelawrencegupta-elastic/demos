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

Add to Observability AI knowledge base — full runbook: [knowledge-base-checkout-oom.md](knowledge-base-checkout-oom.md)

---

# U5 — Application monitoring + RCA agent (automated incident response)

Use after **`elasticco-app-checkout-error-rate`** fires, or run the CLI agent directly.

## RCA agent prompt (Observability AI Assistant)

> checkout-api is failing for tenant acme-retail. Using `labels.demo: elastic-co`, build an incident timeline for the last 2 hours. Correlate APM error rate on checkout-api, OOMKilled events, OutOfMemoryError logs, slow postgres spans, and orchestrator retries. Recommend a single remediation step and draft an email summary for kate.lawrencegupta@elastic.co with: incident id, root cause, blast radius, evidence bullets, and remediation actions taken.

## CLI agent (automated workflow)

```bash
# Human approval
python -m src.cli incident --email kate.lawrencegupta@elastic.co

# Automatic remediation + Kibana case + email
python -m src.cli incident --auto --email kate.lawrencegupta@elastic.co
```

## Expected RCA

Same planted root cause as U4, framed as an application monitoring incident:

1. Alert: checkout-api error rate > 10%
2. Agent correlates OOM + deploy v2.4.1 + DB lock contention
3. Remediation: rollback to v2.4.0 (human-approved or `--auto`)
4. Email summary to kate.lawrencegupta@elastic.co

## Facilitator key — approval flow

- **Manual:** pause for `Approve remediation? [y/N]` — good for customer demos showing human-in-the-loop
- **Auto:** `--auto` flag — good for closing the loop quickly at end of session
