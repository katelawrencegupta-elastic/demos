# AI-assisted triage prompts — Elastic Co. demo (U4 opener / U5 Agent Builder)

Use these after **`elasticco-checkout-correlated-rca`** fires (or against the last 2h of seeded data).

**U4:** Observability AI Assistant is the **contrast opener** (noisy vs quality).  
**U5 close:** Agent Builder agent `elasticco-rca-agent` — do not treat a pasted AI Assistant prompt as the customer exit.

## Contrast opener (noisy vs quality)

> Compare the alerts named `elasticco-noisy-node-cpu` and `elasticco-checkout-correlated-rca`. Which one gives an on-call engineer enough context to start triage without opening five dashboards? What context is missing from the noisy rule? How is that different from the native SLO `elasticco-slo-checkout-availability`?

## Primary RCA prompt (AI Assistant — optional)

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

# U5 — Agent Builder RCA (customer-facing close)

Pre-open **Agent Builder** → **Elastic Co. RCA Agent** (`elasticco-rca-agent`).

## Scripted demo prompt

> checkout-api is failing for acme-retail — reconstruct RCA and recommend one remediation.

Walk tool results: acme-retail error rate / p95, OOMKilled + restarts, slow `FOR UPDATE`. Then: **approve rollback to v2.4.0**. Paste the agent’s comment into the open Observability case. If Cases/email tools appear, use those too.

## Facilitator backup (not the customer close)

```bash
python -m src.cli incident --dry-run
python -m src.cli incident --email oncall@elastic.co
```

Do not say “without leaving Elastic” when using the terminal. The chat agent must never silently call `src.cli incident`.
