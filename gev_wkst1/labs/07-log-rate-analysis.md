# Lab 07 — Log rate analysis (U7)

**Goal:** A log-volume spike is explained by statistically significant field-value combinations — not by grepping. This is a **second planted scenario**, not the checkout OOM.

**Deck:** [../presentations/u7-log-rate-analysis.html](../presentations/u7-log-rate-analysis.html)

**Combined with the native SLO (page vs this flood):** [07-slo-log-rate.md](07-slo-log-rate.md) · Deck: [../presentations/scenario-u7-slo.html](../presentations/scenario-u7-slo.html)

inventory-service canary **v4.0.9** left `com.elasticco.inventory.SkuCache` at **DEBUG**. Last ~35 minutes through now: ingest cliffs. APM for inventory stays healthy. Close: restore INFO (or revert the log config). Do **not** roll back checkout-api.

## Prerequisites

```bash
.venv/bin/python -m src.cli setup
.venv/bin/python -m src.cli backfill --hours 6
# or, if checkout data is already loaded:
.venv/bin/python -m src.cli backfill --hours 2 --scope app_logs
.venv/bin/python -m src.cli backfill --hours 2 --scope orchestrator
.venv/bin/python -m src.cli verify
```

Keep the DEBUG window through now:

```bash
.venv/bin/python -m src.cli stream --tick 60
```

Kibana: **Last 2 hours** · `labels.demo: elastic-co`.

## Walkthrough

1. Discover → data view **Elastic Co. Logs** (`elasticco-logs`) or **Elastic Co. Inventory Logs**. Histogram: quiet, then a cliff in the last ~35 minutes.
2. **Machine Learning → AIOps Labs → Log rate analysis** (global search: “Log rate analysis”). Same data view. Click the spike. Baseline vs deviation brushes.
3. Significant terms should include:
   - `log.level`: **debug**
   - `log.logger`: **com.elasticco.inventory.SkuCache**
   - `service.name`: **inventory-service**
   - `service.version`: **4.0.9**
4. Hover a row to overlay impact. Pin / copy as filter → Discover. Optional: **Log pattern analysis** on the SkuCache messages.
5. APM → **inventory-service** — latency still near baseline. This is ingest/noise, not an availability page.

**Line:** A log spike is not an outage until Log Rate Analysis tells you which field-value combination caused it.

## Beat 2 — same product, U1–U6 incident

Switch **Log rate analysis** to data view **Elastic Co. Orchestrator Logs** (`elasticco-orchestrator`). Last 2 hours. Click the spike in the checkout window (last ~60 minutes).

Significant terms should include:

- `tenant.id`: **acme-retail**
- `log.level`: **error**
- `orchestrator.task_id`: **charge_payment**
- `orchestrator.dag_id`: **fulfillment.checkout**

That is the checkout retry storm (U1–U6). Close stays rollback to **v2.4.0** on the case — do not mix it with the SkuCache DEBUG close.

Fallback ES|QL (Discover ES|QL or the Log Rate dashboard, lower panels):

```esql
FROM logs-elasticco.orchestrator-default
| WHERE @timestamp > NOW() - 2 hours
| WHERE labels.demo == "elastic-co"
| STATS n = COUNT(*) BY tenant.id, log.level
| SORT n DESC
```

## Fallback if AIOps Labs is missing / 403

Dashboard **Elastic Co. — Log Rate** (`elasticco-log-rate`): inventory DEBUG vs INFO on top; orchestrator ERROR × tenant on the lower panels. Still teach baseline vs deviation. Do not invent kubectl.

## Done when

**Beat 1:** histogram cliff → terms name SkuCache DEBUG / inventory 4.0.9 → APM is fine → restore INFO.  
**Beat 2:** same product on Orchestrator Logs → terms name `acme-retail` + `error` + `charge_payment` → that close is still rollback checkout-api **v2.4.0**. Do not mix the two remediations.
