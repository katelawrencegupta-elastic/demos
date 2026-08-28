# Lab 05 — Application monitoring + RCA agent (U5)

**Goal:** Trigger a service failure alert, let the RCA agent correlate telemetry, approve (or auto) remediation, and deliver an incident summary email.

## Prerequisites

```bash
.venv/bin/python -m src.cli setup
.venv/bin/python -m src.cli backfill --hours 6
.venv/bin/python -m src.cli verify
```

## Part A — Application monitoring alert

1. Kibana → **Alerts** → open **`elasticco-app-checkout-error-rate`**.
2. Note the ES|QL query: checkout-api transaction error rate > 10% in 15 minutes.
3. Compare with **`elasticco-noisy-node-cpu`** — this rule includes service + tenant tags.

**Line:** Application monitoring alerts name the failing service and tie to SLO context.

## Part B — RCA agent (investigate)

```bash
# Investigate only — prints RCA report, no changes
.venv/bin/python -m src.cli incident --dry-run
```

Review the evidence block: error rate, OOM events, slow DB spans, orchestrator retries, hero trace.id.

## Part C — Human approval workflow

```bash
.venv/bin/python -m src.cli incident --email kate.lawrencegupta@elastic.co
```

1. Agent prints root cause + remediation plan.
2. Approve with `y` (enter approver name) or reject with `n`.
3. On approval: rollback log indexed, incident audit trail written, **Kibana case updated**, email sent (or HTML saved).

## Part D — Automatic remediation

```bash
.venv/bin/python -m src.cli incident --auto --email kate.lawrencegupta@elastic.co
```

Skips the approval prompt — useful for scripted demos.

## Part E — Verify audit trail

Discover → data view **Elastic Co. Incident Audit** (`elasticco-incidents`).

Filter: `incident.id: <id from CLI output>`

Phases: `detected` → `remediation` → `resolved` → `notified`

## Email delivery options

| Method | Configuration |
|--------|---------------|
| Kibana connector | Set `KIBANA_EMAIL_CONNECTOR_ID` in `.env` (Stack Management → Connectors → Email) |
| SMTP | Set `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` |
| Fallback | HTML saved to `output/incident-emails/<incident-id>.html` |

## Done when

You can explain: alert fires → RCA agent correlates logs/traces/K8s → human or auto approval → rollback → email summary to on-call.

Interactive deck: [../presentations/u5-app-monitoring-rca.html](../presentations/u5-app-monitoring-rca.html)
