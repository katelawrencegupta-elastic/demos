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

## Usage

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# Copy .env.example → .env and set ELASTIC_URL, ELASTIC_API_KEY, KIBANA_URL

.venv/bin/python -m src.cli setup      # integrations, APM, budgets/SLOs
.venv/bin/python -m src.cli sample --scope all
.venv/bin/python -m src.cli backfill --days 30 --scope cloud
.venv/bin/python -m src.cli backfill --days 30 --scope llm
.venv/bin/python -m src.cli backfill --days 30 --scope elastic-ai
.venv/bin/python -m src.cli stream --tick 60 --scope all
.venv/bin/python -m src.cli verify --scope all
.venv/bin/python -m src.cli budgets              # FinOps spend SLOs + ES|QL budget alerts
.venv/bin/python -m src.cli dashboards --variant all        # baseline + classic + AI
.venv/bin/python -m src.cli dashboards --variant baseline   # primary FinOps (default)
.venv/bin/python -m src.cli dashboards --variant classic    # legacy layout (+ security→cost)
.venv/bin/python -m src.cli dashboards --variant ai-assistant
.venv/bin/python -m src.cli backup     # snapshot Kibana/Fleet/ES objects → ./elastic
```

`--scope` accepts `all` | `cloud` | `llm` | `openai-extra` | `elastic-ai`.

`openai-extra` re-indexes only OpenAI images/audio/moderations/rate-limits (fills
OOTB Usage panels without redoing completions/embeddings).

**Dashboard time ranges** are computed at publish from `utcnow()` (same clock as
backfill). After a fresh backfill, re-run `dashboards` so stored windows match.

## Budget SLOs & alerts

Meridian treats cloud + LLM spend as error budgets. `cli budgets` (also run at
the end of `setup`) provisions:

| Kind | Artifacts |
|---|---|
| Spend SLOs (timeslice, 30d rolling, 24h slices) | AWS daily CUR under ceiling · staging cost-leak healthy · `checkout-assistant` daily LLM cost |
| SLO burn-rate rules | staging + checkout |
| ES\|QL budget alerts | AWS trailing-30d vs monthly budget · staging daily · checkout 7d LLM · GCP `meridian-ml-prod` 7d |

Thresholds live in [`config/budgets.yaml`](config/budgets.yaml) and are **intentionally
tight** so the seeded timeline (cost leak, crypto/ML spikes, agent-loop) shows
breached SLOs / Active alerts without waiting for a new incident. FinOps
dashboards include a **Budget posture** section with the same ceilings and deep
links to Observability SLOs / Alerts.

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

- `setup` installs cloud + LLM packages, creates APM gen_ai mappings + 180d
  retention, wires CUR alias / inference data-view Serverless workarounds,
  provisions FinOps spend SLOs + budget alerts, and removes TSDS mode from
  `metrics-aws.ec2_metrics` and `metrics-aws_bedrock.runtime` so multi-month
  metric backfill is accepted.
- Generation is seeded and windows are pure functions of time, so backfill
  and `stream` produce one continuous, reproducible timeline.
- ~1M cloud docs + ~120k native LLM/APM/CUR docs for a 30-day backfill.
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
src/budgets.py             # FinOps spend SLOs + ES|QL budget alert provisioning
src/cli.py                 # setup | sample | backfill | stream | verify | budgets | dashboards | backup
src/dashboards.py          # Kibana FinOps + LLM observability dashboards
src/dashboards_ai.py       # Kibana AI Assistant + inference usage dashboard
src/backup.py              # snapshot Kibana/Fleet/ES objects into ./elastic
```

Also: `config/budgets.yaml` — spend ceilings and alert floors for workshop demos.