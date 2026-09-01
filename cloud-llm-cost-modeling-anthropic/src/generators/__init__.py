from src.generators import (
    aws_billing, aws_billing_cur, aws_cloudtrail, aws_ec2_metrics,
    aws_guardduty, aws_s3access, azure_activity, azure_billing,
    elastic_ai, ess_billing_credits,
    gcp_audit, gcp_billing,
    llm_anthropic, llm_apm, llm_azure_openai, llm_bedrock,
    llm_openai, llm_vertexai,
)

NAMED = {
    "aws_cloudtrail": aws_cloudtrail,
    "aws_guardduty": aws_guardduty,
    "aws_s3access": aws_s3access,
    "aws_ec2_metrics": aws_ec2_metrics,
    "aws_billing": aws_billing,
    "aws_billing_cur": aws_billing_cur,
    "ess_billing_credits": ess_billing_credits,
    "gcp_audit": gcp_audit,
    "gcp_billing": gcp_billing,
    "azure_activity": azure_activity,
    "azure_billing": azure_billing,
    "openai_completions": llm_openai.openai_completions,
    "openai_embeddings": llm_openai.openai_embeddings,
    "openai_images": llm_openai.openai_images,
    "openai_audio_transcriptions": llm_openai.openai_audio_transcriptions,
    "openai_audio_speeches": llm_openai.openai_audio_speeches,
    "openai_moderations": llm_openai.openai_moderations,
    "openai_rate_limits": llm_openai.openai_rate_limits,
    "anthropic_usage": llm_anthropic.anthropic_usage,
    "anthropic_cost": llm_anthropic.anthropic_cost,
    "anthropic_rate_limit": llm_anthropic.anthropic_rate_limit,
    "bedrock_invocation": llm_bedrock.bedrock_invocation,
    "bedrock_runtime": llm_bedrock.bedrock_runtime,
    "bedrock_guardrails": llm_bedrock.bedrock_guardrails,
    "azure_openai_logs": llm_azure_openai.azure_openai_logs,
    "azure_openai_metrics": llm_azure_openai.azure_openai_metrics,
    "azure_openai_billing": llm_azure_openai.azure_openai_billing,
    "vertex_prompt_logs": llm_vertexai.vertex_prompt_logs,
    "vertex_metrics": llm_vertexai.vertex_metrics,
    "vertex_audit_logs": llm_vertexai.vertex_audit_logs,
    "llm_apm": llm_apm,
    "agent_builder_traces": elastic_ai.agent_builder_traces,
    "inference_token_usage": elastic_ai.inference_token_usage,
}

ALL_NAMES = frozenset(NAMED)

CLOUD = [
    aws_cloudtrail, aws_guardduty, aws_s3access, aws_ec2_metrics, aws_billing,
    aws_billing_cur,
    ess_billing_credits,
    gcp_audit, gcp_billing,
    azure_activity, azure_billing,
]

ESS_BILLING = [ess_billing_credits]

LLM = [
    llm_openai.openai_completions, llm_openai.openai_embeddings,
    llm_openai.openai_images, llm_openai.openai_audio_transcriptions,
    llm_openai.openai_audio_speeches, llm_openai.openai_moderations,
    llm_openai.openai_rate_limits,
    llm_anthropic.anthropic_usage, llm_anthropic.anthropic_cost,
    llm_anthropic.anthropic_rate_limit,
    llm_bedrock.bedrock_invocation, llm_bedrock.bedrock_runtime,
    llm_bedrock.bedrock_guardrails,
    llm_azure_openai.azure_openai_logs, llm_azure_openai.azure_openai_metrics,
    llm_azure_openai.azure_openai_billing,
    llm_vertexai.vertex_prompt_logs, llm_vertexai.vertex_metrics,
    llm_vertexai.vertex_audit_logs,
    llm_apm,
]

OPENAI_EXTRA = [
    llm_openai.openai_images, llm_openai.openai_audio_transcriptions,
    llm_openai.openai_audio_speeches, llm_openai.openai_moderations,
    llm_openai.openai_rate_limits,
]

ELASTIC_AI = [
    elastic_ai.agent_builder_traces,
    elastic_ai.inference_token_usage,
]

ALL = CLOUD + LLM + ELASTIC_AI
LOG_GENERATORS = [g for g in ALL if getattr(g, "DATA_STREAM", "").startswith("logs-")]
METRIC_GENERATORS = [g for g in ALL if getattr(g, "DATA_STREAM", "").startswith("metrics-")]

_NAME_BY_OBJ = {id(v): k for k, v in NAMED.items()}


def generator_name(gen) -> str | None:
    return _NAME_BY_OBJ.get(id(gen))


def _by_scope(scope: str):
    if scope == "cloud":
        return CLOUD
    if scope == "llm":
        return LLM
    if scope == "openai-extra":
        return OPENAI_EXTRA
    if scope == "elastic-ai":
        return ELASTIC_AI
    if scope == "ess-billing":
        return ESS_BILLING
    return ALL


def _apply_variant(gens):
    from src.variant import active_variant
    v = active_variant()
    if v.is_all:
        return gens
    allowed = v.generator_names
    out = [g for g in gens if generator_name(g) in allowed]
    return out


def select(scope: str = "all"):
    return _apply_variant(_by_scope(scope))
