# Facilitator guide — Elastic Co. demo

Operator notes. What you **say** is in [talk-track-25.md](talk-track-25.md) and [talk-track-5.md](talk-track-5.md). This file is prep, objects, failure modes, and what not to fake.

## Pick a path

| Room | Script | Deck |
|------|--------|------|
| Full SE (~25–30 min) | [talk-track-25.md](talk-track-25.md) | [scenario-walkthrough.html](../presentations/scenario-walkthrough.html) then U1–U5 |
| Traces + RCA (~12 min) | [talk-track-5.md](talk-track-5.md#combined-u2--u5) | [scenario-u2-u5.html](../presentations/scenario-u2-u5.html) |
| SLO + log rate (~12 min) | [talk-track-5.md](talk-track-5.md#combined-u7--slo) | [scenario-u7-slo.html](../presentations/scenario-u7-slo.html) |
| Log rate (~5 min) | [talk-track-5.md](talk-track-5.md) U7 | [u7-log-rate-analysis.html](../presentations/u7-log-rate-analysis.html) |
| Log telemetry gap (~5 min) | [talk-track-5.md](talk-track-5.md) U8 | [u8-log-telemetry-gap.html](../presentations/u8-log-telemetry-gap.html) |
| One use case (~5 min) | [talk-track-5.md](talk-track-5.md) | matching `uN-*.html` |
| Booth (~2 min) | One **Line** + one Kibana surface | — |
| Hands-on after SE | Labs 01–06 below | — |

Never reset the incident between use cases. Each UC is a lens on the same `trace.id` / same checkout pods.

---

## Hard rules

1. **No kubectl.** Remediation is a case comment: roll back checkout-api **v2.4.1 → v2.4.0**.
2. **No `src.cli incident` in front of the customer.** Facilitator backup only. Do not claim “without leaving Elastic” on a terminal path. The chat agent must never silently call the CLI.
3. **Do not invent counts.** If Agent Builder tools return 0% errors, skip to the open case + `elasticco-checkout-correlated-rca`.
4. **Do not call the correlation alert an SLO.** Page on `elasticco-slo-checkout-availability`. `elasticco-checkout-correlated-rca` is the RCA starter.
5. **Do not show story facts on slide 1.** Let Discover / APM / the dashboard reveal them.
6. **Universal Profiling** — talk only after `CartCache.retainAll`. Do not open the Profiling UI. **Synthetics** — skip.
7. **U7 is not the checkout close.** SkuCache DEBUG → restore INFO. Do not roll back checkout-api.
8. **U8 is not the checkout close.** notification-service log silence → restart agent / check ingest. Do not start `elasticco-detect-remediate`. Do not restore INFO.

---

## Story key (do not show early)

| Fact | Value |
|------|--------|
| Blast tenant | `acme-retail` |
| Healthy tenants | `globex-mart`, `initech-b2b` |
| Cluster | `eks-elastic-prod-usc1` |
| Bad deploy | `checkout-api` **v2.4.1** |
| Good deploy | **v2.4.0** |
| Leak | `CartCache.retainAll` (heap → 512 MiB) |
| Checkout pods | `checkout-api-523f0-5ab4d`, `checkout-api-1cd5c-29f59`, `checkout-api-9de64-c30ad` |
| DAG | `fulfillment.checkout` |
| DB smoking gun | `SELECT … FOR UPDATE` on `orders`, ~2–4s (p95 ~3.1s vs ~400 ms SLO) |
| Hero `trace.id` | `271f8e318871…` (joins orchestrator ↔ APM) |
| Correlation keys | `trace.id`, `tenant.id`, `order.id` |
| Native SLO (page on this) | `elasticco-slo-checkout-availability` |
| Correlation alert (RCA starter) | `elasticco-checkout-correlated-rca` |
| App alert (U5 entry) | `elasticco-app-checkout-error-rate` |
| Agent | `elasticco-rca-agent` |
| Workflow | `elasticco-detect-remediate` |
| Log-rate flood (U7 beat 1) | inventory-service **v4.0.9** · `log.logger: com.elasticco.inventory.SkuCache` · DEBUG last ~35 min |
| Retry storm (U7 beat 2) | Orchestrator ERROR every 4s for `acme-retail` / `charge_payment` in the checkout window |
| Telemetry gap (U8) | notification-service logs silent last ~20 min; APM + pods still healthy; alert `elasticco-log-telemetry-gap` |

Seven-hop path: `edge-gateway` → `identity-service` → `checkout-api` → inventory / fraud / payments → postgres + redis + kafka → `notification-service`.

Planted chain: v2.4.1 leak → OOMKilled / BackOff restart loop → orchestrator retries → lock contention on `orders` for acme-retail. Peers stay near baseline.

---

## Environment

- Elastic Cloud **Serverless** Observability. Credentials in `.env` (`ELASTIC_URL`, `ELASTIC_API_KEY`, `KIBANA_URL`).
- Fictional EKS — no real cluster. Metrics and events are synthetic but ECS-shaped.
- Filter everywhere with `labels.demo: elastic-co`. Time range **Last 2 hours**.
- Alert rule APIs differ by stack. If rule PUT warns, create manually from [../kibana/alert-rules.json](../kibana/alert-rules.json). Serverless: omit `actionTypeId` on rule PUT.
- **Agent Builder write path:** paste the agent’s comment into the case the alert already opened. If Cases / email capabilities appear, “approve rollback” can use those too.
- **Kibana Workflow:** `elasticco-detect-remediate` (ES|QL enrich → `elasticco-rca-agent` → case comment). Must be **enabled**. Quality rules need **Run Workflow**. Manual **Run** if alerts were already firing (`notify_when: onActionGroupChange`). Does not kubectl. Must **not** use `elastic-ai-agent`.
- **CLI backup:** `python -m src.cli incident --dry-run` (lab 05). Email/HTML only via `incident --email` (`KIBANA_EMAIL_CONNECTOR_ID` or SMTP); otherwise `output/incident-emails/`.
- `logs-elasticco.incident-default` is written by the **facilitator CLI**, not by Agent Builder or the workflow. The customer audit is the Observability **case**.

---

## Object inventory

| Object | Role | Starts workflow? |
|--------|------|------------------|
| `elasticco-noisy-node-cpu` | Anti-pattern — host CPU, no tenant/service | No |
| `elasticco-slo-checkout-availability` | **Native SLO** — what you page on | No |
| `elasticco-app-checkout-error-rate` | U5 entry — checkout-api / acme-retail >10%; badges APM inventory / map | No |
| `elasticco-checkout-correlated-rca` | ES\|QL OOM + slow DB + OOM logs; Cases; badges APM map | **Yes** |
| `elasticco-eks-pod-restarts` | Restart loop; Cases; badges APM map | **Yes** |
| `elasticco-rca-agent` | Agent Builder close — ES\|QL tools | — |
| `elasticco-detect-remediate` | Workflow stitch | — |
| Inventory DEBUG flood | U7 log-volume scenario (`logs-elasticco.inventory-default`) | — |
| `elasticco-log-telemetry-gap` | U8 log silence on notification-service; Cases; badges APM map | **No** |

Retired name `elasticco-checkout-slo-burn` must stay **disabled** (renamed to correlated RCA).

Dashboards: `elasticco-incident-overview`, `elasticco-distributed-traces`, `elasticco-e2e-tracing`, `elasticco-eks-restarts`, `elasticco-log-rate`, `elasticco-telemetry-gap`.

---

## Pre-flight

- [ ] `python -m src.cli setup` — pipelines, templates, data views, native SLO, Agent Builder, Workflow, alerts
- [ ] `backfill --hours 6` — no FAILED lines
- [ ] `verify` — all `[ok]`, including hero `trace.id` correlation
- [ ] `verify --alerts` — rules exist and enabled; Cases + **Run Workflow** on correlated RCA + eks-restarts; firing; SLO present; `elasticco-rca-agent` tools; workflow enabled
- [ ] `elasticco-checkout-slo-burn` disabled
- [ ] Discover: structured `tenant.id` on orchestrator
- [ ] Inventory logs: `log.level: debug` + `log.logger: com.elasticco.inventory.SkuCache` in Last 2 hours (`verify` checks the flood)
- [ ] Notification logs: historical docs exist; **last 15m count = 0**; APM notification-service last 15m > 0 (`verify` checks the gap)
- [ ] E2E dashboard: seven hops + DB spans; acme-retail p95 outlier
- [ ] EKS Restarts: OOMKilled / BackOff; memory ~98% of 512 MiB; restart.count ≥ 1
- [ ] Agent Builder: test prompt returns **non-zero** acme-retail errors / slow DB (not 0%)
- [ ] **U4 / U5 / U6 / combined / 25-min / U7 / U8:** `stream --tick 60` in a side terminal. U1–U3 historical path does not need it. Stream also pins the U7 DEBUG window and U8 log silence through now.
- [ ] **Facilitator only:** `python -m src.cli incident --dry-run` prints RCA (non-zero exit if evidence is weak)
- [ ] Tabs pre-opened (see talk-track). Agent Builder **pre-warmed** for any path that includes U5.

---

## Room setup

**Always:** Last 2 hours · `labels.demo: elastic-co`.

| Path | Tabs |
|------|------|
| 25-min | Orchestrator Discover · Ingest pipeline · E2E Tracing · APM Services/map · EKS Restarts · Alerts · SLOs · Cases · Agent Builder |
| U2+U5 | APM Services/map or Alerts or SLOs · E2E Tracing · Agent Builder · Cases |
| U7 | Discover `elasticco-logs` · AIOps Labs → Log rate analysis · dashboard `elasticco-log-rate` · APM inventory |
| U8 | Alerts `elasticco-log-telemetry-gap` · Discover `elasticco-notification` · APM notification-service · dashboard `elasticco-telemetry-gap` |
| U6 | Workflows · Alerts (quality rule Actions) · Cases |

Agent Builder prompt (pre-warm):

> checkout-api is failing for acme-retail — reconstruct RCA and recommend one remediation.

Then, in chat: **approve rollback to v2.4.0**.

---

## Failure modes

| Symptom | Fix |
|---------|-----|
| Orchestrator missing `tenant.id` | Re-run `setup`; confirm index template `default_pipeline`; re-backfill `--scope orchestrator` |
| APM empty | Backfill `--scope apm`; API key must write `traces-apm-default` |
| Alerts not firing / RCA 0% errors | Incident window must cover **now**. Re-backfill; `stream --tick 60`. `verify --alerts` checks last-60m hits |
| Alert create 400 | Create `.es-query` rule from `kibana/alert-rules.json`. Omit `actionTypeId` on Serverless |
| Native SLO 403 | Soft-fail OK. Teach SLO vs correlation in the SLO app if the object exists |
| Agent Builder empty / 0% errors | Do not invent. Skip to open case + correlated RCA. Re-backfill + stream |
| Agent Builder 403 | `python -m src.cli agent` after Agent Builder is enabled on the project |
| Workflows 403 / missing | `python -m src.cli workflow`. If still 403, skip to U5 + Cases. No kubectl |
| Run Workflow missing on rule | Workflow must be **enabled** first; re-run `setup` (alerts after workflow) |
| Workflow does not start from alert | Quality alerts already active — **Manual Run**. `onActionGroupChange` only on first active |
| Inventory empty | Custom `metrics-elasticco.host-*` may not light Inventory. Skip; stay on EKS Restarts |
| AI Assistant vague (U4 opener) | Prompts in `kibana/ai-triage-prompts.md`; Last 2 hours; `labels.demo: elastic-co` |
| AIOps Labs 403 / missing | Dashboard `elasticco-log-rate` + Discover histogram. Still teach baseline vs deviation. |
| Log telemetry gap not firing | Last 15m notification logs must be 0 with a 2h baseline. Re-backfill `--scope app_logs`; `stream --tick 60`. Wait 1–2 min. Do not attach Run Workflow. |
| Notification APM also 0 | App looks down too. Re-backfill `--scope apm` or start stream. |
| CLI email not sent | Lab-only — connector/SMTP; or open `output/incident-emails/*.html` |

Narrow reloads: `--scope orchestrator` \| `apm` \| `apm_deps` \| `traces` \| `k8s` \| `infra` \| `app_logs`. `k8s` includes pod metrics plus host/node/APM-internal (`infra`). `app_logs` is U7 inventory DEBUG plus U8 notification silence.

---

## What we do **not** fake

| Surface | Stance |
|---------|--------|
| Universal Profiling | Talk only after `CartCache.retainAll`. Do not synthesize `profiling-*`. |
| Synthetics | Skip. No browser monitor in this demo. |
| Real EKS / kubectl | Fictional cluster. Close is a case comment, not a rollout. |

---

## Labs (optional after SE path)

Assume backfill is already loaded. Stream for anything that hits 60-minute alerts or Agent Builder tools.

| Lab | Use case |
|-----|----------|
| [01-orchestrator-structuring.md](01-orchestrator-structuring.md) | U1 |
| [02-trace-tenant-db.md](02-trace-tenant-db.md) | U2 |
| [02-05-trace-rca.md](02-05-trace-rca.md) | Combined U2 + U5 |
| [03-eks-restart-rca.md](03-eks-restart-rca.md) | U3 |
| [04-alerting-ai-triage.md](04-alerting-ai-triage.md) | U4 |
| [05-app-monitoring-rca.md](05-app-monitoring-rca.md) | U5 |
| [06-detect-remediate.md](06-detect-remediate.md) | U6 Workflow |
| [07-log-rate-analysis.md](07-log-rate-analysis.md) | U7 Log rate analysis |
| [08-log-telemetry-gap.md](08-log-telemetry-gap.md) | U8 Log telemetry gap |
| [07-slo-log-rate.md](07-slo-log-rate.md) | Combined U7 + native SLO |

---

## Presentations

Open in a browser. ← → navigate, F fullscreen.

| Deck | When |
|------|------|
| [scenario-walkthrough.html](../presentations/scenario-walkthrough.html) | Full-arc opener / lab map |
| [scenario-u2-u5.html](../presentations/scenario-u2-u5.html) | Combined traces + RCA |
| [scenario-u7-slo.html](../presentations/scenario-u7-slo.html) | Combined U7 + native SLO |
| [u1-elastic-components.html](../presentations/u1-elastic-components.html) | U1 |
| [u2-distributed-traces.html](../presentations/u2-distributed-traces.html) | U2 |
| [u3-eks-restart-rca.html](../presentations/u3-eks-restart-rca.html) | U3 |
| [u4-alerting-ai-triage.html](../presentations/u4-alerting-ai-triage.html) | U4 |
| [u5-app-monitoring-rca.html](../presentations/u5-app-monitoring-rca.html) | U5 |
| [u6-detect-to-remediate.html](../presentations/u6-detect-to-remediate.html) | U6 |
| [u7-log-rate-analysis.html](../presentations/u7-log-rate-analysis.html) | U7 |
| [u8-log-telemetry-gap.html](../presentations/u8-log-telemetry-gap.html) | U8 |

---

## Reset

Delete data streams if you need a clean slate:

```
logs-elasticco.orchestrator-default
logs-elasticco.checkout-default
logs-elasticco.inventory-default
logs-elasticco.notification-default
logs-elasticco.k8s.event-default
logs-elasticco.incident-default
metrics-elasticco.k8s.pod-default
```

Then `setup` + `backfill` again. Avoid deleting `traces-apm-default` on shared projects — filter with `labels.demo: elastic-co` instead.
