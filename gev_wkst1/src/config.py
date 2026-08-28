"""Environment / connection configuration."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

ELASTIC_URL = os.environ["ELASTIC_URL"].rstrip("/")
ELASTIC_API_KEY = os.environ["ELASTIC_API_KEY"]
KIBANA_URL = os.environ.get(
    "KIBANA_URL", ELASTIC_URL.replace(".es.", ".kb.").replace(":443", "")
).rstrip("/")

ES_HEADERS = {
    "Authorization": f"ApiKey {ELASTIC_API_KEY}",
    "Content-Type": "application/json",
}
KBN_HEADERS = {
    "Authorization": f"ApiKey {ELASTIC_API_KEY}",
    "kbn-xsrf": "true",
    "Content-Type": "application/json",
}

WORLD_CONFIG = ROOT / "config" / "world.yaml"
PIPELINES_DIR = ROOT / "configs" / "ingest-pipelines"
TEMPLATES_DIR = ROOT / "configs" / "index-templates"
COMPONENTS_DIR = ROOT / "configs" / "component-templates"
KIBANA_DIR = ROOT / "kibana"

# Data streams
DS_ORCHESTRATOR = "logs-elasticco.orchestrator-default"
DS_CHECKOUT = "logs-elasticco.checkout-default"
DS_K8S_EVENT = "logs-elasticco.k8s.event-default"
DS_K8S_POD = "metrics-elasticco.k8s.pod-default"
DS_K8S_NODE = "metrics-elasticco.k8s.node-default"
DS_HOST = "metrics-elasticco.host-default"
DS_APM_INTERNAL = "metrics-apm.internal-default"
DS_TRACES = "traces-apm-default"
DS_INCIDENT = "logs-elasticco.incident-default"

PIPELINE_ORCHESTRATOR = "logs-elasticco.orchestrator"
