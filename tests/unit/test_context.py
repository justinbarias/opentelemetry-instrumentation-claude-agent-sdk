"""Tests for InvocationContext and ContextVar management (T006)."""

from __future__ import annotations

import asyncio

from opentelemetry.instrumentation.claude_agent_sdk._context import (
    InvocationContext,
    get_invocation_context,
    set_invocation_context,
)
from opentelemetry.trace import StatusCode


class TestInvocationContextCreation:
    def test_create_with_all_fields(self, tracer_provider):
        tracer = tracer_provider.get_tracer("test")
        span = tracer.start_span("test")
        ctx = InvocationContext(
            invocation_span=span,
            capture_content=True,
        )

        assert ctx.invocation_span is span
        assert ctx.model is None
        assert ctx.session_id is None
        assert ctx.capture_content is True
        assert ctx.active_tool_spans == {}
        assert ctx.active_subagent_spans == {}
        assert ctx.start_time > 0
        span.end()

    def test_set_model_once(self, tracer_provider):
        tracer = tracer_provider.get_tracer("test")
        span = tracer.start_span("test")
        ctx = InvocationContext(invocation_span=span)

        ctx.set_model("claude-sonnet-4-20250514")
        assert ctx.model == "claude-sonnet-4-20250514"

        # Second set should be ignored (set-once)
        ctx.set_model("claude-opus-4-20250514")
        assert ctx.model == "claude-sonnet-4-20250514"
        span.end()


class TestCleanupUnclosedSpans:
    def test_cleanup_ends_tool_spans_with_error(self, tracer_provider, span_exporter):
        tracer = tracer_provider.get_tracer("test")
        parent_span = tracer.start_span("parent")
        tool_span = tracer.start_span("tool")

        ctx = InvocationContext(invocation_span=parent_span)
        ctx.active_tool_spans["tool-1"] = tool_span

        ctx.cleanup_unclosed_spans()

        assert len(ctx.active_tool_spans) == 0
        spans = span_exporter.get_finished_spans()
        tool_spans = [s for s in spans if s.name == "tool"]
        assert len(tool_spans) == 1
        assert tool_spans[0].status.status_code == StatusCode.ERROR
        parent_span.end()

    def test_cleanup_ends_subagent_spans_with_error(self, tracer_provider, span_exporter):
        tracer = tracer_provider.get_tracer("test")
        parent_span = tracer.start_span("parent")
        subagent_span = tracer.start_span("subagent")

        ctx = InvocationContext(invocation_span=parent_span)
        ctx.active_subagent_spans["sub-1"] = subagent_span

        ctx.cleanup_unclosed_spans()

        assert len(ctx.active_subagent_spans) == 0
        spans = span_exporter.get_finished_spans()
        subagent_spans = [s for s in spans if s.name == "subagent"]
        assert len(subagent_spans) == 1
        assert subagent_spans[0].status.status_code == StatusCode.ERROR
        parent_span.end()

    def test_cleanup_is_idempotent(self, tracer_provider, span_exporter):
        tracer = tracer_provider.get_tracer("test")
        parent_span = tracer.start_span("parent")
        tool_span = tracer.start_span("tool")

        ctx = InvocationContext(invocation_span=parent_span)
        ctx.active_tool_spans["tool-1"] = tool_span

        ctx.cleanup_unclosed_spans()
        ctx.cleanup_unclosed_spans()  # Should not raise

        spans = span_exporter.get_finished_spans()
        tool_spans = [s for s in spans if s.name == "tool"]
        assert len(tool_spans) == 1
        parent_span.end()


class TestContextVarIsolation:
    async def test_contextvar_isolation_across_tasks(self, tracer_provider):
        tracer = tracer_provider.get_tracer("test")

        results: dict[str, str | None] = {}

        async def task_a():
            span = tracer.start_span("task_a")
            ctx = InvocationContext(invocation_span=span)
            ctx.set_model("model-a")
            set_invocation_context(ctx)
            await asyncio.sleep(0.01)
            current = get_invocation_context()
            results["a"] = current.model if current else None
            span.end()

        async def task_b():
            span = tracer.start_span("task_b")
            ctx = InvocationContext(invocation_span=span)
            ctx.set_model("model-b")
            set_invocation_context(ctx)
            await asyncio.sleep(0.01)
            current = get_invocation_context()
            results["b"] = current.model if current else None
            span.end()

        await asyncio.gather(task_a(), task_b())

        assert results["a"] == "model-a"
        assert results["b"] == "model-b"

    def test_context_defaults_to_none(self):
        assert get_invocation_context() is None

    def test_set_and_get_context(self, tracer_provider):
        tracer = tracer_provider.get_tracer("test")
        span = tracer.start_span("test")
        ctx = InvocationContext(invocation_span=span)

        set_invocation_context(ctx)
        assert get_invocation_context() is ctx

        set_invocation_context(None)
        assert get_invocation_context() is None
        span.end()
