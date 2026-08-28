# 5-minute talk-tracks — Elastic Co.

Standalone scripts for a **single use case**. Same planted incident; do not reset the story. For the full arc see [talk-track-25.md](talk-track-25.md).

**Audience:** Platform / SRE / Observability buyers  
**Time range in Kibana:** Last 2 hours · filter `labels.demo: elastic-co` when a query is empty.

## Shared prep

```bash
.venv/bin/python -m src.cli setup
.venv/bin/python -m src.cli backfill --hours 6
.venv/bin/python -m src.cli verify
```

Story facts (do not dump on slide 1): blast tenant `acme-retail`; healthy `globex-mart` / `initech-b2b`; bad deploy `checkout-api` **v2.4.1**; DAG `fulfillment.checkout`; smoking gun `SELECT … FOR UPDATE` on `orders`.

---

## U1 · Unstructured → structured (5 min)

**Outcome:** On-call filters `tenant.id` and clicks into APM — no regex in Discover.  
**Deck:** [../presentations/u1-elastic-components.html](../presentations/u1-elastic-components.html)  
**Tabs:** Discover (`elasticco-orchestrator`) · Stack Management → Ingest Pipelines · APM (leave closed until the click)

| Clock | Do |
|-------|----|
| 0:00–0:40 | **Say:** Elastic Co. is a multi-tenant fulfillment SaaS. Checkout pain shows up first as Airflow-style orchestrator spam — free text, no `tenant.id`, no `trace.id`. |
| 0:40–1:30 | Discover → **Elastic Co. Orchestrator Logs**. Open one doc. Point at `message`. Ask: “Find every error for `acme-retail`.” It is a grep problem. |
| 1:30–3:00 | Ingest pipeline `logs-elasticco.orchestrator`. Show grok extracting `tenant.id`, `trace.id`, `orchestrator.dag_id`, `orchestrator.task_id`. Optional: deck **▶ Run pipeline demo**. |
| 3:00–4:20 | Back to Discover. Filter `tenant.id: acme-retail and log.level: error` (or `warning`). Open a doc. Click **`trace.id`**. |
| 4:20–5:00 | Land in APM (or promise the waterfall). **Line:** Parsing is not vanity — it is how correlation becomes a click, not a scavenger hunt. |

**Skip if late:** pipeline UI — assert the fields exist on a structured doc and go to the filter.  
**If they want more:** U2 waterfall on that same `trace.id`.

---

## U2 · Trace + tenant + DB (5 min)

**Outcome:** Who is hurt (`tenant.id`) and where time went (Postgres span) on one `trace.id`.  
**Deck:** [../presentations/u2-distributed-traces.html](../presentations/u2-distributed-traces.html)  
**Tabs:** APM → Services · Dashboard **Elastic Co. — End-to-End Tracing** · Discover ES|QL (optional)

| Clock | Do |
|-------|----|
| 0:00–0:40 | **Say:** One checkout request crosses seven services. If tenant context is missing, you optimize the wrong customer. |
| 0:40–1:40 | APM → Services → `checkout-api`. Service map: `edge-gateway` → `checkout-api` → postgresql / payments. |
| 1:40–3:20 | Transactions. Filter `tenant.id: acme-retail` (or labels). Open a slow txn. Expand **postgresql** — `SELECT … FOR UPDATE` ~2–4s. Note `service.version: 2.4.1`. Optional: deck **▶ Run waterfall demo**. |
| 3:20–4:30 | Dashboard **Elastic Co. — End-to-End Tracing**: hop p95, tenant lines, slow `trace.id`. Or ES|QL (deck **Copy ES|QL query**): `PERCENTILE` by `tenant.id` — `acme-retail` is the outlier vs `globex-mart` / `initech-b2b`. |
| 4:30–5:00 | **Line:** Tenant on every span answers “who is hurt?” The DB span answers “where did the time go?” |

**Skip if late:** ES|QL — the waterfall + tenant filter is enough.  
**If they want more:** same `trace.id` in orchestrator logs (U1) or OOM on checkout pods (U3).

---

## U3 · Restart → reason (5 min)

**Outcome:** Restarts are a symptom; OOM + deploy version is the reason — same window as the slow traces.  
**Deck:** [../presentations/u3-eks-restart-rca.html](../presentations/u3-eks-restart-rca.html)  
**Tabs:** Dashboard **Elastic Co. — EKS Restarts** · Discover Kubernetes + checkout logs · Alerts / Cases

| Clock | Do |
|-------|----|
| 0:00–0:40 | **Say:** On-call sees checkout pods restarting. The wrong ending is “add memory.” We want reason in one timeline. |
| 0:40–2:00 | Dashboard **Elastic Co. — EKS Restarts**. `kubernetes.event.reason: OOMKilled` on `checkout-api`. Memory vs limit; `kubernetes.pod.restart.count` climbing. |
| 2:00–3:20 | Discover checkout logs: `OutOfMemoryError` + `deploy=2.4.1` + `CartCache.retainAll`. Cluster `eks-elastic-prod-usc1`. |
| 3:20–4:20 | Alert `elasticco-eks-pod-restarts` → Observability case **EKS restart loop — checkout-api**. Same ~90 min incident window as the slow DB spans. |
| 4:20–5:00 | **Line:** Restarts are a symptom. OOM plus deploy version is a reason — not a second mystery. |

**Skip if late:** Cases — stay on the dashboard + one OOM log line.  
**If they want more:** noisy vs quality alerts (U4).

---

## U4 · Alert quality + AI triage (5 min)

**Outcome:** A quality alert names blast radius; AI can state the planted RCA from that context.  
**Deck:** [../presentations/u4-alerting-ai-triage.html](../presentations/u4-alerting-ai-triage.html)  
**Tabs:** Alerts · Cases · AI Assistant  
**Prompt:** [../kibana/ai-triage-prompts.md](../kibana/ai-triage-prompts.md) (Primary RCA)

| Clock | Do |
|-------|----|
| 0:00–0:40 | **Say:** Storage of logs/metrics/traces is table stakes. The question is whether the alert you wake someone for already knows the tenant and the service. |
| 0:40–1:50 | Open **`elasticco-noisy-node-cpu`**. CPU threshold, no service, no tenant. Ask: “Would you page for this?” |
| 1:50–3:00 | Open **`elasticco-checkout-slo-burn`**. Tags: `checkout-api`, `acme-retail`. Query ties OOM + slow DB + OOM logs. Point at the Cases action. |
| 3:00–4:30 | AI Assistant: paste the **Primary RCA prompt**. Expected shape: v2.4.1 leak → OOM → orchestrator retries → `FOR UPDATE` for `acme-retail` → roll back to **2.4.0**. |
| 4:30–5:00 | **Line:** Elastic does not just store the three pillars — it lets you name the blast radius and hand RCA to AI from a high-quality alert. |

**Skip if late:** noisy-rule walkthrough — open the quality alert and go straight to AI.  
**If they want more:** U5 agent that remediates and emails.

---

## U5 · App monitoring + RCA agent (5 min)

**Outcome:** Alert → correlated RCA → human approval → rollback → email / audit trail, without leaving Elastic.  
**Deck:** [../presentations/u5-app-monitoring-rca.html](../presentations/u5-app-monitoring-rca.html)  
**Tabs:** Alerts (`elasticco-app-checkout-error-rate`) · Cases · Discover **Elastic Co. Incident Audit** · terminal

| Clock | Do |
|-------|----|
| 0:00–0:40 | **Say:** Application monitoring names the failing service. The close is not another dashboard — it is approved remediation with an audit trail. |
| 0:40–1:20 | Alerts → **`elasticco-app-checkout-error-rate`**: checkout-api error rate > 10% in 15 min, tenant tags. Contrast with noisy node CPU if they have not seen U4. |
| 1:20–3:20 | Terminal: `.venv/bin/python -m src.cli incident --email kate.lawrencegupta@elastic.co` (or `--dry-run` if you only want the report). Walk OOM + v2.4.1 + slow DB + orchestrator retries + hero `trace.id`. |
| 3:20–4:30 | **Approve** rollback to v2.4.0 (`y`). Agent updates the Kibana case and sends email (or writes `output/incident-emails/`). Discover `elasticco-incidents`: `detected` → `remediation` → `resolved` → `notified`. |
| 4:30–5:00 | **Line:** From alert to root cause to approved remediation to on-call notification — with a full audit trail. |

**Skip if late:** use `--auto` and skip the approval pause; or `--dry-run` and skip email.  
**If they want more:** full 25-min arc from orchestrator grok through this close ([talk-track-25.md](talk-track-25.md)).

---

## Booth / hallway variants

| Time | Run |
|------|-----|
| ~2 min | One **Line** + one Kibana surface (U1 filter, U2 waterfall, U3 OOM dashboard, U4 quality alert, U5 `--dry-run` report) |
| ~5 min | The matching table above |
| ~12 min | U1 (fields only) + U2 waterfall + U4 quality + AI |
| ~25 min | [talk-track-25.md](talk-track-25.md) |
