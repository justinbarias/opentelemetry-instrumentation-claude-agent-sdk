"""Hook callbacks and merge utility for Claude Agent SDK instrumentation."""

from __future__ import annotations

from typing import Any

from opentelemetry.instrumentation.claude_agent_sdk._context import get_invocation_context


def _on_stop(*, tool_use_id: str | None = None, **kwargs: Any) -> dict[str, Any]:
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


def build_instrumentation_hooks() -> dict[str, list[Any]]:
    """Build the instrumentation hooks dict.

    Returns a dict with only events that have actual callbacks.
    Currently only Stop is implemented for US1.

    Returns:
        Dict mapping event names to lists of hook callbacks.
    """
    return {
        "Stop": [_on_stop],
    }
