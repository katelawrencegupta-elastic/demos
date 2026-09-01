"""Environment / connection configuration."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

ELASTIC_URL = os.environ["ELASTIC_URL"].rstrip("/")
ELASTIC_API_KEY = os.environ["ELASTIC_API_KEY"]
# Kibana URL for Fleet API; derivable from the ES URL on Elastic Cloud.
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
