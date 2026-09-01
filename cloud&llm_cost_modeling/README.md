# Multi-Cloud Synthetic Data Factory for Elastic

Generates correlated synthetic AWS / GCP / Azure activity, security, and
billing data for a fictional company (**Meridian Dynamics**) and ships it into
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
| Crypto-mining incident (days -12..-9, `meridian-dev`) | GuardDuty `CryptoCurrency:EC2/BitcoinTool.B` findings, CloudTrail brute-force `ConsoleLogin` + `RunInstances` from attacker IP `185.220.101.34`, CPU pegged 96-99% on the compromised instance, EC2 cost spike in AWS billing, exfil-style S3 GETs |
| ML training burn (days -20..-16, `meridian-ml-prod`) | GCP billing 3.8x spike on Compute Engine / Vertex AI, GCE instance churn in audit logs |
| Cost leak (`meridian-staging`) | ~$340/day of EC2 + RDS spend with disproportionately little API activity |
| S3 public exposure (days -6..-4, `meridian-fintech-prod`) | CloudTrail `PutBucketPolicy`, GuardDuty `Policy:S3/BucketAnonymousAccessGranted`, anonymous curl scrapes of `meridian-fintech-exports`, data-transfer cost spike |
| GenAI shadow-IT ramp (from day -15, `meridian-genai-poc`) | Vertex AI / Compute spend ramps ~2.8x; audit Predict + CustomJob activity |
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
| `gcp` | `cloud-llm-cost-modeling-gcp` | GCP audit/billing + Vertex AI |
| `azure` | `cloud-llm-cost-modeling-azure` | Azure activity/billing + Azure OpenAI |
| `openai` | `cloud-llm-cost-modeling-openai` | OpenAI completions/embeddings/usage streams |
| `anthropic` | `cloud-llm-cost-modeling-anthropic` | Anthropic usage/cost/rate-limit metrics |
| `bedrock` | `cloud-llm-cost-modeling-bedrock` | Amazon Bedrock invocation/runtime/guardrails |
| `vertexai` | `cloud-llm-cost-modeling-vertexai` | Vertex prompt logs, metrics, audit logs |
| `azure-openai` | `cloud-llm-cost-modeling-azure-openai` | Azure OpenAI logs/metrics/billing |
| `elastic-ai` | `cloud-llm-cost-modeling-elastic-ai` | Agent Builder traces + inference token usage |

Each fork ships with `config/active_variant.yaml` and a `FORK.md` quickstart. Re-run
`fork_project.py` from the master tree after code changes to refresh forks (`--force`).

Active variant in any tree: `python -m src.cli variants` (or set `MERIDIAN_VARIANT`).

## Usage

### Workshop quickstart

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# Copy .env.example → .env and set ELASTIC_URL, ELASTIC_API_KEY, KIBANA_URL

.venv/bin/python -m src.cli setup                           # Fleet, APM, budgets, agent
.venv/bin/python -m src.cli backfill --scope all            # default 120 days
.venv/bin/python -m src.cli verify --scope all
.venv/bin/python -m src.cli dashboards --variant all
```

Then open Kibana: **Observability → SLOs** (expect **VIOLATED** spend SLOs), **FinOps dashboard
→ Budget posture** (gauges + SLO table), and **Agent Builder → chat** (`meridian-finops-ai-assistant`).

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
.venv/bin/python -m src.cli recover-slos         # reset SLO transforms + reprocess SLI data
.venv/bin/python -m src.cli agent                # Meridian FinOps AI Assistant (Agent Builder)
.venv/bin/python -m src.cli reindex-elastic-ai   # wipe + re-backfill Agent Builder / inference traces
.venv/bin/python -m src.cli dashboards --variant all        # baseline + classic + AI
.venv/bin/python -m src.cli dashboards --variant baseline   # primary FinOps (default)
.venv/bin/python -m src.cli dashboards --variant classic    # legacy layout (+ security→cost)
.venv/bin/python -m src.cli dashboards --variant ai-assistant
.venv/bin/python -m src.cli backup     # snapshot Kibana/Fleet/ES objects → ./elastic
```

**Dashboard IDs:** `meridian-finops-llm-observability` (baseline — stacked bars/areas),
`meridian-finops-llm-observability-dynamic` (same layout, kept for bookmarks),
`meridian-finops-llm-observability-classic` (legacy treemaps/tables),
`meridian-ai-assistant-inference-usage` (Agent Builder + inference token usage).

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

Meridian treats cloud + LLM spend as error budgets. `cli budgets` (also run at
the end of `setup`) provisions:

| Kind | Artifacts |
|---|---|
| Spend SLOs (timeslice, 30d rolling, 24h slices) | AWS daily CUR under ceiling · staging cost-leak healthy · `checkout-assistant` daily LLM cost |
| SLO burn-rate rules | staging + checkout |
| ES\|QL budget alerts | AWS trailing-30d vs monthly budget · staging daily · checkout 7d LLM · GCP `meridian-ml-prod` 7d |

| SLO ID | Workshop posture |
|---|---|
| `meridian-slo-aws-daily-spend` | **VIOLATED** — crypto + growth burn days exceed $5.2k/day ceiling |
| `meridian-slo-staging-cost-leak` | **VIOLATED** — cost_leak ~$1k/day vs $150/day ceiling |
| `meridian-slo-llm-checkout-spend` | **VIOLATED** — agent-loop spike days vs $0.50/day ceiling |

Thresholds live in [`config/budgets.yaml`](config/budgets.yaml) and are **intentionally
tight** so the seeded timeline shows breached SLOs and active budget alerts without
waiting for a new incident.

FinOps dashboards include a **Budget posture** section: spend gauges (vs monthly
budget and SLO ceilings), a live **Meridian spend SLO posture** table (from
`.slo-observability.summary-v3.6`), and deep links to Observability SLOs / Alerts /
Agent Builder.

**Recover SLOs:** If transforms break or you reset SLI state during prep, run
`python -m src.cli recover-slos` to recreate transforms and reprocess history.
After a reset, violations return once the 30d rolling window backfills (typically
1–2 minutes). To refresh thresholds only, run `cli budgets` without reset.

## Meridian FinOps AI Assistant

`cli agent` (also run at the end of `setup`) provisions **Meridian FinOps AI
Assistant** in Elastic Agent Builder: seven custom ES|QL tools plus a public chat
agent grounded in the seeded billing, SLO, and alert data.

| Tool ID | Use for |
|---|---|
| `meridian-finops-aws-spend` | AWS CUR total / avg daily / % of monthly budget |
| `meridian-finops-aws-top-accounts` | Top linked accounts by spend |
| `meridian-finops-staging-leak` | meridian-staging vs SLO ceiling (cost leak) |
| `meridian-finops-llm-spend-by-app` | LLM cost by `service.name` (APM gen_ai) |
| `meridian-finops-cloud-mix` | AWS + GCP + Azure spend mix |
| `meridian-finops-gcp-ml-burn` | meridian-ml-prod GCP burn |
| `meridian-finops-slo-posture` | Error budget remaining / consumed |

| Command | Purpose |
|---|---|
| `python -m src.cli agent` | Upsert tools + agent (re-run after editing `config/finops_agent.yaml`) |
| `python -m src.cli verify` | Checks tools, agent, budgets, and prints chat URL |

**Chat:** `{KIBANA_URL}/app/agent_builder/chat` — select agent `meridian-finops-ai-assistant`.

Definitions live in [`config/finops_agent.yaml`](config/finops_agent.yaml). Tool queries
use parameterized lookbacks (`?days` integer) with
`TO_DATEPERIOD(CONCAT(TO_STRING(?days), " days"))` — do not use `?days * 1 day` (invalid ES\|QL).

Synthetic Agent Builder traces use agent id **`meridian-finops-ai-assistant`**
and FinOps ES|QL tool names. After renaming the agent, run
`python -m src.cli reindex-elastic-ai` (wipes non-`custom-*` Agent Builder traces
and `tags:synthetic` inference usage, then re-backfills 120 days). `verify` fails
if legacy `finops-copilot` traces remain.

**Workshop prompts** (after backfill + `budgets` + `agent`):

1. *How much AWS spend in the last 30 days vs our monthly budget?*
2. *Which AWS accounts drive the most spend this week?*
3. *Is meridian-staging still leaking cost?*
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
  trace retention, wires CUR alias / inference data-view Serverless workarounds,
  provisions FinOps spend SLOs + budget alerts, provisions the Meridian FinOps AI
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
src/time_window.py         # shared demo time range (aligns with backfill)
src/budgets.py             # FinOps spend SLOs, budget alerts, recover-slos
src/agent_builder.py       # Meridian FinOps AI Assistant (Agent Builder + ES|QL tools)
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