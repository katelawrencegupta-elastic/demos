# EDOT collector lab

Elastic Agent in `otel` mode. See [Lab 3](../labs/03-fleet-vs-edot.md).

Default compose config sends to **Managed OTLP** (`ELASTIC_OTLP_ENDPOINT` in `.env`).

```bash
# from repo root
docker compose --env-file .env -f edot/docker-compose.yml up -d
.venv/bin/python edot/factory.py sample --count 40
.venv/bin/python edot/factory.py stream --tick 2
```

`factory.py` emits correlated **logs, metrics, and traces** (four demo services) plus host **syslog** (`sshd` logins, `sudo` commands, `useradd`/`groupadd`) to `localhost:4318`. Use `--syslog-ratio 1` for syslog only.
`otel-collector.yml` is the Elasticsearch-exporter fallback.
