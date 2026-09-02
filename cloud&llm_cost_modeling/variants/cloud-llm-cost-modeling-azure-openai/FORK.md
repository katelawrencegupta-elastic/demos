# Meridian LLM Observability — Azure OpenAI

Provider/integration-scoped fork of the Meridian synthetic data factory.

- **Variant:** `azure-openai`
- **Source:** `cloud&llm_cost_modeling`

## Quickstart

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env   # set ELASTIC_URL, ELASTIC_API_KEY, KIBANA_URL

.venv/bin/python -m src.cli setup
.venv/bin/python -m src.cli backfill
.venv/bin/python -m src.cli verify
.venv/bin/python -m src.cli dashboards --variant all
```

List all workshop variants: `python -m src.cli variants`

Re-fork from the master project:

```bash
python scripts/fork_project.py --force azure-openai
```
