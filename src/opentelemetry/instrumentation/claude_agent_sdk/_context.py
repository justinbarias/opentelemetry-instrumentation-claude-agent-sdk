"""Per-invocation context management using contextvars."""

from __future__ import annotations

import time
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from opentelemetry.trace import Span, StatusCode, set_span_in_context


@dataclass
class InvocationContext:
    """Mutable per-invocation state tracking active spans and metadata.

    Stored in a ContextVar so each async task gets its own isolated copy.
    """

    invocation_span: Span
    start_time: float = field(default_factory=time.monotonic)
    active_tool_spans: dict[str, Span] = field(default_factory=dict)
    active_subagent_spans: dict[str, Span] = field(default_factory=dict)
    model: str | None = None
    session_id: str | None = None
    capture_content: bool = False
    _model_set: bool = field(default=False, repr=False)
    parent_otel_context: Any = field(default=None, repr=False)

    def __post_init__(self) -> None:
        """Build parent OTel context from the invocation span."""
        if self.parent_otel_context is None:
            self.parent_otel_context = set_span_in_context(self.invocation_span)

    def set_model(self, model: str) -> None:
        """Set model name (set-once semantics)."""
        if not self._model_set:
            self.model = model
            self._model_set = True

    def cleanup_unclosed_spans(self) -> None:
        """End all active tool/subagent spans with ERROR status.

        Idempotent — safe to call multiple times.
        """
        for span in self.active_tool_spans.values():
            span.set_status(StatusCode.ERROR, "Span not properly closed")
            span.end()
        self.active_tool_spans.clear()

        for span in self.active_subagent_spans.values():
            span.set_status(StatusCode.ERROR, "Span not properly closed")
            span.end()
        self.active_subagent_spans.clear()


_invocation_context_var: ContextVar[InvocationContext | None] = ContextVar(
    "otel_claude_invocation_context", default=None
)


def get_invocation_context() -> InvocationContext | None:
    """Get the current invocation context."""
    return _invocation_context_var.get()


def set_invocation_context(ctx: InvocationContext | None) -> None:
    """Set the current invocation context."""
    _invocation_context_var.set(ctx)
