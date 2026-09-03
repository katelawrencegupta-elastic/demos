# 5-minute talk-tracks — Elastic Co.

Standalone scripts. Same planted incident; do not reset the story.

| Need | Use |
|------|-----|
| Full arc (~25 min) | [talk-track-25.md](talk-track-25.md) |
| Combined U2 + U5 (~12 min) | [below](#combined-u2--u5) · lab [02-05-trace-rca.md](02-05-trace-rca.md) |
| Combined U7 + SLO (~12 min) | [below](#combined-u7--slo) · lab [07-slo-log-rate.md](07-slo-log-rate.md) |
| Log rate (~5 min) | [below](#u7--log-rate-analysis-5-min) · lab [07-log-rate-analysis.md](07-log-rate-analysis.md) |
| Log telemetry gap (~5 min) | [below](#u8--log-telemetry-gap-5-min) · lab [08-log-telemetry-gap.md](08-log-telemetry-gap.md) |
| Operator / pre-flight | [facilitator.md](facilitator.md) |
| Full-arc visual | [../presentations/scenario-walkthrough.html](../presentations/scenario-walkthrough.html) |

**Audience:** Platform / SRE / Observability buyers  
**Kibana:** Last 2 hours · `labels.demo: elastic-co` if a view is empty.

---

## Shared prep

```bash
.venv/bin/python -m src.cli setup
.venv/bin/python -m src.cli backfill --hours 6
.venv/bin/python -m src.cli verify
```

U1–U3 play from seeded history. **U4, U5, U6, combined U2+U5, combined U7+SLO, U7, U8, 25-min arc:** start a live tick before the room (`--live-incident` is the default):

```bash
.venv/bin/python -m src.cli stream --tick 60
```

Do **not** dump story facts on slide 1. Facilitator key: blast tenant `acme-retail`; healthy `globex-mart` / `initech-b2b`; bad deploy `checkout-api` **v2.4.1**; DAG `fulfillment.checkout`; smoking gun `SELECT … FOR UPDATE` on `orders`.

Never open a terminal in front of the customer unless they ask how it was seeded.

---

## U1 · Unstructured → structured (5 min)

**Outcome:** On-call filters `tenant.id` and clicks into APM — no regex in Discover.  
**Deck:** [../presentations/u1-elastic-components.html](../presentations/u1-elastic-components.html)  
**Lab:** [01-orchestrator-structuring.md](01-orchestrator-structuring.md)  
**Tabs:** Discover (`elasticco-orchestrator`) · Ingest Pipelines · APM (leave closed until the click)

| Clock | Do |
|-------|----|
| 0:00–0:40 | **Say:** Elastic Co. is a multi-tenant fulfillment SaaS. Checkout pain shows up first as Airflow-style orchestrator spam — free text, no `tenant.id`, no `trace.id`. |
| 0:40–1:30 | Discover → **Elastic Co. Orchestrator Logs**. Open one doc. Point at `message`. Ask: “Find every error for `acme-retail`.” It is a grep problem. |
| 1:30–3:00 | Pipeline `logs-elasticco.orchestrator`. Grok extracts `tenant.id`, `trace.id`, `orchestrator.dag_id`, `orchestrator.task_id`. Optional: deck **▶ Run pipeline demo**. |
| 3:00–4:20 | Discover. Filter `tenant.id: acme-retail and log.level: error` (or `warning`). Open a doc. Click **`trace.id`**. |
| 4:20–5:00 | Land in APM (or promise the waterfall). **Line:** Parsing is not vanity — it is how correlation becomes a click, not a scavenger hunt. |

**Skip if late:** pipeline UI — assert fields on a structured doc, filter, click.  
**If they want more:** U2 waterfall on that same `trace.id`.

---

## U2 · Trace + tenant + DB (5 min)

**Outcome:** Who is hurt (`tenant.id`) and where time went (Postgres span) on one seven-hop `trace.id`.  
**Deck:** [../presentations/u2-distributed-traces.html](../presentations/u2-distributed-traces.html)  
**Lab:** [02-trace-tenant-db.md](02-trace-tenant-db.md)  
**Tabs:** Dashboard **Elastic Co. — End-to-End Tracing** · APM Services / Service map · Discover ES|QL (optional)

| Clock | Do |
|-------|----|
| 0:00–0:40 | **Say:** One checkout request crosses seven hops. If tenant context is missing, you optimize the wrong customer. |
| 0:40–1:40 | **Elastic Co. — End-to-End Tracing** or APM **Services / Service map**: `edge-gateway` → `identity-service` → `checkout-api` → inventory / fraud / payments → postgres + redis + kafka → `notification-service`. Checkout-api should show an **alert badge** (error-rate / correlation / restarts). Peers and the noisy CPU rule do not. |
| 1:40–3:20 | Filter `tenant.id: acme-retail`. Open a slow txn. Expand **postgresql** — `SELECT … FOR UPDATE` ~2–4s. Note `service.version: 2.4.1`. |
| 3:20–4:30 | Dashboard tenant p95, or ES\|QL `PERCENTILE` by `tenant.id` — `acme-retail` vs `globex-mart` / `initech-b2b`. |
| 4:30–5:00 | **Line:** Seven hops, one tenant label, time spent in FOR UPDATE. Tenant answers “who is hurt?” The DB span answers “where did the time go?” |

**Skip if late:** ES|QL — waterfall + tenant filter is enough.  
**If they want more:** same `trace.id` in orchestrator logs (U1), OOM on checkout pods (U3), or combined U2+U5.

---

## U3 · Restart → reason (5 min)

**Outcome:** Restarts are a symptom; OOM + deploy version is the reason — same window as the slow traces.  
**Deck:** [../presentations/u3-eks-restart-rca.html](../presentations/u3-eks-restart-rca.html)  
**Lab:** [03-eks-restart-rca.md](03-eks-restart-rca.md)  
**Tabs:** Dashboard **Elastic Co. — EKS Restarts** · Discover Kubernetes + checkout logs · Alerts / Cases

| Clock | Do |
|-------|----|
| 0:00–0:40 | **Say:** On-call sees checkout pods restarting. The wrong ending is “add memory.” We want reason in one timeline. |
| 0:40–2:20 | **Elastic Co. — EKS Restarts**. `kubernetes.event.reason: OOMKilled` on `checkout-api`. Memory vs 512 MiB limit; `kubernetes.pod.restart.count` climbing. |
| 2:20–3:30 | Checkout logs: `OutOfMemoryError` + `deploy=2.4.1` + `CartCache.retainAll`. *Leak you’d confirm on a flamegraph* (Profiling not seeded). |
| 3:30–4:20 | Alert `elasticco-eks-pod-restarts` → Observability case **EKS restart loop — checkout-api**. |
| 4:20–5:00 | **Line:** Restarts are a symptom. OOM plus deploy version is a reason — not a second mystery. |

**Skip if late:** Cases — stay on the dashboard + one OOM log line.  
**If they want more:** noisy vs SLO vs correlation (U4).

---

## U4 · Alert quality (5 min)

**Outcome:** Three objects — noise you ignore, a native SLO you page on, a correlation alert that starts RCA.  
**Deck:** [../presentations/u4-alerting-ai-triage.html](../presentations/u4-alerting-ai-triage.html)  
**Lab:** [04-alerting-ai-triage.md](04-alerting-ai-triage.md)  
**Tabs:** Alerts · SLOs · Cases · AI Assistant (contrast opener only)  
**Prompt:** [../kibana/ai-triage-prompts.md](../kibana/ai-triage-prompts.md)

| Clock | Do |
|-------|----|
| 0:00–0:40 | **Say:** Storage of logs/metrics/traces is table stakes. The question is whether you page on an SLO and start RCA from a correlation that already knows the tenant. |
| 0:40–1:30 | Open **`elasticco-noisy-node-cpu`**. CPU threshold, no service, no tenant. APM inventory / Service map will **not** badge it. “Would you page for this?” |
| 1:30–2:40 | SLOs → **`elasticco-slo-checkout-availability`**. Native error budget for checkout-api / acme-retail. *This is what you page on.* |
| 2:40–3:50 | Open **`elasticco-checkout-correlated-rca`**. ES\|QL ties OOM + slow DB + OOM logs. Cases action. *RCA starter — not an SLO.* |
| 3:50–4:40 | Optional: AI Assistant contrast prompt. Do not close here — U5 is Agent Builder. |
| 4:40–5:00 | **Line:** Noise you ignore, an SLO you page on, a correlation alert that names the blast radius. |

**Skip if late:** noisy-rule walkthrough — open the native SLO and the correlation alert.  
**If they want more:** U5 Agent Builder, U6 Workflow, or combined U7 + SLO (page vs ingest noise).

---

## U5 · Agent Builder RCA (5 min)

**Outcome:** Alert → tool-backed RCA in Agent Builder → approve rollback into the open case.  
**Deck:** [../presentations/u5-app-monitoring-rca.html](../presentations/u5-app-monitoring-rca.html)  
**Lab:** [05-app-monitoring-rca.md](05-app-monitoring-rca.md)  
**Tabs:** APM Services/map or Alerts or SLOs · Agent Builder (`elasticco-rca-agent`) · Cases  
**Prompt:** checkout-api is failing for acme-retail — reconstruct RCA and recommend one remediation.

Pre-warm the chat before the room (or during U4) so you are walking tool results, not a spinner.

| Clock | Do |
|-------|----|
| 0:00–0:40 | **Say:** Application monitoring names the failing service. The close is grounded RCA in Elastic — not a Python CLI. |
| 0:40–1:20 | APM Services / Service map → **checkout-api** alert badge, **or** Alerts → **`elasticco-app-checkout-error-rate`**, **or** SLOs (error budget). |
| 1:20–3:20 | Agent Builder: paste the prompt. Walk acme-retail p95 / OOM / FOR UPDATE from **tools** (not 0% errors). |
| 3:20–4:30 | “Approve rollback to v2.4.0.” Paste the agent’s comment into the open case. If Cases/email tools appear, use those too. |
| 4:30–5:00 | **Line:** From alert to grounded RCA to the case — without leaving Elastic. |

**Skip if late / Agent Builder empty:** open case + `elasticco-checkout-correlated-rca`. Never open a terminal unless they ask. Facilitator backup: `python -m src.cli incident --dry-run`.  
**If they want more:** combined U2+U5, U6 Workflow, or the 25-min arc.

---

## Combined U2 + U5

**Outcome:** Waterfall proves who is hurt and where time went; Agent Builder writes the same evidence into the case as a v2.4.0 rollback.  
**Time:** ~12 min  
**Deck:** [../presentations/scenario-u2-u5.html](../presentations/scenario-u2-u5.html) — ▶ Walk the lab  
**Lab:** [02-05-trace-rca.md](02-05-trace-rca.md)  
**Tabs:** APM Services/map or Alerts or SLOs · End-to-End Tracing · Agent Builder · Cases  
**Prompt:** checkout-api is failing for acme-retail — reconstruct RCA and recommend one remediation.

Stream `--tick 60` must be running. Pre-warm Agent Builder.

| Clock | Do |
|-------|----|
| 0:00–0:40 | **Say:** Checkout is failing for one tenant. We will name the path, then close in Agent Builder — not a terminal. |
| 0:40–1:20 | APM Services / Service map → **checkout-api** badge, **or** Alerts → **`elasticco-app-checkout-error-rate`**, **or** SLOs (`elasticco-slo-checkout-availability`). |
| 1:20–5:00 | **Elastic Co. — End-to-End Tracing**: seven hops. Filter `tenant.id: acme-retail`. Expand **postgresql** `FOR UPDATE` ~2.8s. Note `service.version: 2.4.1`. Optional ES\|QL p95 by tenant. **Line:** seven hops, one tenant, time in FOR UPDATE. |
| 5:00–9:30 | Agent Builder: paste the prompt. Tools must match the waterfall (p95 / FOR UPDATE / OOM), not 0% errors. |
| 9:30–12:00 | “Approve rollback to v2.4.0.” Paste into the open case. **Line:** From the request path to grounded RCA to the case — without leaving Elastic. |

**Skip if late:** ES|QL — waterfall + one FOR UPDATE span is enough.  
**Skip if Agent Builder empty:** waterfall + open case + `elasticco-checkout-correlated-rca`.

---

## U6 · Workflow detect → remediate (5 min)

**Outcome:** One Kibana Workflow runs Alerting → ES|QL → Agent Builder → Cases, ending in a rollback-to-v2.4.0 **comment** (not kubectl).  
**Deck:** [../presentations/u6-detect-to-remediate.html](../presentations/u6-detect-to-remediate.html)  
**Lab:** [06-detect-remediate.md](06-detect-remediate.md)  
**Tabs:** Workflows (`elasticco-detect-remediate`) · Alerts (quality rule Actions) · Cases

| Clock | Do |
|-------|----|
| 0:00–0:40 | **Say:** Storage is table stakes. The question is whether detect-to-remediate is a product path or a pile of tabs. |
| 0:40–1:30 | Analytics → Workflows → **Elastic Co. detect-to-remediate**. Enabled. Alert + manual triggers. |
| 1:30–3:20 | **Run** (manual) *or* show a finished execution. Walk ES\|QL → `elasticco-rca-agent` → case. Manual Run if alerts were already firing (`onActionGroupChange` will not re-fire). |
| 3:20–4:20 | Cases: recommended remediation (v2.4.1 → v2.4.0). Quality rules `elasticco-eks-pod-restarts` and `elasticco-checkout-correlated-rca`: Actions include **Run Workflow**. YAML `triggers: alert` is not enough alone. |
| 4:20–5:00 | **Line:** Detect in Alerting, enrich in Elasticsearch, reason in Agent Builder, track in Cases — Workflows is the stitch. |

**Skip if Workflows 403 / missing:** U5 Agent Builder + existing Cases action. Do not invent kubectl.

---

## U7 · Log rate analysis (5 min)

**Outcome:** A log-volume cliff is explained by significant field-value pairs (SkuCache DEBUG) — not grep, and not the checkout OOM.  
**Deck:** [../presentations/u7-log-rate-analysis.html](../presentations/u7-log-rate-analysis.html)  
**Lab:** [07-log-rate-analysis.md](07-log-rate-analysis.md)  
**Tabs:** Discover (`elasticco-logs` or `elasticco-inventory`) · AIOps Labs → Log rate analysis · **Elastic Co. Orchestrator Logs** (beat 2) · Dashboard **Elastic Co. — Log Rate** · APM inventory-service

Stream `--tick 60` keeps the last ~35 minutes of DEBUG through now.

| Clock | Do |
|-------|----|
| 0:00–0:40 | **Say:** Logs are on fire. Counting is not RCA. We will let Log Rate Analysis name the field-value combination. |
| 0:40–1:30 | Discover **Elastic Co. Logs**, Last 2 hours. Point at the cliff in the last ~35 minutes. |
| 1:30–3:20 | Machine Learning → **AIOps Labs → Log rate analysis**. Same data view. Click the spike. Terms: `log.level: debug`, `log.logger: com.elasticco.inventory.SkuCache`, `service.name: inventory-service`, `service.version: 4.0.9`. |
| 3:20–4:20 | APM inventory-service still healthy. **Not** checkout-api v2.4.1. Close is restore INFO. |
| 4:20–5:00 | **Line:** A log spike is not an outage until Log Rate Analysis tells you which field-value combination caused it. |
| +1:00 | **Beat 2:** switch data view to **Elastic Co. Orchestrator Logs**. Click the last-60m spike. Terms: `tenant.id: acme-retail`, `log.level: error`, `charge_payment`. That close is rollback v2.4.0 — not restore INFO. |

**Skip if AIOps Labs 403:** dashboard `elasticco-log-rate` + Discover histogram.  
**If they want more:** Beat 2 is seeded — Orchestrator Logs in Log rate analysis names `acme-retail` + ERROR. Combined U7 + SLO if they want the page vs the flood in one room.

---

## U8 · Log telemetry gap (5 min)

**Outcome:** Logs went silent; traces and pods prove the app is alive — page telemetry, not the service.  
**Deck:** [../presentations/u8-log-telemetry-gap.html](../presentations/u8-log-telemetry-gap.html)  
**Lab:** [08-log-telemetry-gap.md](08-log-telemetry-gap.md)  
**Tabs:** Alerts (`elasticco-log-telemetry-gap`) · Discover `elasticco-notification` · APM notification-service · dashboard `elasticco-telemetry-gap` · Cases

Stream `--tick 60` keeps the last ~20 minutes of log silence (and APM ticks) through now.

| Clock | Do |
|-------|----|
| 0:00–0:40 | **Say:** notification-service logs went dark. Before you page the app, ask whether telemetry failed. |
| 0:40–1:30 | Alerts → **`elasticco-log-telemetry-gap`**. Cases. No Run Workflow (that stitch is checkout RCA). |
| 1:30–3:00 | Discover **Elastic Co. Notification Logs**. Last event ~20 min ago. Histogram is a drop, not a spike. |
| 3:00–4:20 | APM **notification-service** still transacting. Optional dashboard: logs last 15m = 0 vs APM last 15m > 0. |
| 4:20–5:00 | **Line:** Logs going dark is not an outage until traces and pods disagree. Close is restart agent / check ingest — not rollback, not restore INFO. |

**Skip if alert not firing:** Discover last-event + APM still live is enough. Wait 1–2 min after backfill.  
**If they want more:** optional Log rate analysis on the **drop** (Notification Logs data view).

---

## Combined U7 + SLO

**Outcome:** Native SLO is the page (checkout / acme-retail). Log Rate Analysis names a second incident (SkuCache DEBUG). Optional beat 2: the same product on orchestrator names the SLO’s incident. Two remediations — never mixed.  
**Time:** ~12 min  
**Deck:** [../presentations/scenario-u7-slo.html](../presentations/scenario-u7-slo.html) — ▶ Walk the lab  
**Lab:** [07-slo-log-rate.md](07-slo-log-rate.md)  
**Tabs:** SLOs · Discover (`elasticco-logs`) · AIOps Labs → Log rate analysis · APM inventory-service · Orchestrator Logs (beat 2)

Stream `--tick 60` keeps the DEBUG window and checkout traces through now. `verify --alerts` must show the SLO as **not** `NO_DATA`.

| Clock | Do |
|-------|----|
| 0:00–0:40 | **Say:** Two signals in the same project. What you page on is not automatically what the logs just did. |
| 0:40–3:20 | SLOs → **`elasticco-slo-checkout-availability`**. 99% / 7d rolling. Status **VIOLATED** (~94%). Scope checkout-api / acme-retail. *This is the page.* Not `elasticco-noisy-node-cpu`. Not the ES\|QL correlation alert. |
| 3:20–4:20 | Discover **Elastic Co. Logs**, Last 2 hours. Point at the cliff in the last ~35 minutes. Do not assume it is the SLO. Counting is not RCA. |
| 4:20–8:00 | AIOps Labs → **Log rate analysis**. Click the spike. Terms: `debug` · `SkuCache` · `inventory-service` · `4.0.9`. APM inventory-service is healthy. **Close:** restore INFO. Do **not** roll back checkout-api. |
| 8:00–10:00 | Optional beat 2: same product, data view **Elastic Co. Orchestrator Logs**. Click last ~60 min. Terms: `acme-retail` · `error` · `charge_payment`. That spike **is** the SLO. Close stays rollback **v2.4.0**. |
| 10:00–12:00 | **Line:** Native SLO is the page. Inventory DEBUG is ingest noise. Orchestrator ERROR is the same availability incident as the SLO. Two closes — never mixed. |

**Skip if late:** drop beat 2. SLO chart + one Log Rate spike + APM inventory is enough.  
**Skip if AIOps Labs 403:** dashboard `elasticco-log-rate` + Discover histogram.

---

## Booth / hallway

| Time | Run |
|------|-----|
| ~2 min | One **Line** + one Kibana surface (U1 filter, U2 waterfall, U3 OOM dashboard, U4 SLO vs correlation, U5 Agent Builder, U6 Workflows stitch, U7 log-rate cliff, U8 log silence vs APM) |
| ~5 min | The matching table above |
| ~12 min | Combined U2 + U5, **or** combined U7 + SLO, **or** U1 fields + U2 waterfall + U4 SLO + correlation |
| ~25 min | [talk-track-25.md](talk-track-25.md) |
