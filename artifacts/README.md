# Elastic Demo Artifacts

Downloadable JSON exports of Elasticsearch **ingest pipelines**, **transforms**, and **ML jobs** used by this demo stack.

## Download

| Artifact | Path | Description |
|----------|------|-------------|
| **ZIP bundle** | [`elastic-demo-artifacts.zip`](elastic-demo-artifacts.zip) | All artifacts + manifest |
| **Manifest** | [`manifest.json`](manifest.json) | Index of exported objects and file paths |

Individual JSON files are organized by type:

```
artifacts/
├── elastic-demo-artifacts.zip
├── manifest.json
├── ingest-pipelines/     # 22 Fleet / integration pipelines
├── transforms/           # Network beaconing pivot transform
├── ml-jobs/              # DGA + network anomaly jobs
├── ml-datafeeds/         # Datafeeds for each ML job
└── ml-trained-models/    # DGA trained model definition
```

## Contents

### Ingest pipelines (22)

Referenced by `logstash/pipeline/main.conf` and ML integrations:

| Pipeline ID | Demo use |
|-------------|----------|
| `logs-netflow.log-2.25.1-klg` | NetFlow generator |
| `logs-network_traffic.*-1.34.2` | Packetbeat protocols (15 datasets) |
| `logs-dga.dns-1.0.0` | DGA generator DNS events |
| `logs-snort.log-1.21.2` | Snort alerts |
| `1.6.0-ml_beaconing_ingest_pipeline` | Beaconing ML enrichment |
| `3.0.1-ml_dga_ingest_pipeline` | DGA ML ingest scoring |
| `3.0.1-ml_dga_inference_pipeline` | DGA ML inference |

### Transforms (1)

| Transform ID | Destination |
|--------------|-------------|
| `logs-beaconing.pivot_transform-default-1.6.0` | `ml_beaconing.all` |

### ML jobs (4)

| Job ID | Purpose |
|--------|---------|
| `dga_high_sum_probability_ea` | DGA probability anomaly detection |
| `high_count_network_events` | Network volume anomalies |
| `high_count_network_denies` | Denied connection anomalies |
| `rare_destination_country` | Rare geo anomalies |

Each job includes a matching `datafeed-<job_id>.json` artifact.

### Trained models (1)

| Model ID | Purpose |
|----------|---------|
| `dga_1611725_2.0` | DGA classification model used by ingest pipelines |

## Regenerate from your deployment

Artifacts are exported from the Elastic deployment configured in `logstash/.env`:

```bash
# From repo root
python3 scripts/export-elastic-artifacts.py
```

This overwrites JSON files in `artifacts/` and rebuilds `elastic-demo-artifacts.zip`.

Requirements:

- `ELASTIC_HOSTS` — Elasticsearch HTTPS endpoint
- `ELASTIC_API_KEY` — API key with read access to ingest pipelines, transforms, and ML APIs

## Import examples

### Ingest pipeline

```bash
curl -X PUT "$ELASTIC_HOSTS/_ingest/pipeline/logs-dga.dns-1.0.0" \
  -H "Authorization: ApiKey $ELASTIC_API_KEY" \
  -H "Content-Type: application/json" \
  -d @artifacts/ingest-pipelines/logs-dga.dns-1.0.0.json
```

Note: pipeline JSON files are wrapped as `{"<pipeline_id>": { ... }}`. Extract the inner object or use the key from the file.

### Transform

```bash
# Review first — transforms include authorization and Fleet-managed settings.
cat artifacts/transforms/logs-beaconing.pivot_transform-default-1.6.0.json
```

Transforms are typically installed via the **Network Beaconing** Fleet integration rather than manual PUT.

### ML job

```bash
curl -X PUT "$ELASTIC_HOSTS/_ml/anomaly_detectors/dga_high_sum_probability_ea" \
  -H "Authorization: ApiKey $ELASTIC_API_KEY" \
  -H "Content-Type: application/json" \
  -d @artifacts/ml-jobs/dga_high_sum_probability_ea.json
```

## Related documentation

- [INGEST_PIPELINES_AND_ML.md](../docs/INGEST_PIPELINES_AND_ML.md) — field mappings, routing, and rule query targets
- [README.md](../README.md) — demo setup and generator overview
