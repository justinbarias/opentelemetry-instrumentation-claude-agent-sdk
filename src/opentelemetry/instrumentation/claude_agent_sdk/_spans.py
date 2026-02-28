"""Span creation and attribute helpers for GenAI semantic conventions."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from opentelemetry.trace import SpanKind, StatusCode, Tracer

from opentelemetry.instrumentation.claude_agent_sdk._constants import (
    ERROR_TYPE,
    FINISH_REASON_MAP,
    GEN_AI_AGENT_NAME,
    GEN_AI_CONVERSATION_ID,
    GEN_AI_OPERATION_NAME,
    GEN_AI_REQUEST_MODEL,
    GEN_AI_RESPONSE_FINISH_REASONS,
    GEN_AI_RESPONSE_MODEL,
    GEN_AI_SYSTEM,
    GEN_AI_USAGE_CACHE_CREATION_INPUT_TOKENS,
    GEN_AI_USAGE_CACHE_READ_INPUT_TOKENS,
    GEN_AI_USAGE_INPUT_TOKENS,
    GEN_AI_USAGE_OUTPUT_TOKENS,
    OPERATION_INVOKE_AGENT,
    SYSTEM_ANTHROPIC,
)

if TYPE_CHECKING:
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
        GEN_AI_SYSTEM: SYSTEM_ANTHROPIC,
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


def set_error_attributes(span: Span, exception: BaseException) -> None:
    """Set error.type and ERROR status on a span.

    Args:
        span: The span to annotate with error info.
        exception: The exception that occurred.
    """
    error_type = type(exception).__qualname__
    span.set_attribute(ERROR_TYPE, error_type)
    span.set_status(StatusCode.ERROR, str(exception))
