# ELK Co FinOps & LLM Observability Demo

Synthetic (and optional live) multi-cloud FinOps + LLM observability for
**Elastic Cloud Serverless**. One deterministic world model (**ELK Co**) feeds
native Elastic integration data streams so out-of-the-box Kibana dashboards,
Discover, SLOs, alerts, Agent Builder, and (on AWS live) workflows work against
correlated spend, security, and GenAI telemetry.

> **Target:** Elastic Cloud **Serverless**. Hosted / ILM tiers are out of scope.

---

## Quick start (recommended)

Runtime demos use this **master** tree (`cloud&llm_cost_modeling/`), not the
workshop forks under `variants/`.

```bash
cd cloud&llm_cost_modeling
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env   # fill DEPLOY_<NAME>_* blocks (see below)

# List named Elastic Cloud targets
.venv/bin/python -m src.cli deployments

# Example: synthetic GCP (Vertex AI + Anthropic)
.venv/bin/python -m src.cli --deployment gcp setup
.venv/bin/python -m src.cli --deployment gcp backfill --scope all
.venv/bin/python -m src.cli --deployment gcp dashboards
.venv/bin/python -m src.cli --deployment gcp verify
.venv/bin/python -m src.cli --deployment gcp smoke
```

**Always pass `--deployment <name>`** (or set `FINOPS_DEPLOYMENT`). The default
in `.env` is easy to leave on `aws` — wrong-target mutations are the #1 footgun.

### Day-of readiness gate

```bash
.venv/bin/python scripts/pre_demo_gate.py \
  --deployment aws --deployment azure --deployment gcp
```

Runs variant consistency, fork drift, and panel smoke. For AWS with
`DEPLOY_AWS_FINOPS_PROFILE=live`, the gate automatically adds `--live` so it
smokes Cost Explorer hub IDs (not synthetic ones).

---

## Configure deployments (`.env`)

Keep multiple Elastic Cloud projects in one file:

```bash
FINOPS_DEPLOYMENT=gcp          # default target when --deployment omitted

DEPLOY_GCP_ELASTIC_URL=https://….es….gcp.elastic.cloud:443
DEPLOY_GCP_ELASTIC_API_KEY=…
DEPLOY_GCP_KIBANA_URL=https://….kb….gcp.elastic.cloud
DEPLOY_GCP_FINOPS_PROFILE=synthetic
DEPLOY_GCP_VARIANT=gcp

DEPLOY_AZURE_ELASTIC_URL=…
DEPLOY_AZURE_ELASTIC_API_KEY=…
DEPLOY_AZURE_KIBANA_URL=…
DEPLOY_AZURE_FINOPS_PROFILE=synthetic
DEPLOY_AZURE_VARIANT=azure

DEPLOY_AWS_ELASTIC_URL=…
DEPLOY_AWS_ELASTIC_API_KEY=…
DEPLOY_AWS_KIBANA_URL=…
DEPLOY_AWS_KIBANA_SPACE=finops
DEPLOY_AWS_FINOPS_PROFILE=live
DEPLOY_AWS_VARIANT=aws
```

| Key | Purpose |
|---|---|
| `DEPLOY_<NAME>_ELASTIC_URL` / `_API_KEY` | Elasticsearch |
| `DEPLOY_<NAME>_KIBANA_URL` | Kibana (space path optional) |
| `DEPLOY_<NAME>_KIBANA_SPACE` | e.g. `finops` for live AWS |
| `DEPLOY_<NAME>_FINOPS_PROFILE` | `synthetic` (factory data) or `live` (object-only / CE hub) |
| `DEPLOY_<NAME>_VARIANT` | Workshop profile from `config/variants.yaml` |

Flat `ELASTIC_URL` / `KIBANA_URL` keys still work for a single-project `.env`.

### Synthetic vs live profile

| Profile | What it does |
|---|---|
| **synthetic** (default) | Install Fleet packs, backfill generators, publish variant FinOps dashboards + budgets + agent |
| **live** | Object-only FinOps hub. **AWS:** Cost Explorer boards, rightsizing, workflows. **GCP/Azure live:** billing SLOs + agent + variant boards (no CE / rightsizing / workflows) |

Typical workshop layout used in practice:

| Deployment | Profile | Variant | Story |
|---|---|---|---|
| `aws` | `live` | `aws` | Cost Explorer, rightsizing queue, spend-spike / rightsize workflows, Bedrock OOTB |
| `azure` | `synthetic` | `azure` | Azure billing + Azure OpenAI + APM + ESS |
| `gcp` | `synthetic` | `gcp` | GCP billing + Vertex AI + Anthropic + APM + ESS |

---

## Deploy a cloud end-to-end

### Synthetic (Azure or GCP)

```bash
.venv/bin/python -m src.cli --deployment azure setup
.venv/bin/python -m src.cli --deployment azure backfill --days 120 --scope all
.venv/bin/python -m src.cli --deployment azure dashboards
.venv/bin/python -m src.cli --deployment azure budgets    # if setup skipped budgets
.venv/bin/python -m src.cli --deployment azure agent
.venv/bin/python -m src.cli --deployment azure smoke
.venv/bin/python scripts/panel_smoke.py --deployment azure
```

Same sequence with `--deployment gcp`.

### Live AWS FinOps hub

```bash
.venv/bin/python -m src.cli --deployment aws --profile live setup
.venv/bin/python -m src.cli --deployment aws dashboards      # imports kibana/live NDJSON + OOTB share
.venv/bin/python -m src.cli --deployment aws workflow --smoke
.venv/bin/python -m src.cli --deployment aws --profile live smoke
.venv/bin/python scripts/panel_smoke.py --deployment aws --live
```

Live AWS setup enables GenAI token-usage tracking, installs `ess_billing`, pins
Inference / ESS / Bedrock OOTB into the FinOps space, seeds the rightsizing
queue, and provisions workflows + budgets + agent.

> **Never reset live AWS mid-workshop.** `scripts/reset_environment.py` needs
> `--yes`; space delete only with `--delete-space`. Cost Explorer / native
> billing is not restored by generators.

### CLI reference

```bash
.venv/bin/python -m src.cli --deployment NAME setup
.venv/bin/python -m src.cli --deployment NAME sample|backfill|stream|verify [--scope …]
.venv/bin/python -m src.cli --deployment NAME dashboards [--variant baseline|classic|ai-assistant|all]
.venv/bin/python -m src.cli --deployment NAME budgets | recover-slos | agent | workflow [--smoke] [--deep]
.venv/bin/python -m src.cli --deployment NAME reindex-elastic-ai [--days 120] [--all]
.venv/bin/python -m src.cli --deployment NAME smoke [--fix] [--deep] [--live] [--variant ID]
.venv/bin/python -m src.cli deployments | variants | backup
```

`--scope`: `all` | `cloud` | `llm` | `openai-extra` | `elastic-ai` | `ess-billing` | `finops-usage`

Default backfill window is **120 days** ([`src/time_window.py`](src/time_window.py)).
Re-run `dashboards` after a fresh backfill so stored Kibana time ranges match.

---

## What to open in Kibana

| Surface | Path / ID pattern |
|---|---|
| FinOps hub | `app/dashboards#/view/elk-finops-llm-observability-<variant>` (synthetic) or live AWS `…-dynamic-aws` |
| Hub tabs | Horizontal **FinOps dashboards** bar → OOTB packs + Overview |
| Budget posture | Hub section + Observability → **SLOs** / **Alerts** |
| Agent Builder | `app/agent_builder/chat` → agent `elk-finops-ai-assistant` |
| Workflows (AWS live) | `app/workflows` (spend spike + rightsizing HITL / auto-approve) |
| Rightsizing (AWS live) | `finops-rightsizing-overview` |

**Talk-track prompts (agent):**

1. *How much cloud spend in the last 30 days vs budget?*
2. *Which projects / accounts / products drive spend?*
3. *Which spend SLOs are violated?*
4. *(GCP)* *Anthropic spend last 30d* · *(AWS)* *Rightsizing queue / run spike workflow*

---

## Variants — what each represents

Catalog: [`config/variants.yaml`](config/variants.yaml).  
**Runtime** selects a variant via `DEPLOY_<NAME>_VARIANT` / `FINOPS_VARIANT`.  
**Workshop forks** are handouts under `variants/` (regenerate after master changes).

```bash
.venv/bin/python -m src.cli variants
.venv/bin/python scripts/fork_project.py --all --force
.venv/bin/python scripts/check_fork_drift.py
```

### Alias map

| Alias | Resolves to |
|---|---|
| `bedrock` | `aws` |
| `anthropic`, `vertexai` | `gcp` |
| `azure-openai`, `azure_openai` | `azure` |

### Always-on (every variant)

Unioned from `variants.yaml` → `always`:

| Area | Content |
|---|---|
| Generators | Agent Builder traces, inference token usage, ESS billing + credits |
| Fleet | `ess_billing` |
| Setup | GenAI token-usage tracking, ESS health |
| Dashboards | AI Assistant board (when enabled for the pack) |
| Hub OOTB tabs | `[Elastic] Inference Token Usage`, ESS Billing + Credits |

### Per-variant matrix

| Variant | Cloud / LLM focus | FinOps boards | Classic (security→cost) | OOTB hub tabs (beyond always) | Budgets / agent |
|---|---|---|---|---|---|
| **`all`** | Full multi-cloud + all LLM packs | Baseline + classic + AI | Yes | CUR, GCP/Azure billing, Anthropic, OpenAI, AOAI, Bedrock, Vertex | Yes |
| **`aws`** | CloudTrail, GuardDuty, S3, EC2, CUR, Bedrock, APM | Baseline + classic | Yes | AWS CUR, Bedrock Overview + Guardrails | Yes |
| **`gcp`** | GCP audit/billing, Vertex AI, Anthropic metrics, APM | Baseline | No | GCP Billing, Vertex Metrics, Anthropic Cost & Billing | Yes |
| **`azure`** | Azure activity/billing, Azure OpenAI, APM | Baseline | No | Azure Billing, Azure OpenAI Overview + Billing | Yes |
| **`openai`** | OpenAI completions/embeddings/images/audio/moderations/rate-limits, APM | Baseline | No | OpenAI Usage Overview | Yes |
| **`elastic-ai`** | Agent Builder + inference only | AI board only | No | Inference Token Usage | Yes |

Fork directories: `variants/cloud-llm-cost-modeling-<variant>/` with `FORK.md` +
`config/active_variant.yaml`. Prefer running CLI from **master** with
`FINOPS_VARIANT=<id>` or `--deployment` rather than inside a fork.

### Generators & data streams (by pack)

**AWS (`aws` / `all`)**

| Stream | Content |
|---|---|
| `logs-aws.cloudtrail-default` | Management events |
| `logs-aws.guardduty-default` | Findings (crypto-mining, S3 exposure, …) |
| `logs-aws.s3access-default` | S3 access logs |
| `metrics-aws.ec2_metrics-default` | CPU / net / disk |
| `metrics-aws.billing-default` | EstimatedCharges + CE-shaped groups |
| `metrics-aws_billing.cur-default` | CUR 2.0 (incl. Bedrock lines) |
| `logs-aws_bedrock.invocation-default` | Bedrock invocations |
| `metrics-aws_bedrock.runtime-default` / `.guardrails-default` | Runtime + Guardrails |
| `traces-apm-default` | gen_ai spans |

**GCP (`gcp` / `all`)**

| Stream | Content |
|---|---|
| `logs-gcp.audit-default` | Audit LogEntry JSON |
| `metrics-gcp.billing-default` | Daily project × service cost |
| `logs-gcp_vertexai.prompt_response_logs-default` | Prompt/response logs |
| `metrics-gcp_vertexai.metrics-default` | Vertex metrics |
| `logs-gcp_vertexai.auditlogs-default` | Vertex audit |
| `metrics-anthropic_metrics.usage\|cost\|rate_limit-default` | Anthropic Admin API shapes |

**Azure (`azure` / `all`)**

| Stream | Content |
|---|---|
| `logs-azure.activitylogs-default` | Activity logs |
| `metrics-azure.billing-default` | Pretax cost |
| `logs-azure_openai.logs-default` | Azure OpenAI logs |
| `metrics-azure.open_ai-default` | Azure OpenAI metrics |

**OpenAI (`openai` / `all`)** — `logs-openai.*` completions, embeddings, images, audio, moderations, rate_limits.

**Elastic AI (always)** — `traces-agent_builder.otel-default`, `logs-elastic.inference_token_usage-default`, `metrics-ess_billing.billing\|credits-default`.

### Correlated scenarios (world model)

Driven by [`config/world.yaml`](config/world.yaml):

| Scenario | Surfaces |
|---|---|
| Crypto-mining (`elk-dev`) | GuardDuty + CloudTrail + EC2 CPU + billing spike |
| ML training burn (`elk-ml-prod`) | GCP billing + Vertex / Compute |
| Staging cost leak (`elk-staging`) | High EC2/RDS spend vs low API activity |
| S3 public exposure (`elk-fintech-prod`) | CloudTrail + GuardDuty + S3 access + transfer cost |
| GenAI shadow-IT (`elk-genai-poc`) | Vertex / Compute ramp |
| LLM agent-loop / migration / cache-miss | APM gen_ai + provider streams |
| Sunday ETL + seasonality | Cross-cloud activity / cost multipliers |

---

## Dashboards — what gets published

### ELK Co FinOps hubs (variant-scoped)

Published by `cli dashboards` (synthetic) or live AWS NDJSON import.

| ID pattern | When |
|---|---|
| `elk-finops-llm-observability-<variant>` | Baseline hub (spend, allocation, LLM sections, budget posture, hub tabs) |
| `elk-finops-llm-observability-classic-<variant>` | Classic layout + security→cost (`aws`, `all` only) |
| `elk-ai-assistant-inference-usage-<variant>` | Agent Builder traces + inference token usage |
| Live AWS: `elk-finops-llm-observability-dynamic-aws`, `finops-aws-billing-overview-unblended`, `finops-spend-vs-savings`, `finops-rightsizing-overview` | `FINOPS_PROFILE=live` + `variant=aws` |

Baseline sections are **capability-filtered** (no Bedrock panels on GCP/Azure hubs, etc.). Horizontal **FinOps dashboards** tabs only link OOTB packs listed for that variant.

### OOTB integration dashboards (hub tabs)

| Hub label | Package / title |
|---|---|
| AWS CUR | AWS Billing CUR dashboards |
| Bedrock / Bedrock Guardrails | `[Amazon Bedrock] Overview` / `Guardrails` |
| GCP Billing | GCP Billing Overview |
| Vertex AI | GCP Vertex AI Metrics |
| Anthropic | Anthropic Cost & Billing |
| Azure Billing | Azure Billing Overview |
| Azure OpenAI / Billing | Azure OpenAI Overview + Billing |
| OpenAI | OpenAI Usage Overview |
| Inference tokens | `[Elastic] Inference Token Usage` (data view retargeted to `logs-elastic.inference_token_usage-default` on Serverless) |
| ESS Billing / Credits | `[Metrics ESS Billing] …` |

### Budgets, alerts, agent

| Cloud | Budgets config | Agent config |
|---|---|---|
| AWS synthetic / multi | `config/budgets.yaml` | `config/finops_agent.yaml` |
| AWS live | `config/live/budgets.yaml` | `config/live/finops_agent.yaml` (+ workflow tools) |
| GCP | `config/budgets_gcp.yaml` (+ live twin) | `config/live/finops_agent_gcp.yaml` |
| Azure | `config/budgets_azure.yaml` (+ live twin) | `config/live/finops_agent_azure.yaml` |
| openai / elastic-ai | `config/budgets_llm.yaml` | scoped LLM agent tools |

Demo thresholds are **intentionally tight** so seeded timelines show **VIOLATED** SLOs and firing budget alerts.

AWS live workflows (spend spike + rightsizing, HITL + auto-approve) live under
`kibana/live/workflows/`. On clusters where bare workflow IDs are tombstoned,
deployed IDs may use `*-1` / `*-2` suffixes — see `config/live/finops_agent.yaml`
and `src/workflows.py`.

---

## How the factory works

Everything derives from one deterministic world model
([`config/world.yaml`](config/world.yaml) → [`src/world/`](src/world/)): business
units, accounts/projects/subscriptions, instances, identities, tag policy
(~80% compliance), and a shared scenario timeline.

- **Log generators** emit raw native payloads (CloudTrail JSON, GuardDuty
  findings, GCP LogEntry, Azure activity, …) into integration data streams and
  let Fleet ingest pipelines do ECS parsing.
- **Billing / metrics generators** emit metricbeat-shaped docs matching
  integration field mappings.
- Shared RNG seeds + time windows keep backfill and `stream` on one continuous
  timeline.

LLM catalog: [`config/llm_models.yaml`](config/llm_models.yaml) (OpenAI, Anthropic,
Gemini, Bedrock, Azure OpenAI) and apps such as checkout-assistant,
support-copilot, rag-research, skunk-agent-lab, …

`setup` installs cloud + LLM packages, creates APM gen_ai mappings + retention,
enables GenAI token-usage tracking, patches TSDS where needed for multi-month
metric backfill, and provisions budgets + agent.

---

## Pre-session checklist

```bash
.venv/bin/python scripts/pre_demo_gate.py \
  --deployment aws --deployment azure --deployment gcp

.venv/bin/python -m src.cli --deployment gcp smoke
.venv/bin/python -m src.cli --deployment azure smoke
.venv/bin/python -m src.cli --deployment aws --profile live smoke

# Optional: refresh Agent Builder synthetic traces after agent ID / tool renames
.venv/bin/python -m src.cli --deployment gcp reindex-elastic-ai
```

Spot-check: hub tabs (no foreign-cloud links), SLOs violated as expected, Alerts
filtered to enabled rules, Agent Builder answers grounded in tools.

---

## Layout

```
config/
  variants.yaml          # workshop profiles + always pack + OOTB groups
  world.yaml             # org model + scenarios
  llm_models.yaml        # providers, pricing, apps
  budgets*.yaml          # spend ceilings / alert floors
  finops_agent.yaml      # default Agent Builder tools
  live/                  # live AWS/GCP/Azure budgets + agent YAMLs
src/
  cli.py                 # setup | backfill | dashboards | smoke | …
  variant.py             # FINOPS_VARIANT + aliases
  dashboards.py          # FinOps hubs + hub tabs
  dashboard_sections.py  # capability-scoped panels
  live_dashboards.py     # AWS live NDJSON import + OOTB share
  budgets.py / agent_builder.py / workflows.py / rightsizing.py
  generators/            # cloud + LLM + Elastic AI + ESS
scripts/
  pre_demo_gate.py       # consistency + drift + panel smoke
  panel_smoke.py         # deep ES|QL / hub / OOTB panel checks
  fork_project.py        # materialize variants/
  check_fork_drift.py
  variant_consistency.py
kibana/live/             # live AWS dashboards.ndjson + workflows
variants/                # workshop forks (handouts; not runtime)
```

---

## Recover / reset notes

| Situation | Action |
|---|---|
| SLO transforms stale / NO_DATA | `cli recover-slos` then wait 1–2 min |
| Inference OOTB panels 404 on `.kibana-inference-token-usage` | Re-run `dashboards` / `setup` (retargets data view to `logs-elastic.inference_token_usage-default`) |
| Agent tools wrong cloud | `cli --deployment X agent` (uses cloud-scoped YAML) |
| Foreign alerts left from prior multi-cloud setup | Disable leftover `elk-alert-aws-*` / `bedrock` / `staging` on GCP/Azure |
| Live AWS wipe | `cli --deployment aws --profile live setup` + `workflow --smoke` (CE lag may be hours) |
