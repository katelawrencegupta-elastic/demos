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

U1–U3 play from Last 2 hours of seeded history. **U4 / U5** (Active Alerts): start `.venv/bin/python -m src.cli stream --tick 60` in a side terminal before the room (`--live-incident` is the default).

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

**Outcome:** Who is hurt (`tenant.id`) and where time went (Postgres span) on one seven-hop `trace.id`.  
**Deck:** [../presentations/u2-distributed-traces.html](../presentations/u2-distributed-traces.html)  
**Tabs:** APM → Services · Dashboard **Elastic Co. — End-to-End Tracing** · Discover ES|QL (optional)

| Clock | Do |
|-------|----|
| 0:00–0:40 | **Say:** One checkout request crosses seven hops. If tenant context is missing, you optimize the wrong customer. |
| 0:40–1:40 | APM Services **or** **Elastic Co. — End-to-End Tracing**: `edge-gateway` → `identity-service` → `checkout-api` → inventory / fraud / payments → postgres + redis + kafka → `notification-service`. |
| 1:40–3:20 | Filter `tenant.id: acme-retail`. Open a slow txn. Expand **postgresql** — `SELECT … FOR UPDATE` ~2–4s. Note `service.version: 2.4.1`. **Line:** seven hops, one tenant label, time spent in FOR UPDATE. |
| 3:20–4:30 | E2E dashboard hop p95 / tenant lines, or ES|QL `PERCENTILE` by `tenant.id` — `acme-retail` is the outlier vs `globex-mart` / `initech-b2b`. |
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
| 0:40–2:20 | Dashboard **Elastic Co. — EKS Restarts**. `kubernetes.event.reason: OOMKilled` on `checkout-api`. Memory vs limit; `kubernetes.pod.restart.count` climbing. |
| 2:20–3:30 | Discover checkout logs: `OutOfMemoryError` + `deploy=2.4.1` + `CartCache.retainAll`. *This is the leak you’d confirm on a flamegraph* (Profiling not seeded). |
| 3:30–4:20 | Alert `elasticco-eks-pod-restarts` → Observability case **EKS restart loop — checkout-api**. |
| 4:20–5:00 | **Line:** Restarts are a symptom. OOM plus deploy version is a reason — not a second mystery. |

**Skip if late:** Cases — stay on the dashboard + one OOM log line.  
**If they want more:** noisy vs SLO vs correlation (U4).

---

## U4 · Alert quality (5 min)

**Outcome:** Three objects — noise you ignore, a native SLO you page on, a correlation alert that starts RCA.  
**Deck:** [../presentations/u4-alerting-ai-triage.html](../presentations/u4-alerting-ai-triage.html)  
**Tabs:** Alerts · SLOs · Cases · AI Assistant (contrast opener only)  
**Prompt:** [../kibana/ai-triage-prompts.md](../kibana/ai-triage-prompts.md) (contrast opener)

| Clock | Do |
|-------|----|
| 0:00–0:40 | **Say:** Storage of logs/metrics/traces is table stakes. The question is whether you page on an SLO and start RCA from a correlation that already knows the tenant. |
| 0:40–1:30 | Open **`elasticco-noisy-node-cpu`**. CPU threshold, no service, no tenant. Ask: “Would you page for this?” |
| 1:30–2:40 | Observability → SLOs → **`elasticco-slo-checkout-availability`**. Native error budget for checkout-api / acme-retail. *This is what you page on.* |
| 2:40–3:50 | Open **`elasticco-checkout-correlated-rca`**. ES\|QL ties OOM + slow DB + OOM logs. Cases action. *RCA starter — not an SLO.* |
| 3:50–4:40 | Optional: AI Assistant contrast prompt (noisy vs correlation). Do not close here — U5 is Agent Builder. |
| 4:40–5:00 | **Line:** Noise you ignore, an SLO you page on, a correlation alert that names the blast radius. |

**Skip if late:** noisy-rule walkthrough — open the native SLO and the correlation alert.  
**If they want more:** U5 Agent Builder.

---

## U5 · Agent Builder RCA (5 min)

**Outcome:** Alert → tool-backed RCA in Agent Builder → approve rollback into the open case (paste if capabilities are read-only).  
**Deck:** [../presentations/u5-app-monitoring-rca.html](../presentations/u5-app-monitoring-rca.html)  
**Tabs:** Alerts or SLOs · Agent Builder (`elasticco-rca-agent`) · Cases  
**Prompt:** checkout-api is failing for acme-retail — reconstruct RCA and recommend one remediation.

| Clock | Do |
|-------|----|
| 0:00–0:40 | **Say:** Application monitoring names the failing service. The close is grounded RCA in Elastic — not a Python CLI. |
| 0:40–1:20 | Alerts → **`elasticco-app-checkout-error-rate`** *or* Observability → SLOs (error budget). |
| 1:20–3:20 | Agent Builder: paste the prompt. Walk acme-retail p95 / OOM / FOR UPDATE from **tools** (not 0% errors). |
| 3:20–4:30 | “Approve rollback to v2.4.0.” Paste the agent’s comment into the open case. If Cases/email tools appear, use those too. |
| 4:30–5:00 | **Line:** From alert to grounded RCA to the case — without leaving Elastic. |

**Skip if late / Agent Builder empty:** open case + correlated RCA alert. Never open a terminal unless they ask. Facilitator backup: `python -m src.cli incident --dry-run`.  
**If they want more:** full 25-min arc ([talk-track-25.md](talk-track-25.md)).

---

## Booth / hallway variants

| Time | Run |
|------|-----|
| ~2 min | One **Line** + one Kibana surface (U1 filter, U2 waterfall, U3 OOM dashboard, U4 SLO vs correlation, U5 Agent Builder) |
| ~5 min | The matching table above |
| ~12 min | U1 (fields only) + U2 7-hop waterfall + U4 SLO + correlation |
| ~25 min | [talk-track-25.md](talk-track-25.md) |
