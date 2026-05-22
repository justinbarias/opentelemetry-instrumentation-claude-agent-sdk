"""Span creation and attribute helpers for GenAI semantic conventions."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from opentelemetry.trace import SpanKind, StatusCode, Tracer

from opentelemetry.instrumentation.claude_agent_sdk._constants import (
    ERROR_TYPE,
    ERROR_TYPE_OTHER,
    FINISH_REASON_MAP,
    GEN_AI_AGENT_NAME,
    GEN_AI_CONVERSATION_ID,
    GEN_AI_INPUT_MESSAGES,
    GEN_AI_OPERATION_NAME,
    GEN_AI_OUTPUT_MESSAGES,
    GEN_AI_PROVIDER_NAME,
    GEN_AI_REQUEST_MODEL,
    GEN_AI_RESPONSE_FINISH_REASONS,
    GEN_AI_RESPONSE_MODEL,
    GEN_AI_SYSTEM_INSTRUCTIONS,
    GEN_AI_TOOL_CALL_ID,
    GEN_AI_TOOL_DEFINITIONS,
    GEN_AI_TOOL_NAME,
    GEN_AI_TOOL_TYPE,
    GEN_AI_USAGE_CACHE_CREATION_INPUT_TOKENS,
    GEN_AI_USAGE_CACHE_READ_INPUT_TOKENS,
    GEN_AI_USAGE_INPUT_TOKENS,
    GEN_AI_USAGE_OUTPUT_TOKENS,
    MCP_TOOL_PREFIX,
    OPERATION_EXECUTE_TOOL,
    OPERATION_INVOKE_AGENT,
    SYSTEM_ANTHROPIC,
    TOOL_TYPE_EXTENSION,
    TOOL_TYPE_FUNCTION,
)

if TYPE_CHECKING:
    from opentelemetry.context import Context
    from opentelemetry.trace import Span


def create_invoke_agent_span(
    tracer: Tracer,
    agent_name: str | None = None,
    request_model: str | None = None,
    options: Any = None,
) -> Span:
    """Create an invoke_agent CLIENT span with GenAI semantic convention attributes.

    Args:
        tracer: OTel tracer instance.
        agent_name: Optional agent name for span name and attribute.
        request_model: Optional model name for gen_ai.request.model.
        options: Optional ClaudeAgentOptions (used to extract model if request_model not set).

    Returns:
        A started span (must be ended by caller).
    """
    span_name = f"{OPERATION_INVOKE_AGENT} {agent_name}" if agent_name else OPERATION_INVOKE_AGENT

    attributes: dict[str, str | int | list[str]] = {
        GEN_AI_OPERATION_NAME: OPERATION_INVOKE_AGENT,
        GEN_AI_PROVIDER_NAME: SYSTEM_ANTHROPIC,
    }

    if agent_name:
        attributes[GEN_AI_AGENT_NAME] = agent_name

    # Resolve model: explicit param > options.model
    model = request_model
    if model is None and options is not None:
        model = getattr(options, "model", None)
    if model is not None:
        attributes[GEN_AI_REQUEST_MODEL] = model

    return tracer.start_span(name=span_name, kind=SpanKind.CLIENT, attributes=attributes)


def set_result_attributes(span: Span, result_message: Any) -> None:
    """Set token usage, finish reason, and conversation.id from a ResultMessage.

    Args:
        span: The invoke_agent span to annotate.
        result_message: SDK ResultMessage with usage, session_id, subtype.
    """
    usage = getattr(result_message, "usage", None)
    if usage is not None:
        input_tokens = usage.get("input_tokens", 0) or 0
        cache_creation = usage.get("cache_creation_input_tokens", 0) or 0
        cache_read = usage.get("cache_read_input_tokens", 0) or 0
        output_tokens = usage.get("output_tokens", 0) or 0

        total_input = input_tokens + cache_creation + cache_read
        span.set_attribute(GEN_AI_USAGE_INPUT_TOKENS, total_input)
        span.set_attribute(GEN_AI_USAGE_OUTPUT_TOKENS, output_tokens)

        if cache_creation > 0:
            span.set_attribute(GEN_AI_USAGE_CACHE_CREATION_INPUT_TOKENS, cache_creation)
        if cache_read > 0:
            span.set_attribute(GEN_AI_USAGE_CACHE_READ_INPUT_TOKENS, cache_read)

    # Finish reason
    subtype = getattr(result_message, "subtype", None)
    if subtype is not None:
        finish_reason = FINISH_REASON_MAP.get(subtype, subtype)
        span.set_attribute(GEN_AI_RESPONSE_FINISH_REASONS, [finish_reason])

    # Conversation ID from session_id
    session_id = getattr(result_message, "session_id", None)
    if session_id is not None:
        span.set_attribute(GEN_AI_CONVERSATION_ID, session_id)


def set_response_model(span: Span, model: str) -> None:
    """Set the response model attribute on a span."""
    span.set_attribute(GEN_AI_RESPONSE_MODEL, model)


def set_message_content_attributes(
    span: Span,
    *,
    input_messages: list[dict[str, Any]] | None,
    output_messages: list[dict[str, Any]] | None,
    system_instructions: list[dict[str, Any]] | None,
    tool_definitions: list[dict[str, Any]] | None,
) -> None:
    """Attach prompt/completion payloads to the GenAI span as JSON strings.

    The events spec carries these as structured attributes on a separate log
    record. Many consumers (the .NET Aspire dashboard, Microsoft.Extensions.AI,
    older OTel-aware backends) read the same payloads off the *span* instead,
    as JSON-string attributes. We emit both so either consumer renders the
    content — at the cost of a little duplication. Callers must already have
    gated on the opt-in content-capture flag before invoking this helper.
    """
    if input_messages:
        span.set_attribute(GEN_AI_INPUT_MESSAGES, json.dumps(input_messages, default=str))
    if output_messages:
        span.set_attribute(GEN_AI_OUTPUT_MESSAGES, json.dumps(output_messages, default=str))
    if system_instructions:
        span.set_attribute(GEN_AI_SYSTEM_INSTRUCTIONS, json.dumps(system_instructions, default=str))
    if tool_definitions:
        span.set_attribute(GEN_AI_TOOL_DEFINITIONS, json.dumps(tool_definitions, default=str))


def set_error_attributes(span: Span, exception: BaseException) -> None:
    """Set error.type and ERROR status on a span.

    Args:
        span: The span to annotate with error info.
        exception: The exception that occurred.
    """
    error_type = type(exception).__qualname__
    span.set_attribute(ERROR_TYPE, error_type)
    span.set_status(StatusCode.ERROR, str(exception))


# --- Tool span helpers ---


def derive_tool_type(tool_name: str) -> str:
    """Derive tool type from tool name.

    'mcp__*' tools are 'extension' (MCP tools), all others are 'function'.
    """
    if tool_name.startswith(MCP_TOOL_PREFIX):
        return TOOL_TYPE_EXTENSION
    return TOOL_TYPE_FUNCTION


def create_execute_tool_span(
    tracer: Tracer,
    tool_name: str,
    tool_use_id: str,
    parent_context: Context | None = None,
) -> Span:
    """Create an execute_tool INTERNAL span with tool attributes.

    Args:
        tracer: OTel tracer instance.
        tool_name: The tool name (e.g., 'Bash', 'mcp__server__action').
        tool_use_id: Unique tool call ID for correlation.
        parent_context: Explicit parent context.  When provided the tool span
            becomes a child of the span stored in *parent_context*.  When
            ``None`` OTel auto-parents under the current span (works in unit
            tests but not in real SDK hook callbacks which run in a separate
            async context).

    Returns:
        A started span (must be ended by caller).
    """
    span_name = f"{OPERATION_EXECUTE_TOOL} {tool_name}"
    tool_type = derive_tool_type(tool_name)

    attributes: dict[str, str] = {
        GEN_AI_OPERATION_NAME: OPERATION_EXECUTE_TOOL,
        GEN_AI_PROVIDER_NAME: SYSTEM_ANTHROPIC,
        GEN_AI_TOOL_NAME: tool_name,
        GEN_AI_TOOL_CALL_ID: tool_use_id,
        GEN_AI_TOOL_TYPE: tool_type,
    }

    return tracer.start_span(
        name=span_name,
        kind=SpanKind.INTERNAL,
        attributes=attributes,
        context=parent_context,
    )


def set_tool_error_attributes(span: Span, error_message: str) -> None:
    """Set error.type and ERROR status on a tool span.

    Args:
        span: The tool span to annotate.
        error_message: Raw error string from PostToolUseFailure.
    """
    # `error.type` is a low-cardinality classifier per OTel semconv. The SDK
    # delivers tool failures as free-form strings, not exception classes, so
    # there is no class name to record — use the spec's catch-all and keep
    # the raw text on the span status description.
    span.set_attribute(ERROR_TYPE, ERROR_TYPE_OTHER)
    span.set_status(StatusCode.ERROR, error_message)
