# SRE-01 talk track — 45 minutes

**Session:** Platform Operations Fundamentals (lecture, not the 90-minute labs)  
**When:** Wed 19 Aug 2026 · SRE-01  
**Visual:** keep [Agent vs OTel: ingest to Lucene shards](../agent-vs-otel-ingest-to-disk.pdf) on screen the whole time. Walk left to right.  
**Live cluster:** Serverless project `my-observability-project-dce7f4`

This is a **talk**. Do not start Docker, `apply.py`, or enroll agents unless a question forces a 30-second Kibana glance. Hands-on lives in labs 1–3.

| Clock | Block | Minutes |
|---|---|---|
| 0:00 | Open — two paths, one disk | 3 |
| 3:00 | Path through Elastic (stages 1–8) | 18 |
| 21:00 | Fleet / Agent vs OTel / EDOT | 14 |
| 35:00 | What people miss | 7 |
| 42:00 | Close + checkout questions | 3 |

**If you are over time, cut in this order:** Kibana Streams, TSDS 2-hour look-back, Lab 1 processor walk. **Never cut:** stages 4–7, the EDOT ≠ APM Server OTLP line, “switching is allowed and not free.”

**Props (optional, 20 seconds each):**

- [Platform logs dashboard](https://my-observability-project-dce7f4.kb.us-east-1.aws.elastic.cloud/app/dashboards#/view/bb3f65fa-c3d7-4b09-8295-b9645c789de9)
- [Agents vs EDOT dashboard](https://my-observability-project-dce7f4.kb.us-east-1.aws.elastic.cloud/app/dashboards#/view/c8f4e1a2-9b3d-4e6f-a7c0-1d2e3f4a5b6c)
- Fleet → Agents (`aks-sre-01` .. `03` on policy `sre-01-workshop`)
- Dev Tools: `GET _data_stream/logs-workshop.platform-default`

Do not paste API keys.

---

## 0:00–3:00 · Open

**Thesis (say this almost verbatim):**  
The APIs are not the hard part. Inconsistent use of streams, templates, and pipelines across workstreams recreates the Prometheus/Grafana-era schema sprawl we are trying to leave. Two ingest philosophies both land in the same Elasticsearch storage layer. Choose on **ownership and schema**, not vendor preference. Expect **coexistence**.

**Point at the diagram:**

- Left to right is **time**, not two clusters.
- The fork is **who owns config** and **which document contract** hits Lucene.
- Writes go to a **data stream name**. Elasticsearch creates hidden backing indices. Lucene segments in the **write** backing index are what sit on disk.

**Promise the room:** by minute 42 they can explain, for any document, which pipeline (if any) ran, which template matched, which stream it joined, and which generation is receiving writes — and they can pick Fleet vs EDOT without a religious argument.

---

## 3:00–21:00 · Path through Elastic

Walk the eight stages. Spend the time on **4–7**. Stages 1–3 set the fork; stage 8 is the landing.

### Stages 1–3 · Origin → shipper → intake (3:00–5:00)

| Stage | Agent lane | OTel lane | Line to say |
|---|---|---|---|
| 1 Origin | `/var/log/secure` and `/var/log/messages` on `aks-sre-01..03` | Apps + factory: OTLP logs, metrics, traces (`well-data-api` and siblings) | Same business signals can start as files or as OTLP. |
| 2 Shipper | Elastic Agent, Fleet policy `sre-01-workshop`, System integration, Beat receivers, **ECS** | EDOT collector: Agent in `otel` mode, OTLP `:4317`/`:4318` | Same binary family. Two operating models. |
| 3 Intake | Fleet Server → bulk index to Elasticsearch | **Managed OTLP** `….ingest.us-east-1.aws.elastic.cloud` — **not** APM Server OTLP | Flag this. You will land the support boundary in part 2. Do not debate it here. |

**One sentence:** after stage 3 the packet is inside Elastic. Everything from here is cluster objects you can name.

### Stage 4 · Ingest pipeline (5:00–9:00)

**Say:** the pipeline is a named processor chain. It runs **after** the document is accepted and **before** Lucene stores it — if the backing index has `index.default_pipeline` set.

**Agent lane:** Fleet integrations ship the contract. On this project:

- `logs-system.auth-2.22.4`
- `logs-system.syslog-2.22.4`
- `metrics-system.cpu-2.22.4` / `metrics-system.memory-2.22.4`

An auth line becomes `event.action`, `process.name`, `user.name` **before** the shard sees it. That is why Discover on System streams looks like Elastic, not like `/var/log/secure`.

**OTel lane:** OTel-native docs **skip those ECS pipelines**. Logs get `logs@default-pipeline` only. Traces and OTel metrics have **no** `default_pipeline`. The mapping **is** the contract.

**Lab 1 as the teachable object** (you can PUT this yourself). Pipeline `logs-workshop.platform`:

1. Stamp `event.ingested`.
2. If `message` looks like JSON → merge to root.
3. Else grok `TS LEVEL [service] message`.
4. Stamp `data_stream.type/dataset/namespace`, `event.dataset`, `labels.workshop=sre-01`.

**Line:** pick a parsing layer and make it the contract. Do not parse only in the collector **or** only in ES with no owner. Simulate (`_simulate`) before the first write. If a team skips this, Discover is unusable six months later.

**Customization:** on Fleet streams, changes belong in `@custom` pipelines and `@custom` component templates. Never edit the integration’s default pipeline — the next package upgrade overwrites you.

### Stage 5 · Template match (9:00–13:00)

**Say:** an index template is the **match rule** plus composition. It is not the index.

Four objects, in the order they compose:

```text
ingest pipeline        → attached as index.default_pipeline (usually via a settings component)
component templates    → reusable mappings + settings
index template         → index_patterns + data_stream{} + composed_of + lifecycle
data stream            → write alias over hidden backing indices (.ds-…)
```

**Lab 1 names to put on the whiteboard:**

| Object | Name | Why it exists |
|---|---|---|
| Pipeline | `logs-workshop.platform` | Parse JSON or grok, then stamp dataset |
| Component | `logs-workshop.platform-mappings` | `@timestamp`, ECS-ish `service` / `log` / `http` |
| Component | `logs-workshop.platform-settings` | `index.default_pipeline` |
| Index template | `logs-workshop.platform` | Pattern `logs-workshop.platform-*`, **priority 500**, `data_stream: {}`, 7-day lifecycle |

**Priority:** `500` beats the built-in `logs-*-*` template at priority `100`. Without that, the workshop stream inherits a generic mapping and the lab looks “broken.”

**Split mappings vs settings** so lifecycle and pipelines can change without rebuilding field types.

**Agent lane:** integration templates, Fleet naming `<type>-<dataset>-<namespace>` → `logs-system.auth-default`.

**OTel lane:** `logs-*.otel-*`, `metrics-otel@template`, `traces-*.otel-*`. Different patterns, different mappings, same template *mechanism*.

**Convention to copy:** one dataset per **signal shape** (`workshop.platform`), not one index per microservice. Namespace is the knob for env / region / BU — not a new dataset per app team.

### Stages 6–7 · Data stream and backing index (13:00–18:00)

**Say:** applications write the **stream name**. Elasticsearch creates and rolls **backing indices**. You never write to `.ds-*` yourself. Data-stream writes use `op_type=create`.

**This project after rollover:**

| Path | Stream | Pipeline | Mode | Write gen |
|---|---|---|---|---|
| Agent | `logs-system.auth-default` | `logs-system.auth-2.22.4` | logsdb | 000001 |
| Agent | `logs-system.syslog-default` | `logs-system.syslog-2.22.4` | logsdb | 000001 |
| Agent | `metrics-system.cpu-default` | `metrics-system.cpu-2.22.4` | time_series | 000001 |
| OTel | `logs-workshop.otel.otel-default` | `logs@default-pipeline` | logsdb | 000002 |
| OTel | `traces-workshop.otel.otel-default` | — | logsdb | 000002 |
| OTel | `metrics-workshop.otel.otel-default` | — | time_series | 000001 |
| Lab 1 | `logs-workshop.platform-default` | `logs-workshop.platform` | logsdb | 000002 |

**Rollover:** `POST <stream>/_rollover` freezes the current generation and opens the next. Search still hits the **stream name**. Retention, force-merge, and (on hosted) tier moves happen on backing indices, not on the name apps know.

**Optional 15-second Dev Tools:** `GET _data_stream/logs-workshop.platform-default` — point at `indices[].index_name` and which one is the write index.

**Line:** “generation 000001 is history; 000002 is the write index” is the whole operational idea.

### Stage 8 · On disk (18:00–21:00)

**Say:** a backing index is still Lucene shards. Serverless **does not expose** `_cat/shards`, `_stats` shard counts, or `index.number_of_shards`. Do not set shard or replica counts in templates here. The write index receives new documents; segments land there.

**Index modes on this project:**

- Logs and traces → **logsdb**
- Metrics → **time_series** (TSDS), keyed on dimensions + `@timestamp`

**Third writer:** `scripts/ingest.py` is not Agent and not OTel. It bulk-indexes `logs-workshop.platform-default` with pipeline `logs-workshop.platform`. Same landing: stream → `.ds-…-000002` → logsdb shards. Use that when someone asks “do we have to use a collector?”

**Close part 1:** both lanes resolve a template, attach to a stream, flush Lucene into the current write backing index. The fork was ownership and schema. The disk abstraction is the same.

---

## 21:00–35:00 · Elastic Agent & Fleet vs OTel / EDOT

**Frame:** from Agent 9.2 onward, Elastic Agent **embeds** an OTel Collector. This workshop runs **Fleet-managed Agent** (System integration, ECS) beside **Agent in `otel` mode** (the EDOT collector). Same distribution, two philosophies.

There are actually **four** collector types. Do not collapse them to “Agent vs OTel”:

| | Fleet-managed Agent | Standalone Agent | Agent in `otel` mode (EDOT) | Upstream OTel Collector |
|---|---|---|---|---|
| Central policy push | Yes | No (can enroll later) | **No — cannot enroll** | No |
| Central monitoring in Fleet | Yes | Planned | Planned | Planned |
| Curated integrations / dashboards / `@custom` | Yes | Yes (local YAML) | OTel input packages (preview) / YAML | No auto asset install |
| Beat receivers (ECS) | Yes | Yes | Available on the binary; this lab does not use them | No |
| Elastic Defend / Cloud Security | Yes | No | No | No |
| Config artifact | Fleet policy (UI / API) | `elastic-agent.yml` | OTel YAML | OTel YAML |
| Who owns rollout | Central SRE / platform | Mix | App or platform + their CM tool | App / platform |

**This room’s two implementations:**

- Path A: policy `sre-01-workshop`, hosts `aks-sre-01..03`, System integration, Beat receivers, ECS pipelines, streams `logs-system.*-default` / `metrics-system.*-default`. Intake: Fleet Server → ES bulk.
- Path B: EDOT container, OTLP 4317/4318, Managed OTLP, OTel semantic conventions, streams `*.otel-*`. Intake: `https://my-observability-project-dce7f4.ingest.us-east-1.aws.elastic.cloud`.

Path C in the lab (Agent in `otel` mode per host) is the same OTel contract with `host.name` stamped. Mention only if asked.

### Features that actually differ (24:00–28:00)

Walk the feature table on the diagram. Hit these hard:

- **Host logs/metrics:** Fleet System integration yes. EDOT only if you configure `filelog` / `hostmetrics`; this lab uses app OTLP + syslog via OTel.
- **Distributed traces:** not on the System integration. Yes on EDOT (`traces-*.otel-*`).
- **Document schema:** ECS (`event.action`, `host.name`, `system.cpu.*`) vs OTel (`resource.attributes`, `severity_text`). **Dashboards cannot share fields.** That is why Agents vs EDOT is a comparison dashboard, not one chart.
- **Security:** Elastic Defend is Fleet-only. If a workstream needs it, the node runs Fleet-managed Agent regardless of how the app is instrumented.

**Optional glance:** Agents vs EDOT dashboard — two columns, two schemas, same time range.

### Support boundary — do not skip (28:00–32:00)

**Say this almost verbatim:**

EDOT SDKs are supported **only** with (1) Elastic Agent in **Gateway** mode, or (2) Elastic Cloud **Managed OTLP Endpoint**. They are **not** supported against **APM Server’s OTLP intake**. Data may appear to ingest. Elastic will not support mapping, enrichment, or break/fix if it goes wrong.

On **this Serverless project**, the supported EDOT path is Managed OTLP. Self-managed / ECE / ECK have no Managed OTLP — those estates **must** run Agent Gateway.

Find the URL: Cloud Console → project Manage → OpenTelemetry (or Add data → Applications → OpenTelemetry). Ours is already `ELASTIC_OTLP_ENDPOINT`.

Stay on this slide. Do not debate “but it worked in a POC.”

### Rule of thumb + switching cost (32:00–35:00)

- Central SRE owns **host, security, packaged integrations** → **Fleet-managed Agent**.
- App team already lives in **OTel Collector YAML / Helm** → **EDOT in `otel` mode** (Managed OTLP here).
- A team can run **both**: Fleet Agent on the node for system/security, EDOT SDK + Managed OTLP for the app. That is a **normal end state**, not a failure to standardize.
- Switching later is **allowed**. It is **not free**: dashboards, parsing, lifecycle, and on-call runbooks all change. New streams, new mappings, new pages.

**Operational non-equivalence:** OTel-native documents will **not** land in `logs-workshop.platform-default`. Different streams, different mappings, different pipelines — same disk abstraction underneath.

---

## 35:00–42:00 · What you might have missed

These are the traps that show up in the next architecture review if you only remember “streams and Fleet vs OTel.”

### 1. Retention is a different product on this cluster (90 s)

This project is **Serverless**. There are **no data tiers** and **no ILM**. Retention is **data stream lifecycle** (`data_retention: 7d` on the Lab 1 template). `data_retention` is the **minimum** time data is kept — Elasticsearch will not delete earlier; it may delete later.

On hosted / self-managed: ILM hot → warm → cold → frozen → delete, or data stream lifecycle there too. If both exist, **ILM wins** unless `index.lifecycle.prefer_ilm` is `false`. Do not copy this Serverless template blindly onto a hosted observability cluster.

`GET _cluster/health` returns **410** here. Use `scripts/ping.py` / `GET /`.

### 2. TSDS is not a 3-day metrics store (60 s)

OTel metrics on this project are time-series with about a **2-hour look-back**. A 3-day metric backfill is rejected into the failure store. If someone says “we backfilled metrics like logs,” they are describing a different index mode. Logs/traces backfill; metrics do not, not like that.

### 3. Search the stream, never `.ds-*` (30 s)

Runbooks that hard-code backing index names break on the next rollover. Discover, alerts, and dashboards use the stream (or a data view on the stream pattern).

### 4. `@custom` or you will lose the next upgrade (45 s)

Fleet package upgrades replace the **default** integration pipeline. Platform parsing that must survive upgrades lives in `@custom` pipelines / component templates. Same idea as splitting Lab 1 mappings vs settings.

### 5. Kibana Streams is the same objects with a product UI (45 s)

The optional Streams workshop is this lab productized: partitioning, parsing, retention, data quality. A stream in that UI **is** an Elasticsearch data stream (for example `logs-myapp-default`). Changes there write the same template/lifecycle objects you just named.

### 6. Four writers, not two (45 s)

1. Lab 1 bulk (`ingest.py`) → `logs-workshop.platform-default`
2. Fleet Agent System integration → `logs-system.*` / `metrics-system.*`
3. EDOT / Managed OTLP → `*.otel-*`
4. (Optional) Agent in `otel` mode per host — still the OTel contract

If you only compare “Agent vs OTel” you miss the **platform log convention** workstream that does not need a collector at all.

### 7. Consistency checklist to copy into SLB (60 s)

- Stable `type` / `dataset` / `namespace` across teams
- One dataset per signal shape; namespace for env/region
- Component templates so mappings, settings, and lifecycle change independently
- Named pipeline as the parse contract (or an explicit decision that OTel mapping is the contract)
- Template priority high enough to beat `logs-*-*`
- Retention lever that matches the **deployment** (DSL here, ILM on hosted)
- Do not set `number_of_shards` on Serverless

---

## 42:00–45:00 · Close

**Restate:** two philosophies, one Lucene landing. Pipeline is the Agent/ECS contract; mapping is the OTel contract. Fleet vs EDOT is an operating-model choice. EDOT SDKs go to Managed OTLP or Gateway — never APM Server OTLP. Coexistence is expected. Switching is allowed and not free.

**Checkout questions (leave these on the last slide):**

1. Who owns config changes — a platform Fleet policy, or the app team’s Git repo?
2. Do they need Elastic Defend or other Fleet-only integrations?
3. Are they instrumenting with **EDOT SDKs**? If yes, Gateway or Managed OTLP is mandatory.
4. Are they willing to operate `*.otel-*` streams, or do they need ECS dashboards on day one?
5. Can they name, for their write path: pipeline, template, stream, write generation?

**Where to go next:** labs 1–3 in this repo. Must-run if time is short later: Lab 1 `apply.py` / `ingest.py`. Cut Docker before you cut the support-boundary slide.

---

## Timeboxed demo script (only if someone asks “show me”)

Keep each under 30 seconds. Skip if the room is with you.

1. Dev Tools: `GET _data_stream/logs-workshop.platform-default` — write index `000002`.
2. Dev Tools: `GET logs-workshop.platform-default/_lifecycle` — `data_retention: 7d`.
3. Fleet → Agents — three healthy, policy `sre-01-workshop`.
4. Discover: `event.action` on `logs-system.auth-*` vs `severity_text` / `resource.attributes` on `logs-*.otel-*`.
5. Dashboard Agents vs EDOT — two schemas, one project.

```http
GET _data_stream/logs-workshop.platform-default
GET _data_stream/logs-workshop.platform-default/_lifecycle
POST _ingest/pipeline/logs-workshop.platform/_simulate
{
  "docs": [{ "_source": { "message": "2026-08-17T14:03:44Z WARN [telemetry-gateway] retrying kafka produce topic=rig.metrics" } }]
}
```
