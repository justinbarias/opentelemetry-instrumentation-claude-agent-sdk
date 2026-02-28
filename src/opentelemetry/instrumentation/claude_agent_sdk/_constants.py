"""GenAI semantic convention constants for OpenTelemetry instrumentation."""

# --- GenAI Attribute Keys ---
GEN_AI_OPERATION_NAME = "gen_ai.operation.name"
GEN_AI_SYSTEM = "gen_ai.system"
GEN_AI_AGENT_NAME = "gen_ai.agent.name"
GEN_AI_REQUEST_MODEL = "gen_ai.request.model"
GEN_AI_RESPONSE_MODEL = "gen_ai.response.model"
GEN_AI_RESPONSE_FINISH_REASONS = "gen_ai.response.finish_reasons"
GEN_AI_USAGE_INPUT_TOKENS = "gen_ai.usage.input_tokens"
GEN_AI_USAGE_OUTPUT_TOKENS = "gen_ai.usage.output_tokens"
GEN_AI_CONVERSATION_ID = "gen_ai.conversation.id"
GEN_AI_TOKEN_TYPE = "gen_ai.token.type"  # nosec B105

# Cache-specific attributes
GEN_AI_USAGE_CACHE_CREATION_INPUT_TOKENS = "gen_ai.usage.cache_creation_input_tokens"
GEN_AI_USAGE_CACHE_READ_INPUT_TOKENS = "gen_ai.usage.cache_read_input_tokens"

# Error attributes
ERROR_TYPE = "error.type"

# --- GenAI Operation Names ---
OPERATION_INVOKE_AGENT = "invoke_agent"

# --- GenAI System Values ---
SYSTEM_ANTHROPIC = "anthropic"

# --- Metric Names ---
GEN_AI_CLIENT_TOKEN_USAGE = "gen_ai.client.token.usage"  # nosec B105
GEN_AI_CLIENT_OPERATION_DURATION = "gen_ai.client.operation.duration"

# --- Histogram Bucket Boundaries ---
TOKEN_USAGE_BUCKETS = [
    1,
    4,
    16,
    64,
    256,
    1024,
    4096,
    16384,
    65536,
    262144,
    1048576,
    4194304,
    16777216,
    67108864,
]

DURATION_BUCKETS = [
    0.01,
    0.02,
    0.04,
    0.08,
    0.16,
    0.32,
    0.64,
    1.28,
    2.56,
    5.12,
    10.24,
    20.48,
    40.96,
    81.92,
]

# --- Finish Reason Mapping ---
FINISH_REASON_MAP: dict[str, str] = {
    "success": "end_turn",
    "error": "error",
    "max_turns": "max_tokens",
}
