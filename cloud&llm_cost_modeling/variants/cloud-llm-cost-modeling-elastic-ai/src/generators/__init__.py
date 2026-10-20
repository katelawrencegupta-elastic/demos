"""Compatibility shim — generators live in data_factories.presets.cost_modeling."""
from data_factories.presets import cost_modeling as _gens
from data_factories.presets.cost_modeling import *  # noqa: F403

# Explicit re-exports used by CLI / setup / variant tools
from data_factories.presets.cost_modeling import NAMED, ALL_NAMES, select  # noqa: F401

try:
    from data_factories.presets.cost_modeling import (  # noqa: F401
        ALL,
        CLOUD,
        ELASTIC_AI,
        ESS_BILLING,
        FINOPS_USAGE,
        LLM,
        OPENAI_EXTRA,
        generator_name,
    )
except ImportError:
    pass
