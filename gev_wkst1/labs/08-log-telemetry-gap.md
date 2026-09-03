# Lab 08 — Log telemetry gap (U8)

**Goal:** An alert fires because **logs went silent**. Triage whether the app is down or **telemetry failed**. This is a **third planted scenario**, not the checkout OOM and not the SkuCache DEBUG flood.

**Deck:** [../presentations/u8-log-telemetry-gap.html](../presentations/u8-log-telemetry-gap.html)

**notification-service** application logs stop for the last ~20 minutes through now. APM transactions and pod metrics for the same service **continue**. Alert `elasticco-log-telemetry-gap` opens a case. Close: restart elastic-agent / check ingest — **not** rollback checkout-api, **not** restore SkuCache INFO. Do **not** start workflow `elasticco-detect-remediate` from this rule.

## Prerequisites

```bash
.venv/bin/python -m src.cli setup
.venv/bin/python -m src.cli backfill --hours 2 --scope app_logs
.venv/bin/python -m src.cli backfill --hours 2 --scope apm
.venv/bin/python -m src.cli verify
```

Keep the silence (and APM) through now:

```bash
.venv/bin/python -m src.cli stream --tick 60
```

Wait 1–2 minutes for `elasticco-log-telemetry-gap` to fire. Kibana: **Last 2 hours** · `labels.demo: elastic-co`.

## Walkthrough

1. Alerts → **`elasticco-log-telemetry-gap`**. ES|QL: last 15 minutes of `logs-elasticco.notification-default` is empty, but a 2-hour baseline exists. Cases action. APM inventory / Service map can badge **notification-service** (`service.name` on the row). There is **no** Run Workflow action.
2. Discover → data view **Elastic Co. Notification Logs** (`elasticco-notification`). Last event ~20 minutes ago. Histogram drops to zero.
3. APM → **notification-service**. Transactions still arriving. Latency near baseline.
4. Optional: dashboard **Elastic Co. — Log Telemetry Gap** (`elasticco-telemetry-gap`) — logs last 15m = 0 vs APM last 15m > 0; pod CPU/restarts healthy.
5. Optional: Log Rate Analysis on **Elastic Co. Notification Logs** — this time the signal is a **drop**, not a spike.

**Line:** Logs going dark is not an outage until traces and pods disagree.

## Fallback ES|QL

```esql
FROM logs-elasticco.notification-default
| WHERE @timestamp >= NOW() - 2 hours
| WHERE labels.demo == "elastic-co"
| STATS last_seen = MAX(@timestamp), n_15m = COUNT(*) WHERE @timestamp >= NOW() - 15 minutes, n_2h = COUNT(*)
```

```esql
FROM traces-apm-default
| WHERE @timestamp >= NOW() - 15 minutes
| WHERE labels.demo == "elastic-co"
| WHERE processor.event == "transaction" AND service.name == "notification-service"
| STATS n = COUNT(*)
```

## Done when

Alert firing → last log ~20m ago → APM still transacting → pods healthy → **fix telemetry, not the app**. Do not mix with v2.4.0 rollback or restore INFO.
