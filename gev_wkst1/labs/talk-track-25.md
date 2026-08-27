# SE talk-track (~22–25 min) — Elastic Co.

**Audience:** Platform / SRE / Observability buyers  
**Goal:** One incident arc; never reset context. End with AI triage stating the planted RCA.

## Prep (before the room)

```bash
.venv/bin/python -m src.cli setup
.venv/bin/python -m src.cli backfill --hours 6
.venv/bin/python -m src.cli verify
```

Open Kibana tabs: Discover (`elasticco-orchestrator`), APM Services, Alerts, AI Assistant, Dashboard `Elastic Co. — Incident Overview`. Time range: **Last 2 hours**.

---

### 0:00–2:00 · Frame

**Say:** Elastic Co. is a multi-tenant fulfillment SaaS. The fear every platform team has: *one noisy tenant takes down checkout for everyone — and you find out in Slack, not in observability.*

**Promise:** In the next 20 minutes we go from raw orchestrator spam → a single `trace.id` → a Postgres span → an OOM restart loop → a quality alert that an AI can triage without dashboard hopping.

---

### 2:00–7:00 · U1 Unstructured → structured

1. Discover → data view **Elastic Co. Orchestrator Logs**.
2. Show raw `message` (Airflow-style free text). Ask: “Find all errors for `acme-retail`.” Hard without fields.
3. Show ingest pipeline `logs-elasticco.orchestrator` (Stack Management → Ingest Pipelines) — grok extracts `tenant.id`, `trace.id`, `orchestrator.dag_id`.
4. Filter `tenant.id: acme-retail and log.level: error` (or `warning`). Open a doc; click **`trace.id`**.

**Line:** Parsing is not vanity — it is how correlation becomes a click, not a grep scavenger hunt.

---

### 7:00–13:00 · U2 Trace + tenant + DB

1. APM → Services → `checkout-api` / service map: `edge-gateway` → `checkout-api` → `payments-api` + `orders-db` (postgresql).
2. Open a transaction for tenant `acme-retail` (filter `tenant.id` / labels).
3. Waterfall: expand the **postgresql** span — `SELECT … FOR UPDATE` lasting ~2–4s.
4. Note `service.version: 2.4.1` on checkout during the incident window.

**Line:** Tenant context on every span answers “who is hurt?” The DB span answers “where did time go?”

---

### 13:00–18:00 · U3 Restart to reason

1. Discover / dashboard: `kubernetes.event.reason: OOMKilled` on `checkout-api` pods.
2. Metrics: memory usage climbing to limit; `kubernetes.pod.restart.count` rising.
3. Checkout logs: `OutOfMemoryError` + `deploy=2.4.1` + `CartCache.retainAll`.

**Line:** Restarts are a symptom. OOM + deploy version is a reason. Same time window as the slow traces — not a second mystery.

---

### 18:00–22:00 · U4 Alert quality + AI triage

1. Alerts: open **`elasticco-noisy-node-cpu`** — CPU threshold, no tenant/service. “Would you wake someone for this?”
2. Open **`elasticco-checkout-slo-burn`** — tags include `checkout-api`, `acme-retail`; query ties OOM + slow DB + OOM logs.
3. AI Assistant: paste the primary RCA prompt from [../kibana/ai-triage-prompts.md](../kibana/ai-triage-prompts.md).
4. Close: leak → OOM → retries → DB lock contention → tenant SLO burn. Remediations: roll back to **2.4.0**, fix cache leak, keep quality alerts.

**Exit line:** Elastic does not just store the three pillars — it lets you *name the blast radius* and *hand the RCA to AI* from a high-quality alert.

---

### If time is short (12 min)

Skip pipeline UI in U1 (assert fields exist). Skip noisy alert; only show quality + AI.
