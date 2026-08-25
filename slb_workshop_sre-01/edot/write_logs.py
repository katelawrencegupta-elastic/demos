#!/usr/bin/env python3
"""Write a few JSON platform logs for the EDOT filelog receiver."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent / "logs"
LOG_FILE = LOG_DIR / "platform.json.log"


def main() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    events = [
        {
            "Timestamp": now,
            "Body": "edot filelog receiver ingested this platform log",
            "SeverityText": "INFO",
            "service.name": "well-data-api",
            "deployment.environment": "workshop",
        },
        {
            "Timestamp": now,
            "Body": "kafka producer backoff",
            "SeverityText": "WARN",
            "service.name": "telemetry-gateway",
            "deployment.environment": "workshop",
        },
    ]
    with LOG_FILE.open("a", encoding="utf-8") as fh:
        for event in events:
            fh.write(json.dumps(event) + "\n")
    print(f"wrote {len(events)} lines -> {LOG_FILE}")


if __name__ == "__main__":
    main()
