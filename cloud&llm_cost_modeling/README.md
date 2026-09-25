# Multi-Cloud Synthetic Data Factory for Elastic

Generates correlated synthetic AWS / GCP / Azure activity, security, and
billing data for a fictional company (**ELK Co**) and ships it into
**native Elastic integration data streams** on **Elastic Cloud Serverless**,
so out-of-the-box dashboards, Discover views, and detection content work
against realistic-looking data.

> **Target:** Elastic Cloud **Serverless** only for this workshop. Hosted
> deployments with hot/warm/cold/frozen ILM are a separate future track.

## How it works

Everything derives from one deterministic **world model**
([config/world.yaml](config/world.yaml) expanded by
[src/world/model.py](src/world/model.py)): 5 business units, 9 AWS accounts,
5 GCP projects, 3 Azure subscriptions, ~120 EC2 instances, ~46 GCE instances,
~27 Azure VMs, 25 named identities, and a tag policy with ~80% compliance
(missing / misspelled `cost_center` tags, untagged shadow-IT resources).

Log generators emit **raw native payloads** (CloudTrail record JSON, GuardDuty
finding JSON, S3 server access log lines, GCP audit LogEntry JSON, Azure
event-hub records) into the integration data streams and let each
integration's real ingest pipeline do the ECS parsing. Billing/metrics
generators emit metricbeat-shaped documents matching the integrations' field
mappings exactly.

Because generators share the model and a common scenario timeline, data
correlates across streams:

| Scenario | Where it shows up |
|---|---|
| Crypto-mining incident (days -12..-9, `elk-dev`) | GuardDuty `CryptoCurrency:EC2/BitcoinTool.B` findings, CloudTrail brute-force `ConsoleLogin` + `RunInstances` from attacker IP `185.220.101.34`, CPU pegged 96-99% on the compromised instance, EC2 cost spike in AWS billing, exfil-style S3 GETs |
| ML training burn (days -20..-16, `elk-ml-prod`) | GCP billing 3.8x spike on Compute Engine / Vertex AI, GCE instance churn in audit logs |
| Cost leak (`elk-staging`) | ~$340/day of EC2 + RDS spend with disproportionately little API activity |
| S3 public exposure (days -6..-4, `elk-fintech-prod`) | CloudTrail `PutBucketPolicy`, GuardDuty `Policy:S3/BucketAnonymousAccessGranted`, anonymous curl scrapes of `elk-fintech-exports`, data-transfer cost spike |
| GenAI shadow-IT ramp (from day -15, `elk-genai-poc`) | Vertex AI / Compute spend ramps ~2.8x; audit Predict + CustomJob activity |
| Sunday ETL batch (02-08 UTC) | Activity + usage/cost multiplier across clouds |
| Seasonality + growth | Diurnal / weekday curves on activity, ~0.8%/day organic cost growth |

## Data streams

| Data stream | Content |
|---|---|
| `logs-aws.cloudtrail-default` | Management events (EC2/S3/IAM/STS/ConsoleLogin) |
| `logs-aws.guardduty-default` | Findings incl. crypto-mining + S3 public exposure |
| `logs-aws.s3access-default` | S3 server access log lines |
| `metrics-aws.ec2_metrics-default` | CPU/network/disk per instance, 5-min period |
| `metrics-aws.billing-default` | EstimatedCharges (12h, cumulative) + Cost Explorer daily groups (SERVICE / LINKED_ACCOUNT / TAG) |
| `logs-gcp.audit-default` | GCP audit LogEntry JSON (compute, BigQuery, Vertex AI, IAM) |
| `metrics-gcp.billing-default` | Daily project x service costs |
| `logs-azure.activitylogs-default` | Azure activity log records |
| `metrics-azure.billing-default` | Per-VM + per-resource-group daily usage costs |

## Workshop forks (per cloud / integration)

The master project (`cloud&llm_cost_modeling`) supports **variant profiles** that scope
generators, Fleet packages, setup steps, and dashboards to one cloud or LLM integration pack.

Materialize self-contained copies (sibling directories under `demos/`):

```bash
python scripts/fork_project.py --list          # variant ids + destination dirs
python scripts/fork_project.py --all           # fork every variant
python scripts/fork_project.py aws gcp azure   # fork selected variants
python scripts/fork_project.py --force openai  # replace an existing fork
```

| Variant | Directory | Focus |
|---|---|---|
| `all` | `cloud-llm-cost-modeling-all` | Full multi-cloud + all LLM + Elastic AI |
| `aws` | `cloud-llm-cost-modeling-aws` | CloudTrail, GuardDuty, S3, EC2, CUR, Bedrock, ESS credits |
| `gcp` | `cloud-llm-cost-modeling-gcp` | GCP audit/billing + Vertex AI (prompt logs, metrics, audit) |
| `azure` | `cloud-llm-cost-modeling-azure` | Azure activity/billing + Azure OpenAI logs/metrics/billing |
| `openai` | `cloud-llm-cost-modeling-openai` | OpenAI completions/embeddings/usage streams |
| `anthropic` | `cloud-llm-cost-modeling-anthropic` | Anthropic usage/cost/rate-limit metrics |
| `bedrock` | `cloud-llm-cost-modeling-bedrock` | Amazon Bedrock invocation/runtime/guardrails |
| `elastic-ai` | `cloud-llm-cost-modeling-elastic-ai` | Agent Builder traces + inference token usage (also installed on every other variant) |

Each fork ships with `config/active_variant.yaml` and a `FORK.md` quickstart. Re-run
`fork_project.py` from the master tree after code changes to refresh forks (`--force`).
`FINOPS_VARIANT=vertexai` is an alias of `gcp` (Vertex AI lives in the default GCP build).
`FINOPS_VARIANT=azure-openai` is an alias of `azure` (Azure OpenAI lives in the default Azure build).
Every variant also installs Elastic AI (`config/variants.yaml` `always`): Agent Builder
traces, inference token usage, GenAI token-usage tracking, and the AI Assistant dashboard.

Active variant in any tree: `python -m src.cli variants` (or set `FINOPS_VARIANT`).

Each variant publishes its own `[ELK Co] FinOps & LLM Observability — …`
dashboard (`elk-finops-llm-observability-<variant>`). GCP panels are GCP billing
+ Vertex AI only; Azure panels are Azure billing + Azure OpenAI only; AWS Cost Explorer
/ CUR panels are not included on either.

## Usage

### Workshop quickstart

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# Copy .env.example → .env and fill DEPLOY_<NAME>_* blocks (or flat ELASTIC_* keys).
# Select a target: FINOPS_DEPLOYMENT=gcp   (or pass --deployment gcp on each command)

.venv/bin/python -m src.cli deployments                     # list named targets
.venv/bin/python -m src.cli --deployment gcp setup          # Fleet, APM, budgets, agent
.venv/bin/python -m src.cli --deployment gcp backfill --scope all
.venv/bin/python -m src.cli --deployment gcp verify --scope all
.venv/bin/python -m src.cli --deployment gcp dashboards --variant all
```

Each `DEPLOY_<NAME>_*` block can set its own `VARIANT` (workshop profile),
`FINOPS_PROFILE` (`synthetic` | `live`), and `KIBANA_SPACE` so AWS / GCP / Azure
Elastic Cloud projects stay side-by-side in one `.env`.

Then open Kibana: **Observability → SLOs** (expect **VIOLATED** spend SLOs), **FinOps dashboard
→ Budget posture** (gauges + SLO table), and **Agent Builder → chat** (`elk-finops-ai-assistant`).

### Live ELK Co FinOps (Cost Explorer objects)

The synthetic factory is the default. To provision the **live** ELK Co FinOps space
(Cost Explorer dashboards, rightsizing stream, workflows, SLOs/alerts, Agent Builder)
without generating data:

```bash
# .env
KIBANA_SPACE=finops
FINOPS_PROFILE=live

.venv/bin/python -m src.cli --profile live setup
.venv/bin/python -m src.cli --profile live verify
```

Live setup also **enables GenAI token usage tracking** (Stack Management → GenAI
Settings) and **installs the Elastic Billing (`ess_billing`) Fleet integration**,
then pins the OOTB Billing / Credits / Inference Token Usage dashboards into
the FinOps space.

`setup` / `dashboards` / `agent` / `budgets` / `verify` honor `FINOPS_PROFILE=live`
**when the workshop variant is `aws`**. Other variants always publish the
variant-scoped ELK Co dashboard and will not import the AWS Cost Explorer hub.

Sources: `config/live/`, `kibana/live/`, `elasticsearch/live/`.

Rightsizing queue (`finops-rightsizing-overview`) uses **Vega-Lite** panels plus an expanded
recommendation catalog (downsize, upsize, stop_idle, delete_volume, migrate_generation,
gp2_to_gp3, purchase_ri_sp, schedule_offhours, rightsize_lambda). Rebuild assets with:

```bash
.venv/bin/python scripts/generate_rightsizing_seed.py
.venv/bin/python scripts/build_rightsizing_dashboard.py
```

Then re-run `--profile live setup` (force-reseeds when the stream is thin / always upserts on live setup).

### All commands

```bash
.venv/bin/python -m src.cli setup      # integrations, APM, budgets/SLOs, FinOps agent
.venv/bin/python -m src.cli sample --scope all
.venv/bin/python -m src.cli backfill --days 120 --scope cloud   # --days defaults to 120
.venv/bin/python -m src.cli backfill --scope llm
.venv/bin/python -m src.cli backfill --scope elastic-ai
.venv/bin/python -m src.cli stream --tick 60 --scope all
.venv/bin/python -m src.cli verify --scope all
.venv/bin/python -m src.cli budgets              # FinOps spend SLOs + ES|QL budget alerts
.venv/bin/python -m src.cli workflow             # live FinOps Kibana workflows (spend spike + rightsizing)
.venv/bin/python -m src.cli recover-slos         # reset SLO transforms + reprocess SLI data
.venv/bin/python -m src.cli agent                # ELK Co FinOps AI Assistant (Agent Builder)
.venv/bin/python -m src.cli reindex-elastic-ai   # wipe + re-backfill Agent Builder / inference traces
.venv/bin/python -m src.cli dashboards --variant all        # baseline + classic + AI
.venv/bin/python -m src.cli dashboards --variant baseline   # primary FinOps (default)
.venv/bin/python -m src.cli dashboards --variant classic    # legacy layout (+ security→cost)
.venv/bin/python -m src.cli dashboards --variant ai-assistant
.venv/bin/python -m src.cli backup     # snapshot Kibana/Fleet/ES objects → ./elastic
```

**Dashboard IDs:** `elk-finops-llm-observability` (baseline — stacked bars/areas),
`elk-finops-llm-observability-dynamic` (same layout, kept for bookmarks),
`elk-finops-llm-observability-classic` (legacy treemaps/tables),
`elk-ai-assistant-inference-usage` (Agent Builder + inference token usage).

`--scope` accepts `all` | `cloud` | `llm` | `openai-extra` | `elastic-ai`.

`openai-extra` re-indexes only OpenAI images/audio/moderations/rate-limits (fills
OOTB Usage panels without redoing completions/embeddings).

**Dashboard time ranges** are computed at publish from `utcnow()` (same clock as
backfill; default window is **120 days** via [`src/time_window.py`](src/time_window.py)).
After a fresh backfill, re-run `dashboards` so stored windows match.

### Pre-session checklist (~10 min)

```bash
.venv/bin/python -m src.cli reindex-elastic-ai   # align Agent Builder trace agent IDs
.venv/bin/python -m src.cli verify --scope all
.venv/bin/python -m src.cli dashboards --variant all   # refresh 120d time window if needed
```

Spot-check in Kibana: **SLOs** (3 violated), **Observability Alerts**, and one
**Agent Builder** prompt (*"Which LLM apps burned the most in the last 7 days?"*).

## Budget SLOs & alerts

ELK Co treats cloud + LLM spend as error budgets. `cli budgets` (also run at
the end of `setup`) provisions:

| Kind | Artifacts |
|---|---|
| Spend SLOs (timeslice, 30d rolling, 24h slices) | AWS daily CUR under ceiling · staging cost-leak healthy · `checkout-assistant` daily LLM cost |
| SLO burn-rate rules | staging + checkout |
| ES\|QL budget alerts | AWS trailing-30d vs monthly budget · staging daily · checkout 7d LLM · GCP `elk-ml-prod` 7d |

| SLO ID | Workshop posture |
|---|---|
| `elk-slo-aws-daily-spend` | **VIOLATED** — crypto + growth burn days exceed $5.2k/day ceiling |
| `elk-slo-staging-cost-leak` | **VIOLATED** — cost_leak ~$1k/day vs $150/day ceiling |
| `elk-slo-llm-checkout-spend` | **VIOLATED** — agent-loop spike days vs $0.50/day ceiling |

Thresholds live in [`config/budgets.yaml`](config/budgets.yaml) and are **intentionally
tight** so the seeded timeline shows breached SLOs and active budget alerts without
waiting for a new incident.

FinOps dashboards include a **Budget posture** section: spend gauges (vs monthly
budget and SLO ceilings), a live **ELK Co spend SLO posture** table (from
`.slo-observability.summary-v3.6`), and deep links to Observability SLOs / Alerts /
Agent Builder.

**Recover SLOs:** If transforms break or you reset SLI state during prep, run
`python -m src.cli recover-slos` to recreate transforms and reprocess history.
After a reset, violations return once the 30d rolling window backfills (typically
1–2 minutes). To refresh thresholds only, run `cli budgets` without reset.

## ELK Co FinOps AI Assistant

`cli agent` (also run at the end of `setup`) provisions **ELK Co FinOps AI
Assistant** in Elastic Agent Builder: seven custom ES|QL tools plus a public chat
agent grounded in the seeded billing, SLO, and alert data.

| Tool ID | Use for |
|---|---|
| `elk-finops-aws-spend` | AWS CUR total / avg daily / % of monthly budget |
| `elk-finops-aws-top-accounts` | Top linked accounts by spend |
| `elk-finops-staging-leak` | elk-staging vs SLO ceiling (cost leak) |
| `elk-finops-llm-spend-by-app` | LLM cost by `service.name` (APM gen_ai) |
| `elk-finops-cloud-mix` | AWS + GCP + Azure spend mix |
| `elk-finops-gcp-ml-burn` | elk-ml-prod GCP burn |
| `elk-finops-slo-posture` | Error budget remaining / consumed |

| Command | Purpose |
|---|---|
| `python -m src.cli agent` | Upsert tools + agent (re-run after editing `config/finops_agent.yaml`) |
| `python -m src.cli verify` | Checks tools, agent, budgets, and prints chat URL |

**Chat:** `{KIBANA_URL}/app/agent_builder/chat` — select agent `elk-finops-ai-assistant`.

Definitions live in [`config/finops_agent.yaml`](config/finops_agent.yaml). Tool queries
use parameterized lookbacks (`?days` integer) with
`TO_DATEPERIOD(CONCAT(TO_STRING(?days), " days"))` — do not use `?days * 1 day` (invalid ES\|QL).

Synthetic Agent Builder traces use agent id **`elk-finops-ai-assistant`**
and FinOps ES|QL tool names. After renaming the agent, run
`python -m src.cli reindex-elastic-ai` (wipes non-`custom-*` Agent Builder traces
and `tags:synthetic` inference usage, then re-backfills 120 days). `verify` fails
if legacy `finops-copilot` traces remain.

**Workshop prompts** (after backfill + `budgets` + `agent`):

1. *How much AWS spend in the last 30 days vs our monthly budget?*
2. *Which AWS accounts drive the most spend this week?*
3. *Is elk-staging still leaking cost?*
4. *Which LLM apps burned the most in the last 7 days?*
5. *What's our multi-cloud spend mix and are any spend SLOs violated?*

## LLM factories

Factories emit into **native Elastic LLM integration data streams** (same shapes
as the real integrations), so OOTB dashboards work:

| Data stream | Package |
|---|---|
| `logs-openai.completions-default` / `logs-openai.embeddings-default` | openai |
| `metrics-anthropic_metrics.usage-default` / `.cost-default` / `.rate_limit-default` | anthropic_metrics |
| `logs-aws_bedrock.invocation-default` / `metrics-aws_bedrock.runtime-default` | aws_bedrock |
| `logs-azure_openai.logs-default` / `metrics-azure.open_ai-default` | azure_openai |
| `logs-gcp_vertexai.prompt_response_logs-default` / `metrics-gcp_vertexai.metrics-default` / `logs-gcp_vertexai.auditlogs-default` | gcp_vertexai |
| `traces-apm-default` | apm (gen_ai spans) |
| `metrics-aws_billing.cur-default` | aws_billing (CUR 2.0, incl. Bedrock lines) |
| `traces-agent_builder.otel-default` | Elastic Agent Builder / AI Assistant OTel spans |
| `logs-elastic.inference_token_usage-default` | Kibana inference token usage (feature, connector, EIS) |

**Providers & models:** OpenAI (GPT-5.6 Sol, GPT-5.4/mini, GPT-4o/mini, o3, embeddings), Anthropic (Opus 5, Sonnet 5, Haiku 4.5), Google Gemini (3.1 Pro, 2.5 Flash, embeddings), AWS Bedrock (Claude Sonnet 5, Llama 4 Maverick), Azure OpenAI (GPT-5.4, GPT-4o-mini).

**Apps:** checkout-assistant, catalog-search-embed, support-copilot, feature-ranker, rag-research, doc-summarizer, fraud-nlp, kyc-classifier, skunk-agent-lab, prompt-playground.

**LLM scenarios:** agent-loop burn, model migration (OpenAI→Anthropic), cache-miss storm, skunkworks GenAI ramp, Sunday embedding batch.

Notes:

- `setup` installs cloud + LLM packages, creates APM gen_ai mappings + **180d**
  trace retention, enables **GenAI Settings → Token usage tracking** (and the
  managed inference dashboard when the API allows), wires CUR alias /
  inference data-view Serverless workarounds,
  provisions FinOps spend SLOs + budget alerts, provisions the ELK Co FinOps AI
  Assistant, and removes TSDS mode from
  `metrics-aws.ec2_metrics` and `metrics-aws_bedrock.runtime` so multi-month
  metric backfill is accepted.
- Generation is seeded and windows are pure functions of time, so backfill
  and `stream` produce one continuous, reproducible timeline.
- Default backfill is **120 days** (~4.5M cloud docs + ~500k LLM/APM/CUR/Agent Builder docs).
- Orphan modules `llm_invocation` / `llm_usage` / `llm_cost` are **not** in
  `backfill --scope llm` (native provider streams + APM are used instead).

## Layout

```
config/world.yaml          # org model: BUs, accounts, resources, tags, scenarios
config/llm_models.yaml     # LLM providers, models, pricing, app workloads
src/world/                 # inventory + scenarios + cloud costs + LLM catalog
src/generators/            # cloud + LLM + Elastic AI Assistant / inference
src/sink/elastic.py        # bulk indexer with batching + retry
src/setup_cmd.py           # Fleet package install, TSDS patch, access checks
src/genai_settings.py      # GenAI token usage tracking + OOTB dashboard install
src/time_window.py         # shared demo time range (aligns with backfill)
src/budgets.py             # FinOps spend SLOs, budget alerts, recover-slos
src/agent_builder.py       # ELK Co FinOps AI Assistant (Agent Builder + ES|QL tools)
src/elastic_ai_reindex.py  # wipe + re-backfill Agent Builder / inference synthetic data
src/cli.py                 # setup | … | variants | dashboards | backup
src/variant.py             # workshop fork profiles (config/variants.yaml)
scripts/fork_project.py    # materialize per-cloud/integration forks
src/dashboards.py          # Kibana FinOps + LLM dashboards (baseline + classic)
src/dashboards_ai.py       # Kibana AI Assistant + inference usage dashboard
src/backup.py              # snapshot Kibana/Fleet/ES objects into ./elastic
```

Also: `config/budgets.yaml` — spend ceilings and alert floors for workshop demos.
Also: `config/finops_agent.yaml` — Agent Builder agent + ES|QL tool definitions.