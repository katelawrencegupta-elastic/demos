"""OpenAI Usage API shape -> native logs-openai.* streams.

Emits hourly usage buckets as raw JSON in `message` for the integration
pipeline. start_time/end_time are UNIX seconds (the Fleet date processor
fails on ISO strings).
"""
import json
from collections import defaultdict

from src.generators.common import iso, log_doc, poisson_count
from src.world.llm_traffic import iter_events
from src.world.scenarios import diurnal, rng_for, weekday_factor

SCOPE = "llm"


def _unix(dt):
    return int(dt.timestamp())


def _usage_doc(dataset, ts, t1, payload):
    payload = {
        **payload,
        "start_time": _unix(ts),
        "end_time": _unix(t1),
    }
    doc = log_doc(dataset, ts, json.dumps(payload))
    doc["event"] = {"dataset": dataset}
    return doc


def _user(world, bu, rng):
    humans = world.humans_in_bu(bu) or world.identities
    actor = rng.choice(humans)
    return f"user-{actor.user.replace('.', '_')}"


def _ids(app_id):
    return {
        "project_id": f"proj_meridian_{app_id.replace('-', '_')}",
        "api_key_id": f"key_{app_id[:12]}",
    }


class _OpenAICompletions:
    DATA_STREAM = "logs-openai.completions-default"
    DATASET = "openai.completions"

    def emit(self, world, t0, t1, anchor):
        buckets = defaultdict(lambda: {
            "requests": 0, "input": 0, "output": 0, "cached": 0,
            "user": None,
        })
        for ev in iter_events(world, t0, t1, anchor):
            if ev.model["provider"] != "openai" or ev.op != "chat":
                continue
            key = (ev.model["id"], ev.actor_user, ev.app["id"])
            b = buckets[key]
            b["requests"] += 1
            b["input"] += ev.input_tokens
            b["output"] += ev.output_tokens
            b["cached"] += ev.cached_input_tokens
            b["user"] = f"user-{ev.actor_user.replace('.', '_')}"

        for (model_id, _, app_id), b in buckets.items():
            yield _usage_doc(self.DATASET, t0, t1, {
                "object": "organization.usage.completions.result",
                "model": model_id,
                **_ids(app_id),
                "user_id": b["user"],
                "num_model_requests": b["requests"],
                "input_tokens": b["input"],
                "output_tokens": b["output"],
                "input_cached_tokens": b["cached"],
                "input_audio_tokens": 0,
                "output_audio_tokens": 0,
                "batch": False,
            })


class _OpenAIEmbeddings:
    DATA_STREAM = "logs-openai.embeddings-default"
    DATASET = "openai.embeddings"

    def emit(self, world, t0, t1, anchor):
        buckets = defaultdict(lambda: {"requests": 0, "input": 0, "user": None})
        for ev in iter_events(world, t0, t1, anchor):
            if ev.model["provider"] != "openai" or ev.op != "embeddings":
                continue
            key = (ev.model["id"], ev.actor_user, ev.app["id"])
            b = buckets[key]
            b["requests"] += 1
            b["input"] += ev.input_tokens
            b["user"] = f"user-{ev.actor_user.replace('.', '_')}"

        for (model_id, _, app_id), b in buckets.items():
            yield _usage_doc(self.DATASET, t0, t1, {
                "object": "organization.usage.embeddings.result",
                "model": model_id,
                **_ids(app_id),
                "user_id": b["user"],
                "num_model_requests": b["requests"],
                "input_tokens": b["input"],
            })


class _OpenAIImages:
    DATA_STREAM = "logs-openai.images-default"
    DATASET = "openai.images"
    WORKLOADS = (
        ("checkout-assistant", "ecommerce", ["gpt-image-1", "dall-e-3"], 4.0),
        ("support-copilot", "ecommerce", ["gpt-image-1"], 1.5),
        ("prompt-playground", "skunkworks", ["gpt-image-1", "dall-e-3"], 3.0),
    )
    SIZES = ("1024x1024", "1024x1792", "1792x1024", "512x512")

    def emit(self, world, t0, t1, anchor):
        rng = rng_for("oaiimg", t0.isoformat())
        load = diurnal(t0) * weekday_factor(t0)
        for app_id, bu, models, rate in self.WORKLOADS:
            for model in models:
                n = poisson_count(rng, rate * load)
                if n <= 0:
                    continue
                size = rng.choice(self.SIZES)
                yield _usage_doc(self.DATASET, t0, t1, {
                    "object": "organization.usage.images.result",
                    "model": model,
                    **_ids(app_id),
                    "user_id": _user(world, bu, rng),
                    "num_model_requests": n,
                    "images": n * rng.randint(1, 3),
                    "size": size,
                    "source": rng.choice(
                        ["image.generation", "image.edit", "image.variation"]),
                })


class _OpenAIAudioTranscriptions:
    DATA_STREAM = "logs-openai.audio_transcriptions-default"
    DATASET = "openai.audio_transcriptions"
    WORKLOADS = (
        ("support-copilot", "ecommerce", ["whisper-1", "gpt-4o-transcribe"], 3.0),
        ("doc-summarizer", "corpit", ["whisper-1"], 2.0),
        ("prompt-playground", "skunkworks", ["whisper-1", "gpt-4o-mini-transcribe"], 1.2),
    )

    def emit(self, world, t0, t1, anchor):
        rng = rng_for("oaitx", t0.isoformat())
        load = diurnal(t0) * weekday_factor(t0)
        for app_id, bu, models, rate in self.WORKLOADS:
            for model in models:
                n = poisson_count(rng, rate * load)
                if n <= 0:
                    continue
                yield _usage_doc(self.DATASET, t0, t1, {
                    "object": "organization.usage.audio_transcriptions.result",
                    "model": model,
                    **_ids(app_id),
                    "user_id": _user(world, bu, rng),
                    "num_model_requests": n,
                    "seconds": n * rng.randint(20, 180),
                })


class _OpenAIAudioSpeeches:
    DATA_STREAM = "logs-openai.audio_speeches-default"
    DATASET = "openai.audio_speeches"
    WORKLOADS = (
        ("checkout-assistant", "ecommerce", ["tts-1", "gpt-4o-mini-tts"], 2.5),
        ("support-copilot", "ecommerce", ["tts-1-hd"], 1.8),
        ("prompt-playground", "skunkworks", ["tts-1", "tts-1-hd"], 1.4),
    )

    def emit(self, world, t0, t1, anchor):
        rng = rng_for("oaits", t0.isoformat())
        load = diurnal(t0) * weekday_factor(t0)
        for app_id, bu, models, rate in self.WORKLOADS:
            for model in models:
                n = poisson_count(rng, rate * load)
                if n <= 0:
                    continue
                yield _usage_doc(self.DATASET, t0, t1, {
                    "object": "organization.usage.audio_speeches.result",
                    "model": model,
                    **_ids(app_id),
                    "user_id": _user(world, bu, rng),
                    "num_model_requests": n,
                    "characters": n * rng.randint(80, 700),
                })


class _OpenAIModerations:
    DATA_STREAM = "logs-openai.moderations-default"
    DATASET = "openai.moderations"
    APPS = (
        ("kyc-classifier", "fintech", 4.0),
        ("support-copilot", "ecommerce", 2.5),
        ("checkout-assistant", "ecommerce", 1.5),
        ("prompt-playground", "skunkworks", 1.0),
    )

    def emit(self, world, t0, t1, anchor):
        rng = rng_for("oaimod", t0.isoformat())
        load = diurnal(t0) * weekday_factor(t0)
        for app_id, bu, rate in self.APPS:
            n = poisson_count(rng, rate * load)
            if n <= 0:
                continue
            yield _usage_doc(self.DATASET, t0, t1, {
                "object": "organization.usage.moderations.result",
                "model": "omni-moderation-latest",
                **_ids(app_id),
                "user_id": _user(world, bu, rng),
                "num_model_requests": n,
                "input_tokens": n * rng.randint(80, 400),
            })


# (rpm, tpm, ipm) — scaled so hourly usage buckets show meaningful headroom.
_RATE_LIMITS = {
    "gpt-4o-mini": (5000, 4_000_000, None),
    "gpt-4o": (4000, 2_000_000, None),
    "gpt-5.4-mini": (5000, 4_000_000, None),
    "gpt-5.4": (2000, 1_500_000, None),
    "gpt-5.6-sol": (500, 800_000, None),
    "o3": (1000, 1_000_000, None),
    "text-embedding-3-large": (10000, 10_000_000, None),
    "gpt-image-1": (100, None, 50),
    "dall-e-3": (50, None, 30),
    "whisper-1": (500, None, None),
    "gpt-4o-transcribe": (500, None, None),
    "gpt-4o-mini-transcribe": (500, None, None),
    "tts-1": (500, None, None),
    "tts-1-hd": (100, None, None),
    "gpt-4o-mini-tts": (500, None, None),
    "omni-moderation-latest": (1000, 1_500_000, None),
}


class _OpenAIRateLimits:
    DATA_STREAM = "logs-openai.rate_limits-default"
    DATASET = "openai.rate_limits"

    def emit(self, world, t0, t1, anchor):
        # Snapshot every 6 hours so MAX(limit) is stable across the window.
        if t0.hour % 6 != 0:
            return
        rng = rng_for("oairl", t0.date().isoformat())
        app_ids = [
            "checkout-assistant", "catalog-search-embed", "support-copilot",
            "feature-ranker", "rag-research", "doc-summarizer", "kyc-classifier",
            "prompt-playground", "fraud-nlp", "skunk-agent-lab",
        ]
        for app_id in app_ids:
            for model, (rpm, tpm, ipm) in _RATE_LIMITS.items():
                jitter = 1 + rng.uniform(-0.05, 0.05)
                payload = {
                    "object": "project.rate_limit",
                    "id": f"rl_{app_id[:8]}_{model[:12]}",
                    "model": model,
                    "project_id": f"proj_meridian_{app_id.replace('-', '_')}",
                    "project_name": f"Meridian {app_id}",
                    "project_status": "active",
                    "max_requests_per_1_minute": int(rpm * jitter),
                    "max_requests_per_1_day": int(rpm * jitter) * 60 * 12,
                    "collected_at": iso(t0),
                }
                if tpm:
                    payload["max_tokens_per_1_minute"] = int(tpm * jitter)
                    payload["max_tokens_per_1_day"] = int(tpm * jitter) * 60 * 12
                if ipm:
                    payload["max_images_per_1_minute"] = int(ipm * jitter)
                doc = log_doc(self.DATASET, t0, json.dumps(payload))
                doc["event"] = {"dataset": self.DATASET}
                yield doc


openai_completions = _OpenAICompletions()
openai_embeddings = _OpenAIEmbeddings()
openai_images = _OpenAIImages()
openai_audio_transcriptions = _OpenAIAudioTranscriptions()
openai_audio_speeches = _OpenAIAudioSpeeches()
openai_moderations = _OpenAIModerations()
openai_rate_limits = _OpenAIRateLimits()
