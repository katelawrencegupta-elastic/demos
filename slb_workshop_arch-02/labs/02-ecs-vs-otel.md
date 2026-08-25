# Lab 2 — ECS vs OTel: aligned, not unified

**Time:** ~25 minutes  
**Goal:** Watch the same well-data incident exist in two schemas, and watch a cross-schema query miss. Then write the rule for where translation is required and where mixed authoring is prohibited.

9.5 alignment **increases** the need for a standard. Convergence is not unification.

Docs: [ECS ↔ OTel alignment overview](https://www.elastic.co/docs/reference/ecs/ecs-otel-alignment-overview) · [alignment details](https://www.elastic.co/docs/reference/ecs/ecs-otel-alignment-details) · [ECS and OpenTelemetry](https://www.elastic.co/docs/reference/ecs/ecs-opentelemetry)

## The four buckets (from the deck)

| Bucket | Example | What breaks |
|---|---|---|
| Clean mappings | many resource attributes ↔ ECS field sets | Usually nothing if you pick one and alias |
| Equivalent but renamed | `trace.id` ↔ `trace_id`, `message` ↔ `body.text`, `log.level` ↔ `severity_text` | Discover, dashboards, alerting |
| Related / translation required | overlapping semantics that are not identical | Aliasing **lies** |
| Metrics data-model gap | OTel metrics ≠ ECS metrics structurally | Cannot be solved by renaming fields |

This lab proves bucket 2 with product evidence. Bucket 4 is a **governance** statement: do not promise a global field alias for metrics.

## 1. The same incident, twice

`scripts/ingest.py` writes one failed `GET /v2/wells/8321/surveys` as:

- ECS → `logs-workshop.app-prod` with `trace.id`, `message`, `log.level`, `service.name`
- OTel-native → `logs-workshop.app.otel-prod` with `trace_id`, `body.text`, `severity_text`, `resource.attributes.service.name`

The OTel pipeline **does not** copy fields into ECS names. If you add that copy, you have mixed authoring on the OTel stream and this lab is void.

```bash
.venv/bin/python scripts/compare_schema.py
```

Expected: hits on the native field, **zero** hits on the cross-schema field.

## 2. Prove it in Dev Tools

Trace id: `4bf92f3577b34da6a3ce929d0e0e4736`

```http
GET logs-workshop.app-prod/_search
{
  "query": { "term": { "trace.id": "4bf92f3577b34da6a3ce929d0e0e4736" } }
}

GET logs-workshop.app-prod/_search
{
  "query": { "term": { "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736" } }
}

GET logs-workshop.app.otel-prod/_search
{
  "query": { "term": { "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736" } }
}

GET logs-workshop.app.otel-prod/_search
{
  "query": { "term": { "trace.id": "4bf92f3577b34da6a3ce929d0e0e4736" } }
}
```

Second and fourth requests are empty. That is a platform incident waiting to happen the first time a dashboard author mixes conventions.

In Kibana Discover:

- Data view **ARCH-02 ECS app logs** — filter `trace.id: 4bf92f3577b34da6a3ce929d0e0e4736`
- Data view **ARCH-02 OTel app logs** — the same KQL on `trace.id` misses; use `trace_id`

## 3. What translation is allowed

| Signal | Target-state (working proposal) | Exception |
|---|---|---|
| New app logs / traces | OTel-native streams (`*.otel-*` or OTel fielding) | ECS only while a Fleet integration is still the source of truth |
| Fleet System / existing integrations | ECS | do not rewrite to OTel in the same stream |
| Metrics | Pick **one** model per dataset | no global alias layer |
| Cross-signal correlation | Translate at query or in a dedicated correlation pipeline, not by dual-writing both names onto every doc | |

**Prohibited:** a single data stream that accepts both `log.level` and `severity_text` as author-time fields.

Fill [artifacts/schema-decision-policy.md](../artifacts/schema-decision-policy.md).

## Architect takeaway

Standardize where translation is allowed, where canonical fielding is required, and where mixed schema authoring is prohibited. 9.5 alignment docs are the dictionary — they are not the policy.

Next: [Lab 3 — Taxonomy and templates](03-taxonomy-and-templates.md)
