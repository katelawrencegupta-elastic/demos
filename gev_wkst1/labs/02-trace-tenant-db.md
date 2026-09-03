# Lab 02 — Tenant traces and DB deep dive (U2)

**Goal:** Compare blast vs healthy tenants and inspect a slow Postgres span on the **seven-hop** checkout path.

## Steps

1. APM → **Services** / **Service map** **or** dashboard **Elastic Co. — End-to-End Tracing**. Hop list: `edge-gateway` → `identity-service` → `checkout-api` → inventory / fraud / payments → postgres + redis + kafka → `notification-service`. Checkout-api should show an **alert badge** (error-rate / correlation / restarts). Peers do not.
2. APM → Transactions for `checkout-api`. Filter `tenant.id: "acme-retail"` (or labels).
3. Open a slow transaction → expand the span `SELECT … FOR UPDATE orders`. Note duration and `service.version` (2.4.1 in the incident window).
4. Run ES|QL (Discover ES|QL mode or Dev Tools `_query`):

```esql
FROM traces-apm-default
| WHERE @timestamp > NOW() - 2 hours
| WHERE labels.demo == "elastic-co"
| WHERE processor.event == "transaction" AND service.name == "checkout-api"
| STATS p95 = PERCENTILE(transaction.duration.us, 95), n = COUNT(*) BY tenant.id
| SORT p95 DESC
```

5. Confirm `acme-retail` is slower / higher than `globex-mart` and `initech-b2b`.
6. Pick a `trace.id` from a slow trace. In Discover orchestrator view, filter `trace.id: <id>` — you should see DAG task lines for the same checkout.

## Done when

You have one `trace.id` that joins APM waterfall ↔ orchestrator logs, and an ES|QL table showing tenant asymmetry.

**Combined with U5 (trace → Agent Builder RCA):** [02-05-trace-rca.md](02-05-trace-rca.md) · Deck: [../presentations/scenario-u2-u5.html](../presentations/scenario-u2-u5.html)
