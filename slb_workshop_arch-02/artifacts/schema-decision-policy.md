# Schema decision policy

**Owner (role):** platform architects  
**Workshop evidence:** `scripts/compare_schema.py`, lab 2

## Target state (working proposal)

New telemetry is **OTel-native**. ECS-compatible paths are **migration exceptions** only. Mixed authoring on one stream is **prohibited**.

| Signal | Canonical | Translation | Mixed authoring |
|---|---|---|---|
| New logs / traces | OTel (`body.text`, `severity_text`, `trace_id`, …) | query-time or dedicated pipeline when correlating with ECS | prohibited |
| Fleet integrations still on ECS | ECS (`message`, `log.level`, `trace.id`, …) | do not rewrite in-stream | prohibited |
| Metrics | one model per dataset | **not** field aliases — data-model gap | prohibited |

Equivalent-but-renamed pairs that **will** break dashboards if mixed:

- `trace.id` ↔ `trace_id`
- `span.id` ↔ `span_id`
- `message` ↔ `body.text`
- `log.level` ↔ `severity_text`

**Q2 answer:** _confirm or reject OTel-native as the default for new telemetry._
