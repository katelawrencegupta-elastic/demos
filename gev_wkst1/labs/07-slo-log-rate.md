# Combined lab — Native SLO + Log rate (U7)

**Goal:** Open the pageable SLO first, then prove the inventory log cliff is a **second** incident. Optional beat 2: the same Log Rate Analysis product on orchestrator logs names the SLO’s checkout retry storm.

Do **not** mix remediations. SkuCache DEBUG → restore INFO. Violated checkout SLO / orchestrator ERROR → roll back checkout-api **v2.4.1 → v2.4.0**.

**Deck:** [../presentations/scenario-u7-slo.html](../presentations/scenario-u7-slo.html) — ▶ Walk the lab.

Standalone if you need only one surface: [04-alerting-ai-triage.md](04-alerting-ai-triage.md) (SLO) · [07-log-rate-analysis.md](07-log-rate-analysis.md) (U7)

## Prerequisites

```bash
.venv/bin/python -m src.cli setup
.venv/bin/python -m src.cli backfill --hours 6
.venv/bin/python -m src.cli verify
.venv/bin/python -m src.cli verify --alerts
```

`verify --alerts` must show the SLO as **not** `NO_DATA` (KQL on `traces-apm-default`). Stream keeps both the DEBUG window and checkout traces through now:

```bash
.venv/bin/python -m src.cli stream --tick 60
```

Kibana: **Last 2 hours** · `labels.demo: elastic-co`.

## Part A — Native SLO (the page)

1. Observability → **SLOs** → **`elasticco-slo-checkout-availability`**.
2. Confirm: 99% / 7-day rolling, scope `checkout-api` + `acme-retail`, status **VIOLATED**, error budget remaining &lt; 0.
3. Optional: APM Services / Service map — `checkout-api` can show the SLO / alert badge (`groupBy: service.name`).

**Line:** This is what you page on. Not host CPU. Not a log-volume cliff.

## Part B — Log cliff (not the page)

1. Discover → **Elastic Co. Logs** (`elasticco-logs`). Histogram cliff in the last ~35 minutes.
2. Machine Learning → **AIOps Labs → Log rate analysis**. Same data view. Click the spike.
3. Significant terms: `log.level: debug`, `log.logger: com.elasticco.inventory.SkuCache`, `service.name: inventory-service`, `service.version: 4.0.9`.
4. APM → **inventory-service** — latency still near baseline.

**Line:** Restore INFO. Do not roll back checkout-api. The SLO you opened is still the checkout / acme-retail page.

## Part C — Beat 2 (optional tie-back)

1. Same Log Rate Analysis. Switch data view to **Elastic Co. Orchestrator Logs**.
2. Click the spike in the last ~60 minutes.
3. Terms: `tenant.id: acme-retail`, `log.level: error`, `orchestrator.task_id: charge_payment`.

That spike **is** the SLO’s incident. Close stays rollback to **v2.4.0** on the case — not restore INFO.

Fallback if AIOps Labs is 403: dashboard **`elasticco-log-rate`**.

## Done when

You can say, without mixing closes: native SLO = the page (checkout / acme-retail); inventory DEBUG = ingest noise (restore INFO); orchestrator ERROR = the same availability incident as the SLO (rollback v2.4.0).
