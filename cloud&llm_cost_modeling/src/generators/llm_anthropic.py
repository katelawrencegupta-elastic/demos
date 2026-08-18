"""Anthropic Admin API metrics -> metrics-anthropic_metrics.usage / .cost."""
from collections import defaultdict
from datetime import timedelta

from src.generators.common import iso, metric_doc
from src.world.llm_traffic import iter_events
from src.world.llm import token_cost_usd

SCOPE = "llm"


class _AnthropicUsage:
    DATA_STREAM = "metrics-anthropic_metrics.usage-default"
    DATASET = "anthropic_metrics.usage"

    def emit(self, world, t0, t1, anchor):
        buckets = defaultdict(lambda: {
            "uncached": 0, "cached": 0, "cache_creation": 0, "output": 0, "requests": 0,
        })
        for ev in iter_events(world, t0, t1, anchor):
            if ev.model["provider"] != "anthropic":
                continue
            key = (ev.model["id"], ev.app["id"])
            b = buckets[key]
            b["requests"] += 1
            b["output"] += ev.output_tokens
            if ev.cached_input_tokens:
                b["cached"] += ev.cached_input_tokens
                b["uncached"] += max(0, ev.input_tokens - ev.cached_input_tokens)
                # treat a fraction as cache-creation on first use in window
                b["cache_creation"] += int(ev.cached_input_tokens * 0.05)
            else:
                b["uncached"] += ev.input_tokens

        for (model_id, app_id), b in buckets.items():
            doc = metric_doc(self.DATASET, t0, "usage", 3600 * 1000)
            doc["anthropic"] = {"usage": {
                "model": model_id,
                "workspace_id": f"ws_meridian_{app_id.replace('-', '_')}",
                "api_key_id": f"sk-ant-api-{app_id[:8]}",
                "service_tier": "standard",
                "inference_geo": "us",
                "context_window": "0-200k",
                "bucket_start_time": iso(t0),
                "bucket_end_time": iso(t1),
                "uncached_input_tokens": b["uncached"],
                "cached_input_tokens": b["cached"],
                "cache_creation_input_tokens": b["cache_creation"],
                "output_tokens": b["output"],
            }}
            doc["labels"] = {"app": app_id}
            doc["tags"] = ["synthetic", "anthropic"]
            yield doc


class _AnthropicCost:
    DATA_STREAM = "metrics-anthropic_metrics.cost-default"
    DATASET = "anthropic_metrics.cost"

    def emit(self, world, t0, t1, anchor):
        # Daily cost docs at midnight boundaries
        from src.generators.common import aligned
        for ts in aligned(t0, t1, 24 * 60):
            day = ts - timedelta(days=1)
            day_end = ts
            by_model = defaultdict(lambda: {
                "uncached": 0, "cached": 0, "output": 0, "cost": 0.0, "app": None,
            })
            hour = day
            while hour < day_end:
                nxt = min(hour + timedelta(hours=1), day_end)
                for ev in iter_events(world, hour, nxt, anchor):
                    if ev.model["provider"] != "anthropic":
                        continue
                    b = by_model[ev.model["id"]]
                    b["uncached"] += max(0, ev.input_tokens - ev.cached_input_tokens)
                    b["cached"] += ev.cached_input_tokens
                    b["output"] += ev.output_tokens
                    b["cost"] += ev.cost_usd
                    b["app"] = ev.app["id"]
                hour = nxt

            for model_id, b in by_model.items():
                # Anthropic cost API returns amount in cents
                for token_type, tokens, usd_share in (
                    ("uncached_input_tokens", b["uncached"], 0.55),
                    ("cache_read_input_tokens", b["cached"], 0.10),
                    ("output_tokens", b["output"], 0.35),
                ):
                    amount_cents = round(b["cost"] * usd_share * 100, 2)
                    if amount_cents <= 0:
                        continue
                    doc = metric_doc(self.DATASET, ts, "cost", 24 * 3600 * 1000)
                    doc["anthropic"] = {"cost": {
                        "amount": amount_cents,
                        "currency": "USD",
                        "model": model_id,
                        "workspace_id": f"ws_meridian_{(b['app'] or 'default').replace('-', '_')}",
                        "service_tier": "standard",
                        "cost_type": "tokens",
                        "token_type": token_type,
                        "context_window": "0-200k",
                        "inference_geo": "us",
                        "description": f"{model_id} {token_type}",
                        "bucket_start_time": iso(day),
                        "bucket_end_time": iso(ts),
                    }}
                    doc["tags"] = ["synthetic", "anthropic"]
                    yield doc


anthropic_usage = _AnthropicUsage()
anthropic_cost = _AnthropicCost()
