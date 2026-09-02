"""GCP Vertex AI -> prompt logs, metrics, and auditlogs data streams."""
import json
from collections import defaultdict
from datetime import datetime, timezone

from src.generators.common import iso, log_doc, metric_doc, poisson_count, spread
from src.world.llm_traffic import iter_events
from src.world.model import stable_uuid
from src.world.scenarios import (
    activity_multiplier, genai_ramp_active, ml_burn_active, rng_for,
)

SCOPE = "llm"
SAMPLE = 0.35

# OOTB Metrics Overview panels filter/break down on these labels. Real GCP
# metricbeat emits separate timeseries per label set (input vs output tokens,
# response_code, endpoint_id); pack the same shape so Lens panels light up.
_ERROR_CODES = ("400", "403", "429", "500")

# OOTB AuditLogs dashboard needs event.action, client.user.email, user_agent,
# resource_name, and source.geo (via geoip on public caller IPs).
AUDIT_RATE_PER_HOUR = 10
AUDIT_METHODS = [
    (18, "google.cloud.aiplatform.v1.PredictionService.Predict",
     "aiplatform.endpoints.predict", "aiplatform.googleapis.com/Endpoint"),
    (8, "google.cloud.aiplatform.v1.EndpointService.DeployModel",
     "aiplatform.endpoints.deploy", "aiplatform.googleapis.com/Endpoint"),
    (6, "google.cloud.aiplatform.v1.EndpointService.CreateEndpoint",
     "aiplatform.endpoints.create", "aiplatform.googleapis.com/Endpoint"),
    (7, "google.cloud.aiplatform.v1.ModelService.UploadModel",
     "aiplatform.models.upload", "aiplatform.googleapis.com/Model"),
    (10, "google.cloud.aiplatform.v1.JobService.CreateCustomJob",
     "aiplatform.customJobs.create", "aiplatform.googleapis.com/CustomJob"),
    (5, "google.cloud.aiplatform.v1.PipelineService.CreatePipelineJob",
     "aiplatform.pipelineJobs.create", "aiplatform.googleapis.com/PipelineJob"),
    (4, "google.cloud.aiplatform.v1.DatasetService.CreateDataset",
     "aiplatform.datasets.create", "aiplatform.googleapis.com/Dataset"),
]
AUDIT_USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "google-cloud-sdk gcloud/488.0.0 darwin python/3.11.9 "
    "(Macintosh; Intel Mac OS X 14.5.0) interactive/False "
    "command/ai.models.list",
    "google-api-python-client/2.131.0 (gzip)",
    "grpc-python/1.64.1 grpc-c/39.0.0 (linux; chttp2)",
]
# TEST-NET corp IPs do not geo-resolve; use public IPs so source.geo panels fill.
AUDIT_PUBLIC_IPS = [
    "8.8.8.8", "1.1.1.1", "208.67.222.222",
    "54.239.28.85", "52.95.110.1", "35.186.224.25",
    "34.102.136.180", "142.250.72.14", "185.220.101.34",
]

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


def _endpoint_id(model_id: str) -> str:
    slug = model_id.replace(".", "-").replace("_", "-")
    return f"meridian-{slug}-endpoint"


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

        from src.world.scenarios import rng_for
        proj = next(p for p in world.cfg["gcp"]["projects"]
                    if p["id"] == "meridian-ml-prod")
        region = world.cfg["gcp"]["regions"][0]
        for (mark, model_id), b in buckets.items():
            ts = datetime.fromtimestamp(mark, tz=timezone.utc)
            rng = rng_for("vertex_met", f"{mark}:{model_id}")
            avg_lat = b["latency_sum"] / max(1, b["invocations"])
            ok = max(0, b["invocations"] - b["errors"])
            endpoint = _endpoint_id(model_id)
            base_labels_resource = {
                "location": region,
                "publisher": "google",
                "model_user_id": model_id,
                "model_version_id": "001",
                "resource_container": proj["id"],
            }

            def _base():
                doc = metric_doc(self.DATASET, ts, "metrics", 300_000)
                doc["cloud"] = {
                    "provider": "gcp",
                    "project": {"id": proj["id"]},
                    "region": region,
                }
                doc["tags"] = ["synthetic", "vertexai"]
                return doc

            # Publisher: invocations + latency + throughput (response_code 200).
            inv = _base()
            inv["gcp"] = {
                "labels": {
                    "resource": dict(base_labels_resource),
                    "metrics": {
                        "method": "Predict",
                        "request_type": "online",
                        "response_code": "200",
                    },
                },
                "vertexai": {
                    "publisher": {"online_serving": {
                        "model_invocation_count": ok if ok else b["invocations"],
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
                },
            }
            yield inv

            # Token usage panels filter type:input / type:output.
            for kind, tokens in (("input", b["input"]), ("output", b["output"])):
                if tokens <= 0:
                    continue
                tok = _base()
                tok["gcp"] = {
                    "labels": {
                        "resource": dict(base_labels_resource),
                        "metrics": {
                            "method": "Predict",
                            "type": kind,
                            "response_code": "200",
                        },
                    },
                    "vertexai": {
                        "publisher": {"online_serving": {
                            "token_count": tokens,
                        }},
                    },
                }
                yield tok

            # Error-rate panels: count docs with response_code >= 400.
            err_code = None
            if b["errors"] > 0:
                err_code = _ERROR_CODES[rng.randrange(len(_ERROR_CODES))]
                err = _base()
                err["gcp"] = {
                    "labels": {
                        "resource": dict(base_labels_resource),
                        "metrics": {
                            "method": "Predict",
                            "request_type": "online",
                            "response_code": err_code,
                            "error_category": (
                                "USER" if err_code in ("400", "403") else "SYSTEM"),
                        },
                    },
                    "vertexai": {
                        "publisher": {"online_serving": {
                            "model_invocation_count": b["errors"],
                        }},
                    },
                }
                yield err

            # Endpoint prediction + infra panels (endpoint_id, cpu/mem/net).
            # Only set error_count when >0 so count(error_count) is meaningful.
            pred_online = {
                "prediction_count": b["invocations"],
                "response_count": ok,
                "prediction_latencies": {
                    "values": [avg_lat],
                    "counts": [b["invocations"]],
                },
                "cpu": {"utilization": 35.0 + rng.random() * 45.0},
                "memory": {"bytes_used": int(2.5e9 + rng.random() * 6e9)},
                "network": {
                    "received_bytes_count": int(5e5 + b["input"] * 12),
                    "sent_bytes_count": int(2e5 + b["output"] * 16),
                },
                "replicas": 1 + (b["invocations"] // 40),
                "target_replicas": 1 + (b["invocations"] // 40),
            }
            if b["errors"] > 0:
                pred_online["error_count"] = b["errors"]

            pred = _base()
            pred["gcp"] = {
                "labels": {
                    "resource": {
                        **base_labels_resource,
                        "endpoint_id": endpoint,
                    },
                    "metrics": {
                        "method": "Predict",
                        "type": "online",
                        "deployed_model_id": f"deployed-{model_id}",
                        "response_code": err_code or "200",
                    },
                },
                "vertexai": {
                    "prediction": {"online": pred_online},
                },
            }
            yield pred


class _VertexAuditLogs:
    """Raw GCP Audit LogEntry JSON -> logs-gcp_vertexai.auditlogs pipeline."""
    DATA_STREAM = "logs-gcp_vertexai.auditlogs-default"
    DATASET = "gcp_vertexai.auditlogs"

    def emit(self, world, t0, t1, anchor):
        rng = rng_for("vertex_audit", t0.isoformat())
        hours = (t1 - t0).total_seconds() / 3600
        mult = activity_multiplier(world, t0, anchor)
        projects = [p for p in world.cfg["gcp"]["projects"]
                    if p["id"] in ("meridian-ml-prod", "meridian-genai-poc",
                                   "meridian-data-warehouse")]
        if not projects:
            projects = world.cfg["gcp"]["projects"][:1]
        region = world.cfg["gcp"]["regions"][0]
        n = poisson_count(rng, AUDIT_RATE_PER_HOUR * mult * hours)
        if ml_burn_active(world, t0 + (t1 - t0) / 2, anchor):
            n += poisson_count(rng, 18 * hours)
        if genai_ramp_active(world, t0 + (t1 - t0) / 2, anchor):
            n += poisson_count(rng, 8 * hours)
        for _ in range(n):
            ts = spread(rng, t0, t1)
            proj = rng.choice(projects)
            _, method, permission, resource_type = rng.choices(
                AUDIT_METHODS, weights=[m[0] for m in AUDIT_METHODS])[0]
            principal, caller_ip = self._principal(world, rng, proj)
            ua = rng.choice(AUDIT_USER_AGENTS)
            resource_id = stable_uuid("vtxres", ts.isoformat(), method, rng.random())[:12]
            short = resource_type.rsplit("/", 1)[-1].lower() + "s"
            resource_name = (
                f"projects/{proj['id']}/locations/{region}/{short}/{resource_id}")
            tstr = ts.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
            denied = rng.random() < 0.04
            entry = {
                "insertId": stable_uuid("vtxaudit", ts.isoformat(), rng.random())[:20],
                "logName": (f"projects/{proj['id']}/logs/"
                            "cloudaudit.googleapis.com%2Fdata_access"),
                "protoPayload": {
                    "@type": "type.googleapis.com/google.cloud.audit.AuditLog",
                    "authenticationInfo": {"principalEmail": principal},
                    "authorizationInfo": [{
                        "granted": not denied,
                        "permission": permission,
                        "resourceAttributes": {"name": resource_name},
                    }],
                    "methodName": method,
                    "requestMetadata": {
                        "callerIp": caller_ip,
                        "callerSuppliedUserAgent": ua,
                    },
                    "resourceName": resource_name,
                    "serviceName": "aiplatform.googleapis.com",
                    "status": ({"code": 7, "message": "PERMISSION_DENIED"}
                               if denied else {}),
                },
                "receiveTimestamp": tstr,
                "resource": {
                    "type": "audited_resource",
                    "labels": {
                        "project_id": proj["id"],
                        "service": "aiplatform.googleapis.com",
                        "method": method,
                    },
                },
                "severity": "ERROR" if denied else "NOTICE",
                "timestamp": tstr,
            }
            yield log_doc(self.DATASET, ts, json.dumps(entry))

    @staticmethod
    def _principal(world, rng, proj):
        if rng.random() < 0.4:
            sa = rng.choice([i for i in world.identities if i.is_service])
            email = f"{sa.user}@{proj['id']}.iam.gserviceaccount.com"
            # Prefer public IP so geoip fills; fall back to known public list.
            return email, rng.choice(AUDIT_PUBLIC_IPS)
        humans = (world.humans_in_bu(proj["business_unit"])
                  or world.humans_in_bu("mlplatform")
                  or [i for i in world.identities if not i.is_service])
        h = rng.choice(humans)
        return h.email, rng.choice(AUDIT_PUBLIC_IPS)


vertex_prompt_logs = _VertexPromptLogs()
vertex_metrics = _VertexMetrics()
vertex_audit_logs = _VertexAuditLogs()
