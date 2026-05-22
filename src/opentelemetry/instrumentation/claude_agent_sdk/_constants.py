"""GenAI semantic convention constants for OpenTelemetry instrumentation."""

# Schema URL — emitted on the tracer, meter, and logger so consumers can tell
# which version of the GenAI semantic conventions this instrumentation targets.
SCHEMA_URL = "https://opentelemetry.io/schemas/gen-ai/1.42.0"

# --- GenAI Attribute Keys ---
GEN_AI_OPERATION_NAME = "gen_ai.operation.name"
GEN_AI_AGENT_NAME = "gen_ai.agent.name"
GEN_AI_REQUEST_MODEL = "gen_ai.request.model"
GEN_AI_RESPONSE_MODEL = "gen_ai.response.model"
GEN_AI_RESPONSE_FINISH_REASONS = "gen_ai.response.finish_reasons"
GEN_AI_USAGE_INPUT_TOKENS = "gen_ai.usage.input_tokens"
GEN_AI_USAGE_OUTPUT_TOKENS = "gen_ai.usage.output_tokens"
GEN_AI_CONVERSATION_ID = "gen_ai.conversation.id"
GEN_AI_TOKEN_TYPE = "gen_ai.token.type"  # nosec B105

# Cache-specific attributes (dotted form per GenAI semconv 1.42.0)
GEN_AI_USAGE_CACHE_CREATION_INPUT_TOKENS = "gen_ai.usage.cache_creation.input_tokens"
GEN_AI_USAGE_CACHE_READ_INPUT_TOKENS = "gen_ai.usage.cache_read.input_tokens"

# Error attributes
ERROR_TYPE = "error.type"
# Catch-all classifier per OTel error.type spec — used when we don't have a
# real exception class (e.g. SDK tool failures arrive as strings).
ERROR_TYPE_OTHER = "_OTHER"

# Exception event attributes (standard OTel + GenAI exceptions semconv)
EXCEPTION_TYPE = "exception.type"
EXCEPTION_MESSAGE = "exception.message"
EXCEPTION_STACKTRACE = "exception.stacktrace"

# --- GenAI Events ---
EVENT_GEN_AI_CLIENT_OPERATION_EXCEPTION = "gen_ai.client.operation.exception"
EVENT_GEN_AI_CLIENT_INFERENCE_OPERATION_DETAILS = "gen_ai.client.inference.operation.details"

# --- Inference details event attribute keys ---
# Opt-in content-bearing attributes per
# https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-events/
# Gated on OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT.
GEN_AI_INPUT_MESSAGES = "gen_ai.input.messages"
GEN_AI_OUTPUT_MESSAGES = "gen_ai.output.messages"
GEN_AI_SYSTEM_INSTRUCTIONS = "gen_ai.system_instructions"
GEN_AI_TOOL_DEFINITIONS = "gen_ai.tool.definitions"

# Other inference-details attributes referenced in the spec.
GEN_AI_OUTPUT_TYPE = "gen_ai.output.type"

# Env var that opts in to capturing prompt/completion content on events.
ENV_CAPTURE_MESSAGE_CONTENT = "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"

# --- GenAI Operation Names ---
OPERATION_INVOKE_AGENT = "invoke_agent"
OPERATION_EXECUTE_TOOL = "execute_tool"

# --- Tool Attributes ---
GEN_AI_TOOL_NAME = "gen_ai.tool.name"
GEN_AI_TOOL_CALL_ID = "gen_ai.tool.call.id"
GEN_AI_TOOL_TYPE = "gen_ai.tool.type"
GEN_AI_TOOL_CALL_ARGUMENTS = "gen_ai.tool.call.arguments"
GEN_AI_TOOL_CALL_RESULT = "gen_ai.tool.call.result"
TOOL_TYPE_EXTENSION = "extension"
TOOL_TYPE_FUNCTION = "function"
MCP_TOOL_PREFIX = "mcp__"

# --- Provider Name ---
# `gen_ai.provider.name` is the spec-current key. The pre-1.37 key
# `gen_ai.system` was renamed and is no longer emitted.
GEN_AI_PROVIDER_NAME = "gen_ai.provider.name"

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
# Maps the SDK's ResultMessage.subtype to a finish-reason string.
#
# `max_turns` is the SDK's orchestration-level turn-count cap, not a model
# stop reason — mapping it to the model-side `max_tokens` would mislead any
# consumer filtering on this attribute. We pass it through as `"max_turns"`
# so downstream backends can tell the two cases apart. `success` continues
# to surface as the canonical `end_turn`; everything else passes through.
FINISH_REASON_MAP: dict[str, str] = {
    "success": "end_turn",
    "error": "error",
    "max_turns": "max_turns",
}
