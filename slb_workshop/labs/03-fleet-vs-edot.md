# Lab 3 — Fleet-managed Elastic Agent vs EDOT collector

**Time:** ~35 minutes  
**Goal:** Run the same outcome (telemetry in Elasticsearch) two ways, and leave with a supportable choice per team — not a religious one.

Neither path is universally better. The SRE-01 brief is: **expect both to coexist**, and choose on operational ownership, flexibility, and support boundaries.

Docs: [Elastic OpenTelemetry](https://www.elastic.co/docs/reference/opentelemetry) · [EDOT / Elastic Agent](https://www.elastic.co/docs/reference/edot-collector) · [Agent as OTel Collector](https://www.elastic.co/docs/reference/fleet/elastic-agent-as-otel-collector) · [Managed OTLP](https://www.elastic.co/docs/reference/opentelemetry/managed-inputs/managed-otlp-endpoint) · [GitHub elastic/opentelemetry](https://github.com/elastic/opentelemetry)

## Two philosophies, one storage layer

```text
                    ┌─ Fleet policy ─ integrations ─ Beat receivers ─┐
App / host telemetry ┤                                                ├─ Elasticsearch
                    └─ OTLP ─ EDOT collector (otel mode) ─────────────┘
                              └─ Managed OTLP Endpoint (this project)
```

From Elastic Agent 9.2 onward, **Elastic Agent embeds an OTel Collector**. Classic integrations still emit **ECS** via Beat receivers and ingest pipelines. OTel-native receivers emit **OTLP/semantic conventions** into `*.otel-*` data streams and **bypass** those ingest pipelines.

Switching a team from one path to the other later is possible. It is not free: dashboards, parsing, ILM/lifecycle, and on-call runbooks all change.

## Support boundary (read this before anyone wires an SDK)

EDOT SDKs are supported **only** with:

1. **Elastic Agent in Gateway mode**, or
2. **Elastic Cloud Managed OTLP Endpoint** (Serverless and Elastic Cloud Hosted)

They are **not** supported against **APM Server’s OTLP intake**. Data may appear to ingest. Elastic will not support mapping, enrichment, or break/fix if it goes wrong.

On **this Serverless project**, the supported EDOT path is Managed OTLP (optional Gateway at the edge for extra processing). Self-managed / ECE / ECK have no Managed OTLP — those estates **must** run Agent Gateway.

Find the Managed OTLP URL: Elastic Cloud Console → project **Manage** → **OpenTelemetry** (or in-product **Add data → Applications → OpenTelemetry**). This workshop project is already set in `.env` as `ELASTIC_OTLP_ENDPOINT=https://my-observability-project-dce7f4.ingest.us-east-1.aws.elastic.cloud`.

## Comparison you can take to a workstream

| | Fleet-managed Elastic Agent | Standalone Agent | Agent in `otel` mode (EDOT Collector) | Upstream OTel Collector |
|---|---|---|---|---|
| Central policy push (Fleet) | Yes | No (can enroll later) | No (enrollment not supported) | No |
| Central monitoring in Fleet | Yes | Planned | Planned | Planned |
| Curated integrations, dashboards, `@custom` pipelines | Yes | Yes (local YAML) | OTel input packages (preview) / YAML | No auto asset install |
| Beat receivers (ECS) | Yes | Yes | Yes | No |
| Elastic Defend / Cloud Security | Yes | No | No | No |
| Config shape | Policy UI / API | `elastic-agent.yml` | OTel YAML (`receivers` / `processors` / `exporters`) | OTel YAML |
| Who owns rollout | Central platform team | Mix | App/platform team + their CM tool | App/platform team |

Source: [collector type comparison](https://www.elastic.co/docs/reference/fleet/elastic-agent-as-otel-collector#collector-comparison).

**Rule of thumb for SLB:**

- Central SRE owns host + security + packaged integrations → **Fleet-managed Agent**.
- App team already lives in OTel Collector YAML / Helm and wants vendor-neutral receivers → **EDOT in `otel` mode** (or Gateway + Managed OTLP).
- Do not point EDOT SDKs at APM Server OTLP.

## Path A — Fleet-managed Agent (Kibana)

The policy is the artifact; the binary is cattle. This workshop project already has policy **`sre-01-workshop`** (System integration, namespace `default`).

From the repo root (Docker required):

```bash
.venv/bin/python agents/enroll.py
```

That enrolls three containers (`aks-sre-01` .. `03`) into Fleet. They are **not** in `otel` mode — standalone Agent in otel mode cannot enroll.

1. Open Kibana → **Fleet** → **Agent policies** → `sre-01-workshop`.  
   Note the data streams Fleet will create (`metrics-system.*-default`, `logs-system.syslog-default`, …).
2. **Fleet → Agents** — wait until the three hosts are `Healthy`. Later policy edits roll out without SSH.
3. Confirm the new streams under **Fleet → Data streams**, then Discover.

Generate host syslog (ssh logins, sudo, useradd/groupadd) into the agent containers:

```bash
.venv/bin/python agents/syslog_factory.py sample --count 80
```

That appends classic `/var/log/secure` and `/var/log/messages` lines. Look in Discover at `logs-system.auth-*` and `logs-system.syslog-*`.

Optional: add an **OpenTelemetry** input package to the **same** policy (preview). That is how one agent runs Beat receivers and OTel receivers in one Collector process.

If you cannot run Docker in this session, walk the policy UI anyway — the operational lesson is **central push vs local YAML**, not the binary install.

## Path B — EDOT collector on your laptop (OTel YAML)

This is Elastic Agent in `otel` mode: [same distribution](https://www.elastic.co/docs/reference/edot-collector), **not** Fleet-managed. You own config management (git, Helm, Ansible).

From the repo root (Docker required):

```bash
mkdir -p edot/logs
docker compose --env-file .env -f edot/docker-compose.yml up
```

In another terminal, run the OTLP factory (logs + metrics + traces through the collector):

```bash
.venv/bin/python edot/factory.py sample --count 40
.venv/bin/python edot/factory.py stream --tick 2
```

The collector forwards to the **Managed OTLP Endpoint** (`ELASTIC_OTLP_ENDPOINT` in `.env`) — the supported EDOT path on this Serverless project.

The factory also emits host syslog (`sshd` accepted/failed logins, `sudo` commands, `useradd`/`groupadd`/`usermod`). Filter Discover on `service.name: rsyslog` or `event.action: ssh_login / sudo_command / user_add`. `--syslog-ratio 1` is syslog only.

To fall back to the Elasticsearch exporter instead, change the compose command to `--config=/etc/otel/otel-collector.yml`.

Search Kibana **Applications → Service Inventory** for `well-data-api`, `telemetry-gateway`, `identity-service`, and `rig-scheduler`. OTel-native documents land in streams such as `logs-workshop.otel-default` / `traces-*.otel-default` / `metrics-*.otel-default`, **not** in `logs-workshop.platform-default`. That is the operational non-equivalence: different streams, different mappings, different pipelines.

Side-by-side in Kibana: [SRE-01 Workshop — Agents vs EDOT](https://my-observability-project-dce7f4.kb.us-east-1.aws.elastic.cloud/app/dashboards#/view/c8f4e1a2-9b3d-4e6f-a7c0-1d2e3f4a5b6c) (recreate with `.venv/bin/python scripts/create_kibana.py`).

Stop the collector with `docker compose -f edot/docker-compose.yml down`.

## Path C — Factory of Elastic Agents (same signals, Agent as collector)

Same four services and the same logs / metrics / traces, but each **host** is an Elastic Agent in `otel` mode instead of one shared EDOT collector.

```bash
docker compose --env-file .env -f agents/docker-compose.otel.yml up -d
.venv/bin/python agents/factory.py sample --count 60
.venv/bin/python agents/factory.py stream --tick 2
```

Agents listen on `14318` / `15318` / `16318` and stamp `host.name` (`aks-sre-01` .. `03`) plus `telemetry.collector: elastic-agent`. Filter on that field in Discover to compare with Path B.

## What “not interchangeable” means in practice

| Concern | Fleet integrations | EDOT / OTel-native |
|---|---|---|
| Parsing | ES ingest pipelines + `@custom` | Collector processors; ES pipelines skipped for OTel-native |
| Schema | ECS | OTel semantic conventions (`*.otel-*` streams) |
| Upgrades | Fleet binary + package versions | Collector image / Helm chart you roll |
| Troubleshooting | Agent status in Fleet, integration docs | Collector logs, OTLP, exporter failures |
| Packaged assets | Dashboards on install | Content packages for Agent-ingested OTel; **not** for third-party collectors |

A team can run **both**: Fleet Agent on the node for system/security, EDOT SDK + Gateway/Managed OTLP for the application. That is a normal end state, not a failure to standardize.

## Check-out questions

1. Who owns config changes — a platform Fleet policy, or the app team’s Git repo?
2. Do they need Elastic Defend or other Fleet-only integrations?
3. Are they instrumenting with **EDOT SDKs**? If yes, Gateway or Managed OTLP is mandatory.
4. Are they willing to operate `*.otel-*` streams, or do they need ECS dashboards on day one?

Back to [Lab 1](01-data-streams-templates-pipelines.md) if you want to compare the ECS workshop stream with the OTel stream side by side in Discover.
