"""Daily LLM cost rollups -> metrics-llm.cost-default.

ORPHAN — not registered in src.generators.select() / ALL. Native provider
billing + APM labels.llm_cost_usd cover the live demo.

Billing-style docs: cost by provider, model, app, and cost_center for the
prior UTC day — designed for correlation with cloud billing streams.
"""
from collections import defaultdict
from datetime import timedelta

from src.generators import llm_invocation
from src.generators.common import aligned, metric_doc
from src.world.llm import load_llm_catalog

DATA_STREAM = "metrics-llm.cost-default"
DATASET = "llm.cost"
SCOPE = "llm"


def emit(world, t0, t1, anchor, catalog=None):
    catalog = catalog or load_llm_catalog()
    for ts in aligned(t0, t1, 24 * 60):
        day = ts - timedelta(days=1)
        day_end = ts
        # Aggregate a full day of invocations
        by_provider = defaultdict(lambda: {"cost": 0.0, "input": 0, "output": 0, "requests": 0})
        by_model = defaultdict(lambda: {"cost": 0.0, "input": 0, "output": 0, "requests": 0,
                                         "provider": None})
        by_app = defaultdict(lambda: {"cost": 0.0, "input": 0, "output": 0, "requests": 0,
                                       "bu": None, "labels": {}})
        by_cc = defaultdict(lambda: {"cost": 0.0, "input": 0, "output": 0, "requests": 0})

        # Walk hour-by-hour to keep memory bounded / deterministic
        hour = day
        while hour < day_end:
            nxt = hour + timedelta(hours=1)
            for doc in llm_invocation.emit(world, hour, nxt, anchor, catalog=catalog):
                llm = doc["llm"]
                usage = doc["gen_ai"]["usage"]
                cost = llm["cost"]["usd"]
                provider = llm["provider"]
                model_id = llm["model"]["id"]
                app = doc["service"]["name"]
                labels = doc.get("labels") or {}
                cc = labels.get("cost_center") or "untagged"

                by_provider[provider]["cost"] += cost
                by_provider[provider]["input"] += usage["input_tokens"]
                by_provider[provider]["output"] += usage["output_tokens"]
                by_provider[provider]["requests"] += 1

                by_model[(provider, model_id)]["cost"] += cost
                by_model[(provider, model_id)]["input"] += usage["input_tokens"]
                by_model[(provider, model_id)]["output"] += usage["output_tokens"]
                by_model[(provider, model_id)]["requests"] += 1
                by_model[(provider, model_id)]["provider"] = provider

                by_app[app]["cost"] += cost
                by_app[app]["input"] += usage["input_tokens"]
                by_app[app]["output"] += usage["output_tokens"]
                by_app[app]["requests"] += 1
                by_app[app]["bu"] = labels.get("team")
                by_app[app]["labels"] = labels

                by_cc[cc]["cost"] += cost
                by_cc[cc]["input"] += usage["input_tokens"]
                by_cc[cc]["output"] += usage["output_tokens"]
                by_cc[cc]["requests"] += 1
            hour = nxt

        def _base(group_type, group_key, group_value, stats, labels=None):
            doc = metric_doc(DATASET, ts, "cost", 24 * 3600 * 1000)
            doc["llm"] = {
                "billing": {
                    "date": day.strftime("%Y-%m-%d"),
                    "group_type": group_type,
                    "group_key": group_key,
                    "group_value": group_value,
                    "currency": "USD",
                    "cost_usd": round(stats["cost"], 4),
                    "input_tokens": stats["input"],
                    "output_tokens": stats["output"],
                    "total_tokens": stats["input"] + stats["output"],
                    "requests": stats["requests"],
                }
            }
            if labels:
                doc["labels"] = labels
            doc["tags"] = ["synthetic", "llm"]
            return doc

        for provider, stats in by_provider.items():
            yield _base("provider", "provider", provider, stats)

        for (provider, model_id), stats in by_model.items():
            doc = _base("model", "model", model_id, stats)
            doc["llm"]["provider"] = provider
            doc["llm"]["model"] = {"id": model_id}
            yield doc

        for app, stats in by_app.items():
            doc = _base("app", "app", app, stats, labels=stats["labels"])
            if stats["bu"]:
                doc["llm"]["business_unit"] = stats["bu"]
            yield doc

        for cc, stats in by_cc.items():
            yield _base("cost_center", "cost_center", cc, stats,
                        labels={"cost_center": cc} if cc != "untagged" else {})
