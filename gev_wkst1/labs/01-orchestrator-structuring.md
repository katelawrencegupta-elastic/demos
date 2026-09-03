# Lab 01 — Orchestrator log structuring (U1)

**Goal:** On-call filters `tenant.id` and clicks into APM — no regex in Discover. Parsing is how correlation becomes a click, not a scavenger hunt.

**Deck:** [../presentations/u1-elastic-components.html](../presentations/u1-elastic-components.html)

**Tabs:** Discover (`elasticco-orchestrator`) · Stack Management → Ingest Pipelines · APM (leave closed until the click)

Airflow-style orchestrator lines arrive as free text. Elasticsearch ingest pipelines parse them into ECS keyword fields **at write time**. Kibana Discover then filters on `tenant.id` and `trace.id` without regex.

## Elastic resources (U1)

| Component | Resource id | Role | Where |
|-----------|-------------|------|--------|
| Ingest pipeline | `logs-elasticco.orchestrator` | Grok + ECS enrichment | Stack Management → Ingest Pipelines |
| Component template | `logs-elasticco.orchestrator` | Keyword mappings + `default_pipeline` | Index Management |
| Index template | `logs-elasticco.orchestrator` | Routes `logs-elasticco.orchestrator-*` to a data stream | Index Management |
| Data stream | `logs-elasticco.orchestrator-default` | Structured log storage | Index Management → Data Streams |
| Data view | `elasticco-orchestrator` | `logs-elasticco.orchestrator-*` | Discover |
| Saved object | `elasticco-orchestrator` | Index-pattern NDJSON | `api/saved_objects/_import` |

Ingest path: **Elasticsearch** (bulk) → **index template** → **ingest pipeline** (on every write) → **data stream** → **data view** → **Discover**.

## Walkthrough

1. Discover → data view **Elastic Co. Orchestrator Logs**. Time range **Last 2 hours**. Filter `labels.demo: elastic-co` if the view is empty. Open one document. Point at `message` — Airflow-style free text. Ask: “Find every error for `acme-retail`.” Without fields, that is a grep problem.
2. Stack Management → Ingest Pipelines → `logs-elasticco.orchestrator`. Show grok extracting `tenant.id`, `trace.id`, `orchestrator.dag_id`, `orchestrator.task_id`, `log.level`, `order.id`. Optional: deck **▶ Run pipeline demo** (8 processors: set → grok → fallback grok → date → lowercase → data_stream / event fields).
3. Optional simulate (Dev Tools, or deck **Copy simulate query**):

```http
POST _ingest/pipeline/logs-elasticco.orchestrator/_simulate
{
  "docs": [{
    "_source": {
      "@timestamp": "2026-08-26T18:22:00.120Z",
      "message": "2026-08-26T18:22:00.120Z [fulfillment.checkout] charge_payment tenant=acme-retail order=ord-59c78d11 trace_id=271f8e318871ab12 ERROR: Task failed after checkout-api timeout; scheduling retry attempt=3",
      "service": { "name": "orchestrator" }
    }
  }]
}
```

Confirm `tenant.id`, `trace.id`, `orchestrator.dag_id`, `orchestrator.task_id` on the simulate result. `event.original` keeps the raw line.
4. Component template `logs-elasticco.orchestrator`: those fields are **keyword** so Discover can filter them. `message` is `match_only_text` (task detail after grok). `default_pipeline` is what attaches the grok to every write — the pipeline does not run because someone opened Discover.
5. Back to Discover. Filter `tenant.id: acme-retail and log.level: error` (or `warning`). Open a doc. Click **`trace.id`**.
6. Land in APM (or promise the waterfall). Same `trace.id` exists on `traces-apm-default`. That is U2 — do not reset the story.

**Line:** Parsing is not vanity — it is how correlation becomes a click, not a scavenger hunt.

**Skip if late:** skip pipeline UI and Dev Tools. Assert `tenant.id` and `trace.id` exist on a structured doc, filter, click `trace.id`.

**Next:** [Lab 02 — seven-hop trace + tenant + FOR UPDATE](02-trace-tenant-db.md)
