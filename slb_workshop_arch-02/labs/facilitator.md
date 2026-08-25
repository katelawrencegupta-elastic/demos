# Facilitator notes — ARCH-02 workshop

**Session:** Lifecycle, Governance & Standards  
**Audience:** Architects  
**When:** Wed Sep 23, 2026 · 5:00 AM PST · 60 min classroom  
**Deck:** [SLB - Enablement - ARCH 02](https://docs.google.com/presentation/d/1fowlbV3TjGpYHDFuX1lVrsjyZmpJ8uC6/edit)

This repo is the hands-on companion (about 90 minutes if all four labs run). The deck format is **80% design review, 20% product evidence** — do not turn this into a Fleet click-through.

## Outcomes

Participants leave with:

- Four retention classes mapped to a lifecycle **mechanism** (DLM here, ILM on hosted) — not a pile of ILM settings.
- A schema rule: OTel-native by default for new telemetry; ECS only as a migration exception; mixed authoring prohibited on a given stream.
- A namespace decision on the table (working proposal: **environment**).
- Named owners for templates, datasets, and exceptions.

## Timing

**60-minute lecture** (deck on screen, no labs): [talk-track-60.md](talk-track-60.md)

| Block | Classroom (60 min) | Hands-on (90 min) |
|---|---|---|
| Why it matters + governance decisions | 8 min | — |
| Retention classes | 10 min | Lab 1, 25 min |
| Fleet vs EDOT operating model | 8 min | Fold into lab 4 |
| ECS ↔ OTel | 10 min | Lab 2, 25 min |
| Taxonomy + ownership | 8 min | Lab 3, 20 min |
| Artifacts + Q1–Q4 | 10 min | Lab 4, 20 min |
| Q&A | 6 min | remaining |

If time is short, **cut lab 3 CLI** and keep the namespace decision plus lab 2 `compare_schema.py`. Never cut the architect rule (policy before mechanism), mixed-authoring prohibition, or Q1–Q4.

## Before the room

```bash
.venv/bin/python scripts/ping.py
.venv/bin/python scripts/teardown.py
.venv/bin/python scripts/apply.py
.venv/bin/python scripts/ingest.py
.venv/bin/python scripts/verify.py
.venv/bin/python scripts/compare_schema.py
.venv/bin/python scripts/create_kibana.py
```

Confirm Kibana login on `https://klg-slb-workshop-arch02-939ab5.kb.us-central1.gcp.cloud.es.io`.

Do not paste API keys into slides or chat transcripts.

## Talking points from the deck (do not skip)

1. 5+ legacy tools already fragmented dashboards, schemas, and ownership — do not repeat this.
2. OTel/EDOT increases flexibility **and** the governance surface.
3. Don't define governance as "ILM settings." Define retention classes by value, cost, and compliance.
4. ECS and OTel are aligned, not unified. Metrics are a data-model gap, not a rename.
5. Uncontrolled dataset creation is the fastest path back to fragmentation.
6. Central platform owns guardrails; domain teams own instrumentation inside them.

## Known gotchas on this cluster

- This is **Elastic Cloud Hosted**, not Serverless. `GET _cluster/health` and ILM APIs work.
- Labs still attach **data stream lifecycle** per retention class. Treat ILM as the hosted mapping, not a second policy on the same stream unless you intend ILM to win.
- Do not PUT `configs/ilm/hosted-audit-hot-warm-cold-frozen.json` unless you mean to enable frozen searchable snapshots on this deployment.
- OTel docs are **intentionally** left untranslated. If someone "fixes" the pipeline by copying `body.text` → `message`, they have violated the mixed-authoring rule this lab exists to show.

## Reset

```bash
.venv/bin/python scripts/teardown.py
```
