"""Generator registry."""
from src.generators import apm, apm_deps, infra, k8s, orchestrator

GENERATORS = {
    "orchestrator": orchestrator,
    "apm": apm,
    "apm_deps": apm_deps,
    "k8s": k8s,
    "infra": infra,
}


def select(scope: str = "all"):
    if scope == "all":
        return list(GENERATORS.values())
    if scope == "traces":
        return [apm, apm_deps]
    if scope == "k8s":
        # Pods + hosts + nodes + APM runtime metrics
        return [k8s, infra]
    if scope not in GENERATORS:
        raise SystemExit(
            f"unknown scope {scope}; choose all|traces|{'|'.join(GENERATORS)}"
        )
    return [GENERATORS[scope]]
