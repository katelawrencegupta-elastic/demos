# Elastic Co. runbook — checkout-api OOM (U4 knowledge base)

Import this content into **Observability AI Assistant → Knowledge base** (or Agent Builder knowledge) before the U4 AI triage demo.

---

## Title

Elastic Co. runbook — checkout-api OOM

## Tags

`elastic-co`, `checkout-api`, `oom`, `eks`, `runbook`, `u4`

## Content (paste as knowledge entry)

If **OOMKilled** events appear on Deployment `checkout-api` in cluster `eks-elastic-prod-usc1` shortly after a deploy, treat it as a **bad release**, not capacity noise.

### First checks (2 minutes)

1. **Deploy version:** filter `logs-elasticco.checkout-default` or APM for `service.name: checkout-api` and compare `service.version`. Incident seed uses **v2.4.1**.
2. **K8s evidence:** `logs-elasticco.k8s.event-default` for `kubernetes.event.reason: OOMKilled` or `BackOff` on checkout-api pods.
3. **App logs:** `OutOfMemoryError` or `java.lang.OutOfMemoryError` in checkout container logs.
4. **Blast radius:** filter `tenant.id: acme-retail` on traces and orchestrator logs — other tenants may stay healthy.

### Known bad release

**v2.4.1** introduced a memory leak in `CartCache.retainAll`. Roll back to **v2.4.0** and restart pods.

### Correlation pattern

Orchestrator DAG **`fulfillment.checkout`** retries amplify load on the `orders` table. Look for slow PostgreSQL spans:

- `span.type: db`, `span.subtype: postgresql`
- Statement pattern: `SELECT … FOR UPDATE` on `orders`
- Join orchestrator logs ↔ APM via **`trace.id`**

### Remediation order

1. Roll back checkout-api to **v2.4.0** (stop the leak).
2. Scale/restart pods if still in BackOff after rollback.
3. Watch acme-retail checkout p95 and error rate return toward SLO.
4. Open or update Observability **Case** linked from alert `elasticco-checkout-slo-burn`.

### Alerts to trust in this demo

| Rule | Role |
|------|------|
| `elasticco-noisy-node-cpu` | **Anti-pattern** — high CPU on any pod, no service/tenant context |
| `elasticco-checkout-slo-burn` | **Quality** — ES\|QL ties OOM + slow DB spans + OOM logs for acme-retail |
| `elasticco-eks-pod-restarts` | **Quality** — restart loop with Cases action |

### ES\|QL sanity check (last 2 hours)

```
FROM traces-apm-default
| WHERE @timestamp > NOW() - 2 hours
| WHERE labels.demo == "elastic-co"
| WHERE processor.event == "transaction" AND service.name == "checkout-api"
| STATS p95 = PERCENTILE(transaction.duration.us, 95), n = COUNT(*) BY tenant.id
| SORT p95 DESC
```

Expect **acme-retail** p95 elevated vs peer tenants during the incident window.
