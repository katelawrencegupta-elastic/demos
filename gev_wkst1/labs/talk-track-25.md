# SE talk-track (~25–30 min) — Elastic Co.

**Audience:** Platform / SRE / Observability buyers  
**Goal:** One incident arc; never reset context. U4 names blast radius (noisy vs **native SLO** vs correlated RCA). U5 closes in **Agent Builder** — grounded RCA, then approve rollback into the open case.

Single use case in five minutes: [talk-track-5.md](talk-track-5.md).

## Prep (before the room)

```bash
.venv/bin/python -m src.cli setup
.venv/bin/python -m src.cli backfill --hours 6
.venv/bin/python -m src.cli verify
.venv/bin/python -m src.cli verify --alerts
```

Start a live tick in a **side terminal** before the room (`--live-incident` is the default):

```bash
.venv/bin/python -m src.cli stream --tick 60
```

Open Kibana tabs: Discover (`elasticco-orchestrator`), APM Services, Dashboard **Elastic Co. — End-to-End Tracing**, Alerts, SLOs, Cases, **Agent Builder** (`elasticco-rca-agent`). Time range: **Last 2 hours**.

Do **not** open a terminal in front of the customer unless they ask how the demo was seeded. `cli incident --dry-run` is a facilitator backup only.

---

### 0:00–2:00 · Frame

**Say:** Elastic Co. is a multi-tenant fulfillment SaaS. The fear every platform team has: *one noisy tenant takes down checkout for everyone — and you find out in Slack, not in observability.*

**Promise:** In the next 25 minutes we go from raw orchestrator spam → a seven-hop `trace.id` → a Postgres `FOR UPDATE` → an OOM restart loop → noisy vs SLO vs correlation → an Agent Builder RCA you can paste into the case.

---

### 2:00–7:00 · U1 Unstructured → structured

1. Discover → data view **Elastic Co. Orchestrator Logs**.
2. Show raw `message` (Airflow-style free text). Ask: “Find all errors for `acme-retail`.” Hard without fields.
3. Show ingest pipeline `logs-elasticco.orchestrator` (Stack Management → Ingest Pipelines) — grok extracts `tenant.id`, `trace.id`, `orchestrator.dag_id`.
4. Filter `tenant.id: acme-retail and log.level: error` (or `warning`). Open a doc; click **`trace.id`**.

**Line:** Parsing is not vanity — it is how correlation becomes a click, not a grep scavenger hunt.

---

### 7:00–13:00 · U2 Trace + tenant + DB (7 hops)

1. APM → Services **or** dashboard **Elastic Co. — End-to-End Tracing**: seven hops — `edge-gateway` → `identity-service` → `checkout-api` → inventory / fraud / payments → postgres + redis + kafka → `notification-service`.
2. Filter `tenant.id: acme-retail`. Open a slow transaction. Expand the **postgresql** span — `SELECT … FOR UPDATE` (~2–4s). Note `service.version: 2.4.1`.
3. One line: *seven hops, one tenant label, time spent in FOR UPDATE.*

**Line:** Tenant context on every span answers “who is hurt?” The DB span answers “where did time go?”

---

### 13:00–17:00 · U3 Restart to reason (+ Inventory 30s)

1. Inventory (if hosts render): host for `eks-elastic-prod-usc1` → same checkout pod on **EKS Restarts**. Skip if Inventory ignores custom `metrics-elasticco.*` datasets — do not force a dead click.
2. Dashboard **Elastic Co. — EKS Restarts**: `kubernetes.event.reason: OOMKilled` on `checkout-api` pods. Memory vs limit; `kubernetes.pod.restart.count` rising.
3. Checkout logs: `OutOfMemoryError` + `deploy=2.4.1` + `CartCache.retainAll`. *This is the leak you’d confirm on a flamegraph* (Universal Profiling is not seeded — talk only).
4. Alert `elasticco-eks-pod-restarts` + Observability case **EKS restart loop — checkout-api**.

**Line:** Restarts are a symptom. OOM + deploy version is a reason. Same time window as the slow traces — not a second mystery.

---

### 17:00–21:00 · U4 Noisy vs SLO vs correlated RCA

1. Alerts: **`elasticco-noisy-node-cpu`** — CPU threshold, no tenant/service. “Would you wake someone for this?”
2. Observability → **SLOs**: **`elasticco-slo-checkout-availability`** — native error budget / burn for `checkout-api` + `tenant.id: acme-retail`. *This is what you page on.*
3. Alerts: **`elasticco-checkout-correlated-rca`** — ES|QL quality **correlation** (OOM + slow DB + OOM logs). Tags include `checkout-api`, `acme-retail`. Cases action. *This is the RCA starter — not an SLO.*
4. Optional contrast opener: paste the noisy-vs-quality prompt into AI Assistant. Do **not** close U4 in AI Assistant — U5 is Agent Builder.

**Line:** Three objects: noise you ignore, an SLO you page on, and a correlation alert that already knows the blast radius.

---

### 21:00–28:00 · U5 Agent Builder close

Deck: [../presentations/u5-app-monitoring-rca.html](../presentations/u5-app-monitoring-rca.html)

1. Alerts: **`elasticco-app-checkout-error-rate`** *or* native SLO burn on checkout-api / acme-retail.
2. Agent Builder chat (pre-opened tab, agent `elasticco-rca-agent`):

> checkout-api is failing for acme-retail — reconstruct RCA and recommend one remediation.

3. Walk tool-backed evidence: acme-retail p95 / OOM / `FOR UPDATE` — not 0% errors. If tools are empty, skip to the open case + quality alert (do not invent).
4. “Approve rollback to v2.4.0” → Cases + email if elastic capabilities allow; otherwise paste the agent’s case comment into the open Observability case.
5. Discover incident audit **only if** a write path existed; otherwise the case thread is the audit.

**If Agent Builder is slow or empty:** skip to the open case + `elasticco-checkout-correlated-rca` (U4 exit line). Never open a terminal unless they ask.

**Exit line:** From alert to grounded RCA to the case — without leaving Elastic.

---

### If time is short (12 min)

Skip pipeline UI in U1 (assert fields exist). Skip Inventory. Skip noisy alert; show native SLO + correlated RCA. Skip U5 if Agent Builder is cold — stop after U4.

### If time is short (20 min)

Run U1–U4; mention U5 as “Agent Builder closes the loop on the same case.”
