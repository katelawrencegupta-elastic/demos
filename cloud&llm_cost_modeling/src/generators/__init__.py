from src.generators import (
    aws_billing, aws_billing_cur, aws_cloudtrail, aws_ec2_metrics,
    aws_guardduty, aws_s3access, azure_activity, azure_billing,
    gcp_audit, gcp_billing,
    llm_anthropic, llm_apm, llm_azure_openai, llm_bedrock,
    llm_openai, llm_vertexai,
)

CLOUD = [
    aws_cloudtrail, aws_guardduty, aws_s3access, aws_ec2_metrics, aws_billing,
    aws_billing_cur,
    gcp_audit, gcp_billing,
    azure_activity, azure_billing,
]

LLM = [
    llm_openai.openai_completions, llm_openai.openai_embeddings,
    llm_openai.openai_images, llm_openai.openai_audio_transcriptions,
    llm_openai.openai_audio_speeches, llm_openai.openai_moderations,
    llm_openai.openai_rate_limits,
    llm_anthropic.anthropic_usage, llm_anthropic.anthropic_cost,
    llm_bedrock.bedrock_invocation, llm_bedrock.bedrock_runtime,
    llm_azure_openai.azure_openai_logs, llm_azure_openai.azure_openai_metrics,
    llm_azure_openai.azure_openai_billing,
    llm_vertexai.vertex_prompt_logs, llm_vertexai.vertex_metrics,
    llm_apm,
]

# Extra OpenAI Usage streams (images/audio/moderations/rate limits). Used to
# fill OOTB dashboard panels without re-indexing completions/embeddings.
OPENAI_EXTRA = [
    llm_openai.openai_images, llm_openai.openai_audio_transcriptions,
    llm_openai.openai_audio_speeches, llm_openai.openai_moderations,
    llm_openai.openai_rate_limits,
]

ALL = CLOUD + LLM
LOG_GENERATORS = [g for g in ALL if getattr(g, "DATA_STREAM", "").startswith("logs-")]
METRIC_GENERATORS = [g for g in ALL if getattr(g, "DATA_STREAM", "").startswith("metrics-")]


def select(scope: str = "all"):
    if scope == "cloud":
        return CLOUD
    if scope == "llm":
        return LLM
    if scope == "openai-extra":
        return OPENAI_EXTRA
    return ALL
