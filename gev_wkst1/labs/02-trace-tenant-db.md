# Lab 02 — Tenant traces and DB deep dive

**Goal:** Compare blast vs healthy tenants and inspect a slow Postgres span.

## Steps

1. APM → Transactions for `checkout-api`. Filter `tenant.id: "acme-retail"` (or labels).
2. Open a slow transaction → expand the span `SELECT … FOR UPDATE orders`. Note duration and `service.version`.
3. Run ES|QL (Discover ES|QL mode or Dev Tools `_query`):

```esql
FROM traces-apm-default
| WHERE @timestamp > NOW() - 2 hours
| WHERE labels.demo == "elastic-co"
| WHERE processor.event == "transaction" AND service.name == "checkout-api"
| STATS p95 = PERCENTILE(transaction.duration.us, 95), n = COUNT(*) BY tenant.id
| SORT p95 DESC
```

4. Confirm `acme-retail` is slower / higher than `globex-mart` and `initech-b2b`.
5. Pick a `trace.id` from a slow trace. In Discover orchestrator view, filter `trace.id: <id>` — you should see DAG task lines for the same checkout.

## Done when

You have one `trace.id` that joins APM waterfall ↔ orchestrator logs, and an ES|QL table showing tenant asymmetry.
