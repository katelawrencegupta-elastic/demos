# ARCH-02 collectors

Two collection paths, same storage layer. Architects decide **who** is allowed which path — see [artifacts/collection-model-standard.md](../artifacts/collection-model-standard.md).

## Path A — Fleet-managed Elastic Agent

Three policies, four hosts. Platform owns the integration allow-list (System only). Namespace is environment.

| Policy | Namespace | Hosts | Why it exists |
|---|---|---|---|
| `arch-02-platform-prod` | `prod` | `aks-arch-01`, `aks-arch-02` | Shared / regulated collectors — default Fleet path |
| `arch-02-drilling-prod` | `prod` | `aks-arch-03` | Domain team allowed on Fleet. Platform still owns the package list |
| `arch-02-platform-nonprod` | `nonprod` | `aks-arch-nonprod` | Same allow-list, different namespace. Not team / region / alice-test |

```bash
.venv/bin/python agents/enroll.py
```

That creates the policies, attaches **System**, fetches enrollment tokens from Kibana (not stored in `.env`), and starts the four containers. Confirm in Kibana → **Fleet → Agents**.

Policies only (no Docker):

```bash
.venv/bin/python agents/enroll.py --policies-only
```

Do not set `ELASTIC_AGENT_OTEL=true` on these containers — otel mode cannot enroll.

## Path B — EDOT-native (Agent in `otel` mode)

`reservoir-apps` is the workshop stand-in for a team granted vendor-neutral collector config. Config is `otel-agent.yml` in git — not a Fleet policy. Sink is **Managed OTLP** (`ELASTIC_OTLP_ENDPOINT` in `.env`). APM Server OTLP is unsupported.

| Container | Host | Environment | OTLP HTTP |
|---|---|---|---|
| `slb-arch02-otel-01` | `aks-arch-edot-01` | prod | `localhost:14318` |
| `slb-arch02-otel-02` | `aks-arch-edot-02` | prod | `localhost:15318` |
| `slb-arch02-otel-nonprod` | `aks-arch-edot-nonprod` | nonprod | `localhost:16318` |

```bash
docker compose --env-file .env -f agents/docker-compose.otel.yml up -d
.venv/bin/pip install -r requirements.txt   # needs OTel SDK deps
.venv/bin/python agents/factory.py sample --count 40
```

Fan out across all three agents:

```bash
.venv/bin/python agents/factory.py sample --count 60 \
  --endpoint http://127.0.0.1:14318 --host aks-arch-edot-01 \
  --endpoint http://127.0.0.1:15318 --host aks-arch-edot-02 \
  --endpoint http://127.0.0.1:16318 --host aks-arch-edot-nonprod
```

Continuous stream: `.venv/bin/python agents/factory.py stream --tick 2`

Confirm in Kibana **Applications → Service Inventory** for `well-data-api`, `reservoir-modeler`, `survey-ingest`. Filter on `team: reservoir-apps` or `telemetry.workshop: arch-02`.

Stop: `docker compose -f agents/docker-compose.otel.yml down`.

## What to say in the room

- Fleet agents appear under **Fleet → Agents**. OTel agents do **not** — central health is not free on this path.
- Changing otel retention / processors means a PR to `otel-agent.yml`, not a Fleet policy edit.
- Switching a team from A → B later is allowed and **not free** (streams, dashboards, on-call).
