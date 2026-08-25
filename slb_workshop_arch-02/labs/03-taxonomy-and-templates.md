# Lab 3 — Dataset / namespace taxonomy and template ownership

**Time:** ~20 minutes  
**Goal:** Make namespace mean one thing, stop unsanctioned datasets, and show the only approved way a team adds a field.

Uncontrolled dataset proliferation is the fastest path back to the 5-tool mess. Most teams skip this layer until Discover is unusable.

Docs: [OTel data streams](https://www.elastic.co/docs/reference/opentelemetry/data-streams) · [index / component templates](https://www.elastic.co/docs/manage-data/data-store/templates) · [Fleet naming](https://www.elastic.co/docs/reference/fleet/data-streams)

## The naming contract

```text
<type>-<dataset>-<namespace>
logs-workshop.app-prod
logs-workshop.app-nonprod
logs-workshop.app.otel-prod
```

| Part | Meaning in this workshop | Working proposal for SLB |
|---|---|---|
| `type` | `logs` / `metrics` / `traces` | same |
| `dataset` | signal **shape** (`workshop.app`, `workshop.audit`) | integration or bounded context — **not** one dataset per microservice |
| `namespace` | `prod` / `nonprod` | **environment**. If you pick team or region instead, write it down in lab 4 Q3 and change these streams |

If namespace becomes a dumping ground ("prod", "drilling", "us-east", "alice-test"), it has no governance value.

## 1. Central templates vs team extension

Platform owns:

- `arch02-ecs-mappings` / `arch02-otel-mappings` / `arch02-metrics-mappings` / `arch02-traces-mappings`
- index templates at priority **500+** so they beat built-in `logs-*-*` (100)

Domain teams extend **one** component template:

```text
logs-workshop.app@custom   →  slb.well_id
```

That field is on ECS app docs from `ingest.py`. It is **not** a fork of the base mapping.

```http
GET _component_template/logs-workshop.app@custom

GET _index_template/logs-workshop.app
```

Confirm `composed_of` includes the `@custom` template and `ignore_missing_component_templates` is set so a missing extension does not block ingest.

## 2. Namespace carries retention, not a new dataset

`logs-workshop.app-prod` (30d) and `logs-workshop.app-nonprod` (14d) share the dataset `workshop.app`. Lab 1 already set different DLM on the two streams.

```http
GET _data_stream/logs-workshop.app-prod,logs-workshop.app-nonprod/_lifecycle
```

A team that wants "drilling-prod-us" as a **dataset** is asking for a new shape. That is an exception (lab 4), not a namespace.

## 3. Unsanctioned dataset

`ingest.py` also writes `logs-rogue.drilling-prod` — no ARCH-02 template, no `labels.workshop`, fields `service_name` / `lvl` instead of the contract.

```http
GET _data_stream/logs-rogue.drilling-prod

GET logs-rogue.drilling-prod/_mapping
```

Compare with:

```http
GET logs-workshop.app-prod/_mapping
```

The rogue stream still "works." That is the failure mode: Elasticsearch will accept the write. Governance is the approval path that **prevents the stream from existing**, not a mapping that rejects it after the fact.

Fill [artifacts/dataset-namespace-taxonomy.md](../artifacts/dataset-namespace-taxonomy.md) and [artifacts/template-ownership-model.md](../artifacts/template-ownership-model.md).

Next: [Lab 4 — Governance blueprint](04-governance-blueprint.md)
