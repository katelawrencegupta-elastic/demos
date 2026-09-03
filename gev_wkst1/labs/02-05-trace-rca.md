# Combined lab — Trace (U2) + Agent Builder RCA (U5)

**Goal:** From a service-level page to a seven-hop waterfall (who is hurt, where time went), then a tool-backed RCA in Agent Builder that lands as a rollback comment on the Observability case.

Same planted incident as the standalone labs. Do **not** reset between U2 and U5.

**Deck:** [../presentations/scenario-u2-u5.html](../presentations/scenario-u2-u5.html) — ▶ Walk the lab.

Standalone if you need only one surface: [02-trace-tenant-db.md](02-trace-tenant-db.md) · [05-app-monitoring-rca.md](05-app-monitoring-rca.md)

## Prerequisites

```bash
.venv/bin/python -m src.cli setup
.venv/bin/python -m src.cli backfill --hours 6
.venv/bin/python -m src.cli verify
.venv/bin/python -m src.cli verify --alerts
.venv/bin/python -m src.cli agent --verify-only
```

Start a live tick in a side terminal before opening Alerts (`--live-incident` is the default). U5 tools look back 60 minutes:

```bash
.venv/bin/python -m src.cli stream --tick 60
```

Kibana time range: **Last 2 hours** · filter `labels.demo: elastic-co` if a view is empty.

## Part A — Detect (U5 entry)

1. APM → **Services** / **Service map** → **checkout-api** alert badge, **or**
2. Kibana → **Alerts** → **`elasticco-app-checkout-error-rate`** (checkout-api / acme-retail error rate > 10% in 60 minutes), **or**
3. Observability → **SLOs** → **`elasticco-slo-checkout-availability`**.

**Line:** You page on the SLO (or the app error-rate). Next question is the request path — not kubectl, not “add memory.”

## Part B — Trace (U2)

1. Dashboard **Elastic Co. — End-to-End Tracing** or APM → Services / Service map. Hop list: `edge-gateway` → `identity-service` → `checkout-api` → inventory / fraud / payments → postgres + redis + kafka → `notification-service`. The same checkout-api node should still show the alert badge.
2. Filter `tenant.id: "acme-retail"`. Open a slow transaction.
3. Expand the span `SELECT … FOR UPDATE orders`. Note duration (~2–4s) and `service.version` (**2.4.1** in the incident window).
4. Optional — Discover ES|QL or Dev Tools `_query`:

```esql
FROM traces-apm-default
| WHERE @timestamp > NOW() - 2 hours
| WHERE labels.demo == "elastic-co"
| WHERE processor.event == "transaction" AND service.name == "checkout-api"
| STATS p95 = PERCENTILE(transaction.duration.us, 95), n = COUNT(*) BY tenant.id
| SORT p95 DESC
```

Confirm `acme-retail` is the outlier vs `globex-mart` and `initech-b2b`.

5. Optional — copy a slow `trace.id` (hero `271f8e318871…`) into Discover **Elastic Co. Orchestrator Logs**. Same DAG `fulfillment.checkout`.

**Line:** Seven hops, one tenant label, time spent in FOR UPDATE.

## Part C — Agent Builder (U5 close)

1. **Agent Builder** → **Elastic Co. RCA Agent** (`elasticco-rca-agent`).
2. Paste:

> checkout-api is failing for acme-retail — reconstruct RCA and recommend one remediation.

3. Confirm the agent **calls tools**. Results must show acme-retail p95 / slow `FOR UPDATE` / OOM — the same facts as Part B, not 0% errors.
4. Say **approve rollback to v2.4.0**.
   - Copy the paste-ready case comment into the Observability case already opened by the correlation or EKS-restarts alert.
   - If built-in Cases / email capabilities appear, use them as well.

Do **not** run `src.cli incident` in front of the customer.

## Part D — Case thread

Observability → **Cases**: the thread holds the RCA (agent comment or paste). Discover **Elastic Co. Incident Audit** only if a write path actually indexed `logs-elasticco.incident-default`.

## Done when

You can explain: alert or SLO → waterfall proves acme-retail + FOR UPDATE → Agent Builder tools repeat that evidence → human “approve rollback” → case comment — without inventing counts.

**Skip if late:** ES|QL in Discover — dashboard tenant lines + one FOR UPDATE span are enough.  
**Skip if Agent Builder empty:** stay on the waterfall + the open case + `elasticco-checkout-correlated-rca`. Never open a terminal unless they ask how the demo was seeded.

**Facilitator backup:** `python -m src.cli incident --dry-run` (still a terminal path — do not claim “without leaving Elastic”).
