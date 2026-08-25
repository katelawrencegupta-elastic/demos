# Lab 2 — Data tiers (ILM) vs data stream lifecycle

**Time:** ~20 minutes  
**Goal:** Use the retention lever that actually exists on **this** project, and know what hot/warm/cold/frozen maps to on hosted clusters.

This workshop cluster is **Elasticsearch Serverless**. Serverless has **no data tiers** and **no ILM**. Retention is [data stream lifecycle](https://www.elastic.co/docs/manage-data/lifecycle/data-stream). ILM remains the tool on Elastic Cloud Hosted and self-managed. See [differences from other offerings](https://www.elastic.co/docs/deploy-manage/deploy/elastic-cloud/differences-from-other-elasticsearch-offerings).

## What “data tiers” means on hosted / self-managed

ILM moves backing indices through hardware-shaped phases as they age:

| Phase | Typical intent |
|---|---|
| **Hot** | Write + frequent query. Rollover on size/age. |
| **Warm** | Read-mostly. Often force-merge, fewer replicas. |
| **Cold** | Infrequent query, cheaper storage. |
| **Frozen** | Searchable snapshots; query is slower and cheaper. |
| **Delete** | Drop after retention. |

A reference policy lives at `configs/ilm/hosted-logs-hot-warm-cold.json` (7d warm / 30d cold / 90d frozen / 365d delete). **Do not PUT it on this cluster** — the ILM API is unavailable in Serverless.

On hosted, you attach ILM with `index.lifecycle.name` on the index template, **or** you use data stream lifecycle there too. If both exist, ILM wins unless `index.lifecycle.prefer_ilm` is `false`.

## What this Serverless project does instead

Data stream lifecycle is configured **on the data stream** (via the index template `template.lifecycle` block), not as a named cluster policy:

```json
"lifecycle": {
  "enabled": true,
  "data_retention": "7d"
}
```

`data_retention` is the **minimum** time data is kept. Elasticsearch may delete it later; it will not delete earlier. Rollover and tail-merge still happen in the background. Frozen searchable-snapshot transitions (`frozen_after`) are **not** available on Serverless.

Lab 1 already set 7-day retention on `logs-workshop.platform-default`. Inspect it:

```bash
.venv/bin/python scripts/verify.py
```

```http
GET _data_stream/logs-workshop.platform-default/_lifecycle

GET _data_stream/logs-workshop.platform-default/_lifecycle/explain
```

You should see `enabled: true`, `data_retention: 7d`, and backing indices `managed_by_lifecycle: true`.

## Change retention (the SRE move)

Shorten workshop data to 3 days — still via the **template**, then roll over so new backing indices pick up template changes. Lifecycle itself applies at the **data stream** level when you update it via API:

```http
PUT _data_stream/logs-workshop.platform-default/_lifecycle
{
  "data_retention": "3d"
}

GET _data_stream/logs-workshop.platform-default/_lifecycle
```

Put it back to 7 days when you are done so the shared project does not surprise the next session:

```http
PUT _data_stream/logs-workshop.platform-default/_lifecycle
{
  "data_retention": "7d"
}
```

Updating lifecycle does **not** require rebuilding mappings. That is why lab 1 split mappings and settings into component templates and left lifecycle on the index template / data stream.

## Mapping the two models for SLB

| Question | Serverless (this project) | Hosted / self-managed |
|---|---|---|
| How long do we keep logs? | `data_retention` | ILM `delete` phase **or** `data_retention` |
| How do we cut storage cost for old data? | Elastic manages hardware | Warm / cold / frozen tiers + searchable snapshots |
| How do we rollover? | Automatic (lifecycle) | ILM `rollover` action and/or data stream lifecycle |
| What do app teams name? | Data stream (`logs-…-…`) | Same — never the backing index |

If a workstream later lands on a **hosted** observability cluster, do not copy this Serverless template blindly. Add an ILM policy (or `frozen_after` on data stream lifecycle, Stack 9.5+) that matches their retention and restore SLAs.

## Kibana Streams (optional follow-on)

The enablement deck’s optional 60-minute **Streams** workshop is the productized version of this lab: partitioning, parsing, retention, and data quality from one UI. A stream in that UI **is** an Elasticsearch data stream (for example `logs-myapp-default`). Changes there write the same template/lifecycle objects you just managed via API.

Docs: [Streams](https://www.elastic.co/docs/solutions/observability/streams/streams)

Next: [Lab 3 — Fleet vs EDOT](03-fleet-vs-edot.md)
