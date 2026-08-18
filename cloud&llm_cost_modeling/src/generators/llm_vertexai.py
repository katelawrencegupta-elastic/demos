"""GCP Vertex AI -> logs-gcp_vertexai.prompt_response_logs + metrics-gcp_vertexai.metrics."""
from collections import defaultdict

from src.generators.common import iso, metric_doc
from src.world.llm_traffic import iter_events

SCOPE = "llm"
SAMPLE = 0.35


class _VertexPromptLogs:
    DATA_STREAM = "logs-gcp_vertexai.prompt_response_logs-default"
    DATASET = "gcp_vertexai.prompt_response_logs"

    def emit(self, world, t0, t1, anchor):
        from src.world.scenarios import rng_for
        rng = rng_for("vertex_pr", t0.isoformat())
        proj = next(p for p in world.cfg["gcp"]["projects"]
                    if p["id"] == "meridian-ml-prod")
        for ev in iter_events(world, t0, t1, anchor):
            if ev.model["provider"] != "google":
                continue
            if rng.random() > SAMPLE:
                continue
            # Pipeline expects gcp.vertexai_logs which it renames
            doc = {
                "@timestamp": iso(ev.ts),
                "data_stream": {"type": "logs", "dataset": self.DATASET,
                                "namespace": "default"},
                "cloud": {"provider": "gcp", "project": {"id": proj["id"]},
                          "region": world.cfg["gcp"]["regions"][0]},
                "gcp": {"vertexai_logs": {
                    "api_method": ("google.cloud.aiplatform.v1.PredictionService.Predict"
                                   if ev.op == "chat"
                                   else "google.cloud.aiplatform.v1.PredictionService.Predict"),
                    "model": ev.model["id"],
                    "model_version": "001",
                    "request_id": ev.request_id,
                    "logging_time": iso(ev.ts),
                    "request_payload": f'[{{"role":"user","content":"[{ev.app["id"]}]"}}]',
                    "response_payload": '{"candidates":[{"content":{"role":"model","parts":[{"text":"..."}]}}]}',
                    "metadata": {"request_latency": float(ev.latency_ms)},
                    "full_request": {
                        "model": f"publishers/google/models/{ev.model['id']}",
                        "contents": [{"role": "user",
                                      "parts": [{"text": f"[{ev.app['id']}] request"}]}],
                    },
                    "full_response": {
                        "model_version": ev.model["id"],
                        "response_id": ev.request_id[:16],
                        "create_time": iso(ev.ts),
                        "usage_metadata": {
                            "prompt_token_count": ev.input_tokens,
                            "candidates_token_count": ev.output_tokens,
                            "total_token_count": ev.input_tokens + ev.output_tokens,
                            "traffic_type": "ON_DEMAND",
                        },
                        "candidates": [{
                            "finish_reason": "STOP" if ev.ok else "SAFETY",
                            "content": {"role": "model", "parts": [{"text": "..."}]},
                        }],
                    },
                }},
                "labels": ev.labels,
                "user": {"name": ev.actor_user, "email": ev.actor_email},
                "service": {"name": ev.app["id"]},
                "tags": ["synthetic", "vertexai"],
                "ecs": {"version": "8.17.0"},
            }
            yield doc


class _VertexMetrics:
    DATA_STREAM = "metrics-gcp_vertexai.metrics-default"
    DATASET = "gcp_vertexai.metrics"

    def emit(self, world, t0, t1, anchor):
        buckets = defaultdict(lambda: {
            "invocations": 0, "errors": 0, "input": 0, "output": 0, "latency_sum": 0,
        })
        for ev in iter_events(world, t0, t1, anchor):
            if ev.model["provider"] != "google":
                continue
            mark = int(ev.ts.timestamp() // 300) * 300
            key = (mark, ev.model["id"])
            b = buckets[key]
            b["invocations"] += 1
            b["input"] += ev.input_tokens
            b["output"] += ev.output_tokens
            b["latency_sum"] += ev.latency_ms
            if not ev.ok:
                b["errors"] += 1

        from datetime import datetime, timezone
        proj = next(p for p in world.cfg["gcp"]["projects"]
                    if p["id"] == "meridian-ml-prod")
        for (mark, model_id), b in buckets.items():
            ts = datetime.fromtimestamp(mark, tz=timezone.utc)
            doc = metric_doc(self.DATASET, ts, "metrics", 300_000)
            doc["cloud"] = {
                "provider": "gcp",
                "project": {"id": proj["id"]},
                "region": world.cfg["gcp"]["regions"][0],
            }
            avg_lat = b["latency_sum"] / max(1, b["invocations"])
            doc["gcp"] = {
                "labels": {
                    "resource": {
                        "location": world.cfg["gcp"]["regions"][0],
                        "publisher": "google",
                        "model_user_id": model_id,
                        "resource_container": proj["id"],
                    },
                    "metrics": {"method": "Predict", "type": "online"},
                },
                "vertexai": {
                    "publisher": {"online_serving": {
                        "model_invocation_count": b["invocations"],
                        "token_count": b["input"] + b["output"],
                        "character_count": (b["input"] + b["output"]) * 4,
                        "consumed_throughput": b["input"] + b["output"],
                        "model_invocation_latencies": {
                            "values": [avg_lat],
                            "counts": [b["invocations"]],
                        },
                        "first_token_latencies": {
                            "values": [avg_lat * 0.3],
                            "counts": [b["invocations"]],
                        },
                    }},
                    "prediction": {"online": {
                        "prediction_count": b["invocations"],
                        "response_count": b["invocations"] - b["errors"],
                        "error_count": b["errors"],
                        "prediction_latencies": {
                            "values": [avg_lat],
                            "counts": [b["invocations"]],
                        },
                    }},
                },
            }
            doc["tags"] = ["synthetic", "vertexai"]
            yield doc


vertex_prompt_logs = _VertexPromptLogs()
vertex_metrics = _VertexMetrics()
