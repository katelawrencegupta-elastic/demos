#!/usr/bin/env python3
"""Send a single OTLP/HTTP log to the local EDOT collector (port 4318)."""

from __future__ import annotations

import json
import time
import urllib.request

ENDPOINT = "http://127.0.0.1:4318/v1/logs"


def main() -> None:
    now_nano = str(time.time_ns())
    payload = {
        "resourceLogs": [
            {
                "resource": {
                    "attributes": [
                        {
                            "key": "service.name",
                            "value": {"stringValue": "workshop-demo"},
                        },
                        {
                            "key": "data_stream.dataset",
                            "value": {"stringValue": "workshop.otel"},
                        },
                    ]
                },
                "scopeLogs": [
                    {
                        "scope": {"name": "sre-01"},
                        "logRecords": [
                            {
                                "timeUnixNano": now_nano,
                                "severityText": "INFO",
                                "body": {
                                    "stringValue": "otlp ping from SRE-01 workshop"
                                },
                            }
                        ],
                    }
                ],
            }
        ]
    }
    req = urllib.request.Request(
        ENDPOINT,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        print(f"status={resp.status} body={resp.read().decode() or '<empty>'}")


if __name__ == "__main__":
    main()
