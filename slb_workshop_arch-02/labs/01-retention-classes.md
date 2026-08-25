# Lab 1 — Retention classes: policy first, mechanism second

**Time:** ~25 minutes  
**Goal:** Define four retention classes by data value, then attach a lifecycle **mechanism**. On this Serverless project that mechanism is data stream lifecycle. On hosted clusters it is ILM (or DLM with `frozen_after` in 9.5).

The ARCH-02 point is not that ILM JSON is hard. It is that **hardcoding one mechanism** (or copying SRE-01's 7-day workshop retention onto every stream) is not a platform design.

Docs: [data stream lifecycle](https://www.elastic.co/docs/manage-data/lifecycle/data-stream) · [ILM](https://www.elastic.co/docs/manage-data/lifecycle/index) · [migrate ILM → DLM](https://www.elastic.co/docs/manage-data/lifecycle/data-stream/tutorial-migrate-ilm-managed-data-stream-to-data-stream-lifecycle)

## Architect rule

> Don't define governance as "ILM settings." Define retention classes by data value, cost, and compliance need. Governance must cover **both** ILM and data stream lifecycle.

## The four classes on this project

| Class | Stream | DLM `data_retention` | Hosted mapping (do not PUT here) |
|---|---|---|---|
| Platform metrics | `metrics-workshop.platform-prod` | 7d | hot → delete 7d |
| Application logs | `logs-workshop.app-prod` | 30d | hot → warm 7d → delete 30d |
| Application logs (nonprod) | `logs-workshop.app-nonprod` | 14d | same policy, shorter delete |
| Audit / security | `logs-workshop.audit-prod` | 90d | hot → warm → cold → frozen → delete 365d |
| Traces (sampled) | `traces-workshop.app-prod` | 3d | hot → delete 3d |

90d audit is a **workshop stand-in** for a 1y+ compliance class. Serverless has no frozen tier; the hosted policy lives at `configs/ilm/hosted-audit-hot-warm-cold-frozen.json`.

## 1. Apply the classes

```bash
.venv/bin/python scripts/apply.py
.venv/bin/python scripts/ingest.py
.venv/bin/python scripts/verify.py
```

`apply.py` PUTs templates (each with a default `template.lifecycle.data_retention`) then sets **per-stream** lifecycle so `prod` and `nonprod` can differ without forking the dataset.

## 2. Inspect in Dev Tools

```http
GET _data_stream/metrics-workshop.platform-prod,logs-workshop.app-prod,logs-workshop.app-nonprod,logs-workshop.audit-prod,traces-workshop.app-prod/_lifecycle

GET _data_stream/logs-workshop.app-prod/_lifecycle/explain
```

You should see `enabled: true`, the retentions from the table, and backing indices `managed_by_lifecycle: true`.

This cluster has **no ILM**. This will 410/fail — that is the lesson, not an error in the lab:

```http
GET _ilm/policy
```

## 3. Change one class without touching mappings

Shorten nonprod logs to 7 days, then put them back. Lifecycle is not a mapping change.

```http
PUT _data_stream/logs-workshop.app-nonprod/_lifecycle
{
  "data_retention": "7d"
}

GET _data_stream/logs-workshop.app-nonprod/_lifecycle

PUT _data_stream/logs-workshop.app-nonprod/_lifecycle
{
  "data_retention": "14d"
}
```

## 4. Map to hosted (read-only)

Open `configs/ilm/README.md`. For a workstream that lands on **hosted** observability, do not copy these Serverless templates blindly. Attach ILM (or DLM `frozen_after` on Stack 9.5+) that matches restore SLAs for audit.

Fill the **mechanism** and **cost tier** columns in [artifacts/retention-class-matrix.md](../artifacts/retention-class-matrix.md).

## What to copy into SLB conventions

- Classes are named (metrics / app logs / audit / traces), not "the ILM policy from cluster A."
- Namespace can carry a **different retention** of the same dataset (`prod` 30d, `nonprod` 14d) without a new dataset.
- Platform owns the class matrix. Teams do not invent a fifth class in a ticket comment.

Next: [Lab 2 — ECS vs OTel](02-ecs-vs-otel.md)
