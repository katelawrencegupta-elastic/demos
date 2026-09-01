"""Derive which FinOps dashboard panels apply to the active workshop variant."""
from __future__ import annotations

from dataclasses import dataclass

from src.variant import Variant, active_variant

TS = "@timestamp >= ?_tstart AND @timestamp <= ?_tend"


@dataclass(frozen=True)
class DashboardCaps:
    aws_cur: bool
    aws_tags: bool
    aws_ec2: bool
    aws_security: bool
    gcp_billing: bool
    azure_billing: bool
    llm_apm: bool
    openai: bool
    anthropic: bool
    bedrock: bool
    vertex: bool
    azure_openai: bool
    ess: bool
    budgets: bool
    classic_layout: bool
    ai_dashboard: bool

    @property
    def any_cloud_billing(self) -> bool:
        return self.aws_cur or self.gcp_billing or self.azure_billing

    @property
    def multi_cloud_billing(self) -> bool:
        return sum((self.aws_cur, self.gcp_billing, self.azure_billing)) > 1

    def cloud_billing_streams(self) -> list[str]:
        streams = []
        if self.aws_cur:
            streams.append("metrics-aws_billing.cur-default")
        if self.gcp_billing:
            streams.append("metrics-gcp.billing-default")
        if self.azure_billing:
            streams.append("metrics-azure.billing-default")
        return streams

    def cloud_mix_query(self, _q) -> str | None:
        streams = self.cloud_billing_streams()
        if not streams:
            return None
        from_clause = ", ".join(streams)
        return _q(
            f"FROM {from_clause}",
            f"| WHERE {TS}",
            "| EVAL cost = COALESCE(aws_billing.cur.line_item.unblended_cost, gcp.billing.total, azure.billing.pretax_cost)",
            "| EVAL provider = data_stream.dataset",
            "| STATS cost = SUM(cost) BY provider",
            "| SORT cost DESC",
        )

    def daily_cloud_query(self, _q) -> str | None:
        streams = self.cloud_billing_streams()
        if not streams:
            return None
        from_clause = ", ".join(streams)
        return _q(
            f"FROM {from_clause}",
            f"| WHERE {TS}",
            "| EVAL cost = COALESCE(aws_billing.cur.line_item.unblended_cost, gcp.billing.total, azure.billing.pretax_cost)",
            "| EVAL provider = data_stream.dataset",
            "| STATS cost = SUM(cost) BY day = BUCKET(@timestamp, 1d), provider",
            "| SORT day",
        )


def caps_from_variant(v: Variant | None = None) -> DashboardCaps:
    v = v or active_variant()
    g = v.generator_names
    all_ = v.is_all

    def has(*names: str) -> bool:
        return all_ or any(n in g for n in names)

    def has_prefix(prefix: str) -> bool:
        return all_ or any(n.startswith(prefix) for n in g)

    dash = v.dashboards
    return DashboardCaps(
        aws_cur=has("aws_billing_cur"),
        aws_tags=has("aws_billing"),
        aws_ec2=has("aws_ec2_metrics"),
        aws_security=has("aws_guardduty", "aws_cloudtrail"),
        gcp_billing=has("gcp_billing"),
        azure_billing=has("azure_billing", "azure_openai_billing"),
        llm_apm=has("llm_apm"),
        openai=has_prefix("openai_"),
        anthropic=has_prefix("anthropic_"),
        bedrock=has_prefix("bedrock_"),
        vertex=has_prefix("vertex_"),
        azure_openai=has_prefix("azure_openai_"),
        ess=has("ess_billing_credits"),
        budgets=v.setup_enabled("budgets"),
        classic_layout=bool(dash.get("classic")),
        ai_dashboard=bool(dash.get("ai")),
    )
