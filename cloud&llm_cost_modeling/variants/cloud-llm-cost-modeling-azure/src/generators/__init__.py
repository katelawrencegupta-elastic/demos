"""Compatibility shim — generators live in data_factories.finops.generators."""
from data_factories.finops import generators as _gens
from data_factories.finops.generators import *  # noqa: F403

# Explicit re-exports used by CLI / setup / variant tools
from data_factories.finops.generators import NAMED, ALL_NAMES, select  # noqa: F401

try:
    from data_factories.finops.generators import (  # noqa: F401
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
