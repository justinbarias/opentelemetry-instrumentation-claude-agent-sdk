"""GenAI event emission helpers.

OpenTelemetry's GenAI semantic conventions model agent telemetry not just as
spans + metrics but also as discrete log records ("events"). Backends that
sample or retain logs and traces separately rely on these to surface things
like exceptions independently of the span. See
``docs/gen-ai/gen-ai-exceptions.md`` and ``docs/gen-ai/gen-ai-events.md`` in
``open-telemetry/semantic-conventions-genai``.

We use ``opentelemetry._logs`` rather than the older ``opentelemetry._events``
``EventLogger``: the latter is deprecated as of opentelemetry-api 1.39 in
favor of representing events as log records with ``event_name`` set.
"""

from __future__ import annotations

import os
import traceback
from typing import TYPE_CHECKING, Any

from opentelemetry._logs import LogRecord, SeverityNumber

from opentelemetry.instrumentation.claude_agent_sdk._constants import (
    ENV_CAPTURE_MESSAGE_CONTENT,
    EVENT_GEN_AI_CLIENT_INFERENCE_OPERATION_DETAILS,
    EVENT_GEN_AI_CLIENT_OPERATION_EXCEPTION,
    EXCEPTION_MESSAGE,
    EXCEPTION_STACKTRACE,
    EXCEPTION_TYPE,
    GEN_AI_INPUT_MESSAGES,
    GEN_AI_OUTPUT_MESSAGES,
    GEN_AI_SYSTEM_INSTRUCTIONS,
    GEN_AI_TOOL_DEFINITIONS,
)

if TYPE_CHECKING:
    from opentelemetry._logs import Logger


def emit_operation_exception_event(
    logger: Logger | None,
    exception: BaseException,
    span_attributes: dict[str, Any] | None = None,
) -> None:
    """Emit a ``gen_ai.client.operation.exception`` log record.

    Per spec the event MUST carry ``exception.type`` and/or ``exception.message``
    and SHOULD carry ``exception.stacktrace``. The instrumentation MAY copy the
    corresponding GenAI client span attributes onto the event — we do so to
    let downstream consumers correlate the event with the operation without
    a span join.

    No-op when ``logger`` is ``None`` (no log provider configured).
    """
    if logger is None:
        return

    attributes: dict[str, Any] = {
        EXCEPTION_TYPE: type(exception).__qualname__,
        EXCEPTION_MESSAGE: str(exception),
        EXCEPTION_STACKTRACE: "".join(traceback.format_exception(exception)),
    }
    if span_attributes:
        attributes.update(span_attributes)

    logger.emit(
        LogRecord(
            event_name=EVENT_GEN_AI_CLIENT_OPERATION_EXCEPTION,
            severity_number=SeverityNumber.WARN,
            attributes=attributes,
        )
    )


# ---------------------------------------------------------------------------
# gen_ai.client.inference.operation.details
# ---------------------------------------------------------------------------
#
# The details event carries the request/response payload for a GenAI inference.
# Per the events spec the content-bearing fields (input.messages, output.messages,
# system_instructions, tool.definitions) are opt-in and gated on the env var
# OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT (or the instrumentor's
# ``capture_content=True`` config). When the gate is off we still emit the
# event — but with only the non-content metadata — because the per-inference
# usage / finish_reason summary remains useful on its own.


def capture_content_enabled(capture_content_config: bool) -> bool:
    """Return True when prompt/completion content may be attached to events.

    Either the env var or the instrumentor config opts in. Env var values are
    interpreted loosely — any of {"true", "1", "yes"} (case-insensitive) opts
    in, matching the convention used by other OTel instrumentations.
    """
    if capture_content_config:
        return True
    env = os.environ.get(ENV_CAPTURE_MESSAGE_CONTENT, "").strip().lower()
    return env in {"true", "1", "yes"}


def _block_to_part(block: Any) -> dict[str, Any] | None:
    """Convert a single SDK content block into a structured ``part`` dict.

    Returns ``None`` for blocks we don't model on the wire (e.g. thinking).
    The shapes mirror the JSON schemas linked from the GenAI events spec:
    text → ``{"type": "text", "content": "..."}``
    tool_use → ``{"type": "tool_call", "id": "...", "name": "...", "arguments": {...}}``
    tool_result → ``{"type": "tool_call_response", "id": "...", "response": ...}``
    """
    # Duck-typed against TextBlock / ToolUseBlock / ToolResultBlock / ThinkingBlock.
    if hasattr(block, "text"):
        return {"type": "text", "content": block.text}
    if hasattr(block, "name") and hasattr(block, "input") and hasattr(block, "id"):
        return {
            "type": "tool_call",
            "id": block.id,
            "name": block.name,
            "arguments": block.input,
        }
    if hasattr(block, "tool_use_id") and hasattr(block, "content"):
        return {
            "type": "tool_call_response",
            "id": block.tool_use_id,
            "response": block.content,
        }
    # ThinkingBlock and any future block types are intentionally dropped — the
    # GenAI events schema does not yet model them, and emitting unknown parts
    # would break payload-validation in downstream consumers.
    return None


def _blocks_to_parts(blocks: Any) -> list[dict[str, Any]]:
    """Convert a list of blocks (or a plain string) into a list of parts."""
    if isinstance(blocks, str):
        return [{"type": "text", "content": blocks}]
    parts: list[dict[str, Any]] = []
    for block in blocks or []:
        part = _block_to_part(block)
        if part is not None:
            parts.append(part)
    return parts


def user_message_to_structured(message: Any) -> dict[str, Any]:
    """Build a structured input message from an SDK ``UserMessage``."""
    return {"role": "user", "parts": _blocks_to_parts(getattr(message, "content", []))}


def assistant_message_to_structured(message: Any, finish_reason: str | None = None) -> dict[str, Any]:
    """Build a structured output message from an SDK ``AssistantMessage``."""
    out: dict[str, Any] = {"role": "assistant", "parts": _blocks_to_parts(getattr(message, "content", []))}
    if finish_reason is not None:
        out["finish_reason"] = finish_reason
    return out


def prompt_to_input_message(prompt: Any) -> dict[str, Any] | None:
    """Convert the SDK's ``prompt=`` argument into a single input message.

    Returns ``None`` for streaming prompts (AsyncIterable) since consuming them
    would steal the SDK's input — those flow through as ``UserMessage``s in the
    response stream instead, which we already capture.
    """
    if isinstance(prompt, str):
        return {"role": "user", "parts": [{"type": "text", "content": prompt}]}
    return None


def system_prompt_to_instructions(system_prompt: Any) -> list[dict[str, Any]] | None:
    """Build the ``gen_ai.system_instructions`` payload from ``options.system_prompt``.

    The SDK accepts either a plain string or a ``SystemPromptPreset`` mapping.
    Presets are CLI-side and don't expose their resolved text to the SDK, so we
    surface only the preset identifier in that case.
    """
    if system_prompt is None:
        return None
    if isinstance(system_prompt, str):
        return [{"type": "text", "content": system_prompt}]
    if isinstance(system_prompt, dict):
        preset = system_prompt.get("preset") or system_prompt.get("type")
        if preset:
            return [{"type": "text", "content": f"preset:{preset}"}]
    return None


def options_to_tool_definitions(options: Any) -> list[dict[str, Any]] | None:
    """Best-effort extraction of the agent's tool definitions from options.

    The Claude Agent SDK exposes tool *names* (allowed_tools / tools) but does
    not surface tool schemas — those live in the CLI. We emit name-only entries
    so consumers at least see what tool surface the agent was configured with.
    """
    if options is None:
        return None
    names: list[str] = []
    for attr in ("allowed_tools", "tools"):
        value = getattr(options, attr, None)
        if isinstance(value, list):
            names.extend(str(n) for n in value if n)
    if not names:
        return None
    # Deduplicate while preserving order.
    seen: set[str] = set()
    deduped: list[str] = []
    for name in names:
        if name not in seen:
            seen.add(name)
            deduped.append(name)
    return [{"type": "function", "name": name} for name in deduped]


def emit_inference_operation_details_event(
    logger: Logger | None,
    *,
    base_attributes: dict[str, Any],
    input_messages: list[dict[str, Any]] | None,
    output_messages: list[dict[str, Any]] | None,
    system_instructions: list[dict[str, Any]] | None,
    tool_definitions: list[dict[str, Any]] | None,
    include_content: bool,
) -> None:
    """Emit a ``gen_ai.client.inference.operation.details`` log record.

    ``base_attributes`` should already contain the required + recommended
    non-content attributes (gen_ai.operation.name, gen_ai.provider.name,
    request/response models, finish reasons, usage tokens, etc.).

    The four content payloads are appended only when ``include_content`` is
    True — callers compute that with :func:`capture_content_enabled`.

    No-op when ``logger`` is ``None`` (no log provider configured).
    """
    if logger is None:
        return

    attributes: dict[str, Any] = dict(base_attributes)
    if include_content:
        if input_messages:
            attributes[GEN_AI_INPUT_MESSAGES] = input_messages
        if output_messages:
            attributes[GEN_AI_OUTPUT_MESSAGES] = output_messages
        if system_instructions:
            attributes[GEN_AI_SYSTEM_INSTRUCTIONS] = system_instructions
        if tool_definitions:
            attributes[GEN_AI_TOOL_DEFINITIONS] = tool_definitions

    logger.emit(
        LogRecord(
            event_name=EVENT_GEN_AI_CLIENT_INFERENCE_OPERATION_DETAILS,
            severity_number=SeverityNumber.INFO,
            attributes=attributes,
        )
    )
