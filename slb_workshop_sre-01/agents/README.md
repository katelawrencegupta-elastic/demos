# Elastic Agent factory

Two compose files, same three hostnames (`aks-sre-01` .. `03`):

| File | Mode | Appears in Fleet? |
|---|---|---|
| `docker-compose.yml` | Fleet-managed (policy `sre-01-workshop`) | Yes |
| `docker-compose.otel.yml` | Standalone Agent in **otel** mode | No — otel mode cannot enroll |

## Fleet (Path A)

```bash
# from repo root
.venv/bin/python agents/enroll.py
```

That fetches the enrollment token from Kibana (it is not stored in `.env`) and recreates `slb-workshop-agent-01` .. `03` with `FLEET_ENROLL=1`. Confirm in Kibana → **Fleet → Agents**. The policy includes the **System** integration.

Host syslog (ssh, sudo, useradd/groupadd) is written into each container’s `/var/log/secure` and `/var/log/messages`. After agents are up:

```bash
.venv/bin/python agents/syslog_factory.py sample --count 80
.venv/bin/python agents/syslog_factory.py stream --tick 2
```

Discover `logs-system.auth-default` and `logs-system.syslog-default`, filtered by `host.name: aks-sre-01`.

Do not set `ELASTIC_AGENT_OTEL=true` on these containers — that mode cannot enroll.

## OTel mode (Path C)

```bash
docker compose --env-file .env -f agents/docker-compose.otel.yml up -d
.venv/bin/python agents/factory.py sample --count 60
.venv/bin/python agents/factory.py stream --tick 2
```

| Agent | Host | OTLP HTTP |
|---|---|---|
| `slb-workshop-agent-01` | aks-sre-01 | `localhost:14318` |
| `slb-workshop-agent-02` | aks-sre-02 | `localhost:15318` |
| `slb-workshop-agent-03` | aks-sre-03 | `localhost:16318` |

Agents listen on those ports and stamp `host.name` plus `telemetry.collector: elastic-agent`. Filter on that field in Discover to compare with the EDOT collector path.

Service names are the same as EDOT: `well-data-api`, `telemetry-gateway`, `identity-service`, `rig-scheduler`.
