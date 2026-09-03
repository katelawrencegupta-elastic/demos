# SE talk-track — Elastic Co. (~25–30 min)

**Audience:** Platform / SRE / Observability buyers  
**Incident:** One planted checkout failure for tenant `acme-retail`. Never reset the story.  
**Close:** Agent Builder `elasticco-rca-agent` — grounded RCA, then approve rollback to **v2.4.0** into the Observability case.

| Need | Use |
|------|-----|
| One use case (~5 min) | [talk-track-5.md](talk-track-5.md) |
| Traces + RCA only (~12 min) | [talk-track-5.md](talk-track-5.md#combined-u2--u5) · [02-05-trace-rca.md](02-05-trace-rca.md) |
| SLO + log rate (~12 min) | [talk-track-5.md](talk-track-5.md#combined-u7--slo) · [07-slo-log-rate.md](07-slo-log-rate.md) |
| Operator / pre-flight | [facilitator.md](facilitator.md) |
| Visual opener | [../presentations/scenario-walkthrough.html](../presentations/scenario-walkthrough.html) |

---

## Prep (before the room)

```bash
.venv/bin/python -m src.cli setup
.venv/bin/python -m src.cli backfill --hours 6
.venv/bin/python -m src.cli verify
.venv/bin/python -m src.cli verify --alerts
```

Live tick in a **side terminal** (`--live-incident` is the default). Keeps the 60-minute window through now so alerts and Agent Builder tools are not empty:

```bash
.venv/bin/python -m src.cli stream --tick 60
```

**Kibana time range:** Last 2 hours. Filter `labels.demo: elastic-co` if a view is empty.

**Tabs (in order):**

1. Discover — **Elastic Co. Orchestrator Logs**
2. Stack Management → Ingest Pipelines — `logs-elasticco.orchestrator` (U1)
3. Dashboard **Elastic Co. — End-to-End Tracing**
4. Dashboard **Elastic Co. — EKS Restarts**
5. Alerts
6. SLOs
7. Cases
8. Agent Builder — `elasticco-rca-agent` (**pre-warm** — paste the prompt during U4 or before the room)

**Pre-warm prompt:**

> checkout-api is failing for acme-retail — reconstruct RCA and recommend one remediation.

Do **not** open a terminal in front of the customer unless they ask how the demo was seeded. `cli incident --dry-run` is facilitator-only.

---

### 0:00–2:00 · Frame

**Say:** Elastic Co. is a multi-tenant fulfillment SaaS. The fear every platform team has: *one noisy tenant takes down checkout for everyone — and you find out in Slack, not in observability.*

**Promise:** Raw orchestrator spam → a seven-hop `trace.id` → Postgres `FOR UPDATE` → an OOM restart loop → noisy vs SLO vs correlation → an Agent Builder RCA you paste into the case.

Optional: ▶ Walk the scenario in [scenario-walkthrough.html](../presentations/scenario-walkthrough.html) (keep it to 60 seconds).

---

### 2:00–7:00 · U1 Unstructured → structured

**Deck:** [../presentations/u1-elastic-components.html](../presentations/u1-elastic-components.html)

1. Discover → **Elastic Co. Orchestrator Logs**. Open one doc. Point at `message` (Airflow-style free text).
2. Ask: “Find all errors for `acme-retail`.” Hard without fields — it is a grep problem.
3. Ingest pipeline `logs-elasticco.orchestrator` — grok extracts `tenant.id`, `trace.id`, `orchestrator.dag_id`, `orchestrator.task_id`.
4. Back to Discover. Filter `tenant.id: acme-retail and log.level: error` (or `warning`). Open a doc. Click **`trace.id`**.

**Line:** Parsing is not vanity — it is how correlation becomes a click, not a scavenger hunt.

**Skip if late:** pipeline UI. Assert `tenant.id` / `trace.id` on a structured doc, filter, click.

---

### 7:00–13:00 · U2 Trace + tenant + DB

**Deck:** [../presentations/u2-distributed-traces.html](../presentations/u2-distributed-traces.html)

1. Dashboard **Elastic Co. — End-to-End Tracing** or APM **Services / Service map**: `edge-gateway` → `identity-service` → `checkout-api` → inventory / fraud / payments → postgres + redis + kafka → `notification-service`. Checkout-api should show an **alert badge**; peers and the noisy CPU rule do not.
2. Filter `tenant.id: acme-retail`. Open a slow transaction. Expand **postgresql** — `SELECT … FOR UPDATE` (~2–4s). Note `service.version: 2.4.1`.
3. Tenant lines on the dashboard (or ES|QL `PERCENTILE` by `tenant.id`): `acme-retail` is the outlier vs `globex-mart` / `initech-b2b`.

**Line:** Seven hops, one tenant label, time spent in FOR UPDATE. Tenant answers “who is hurt?” The DB span answers “where did the time go?”

**Skip if late:** ES|QL — waterfall + tenant filter is enough.

---

### 13:00–17:00 · U3 Restart to reason

**Deck:** [../presentations/u3-eks-restart-rca.html](../presentations/u3-eks-restart-rca.html)

1. Dashboard **Elastic Co. — EKS Restarts**: `kubernetes.event.reason: OOMKilled` on `checkout-api`. Memory vs 512 MiB limit; `kubernetes.pod.restart.count` climbing.
2. Checkout logs: `OutOfMemoryError` + `deploy=2.4.1` + `CartCache.retainAll`. *This is the leak you’d confirm on a flamegraph* (Universal Profiling is not seeded — talk only).
3. Alert `elasticco-eks-pod-restarts` → Observability case **EKS restart loop — checkout-api**.

**Line:** Restarts are a symptom. OOM plus deploy version is the reason — same window as the slow traces, not a second mystery.

**Skip if late:** Cases. Stay on the dashboard + one OOM log line.

---

### 17:00–21:00 · U4 Noisy vs SLO vs correlated RCA

**Deck:** [../presentations/u4-alerting-ai-triage.html](../presentations/u4-alerting-ai-triage.html)  
**Contrast prompt:** [../kibana/ai-triage-prompts.md](../kibana/ai-triage-prompts.md)

1. Alerts → **`elasticco-noisy-node-cpu`**. CPU threshold, no service, no tenant. It will **not** badge on APM inventory / Service map. “Would you wake someone for this?”
2. Observability → SLOs → **`elasticco-slo-checkout-availability`**. Native error budget for `checkout-api` + `acme-retail`. *This is what you page on.*
3. Alerts → **`elasticco-checkout-correlated-rca`**. ES|QL ties OOM + slow DB + OOM logs. Cases action. *RCA starter — not an SLO.*
4. Optional: AI Assistant contrast prompt (noisy vs correlation). Do **not** close here — U5 is Agent Builder.

**Line:** Three objects: noise you ignore, an SLO you page on, a correlation alert that already knows the blast radius.

**Skip if late:** noisy-rule walkthrough. Open the SLO and the correlation alert.

---

### 21:00–28:00 · U5 Agent Builder close

**Deck:** [../presentations/u5-app-monitoring-rca.html](../presentations/u5-app-monitoring-rca.html)

1. APM Services / Service map → **checkout-api** alert badge, **or** Alerts → **`elasticco-app-checkout-error-rate`**, **or** the native SLO chart.
2. Agent Builder (`elasticco-rca-agent`) — walk the pre-warmed chat, or paste:

> checkout-api is failing for acme-retail — reconstruct RCA and recommend one remediation.

3. Tool results must show acme-retail p95 / OOM / `FOR UPDATE` — not 0% errors. If tools are empty, skip to the open case + quality alert. Do not invent counts.
4. “Approve rollback to v2.4.0.” Paste the agent’s comment into the open Observability case. If Cases / email tools appear, use those too.
5. The **case thread** is the audit. Discover incident stream only if a CLI write path existed (lab-only).

**If Agent Builder is slow or empty:** open case + `elasticco-checkout-correlated-rca`. Never open a terminal unless they ask.

**Exit line:** From alert to grounded RCA to the case — without leaving Elastic.

---

### Optional closer · U6 Workflow (~2 min)

If they ask how this is automated — do not invent kubectl.

**Deck:** [../presentations/u6-detect-to-remediate.html](../presentations/u6-detect-to-remediate.html)

1. Analytics → Workflows → **Elastic Co. detect-to-remediate** (`elasticco-detect-remediate`). **Run** if you need a fresh execution (alerts already firing will not re-trigger `onActionGroupChange`).
2. Walk: ES|QL (OOM, FOR UPDATE, tenant p95) → `elasticco-rca-agent` → case comment (v2.4.1 → v2.4.0).
3. Quality alerts `elasticco-eks-pod-restarts` and `elasticco-checkout-correlated-rca` have **Run Workflow**. YAML `triggers: alert` is not enough without that action.

**Line:** Detect in Alerting, enrich in Elasticsearch, reason in Agent Builder, track in Cases — Workflows is the stitch.

**Skip if Workflows 403:** stay on U5 + Cases.

---

### Optional sibling · U7 Log rate analysis (~5 min)

Do **not** insert this into the checkout close. It is a second planted scenario (inventory SkuCache DEBUG).

**Deck:** [../presentations/u7-log-rate-analysis.html](../presentations/u7-log-rate-analysis.html) · script: [talk-track-5.md](talk-track-5.md)  
**With the native SLO (~12 min):** [talk-track-5.md](talk-track-5.md#combined-u7--slo) · [../presentations/scenario-u7-slo.html](../presentations/scenario-u7-slo.html)

Discover **Elastic Co. Logs** → cliff last ~35 min → AIOps **Log rate analysis** names `debug` / `SkuCache` / `inventory-service` / `4.0.9`. APM inventory is healthy. Restore INFO — do not rollback checkout-api.

**Beat 2 (seeded):** switch the analysis data view to **Elastic Co. Orchestrator Logs**. Terms: `tenant.id: acme-retail`, `log.level: error`, `charge_payment`. That is U1–U6 — close is still v2.4.0 on the case.

**Line:** A log spike is not an outage until Log Rate Analysis tells you which field-value combination caused it.

---

### Optional sibling · U8 Log telemetry gap (~5 min)

Do **not** insert this into the checkout close. Logs went silent on **notification-service**; APM still flows.

**Deck:** [../presentations/u8-log-telemetry-gap.html](../presentations/u8-log-telemetry-gap.html) · script: [talk-track-5.md](talk-track-5.md)

Alerts → **`elasticco-log-telemetry-gap`** → Discover Notification Logs (last event ~20 min) → APM notification-service still transacting. Close is restart agent / check ingest. Do not start `elasticco-detect-remediate`. Do not rollback checkout-api. Do not restore SkuCache INFO.

**Line:** Logs going dark is not an outage until traces and pods disagree.

---

## Cut for time

| Clock | Cut |
|-------|-----|
| ~12 min | U1 fields only (no pipeline UI) + U2 waterfall + U4 SLO + correlation. Skip U3 Cases and U5 if Agent Builder is cold. |
| ~12 min (traces + RCA) | Combined U2 + U5 — [talk-track-5.md](talk-track-5.md#combined-u2--u5) |
| ~20 min | U1–U4. Name U5: “Agent Builder closes the loop on the same case.” |
| ~25 min | Full U1–U5. U6 only if they ask. |

Do not skip the **Line** at the end of whatever you did run.
