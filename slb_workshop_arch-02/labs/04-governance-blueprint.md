# Lab 4 — Governance blueprint

**Time:** ~20 minutes  
**Goal:** Leave with named deliverables and answers to the four questions on the last slide. This is the session. Labs 1–3 were evidence.

Deck format: 80% design review, 20% product evidence. Fill the files in `artifacts/` — do not ship empty templates.

## Collection model (operating model, not a feature matrix)

| Path | When SLB should allow it | What must exist on day one |
|---|---|---|
| Fleet-managed Elastic Agent | Central policy, health, versions required (shared infra, regulated collectors) | Fleet policies owned by platform; integration allow-list |
| EDOT-native / standalone | Team needs vendor-neutral collector config | External config governance: versioning, approval, promotion, audit |

Neither path is "the Elastic one." If a team is on EDOT-native and has no config promotion story, they do not have a collection standard — they have a snowflake.

SRE-01 already covered support boundaries (EDOT SDKs → Managed OTLP / Agent Gateway, not APM Server OTLP). Do not re-open that debate here. Write the **who** in [artifacts/collection-model-standard.md](../artifacts/collection-model-standard.md).

## Six artifacts

Complete these in order. Owners must be roles, not "the platform" in the abstract.

1. [retention-class-matrix.md](../artifacts/retention-class-matrix.md)
2. [dataset-namespace-taxonomy.md](../artifacts/dataset-namespace-taxonomy.md)
3. [schema-decision-policy.md](../artifacts/schema-decision-policy.md)
4. [collection-model-standard.md](../artifacts/collection-model-standard.md)
5. [template-ownership-model.md](../artifacts/template-ownership-model.md)
6. [exception-process.md](../artifacts/exception-process.md)

## Ownership split (from the deck)

**Central platform owns:** approved integrations, base component templates, retention classes, namespace/dataset standard, shared processors, schema guardrails, cross-team dashboards/SLO standards.

**Domain teams own:** instrumentation and OTel adoption, approved collector deployment, dashboards on **standard** fields, limited custom attributes under policy, exception requests, service SLOs, team alerts.

If a team dashboard requires a new field, that is an exception (artifact 6), not a local mapping fork.

## Four questions — take these forward

**Q1.** Who owns retention classes and exception approval — and does that match who should own them at 10x scale?

**Q2.** Should new telemetry default to OTel-native data streams, with ECS-compatible paths only for migration exceptions?

**Q3.** What should namespace represent at SLB: environment, team, region, or tenancy boundary?

**Q4.** What changes require central approval: new datasets, custom fields, template modifications, or new ingest pipelines?

Write the answers at the bottom of each artifact. If Q3 is not **environment**, change the workshop streams before the next session — do not leave two answers in production.

## Checkout

Each architect can state, without notes:

1. One retention class and its mechanism on Serverless vs hosted.
2. One field name that must not appear on an OTel-native stream.
3. One change they would have to file an exception for.
