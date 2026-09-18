"""Environment / connection configuration."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

ELASTIC_URL = os.environ["ELASTIC_URL"].rstrip("/")
ELASTIC_API_KEY = os.environ["ELASTIC_API_KEY"]
# Kibana URL for Fleet API; derivable from the ES URL on Elastic Cloud.
KIBANA_SPACE = os.environ.get("KIBANA_SPACE", "").strip()
_KIBANA_ROOT = os.environ.get(
    "KIBANA_URL", ELASTIC_URL.replace(".es.", ".kb.").replace(":443", "")
).rstrip("/")
KIBANA_ROOT = _KIBANA_ROOT
# Space-scoped APIs and deep links: /s/<space>/api/... and /s/<space>/app/...
if KIBANA_SPACE and KIBANA_SPACE.lower() != "default":
    KIBANA_URL = f"{_KIBANA_ROOT}/s/{KIBANA_SPACE}"
else:
    KIBANA_URL = _KIBANA_ROOT

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
