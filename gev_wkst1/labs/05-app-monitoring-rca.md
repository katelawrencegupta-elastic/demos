# Lab 05 — Application monitoring + Agent Builder RCA (U5)

**Goal:** From a service-level alert (or native SLO error-budget chart) to a tool-backed RCA in Agent Builder, then approve rollback into the Observability case.

The Python CLI (`incident --dry-run`) is a **facilitator backup**, not the customer-facing close.

## Prerequisites

```bash
.venv/bin/python -m src.cli setup
.venv/bin/python -m src.cli backfill --hours 6
.venv/bin/python -m src.cli verify
.venv/bin/python -m src.cli verify --alerts
.venv/bin/python -m src.cli agent --verify-only
```

Start a live tick in a side terminal before opening Alerts (`--live-incident` is the default):

```bash
.venv/bin/python -m src.cli stream --tick 60
```

## Part A — Application alert or native SLO

1. APM → **Services** / **Service map** → **checkout-api** (alert badge from `elasticco-app-checkout-error-rate` and the other checkout rules), **or**
2. Kibana → **Alerts** → open **`elasticco-app-checkout-error-rate`** (checkout-api / acme-retail error rate > 10% in 60 minutes), **or**
3. Observability → **SLOs** → **`elasticco-slo-checkout-availability`** (native error budget for `checkout-api` + `acme-retail`).

Contrast with **`elasticco-noisy-node-cpu`** if you skipped U4.

**Line:** You page on the SLO (or the app error-rate). The ES|QL rule `elasticco-checkout-correlated-rca` is the RCA starter, not an SLO.

## Part B — Agent Builder (customer close)

1. Open **Agent Builder** → agent **Elastic Co. RCA Agent** (`elasticco-rca-agent`).
2. Paste:

> checkout-api is failing for acme-retail — reconstruct RCA and recommend one remediation.

3. Confirm the agent **calls tools**. Evidence must show acme-retail p95 / OOM / slow `FOR UPDATE` — not 0% errors.
4. Say **approve rollback to v2.4.0**.
   - Copy the paste-ready case comment (and email) into the Observability case already opened by the correlation or EKS-restarts alert.
   - If built-in Cases / email capabilities appear, use them as well.

Do **not** run `src.cli incident` in front of the customer. The chat agent must not silently call the CLI.

## Part C — Facilitator backup (lab / dry-run)

```bash
.venv/bin/python -m src.cli incident --dry-run
```

Prints the same planted RCA from Elasticsearch. Exits non-zero if evidence cannot support the story (re-run backfill). This path still uses the terminal — do not claim “without leaving Elastic” when you use it.

Full write path (case + email) for lab practice:

```bash
.venv/bin/python -m src.cli incident --email oncall@elastic.co
```

## Part D — Verify the case thread

Observability → **Cases**: the thread should hold the RCA (agent comment or paste). Discover **Elastic Co. Incident Audit** only if a write path actually indexed `logs-elasticco.incident-default`.

## Done when

You can explain: alert or SLO chart → Agent Builder tools prove OOM + FOR UPDATE for acme-retail → human “approve rollback” → case comment (in product or pasted) — without inventing counts.

Interactive deck: [../presentations/u5-app-monitoring-rca.html](../presentations/u5-app-monitoring-rca.html)

**Combined with U2 (waterfall then this close):** [02-05-trace-rca.md](02-05-trace-rca.md) · Deck: [../presentations/scenario-u2-u5.html](../presentations/scenario-u2-u5.html)
