"""Hook callbacks and merge utility for Claude Agent SDK instrumentation."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from opentelemetry.instrumentation.claude_agent_sdk._constants import (
    GEN_AI_TOOL_CALL_ARGUMENTS,
    GEN_AI_TOOL_CALL_RESULT,
)
from opentelemetry.instrumentation.claude_agent_sdk._context import get_invocation_context
from opentelemetry.instrumentation.claude_agent_sdk._spans import (
    create_execute_tool_span,
    set_tool_error_attributes,
)

if TYPE_CHECKING:
    from opentelemetry.trace import Tracer


def _get_field(data: Any, field: str, default: Any = None) -> Any:
    """Get a field from hook input data (dict from SDK or object from tests)."""
    if isinstance(data, dict):
        return data.get(field, default)
    return getattr(data, field, default)


def _make_hook_matcher(callback: Any, matcher: str | None = None) -> Any:
    """Wrap a callback in a HookMatcher expected by the SDK.

    The Claude Agent SDK's ``_convert_hooks_to_internal_format`` uses
    ``hasattr(matcher, 'hooks')`` (attribute access), so plain dicts are
    silently converted to empty hook lists.  We import the real
    ``HookMatcher`` dataclass at runtime to satisfy this contract.
    """
    try:
        from claude_agent_sdk.types import HookMatcher

        return HookMatcher(matcher=matcher, hooks=[callback])
    except Exception:
        # Fallback for environments where claude_agent_sdk is not installed
        return {"matcher": matcher, "hooks": [callback]}


async def _on_stop(
    input_data: Any, tool_use_id: str | None = None, context: Any = None, **kwargs: Any
) -> dict[str, Any]:
    """Hook callback for Stop event — records stop reason on invocation span."""
    ctx = get_invocation_context()
    if ctx is not None:
        # Stop event indicates the agent is done; no additional attributes needed
        # The ResultMessage will carry the actual stop reason
        pass
    return {}


def merge_hooks(
    user_hooks: dict[str, list[Any]],
    instrumentation_hooks: dict[str, list[Any]],
) -> dict[str, list[Any]]:
    """Merge instrumentation hooks after user hooks.

    User hooks execute first, instrumentation hooks observe final state.

    Args:
        user_hooks: User-provided hooks dict (modified in-place and returned).
        instrumentation_hooks: Instrumentation hooks to append.

    Returns:
        The merged hooks dict.
    """
    merged = dict(user_hooks)
    for event, matchers in instrumentation_hooks.items():
        existing = merged.get(event, [])
        merged[event] = existing + matchers
    return merged


def build_instrumentation_hooks(
    tracer: Tracer | None = None,
    capture_content: bool = False,
) -> dict[str, list[Any]]:
    """Build the instrumentation hooks dict.

    Args:
        tracer: OTel tracer instance. When None, only Stop hook is returned (backward compat).
        capture_content: Whether to capture tool arguments/results as span attributes.

    Returns:
        Dict mapping event names to lists of hook callbacks.
    """
    hooks: dict[str, list[Any]] = {
        "Stop": [_make_hook_matcher(_on_stop)],
    }

    if tracer is None:
        return hooks

    # --- Tool hook closures (require tracer) ---

    async def _on_pre_tool_use(
        input_data: Any, tool_use_id: str | None = None, context: Any = None, **kwargs: Any
    ) -> dict[str, Any]:
        """Hook callback for PreToolUse — start an execute_tool span."""
        ctx = get_invocation_context()
        if ctx is None or tool_use_id is None:
            return {}

        tool_name = _get_field(input_data, "tool_name", "unknown")
        span = create_execute_tool_span(
            tracer,
            tool_name=tool_name,
            tool_use_id=tool_use_id,
            parent_context=ctx.parent_otel_context,
        )
        ctx.active_tool_spans[tool_use_id] = span

        # Optionally capture tool arguments
        if capture_content and ctx.capture_content:
            tool_input = _get_field(input_data, "tool_input")
            if tool_input is not None:
                try:
                    args_str = json.dumps(tool_input) if isinstance(tool_input, dict) else str(tool_input)
                    span.set_attribute(GEN_AI_TOOL_CALL_ARGUMENTS, args_str)
                except (TypeError, ValueError):
                    span.set_attribute(GEN_AI_TOOL_CALL_ARGUMENTS, str(tool_input))

        return {}

    async def _on_post_tool_use(
        input_data: Any, tool_use_id: str | None = None, context: Any = None, **kwargs: Any
    ) -> dict[str, Any]:
        """Hook callback for PostToolUse — end the execute_tool span successfully."""
        ctx = get_invocation_context()
        if ctx is None or tool_use_id is None:
            return {}

        span = ctx.active_tool_spans.pop(tool_use_id, None)
        if span is None:
            return {}

        # Optionally capture tool result
        if capture_content and ctx.capture_content:
            tool_response = _get_field(input_data, "tool_response")
            if tool_response is not None:
                result_str = str(tool_response)
                span.set_attribute(GEN_AI_TOOL_CALL_RESULT, result_str)

        span.end()
        return {}

    async def _on_post_tool_use_failure(
        input_data: Any, tool_use_id: str | None = None, context: Any = None, **kwargs: Any
    ) -> dict[str, Any]:
        """Hook callback for PostToolUseFailure — end the execute_tool span with error."""
        ctx = get_invocation_context()
        if ctx is None or tool_use_id is None:
            return {}

        span = ctx.active_tool_spans.pop(tool_use_id, None)
        if span is None:
            return {}

        error_msg = _get_field(input_data, "error", "unknown error")
        set_tool_error_attributes(span, str(error_msg))
        span.end()
        return {}

    hooks["PreToolUse"] = [_make_hook_matcher(_on_pre_tool_use)]
    hooks["PostToolUse"] = [_make_hook_matcher(_on_post_tool_use)]
    hooks["PostToolUseFailure"] = [_make_hook_matcher(_on_post_tool_use_failure)]

    return hooks
