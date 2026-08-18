"""LLM model catalog + app workloads loaded from config/llm_models.yaml."""
from pathlib import Path

import yaml

from src.config import ROOT

LLM_CONFIG = ROOT / "config" / "llm_models.yaml"


class LlmCatalog:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.models = cfg["models"]
        self.apps = cfg["apps"]
        # (provider, id) unique key — azure and openai can share model ids
        self._by_key = {(m["provider"], m["id"]): m for m in self.models}

    def model(self, provider: str, model_id: str) -> dict:
        return self._by_key[(provider, model_id)]

    def models_for(self, provider: str = None, op: str = None, tier: str = None):
        out = self.models
        if provider:
            out = [m for m in out if m["provider"] == provider]
        if op:
            out = [m for m in out if op in m["ops"]]
        if tier:
            out = [m for m in out if m["tier"] == tier]
        return out

    def pick_model(self, rng, app: dict, provider: str = None) -> dict:
        """Choose a model for an app, optionally forcing a provider."""
        preferred = app["preferred_models"]
        providers = [provider] if provider else app["primary_providers"]
        candidates = []
        for m in self.models:
            if m["provider"] not in providers:
                continue
            if m["id"] in preferred or any(p == m["id"] for p in preferred):
                candidates.append(m)
        if not candidates:
            # fall back to any model for the provider that supports the app's ops
            op = app["ops"][0]
            candidates = [m for m in self.models
                          if m["provider"] in providers and op in m["ops"]]
        if not candidates:
            candidates = self.models_for(op=app["ops"][0])
        # weight preferred / cheaper models higher for volume apps
        weights = []
        for m in candidates:
            w = 3 if m["id"] in preferred else 1
            if m["tier"] == "cheap":
                w *= 2
            if m["tier"] == "flagship":
                w *= 0.5
            weights.append(w)
        return rng.choices(candidates, weights=weights)[0]


def load_llm_catalog() -> LlmCatalog:
    return LlmCatalog(yaml.safe_load(LLM_CONFIG.read_text()))


def token_cost_usd(model: dict, input_tokens: int, output_tokens: int,
                   cached_input_tokens: int = 0) -> float:
    """USD for a single invocation given list prices."""
    billable_input = max(0, input_tokens - cached_input_tokens)
    cost = (billable_input / 1_000_000.0) * model["input_per_m"]
    cost += (cached_input_tokens / 1_000_000.0) * model["cached_input_per_m"]
    cost += (output_tokens / 1_000_000.0) * model["output_per_m"]
    return round(cost, 8)
