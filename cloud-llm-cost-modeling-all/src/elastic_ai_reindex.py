"""Wipe + re-backfill Elastic AI Assistant synthetic data streams.

Used after renaming Agent Builder agent IDs (e.g. finops-copilot →
meridian-finops-ai-assistant) so dashboards and verify stay aligned.
"""
from __future__ import annotations

import requests

from src.agent_builder import agent_id
from src.config import ELASTIC_URL, ES_HEADERS

ELASTIC_AI_STREAMS = [
    "traces-agent_builder.otel-default",
    "logs-elastic.inference_token_usage-default",
]

LEGACY_FINOPS_AGENT_ID = "finops-copilot"


def _delete_query(data_stream: str, *, all_docs: bool) -> dict:
    if all_docs:
        return {"match_all": {}}
    if data_stream == "traces-agent_builder.otel-default":
        # OTel spans have no tags field; keep live Agent Builder chat (custom-* ids).
        return {
            "bool": {
                "must_not": [
                    {"prefix": {"attributes.gen_ai.agent.id": "custom-"}},
                ],
            },
        }
    return {"term": {"tags": "synthetic"}}


def wipe_elastic_ai(*, all_docs: bool = False) -> dict[str, int]:
    """Delete docs from Agent Builder + inference token-usage streams.

    Default: synthetic inference usage (``tags:synthetic``) and all Agent Builder
    traces except live chat agents (``custom-*`` ids). Pass ``all_docs=True`` to
    delete everything in those streams.
    """
    deleted: dict[str, int] = {}

    print("== Wipe elastic-ai data streams ==")
    for ds in ELASTIC_AI_STREAMS:
        query = _delete_query(ds, all_docs=all_docs)
        label = "all docs" if all_docs else (
            "non-custom Agent Builder traces" if ds.startswith("traces-")
            else "tags:synthetic")
        r = requests.post(
            f"{ELASTIC_URL}/{ds}/_delete_by_query?conflicts=proceed&refresh=true",
            headers=ES_HEADERS,
            json={"query": query},
            timeout=300,
        )
        if r.status_code >= 300:
            raise SystemExit(
                f"  [fail] delete {ds}: {r.status_code} {r.text[:400]}")
        n = int(r.json().get("deleted") or 0)
        deleted[ds] = n
        print(f"  [ok] {ds}: deleted {n:,} ({label})")
    return deleted


def reindex_elastic_ai(days: int, *, all_docs: bool = False) -> None:
    """Delete elastic-ai stream docs, then backfill ``--scope elastic-ai``."""
    from src.cli import cmd_backfill

    wipe_elastic_ai(all_docs=all_docs)
    print()
    cmd_backfill(days, "elastic-ai")


def verify_finops_agent_traces(agents: dict[str, int], total_traces: int) -> bool:
    """Return False if legacy finops-copilot remains or FinOps agent is missing."""
    ok = True
    finops_id = agent_id()
    legacy = agents.get(LEGACY_FINOPS_AGENT_ID, 0)
    finops = agents.get(finops_id, 0)

    if legacy:
        print(f"  [fail] legacy agent {LEGACY_FINOPS_AGENT_ID}: {legacy:,} traces "
              f"(run: python -m src.cli reindex-elastic-ai)")
        ok = False
    else:
        print(f"  [ok] no legacy {LEGACY_FINOPS_AGENT_ID} traces")

    if total_traces == 0:
        print("  [warn] Agent Builder traces: 0 docs")
    elif finops == 0:
        print(f"  [fail] missing {finops_id} traces (run: python -m src.cli reindex-elastic-ai)")
        ok = False
    else:
        print(f"  [ok] {finops_id}: {finops:,} traces")
    return ok
