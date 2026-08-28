# Lab 01 — Orchestrator log structuring (U1)

**Goal:** Prove the grok pipeline turns free-text Airflow lines into `tenant.id` + `trace.id`.

## Steps

1. In Kibana → Stack Management → Ingest Pipelines → open `logs-elasticco.orchestrator`.
2. Copy one raw `message` from Discover (`elasticco-orchestrator`), e.g. a line containing `tenant=acme-retail`.
3. Dev Tools:

```http
POST _ingest/pipeline/logs-elasticco.orchestrator/_simulate
{
  "docs": [
    {
      "_source": {
        "@timestamp": "2026-08-26T14:10:00.000Z",
        "message": "PASTE_RAW_LINE_HERE",
        "service": { "name": "orchestrator" }
      }
    }
  ]
}
```

4. Confirm `tenant.id`, `trace.id`, `orchestrator.dag_id`, `orchestrator.task_id`, `log.level` in the simulate result.
5. **Stretch:** Change the grok pattern so `order=` becomes `order.id` still — break it on purpose, simulate, then restore from `configs/ingest-pipelines/logs-elasticco.orchestrator.json` and `python -m src.cli setup`.

## Done when

You can explain why Discover filters on `tenant.id` only work *after* the pipeline, and how `@custom`-style ownership protects upgrade-safe parsing.
