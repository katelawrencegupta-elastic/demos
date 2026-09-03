# Lab 06 — Detection through remediation (Kibana Workflows)

**Goal:** Show one Kibana Workflow that stitches Alerting → Elasticsearch ES|QL → Agent Builder → Cases, ending in a recommended rollback to checkout-api **v2.4.0**.

**Deck:** [../presentations/u6-detect-to-remediate.html](../presentations/u6-detect-to-remediate.html)  
**Full-arc visual:** [../presentations/scenario-walkthrough.html](../presentations/scenario-walkthrough.html)

This is the automated path for the same planted incident as U3–U5. It does **not** kubectl. Human approval stays in the case.

## Objects

| Product | Object | Job |
|---------|--------|-----|
| Alerting | `elasticco-eks-pod-restarts`, `elasticco-checkout-correlated-rca` | Detect; **Run Workflow** on first active |
| SLOs | `elasticco-slo-checkout-availability` | What you **page** on — not the workflow trigger |
| Workflows | `elasticco-detect-remediate` | Stitch |
| Elasticsearch | `elasticsearch.esql.query` × 3 | OOM / FOR UPDATE / tenant p95 |
| Agent Builder | `elasticco-rca-agent` | RCA (not `elastic-ai-agent`) |
| Cases | Observability case | Audit + rollback comment |

## Walkthrough

1. Analytics → **Workflows** → **Elastic Co. detect-to-remediate** (`elasticco-detect-remediate`). Confirm **enabled**.
2. Optional: **Run** (manual trigger) so you do not wait for an alert-state change.
3. Walk the execution: `query_oom` → `query_slow_db` → `query_tenant_p95` → `rca_analysis` → `create_case` → comments.
4. Observability → **Cases** — open the workflow-created case. Point at the **Recommended remediation** comment (v2.4.1 → v2.4.0).
5. Alerts → `elasticco-eks-pod-restarts` (or correlated RCA): Actions include Cases **and** Run Workflow. Remind: `triggers: alert` in YAML is not enough without this attachment.

**Line:** Detect in Alerting, enrich in Elasticsearch, reason in Agent Builder, track in Cases — Workflows is the stitch, not a second observability product.

**Skip if Workflows 403:** stay on U5 Agent Builder + the existing Cases action. Do not invent a kubectl step.

**YAML:** [../kibana/workflow-detect-remediate.yaml](../kibana/workflow-detect-remediate.yaml)
