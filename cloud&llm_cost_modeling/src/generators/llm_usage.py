"""Hourly LLM usage rollups -> metrics-llm.usage-default.

One doc per (hour, app, provider, model) with summed tokens / requests /
cost — useful for time-series dashboards without scanning every invocation.
"""
from collections import defaultdict

from src.generators import llm_invocation
from src.generators.common import metric_doc
from src.world.llm import load_llm_catalog

DATA_STREAM = "metrics-llm.usage-default"
DATASET = "llm.usage"
SCOPE = "llm"


def emit(world, t0, t1, anchor, catalog=None):
    catalog = catalog or load_llm_catalog()
    # Aggregate the same invocations the logs generator would emit this hour
    buckets = defaultdict(lambda: {
        "requests": 0, "errors": 0, "input_tokens": 0, "output_tokens": 0,
        "cached_input_tokens": 0, "cost_usd": 0.0, "latency_sum": 0,
    })
    for doc in llm_invocation.emit(world, t0, t1, anchor, catalog=catalog):
        llm = doc["llm"]
        key = (doc["service"]["name"], llm["provider"], llm["model"]["id"],
               llm["operation"], doc["@timestamp"][:13])  # YYYY-MM-DDTHH
        b = buckets[key]
        b["requests"] += 1
        if llm["status"] != "success":
            b["errors"] += 1
        b["input_tokens"] += doc["gen_ai"]["usage"]["input_tokens"]
        b["output_tokens"] += doc["gen_ai"]["usage"]["output_tokens"]
        b["cached_input_tokens"] += doc["gen_ai"]["usage"]["cached_input_tokens"]
        b["cost_usd"] += llm["cost"]["usd"]
        b["latency_sum"] += llm["latency_ms"]
        b["labels"] = doc.get("labels") or {}
        b["env"] = doc["service"]["environment"]
        b["bu"] = (doc.get("labels") or {}).get("team")
        b["hour_ts"] = doc["@timestamp"][:13] + ":00:00.000Z"

    for (app, provider, model_id, op, _), b in buckets.items():
        ts_str = b["hour_ts"]
        # parse back for metric_doc — use the hour mark
        from datetime import datetime, timezone
        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00")).astimezone(timezone.utc)
        doc = metric_doc(DATASET, ts, "usage", 3600 * 1000)
        doc["labels"] = b["labels"]
        doc["service"] = {"name": app, "environment": b["env"], "type": "llm-gateway"}
        doc["llm"] = {
            "provider": provider,
            "operation": op,
            "model": {"id": model_id},
            "usage": {
                "requests": b["requests"],
                "errors": b["errors"],
                "input_tokens": b["input_tokens"],
                "output_tokens": b["output_tokens"],
                "total_tokens": b["input_tokens"] + b["output_tokens"],
                "cached_input_tokens": b["cached_input_tokens"],
                "avg_latency_ms": int(b["latency_sum"] / max(1, b["requests"])),
            },
            "cost": {"usd": round(b["cost_usd"], 6), "currency": "USD"},
        }
        doc["tags"] = ["synthetic", "llm"]
        yield doc
