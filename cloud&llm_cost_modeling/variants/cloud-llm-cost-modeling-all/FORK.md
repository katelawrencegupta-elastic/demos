# ELK Co FinOps & LLM Observability — full multi-cloud

Provider/integration-scoped fork of the ELK Co synthetic data factory.

- **Variant:** `all`
- **Source:** `cloud&llm_cost_modeling`
- **Path:** `variants/cloud-llm-cost-modeling-all`

> **Runtime demos use the master tree** (`cloud&llm_cost_modeling/`), not this
> fork. Forks are workshop handouts regenerated with `fork_project.py --force`.
> Prefer running CLI / setup / dashboards from master with `FINOPS_VARIANT=all`.

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

Re-fork from the master project (`cloud&llm_cost_modeling/`):

```bash
python scripts/fork_project.py --force all
```
