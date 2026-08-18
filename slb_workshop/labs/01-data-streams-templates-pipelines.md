# Lab 1 — Data streams, index templates, ingest pipelines

**Time:** ~35 minutes  
**Goal:** Stand up one consistent platform-log stream instead of letting each team invent an index name.

The SRE-01 point is not that these APIs are hard. It is that **inconsistent use** across workstreams recreates the Prometheus/Grafana-era schema sprawl SLB is trying to leave behind.

Docs: [data streams](https://www.elastic.co/docs/manage-data/data-store/data-streams) · [templates](https://www.elastic.co/docs/manage-data/data-store/templates) · [ingest pipelines](https://www.elastic.co/docs/manage-data/ingest/transform-enrich/ingest-pipelines) · [Fleet naming scheme](https://www.elastic.co/docs/reference/fleet/data-streams)

## The four objects (and how they compose)

```text
ingest pipeline  →  attached as index.default_pipeline
component templates  →  reusable mappings + settings
index template  →  index_patterns + data_stream{} + composed_of + lifecycle
data stream  →  write alias over hidden backing indices (.ds-…)
```

Write requests go to the **data stream name**. Elasticsearch creates and rolls **backing indices**. You never write to `.ds-*` yourself.

Fleet integrations use the same idea with a naming scheme:

```text
<type>-<dataset>-<namespace>
logs-workshop.platform-default
```

Keep `type` / `dataset` / `namespace` stable across teams. Namespace is the knob for env, region, or business unit — not a new dataset per app team.

## 1. Apply the workshop objects

From the repo root:

```bash
.venv/bin/python scripts/apply.py
```

This PUTs, in order:

| Object | Name | File |
|---|---|---|
| Ingest pipeline | `logs-workshop.platform` | `configs/ingest-pipelines/logs-workshop.platform.json` |
| Component template | `logs-workshop.platform-mappings` | mappings (`@timestamp`, ECS-ish `service`, `log`, `http`) |
| Component template | `logs-workshop.platform-settings` | `index.default_pipeline` |
| Index template | `logs-workshop.platform` | pattern `logs-workshop.platform-*`, priority **500**, `data_stream: {}`, 7-day lifecycle |
| Data stream | `logs-workshop.platform-default` | created if missing |

Priority `500` beats the built-in `logs-*-*` template (priority `100`) so this workshop stream does not inherit a random generic mapping.

## 2. Simulate the pipeline before you write

The pipeline does two jobs that show up in every production log stream:

1. **JSON** `message` bodies are merged to the root (structured app logs).
2. **Grok** parses `TS LEVEL [service] message` lines (unstructured platform logs).
3. It then stamps `data_stream.*`, `event.dataset`, `event.ingested`, and `labels.workshop=sre-01`.

```bash
.venv/bin/python scripts/simulate_pipeline.py
```

Or in Kibana **Dev Tools**:

```http
POST _ingest/pipeline/logs-workshop.platform/_simulate
{
  "docs": [
    {
      "_source": {
        "message": "{\"service\":{\"name\":\"well-data-api\"},\"log\":{\"level\":\"ERROR\"},\"http\":{\"response\":{\"status_code\":500}},\"message\":\"survey lookup failed\"}"
      }
    },
    {
      "_source": {
        "message": "2026-08-17T14:03:44Z WARN [telemetry-gateway] retrying kafka produce topic=rig.metrics"
      }
    }
  ]
}
```

Confirm `service.name`, `log.level`, and `data_stream.dataset` are present on **both** docs. If a team skips this step and ships raw lines, Discover becomes unusable six months later.

## 3. Index sample traffic

```bash
.venv/bin/python scripts/ingest.py
.venv/bin/python scripts/verify.py
```

`ingest.py` writes mixed JSON and grok-able lines into `logs-workshop.platform-default` with `op_type=create` (required for data streams).

In Dev Tools:

```http
GET logs-workshop.platform-default/_data_stream

GET logs-workshop.platform-default/_search
{
  "size": 0,
  "aggs": {
    "services": { "terms": { "field": "service.name" } },
    "levels": { "terms": { "field": "log.level" } }
  }
}
```

Open **Discover** in Kibana on the `Workshop platform logs` data view, or run:

```bash
.venv/bin/python scripts/create_kibana.py
```

That script also publishes the starter dashboard **SRE-01 Workshop — Platform logs**:
https://klgslbworkshopsre01-cecd27.kb.us-central1.gcp.elastic.cloud/app/dashboards#/view/bb3f65fa-c3d7-4b09-8295-b9645c789de9

## 4. Look at backing indices and rollover

```http
GET _data_stream/logs-workshop.platform-default

POST logs-workshop.platform-default/_rollover
```

After rollover you still search the **stream name**. The write index is a new `.ds-logs-workshop.platform-default-...-000002`. That is the whole point: retention, force-merge, and (on hosted) tier moves happen on backing indices, not on the name your applications know.

## 5. What to copy into SLB conventions

- One dataset per signal shape (`workshop.platform`), not one index per microservice.
- Namespace for `prod` / `nonprod` / region — not a new template per team.
- Component templates for mappings vs settings so lifecycle and pipelines can change independently.
- Always attach parsing with `index.default_pipeline` (or Fleet `@custom` pipelines). Do not parse only in the collector **or** only in ES — pick a layer and make it the contract.
- Customization on Fleet streams belongs in `@custom` component templates and `@custom` pipelines, never by editing the integration's default pipeline.

## Optional Kibana path (no CLI)

**Stack Management → Ingest Pipelines → Create pipeline** using the processors in `configs/ingest-pipelines/logs-workshop.platform.json`.

**Stack Management → Index Management → Component Templates / Index Templates** with `data stream` enabled and the same priority.

Next: [Lab 2 — Data tiers vs data stream lifecycle](02-data-tiers-lifecycle.md)
