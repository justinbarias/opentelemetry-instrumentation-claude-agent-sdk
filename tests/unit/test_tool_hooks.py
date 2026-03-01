"""Tests for tool hook callbacks (T005-T010)."""

from __future__ import annotations

from typing import Any

from opentelemetry.trace import StatusCode

from opentelemetry.instrumentation.claude_agent_sdk._constants import (
    ERROR_TYPE,
    GEN_AI_OPERATION_NAME,
    GEN_AI_TOOL_CALL_ARGUMENTS,
    GEN_AI_TOOL_CALL_ID,
    GEN_AI_TOOL_CALL_RESULT,
    GEN_AI_TOOL_NAME,
    GEN_AI_TOOL_TYPE,
    OPERATION_EXECUTE_TOOL,
    TOOL_TYPE_FUNCTION,
)
from opentelemetry.instrumentation.claude_agent_sdk._context import (
    InvocationContext,
    set_invocation_context,
)
from opentelemetry.instrumentation.claude_agent_sdk._hooks import (
    build_instrumentation_hooks,
)
from tests.unit.conftest import (
    MockHookContext,
    MockPostToolUseFailureHookInput,
    MockPostToolUseHookInput,
    MockPreToolUseHookInput,
)


def _get_callback(hooks: dict[str, list[Any]], event: str) -> Any:
    """Extract the first callback from a HookMatcher (dataclass or dict)."""
    matcher = hooks[event][0]
    # Support both HookMatcher dataclass (attribute access) and plain dict
    hook_list = getattr(matcher, "hooks", None) or matcher.get("hooks", [])
    return hook_list[0]


# --- T005: TestPreToolUseHook ---


class TestPreToolUseHook:
    async def test_starts_span_and_stores_in_context(self, tracer_provider, span_exporter):
        tracer = tracer_provider.get_tracer("test")
        hooks = build_instrumentation_hooks(tracer=tracer, capture_content=False)
        pre_cb = _get_callback(hooks, "PreToolUse")

        # Set up invocation context
        parent_span = tracer.start_span("invoke_agent test-agent")
        ctx = InvocationContext(invocation_span=parent_span, capture_content=False)
        set_invocation_context(ctx)

        try:
            input_data = MockPreToolUseHookInput(tool_name="Bash")
            await pre_cb(input_data, "toolu_123", MockHookContext())

            assert "toolu_123" in ctx.active_tool_spans
            # Span should not be finished yet (still active)
            assert len(span_exporter.get_finished_spans()) == 0
        finally:
            # Clean up
            ctx.active_tool_spans["toolu_123"].end()
            parent_span.end()
            set_invocation_context(None)

    async def test_sets_tool_attributes(self, tracer_provider, span_exporter):
        tracer = tracer_provider.get_tracer("test")
        hooks = build_instrumentation_hooks(tracer=tracer, capture_content=False)
        pre_cb = _get_callback(hooks, "PreToolUse")

        parent_span = tracer.start_span("invoke_agent test-agent")
        ctx = InvocationContext(invocation_span=parent_span, capture_content=False)
        set_invocation_context(ctx)

        try:
            input_data = MockPreToolUseHookInput(tool_name="Bash")
            await pre_cb(input_data, "toolu_abc", MockHookContext())

            # End the tool span so we can inspect it
            tool_span = ctx.active_tool_spans.pop("toolu_abc")
            tool_span.end()

            spans = span_exporter.get_finished_spans()
            tool_spans = [s for s in spans if s.name.startswith("execute_tool")]
            assert len(tool_spans) == 1

            attrs = dict(tool_spans[0].attributes or {})
            assert attrs[GEN_AI_OPERATION_NAME] == OPERATION_EXECUTE_TOOL
            assert attrs[GEN_AI_TOOL_NAME] == "Bash"
            assert attrs[GEN_AI_TOOL_CALL_ID] == "toolu_abc"
            assert attrs[GEN_AI_TOOL_TYPE] == TOOL_TYPE_FUNCTION
        finally:
            parent_span.end()
            set_invocation_context(None)

    async def test_captures_arguments_when_enabled(self, tracer_provider, span_exporter):
        tracer = tracer_provider.get_tracer("test")
        hooks = build_instrumentation_hooks(tracer=tracer, capture_content=True)
        pre_cb = _get_callback(hooks, "PreToolUse")

        parent_span = tracer.start_span("invoke_agent test-agent")
        ctx = InvocationContext(invocation_span=parent_span, capture_content=True)
        set_invocation_context(ctx)

        try:
            input_data = MockPreToolUseHookInput(tool_name="Bash", tool_input={"command": "echo hello"})
            await pre_cb(input_data, "toolu_cap", MockHookContext())

            tool_span = ctx.active_tool_spans.pop("toolu_cap")
            tool_span.end()

            spans = span_exporter.get_finished_spans()
            tool_spans = [s for s in spans if s.name.startswith("execute_tool")]
            attrs = dict(tool_spans[0].attributes or {})
            assert GEN_AI_TOOL_CALL_ARGUMENTS in attrs
            assert "echo hello" in attrs[GEN_AI_TOOL_CALL_ARGUMENTS]
        finally:
            parent_span.end()
            set_invocation_context(None)

    async def test_no_arguments_when_capture_disabled(self, tracer_provider, span_exporter):
        tracer = tracer_provider.get_tracer("test")
        hooks = build_instrumentation_hooks(tracer=tracer, capture_content=False)
        pre_cb = _get_callback(hooks, "PreToolUse")

        parent_span = tracer.start_span("invoke_agent test-agent")
        ctx = InvocationContext(invocation_span=parent_span, capture_content=False)
        set_invocation_context(ctx)

        try:
            input_data = MockPreToolUseHookInput(tool_name="Bash", tool_input={"command": "echo hello"})
            await pre_cb(input_data, "toolu_nocap", MockHookContext())

            tool_span = ctx.active_tool_spans.pop("toolu_nocap")
            tool_span.end()

            spans = span_exporter.get_finished_spans()
            tool_spans = [s for s in spans if s.name.startswith("execute_tool")]
            attrs = dict(tool_spans[0].attributes or {})
            assert GEN_AI_TOOL_CALL_ARGUMENTS not in attrs
        finally:
            parent_span.end()
            set_invocation_context(None)

    async def test_graceful_no_context(self, tracer_provider, span_exporter):
        """PreToolUse should no-op when there's no invocation context."""
        tracer = tracer_provider.get_tracer("test")
        hooks = build_instrumentation_hooks(tracer=tracer, capture_content=False)
        pre_cb = _get_callback(hooks, "PreToolUse")

        set_invocation_context(None)

        input_data = MockPreToolUseHookInput(tool_name="Bash")
        result = await pre_cb(input_data, "toolu_orphan", MockHookContext())

        # Should not raise, and no spans should be created
        assert len(span_exporter.get_finished_spans()) == 0
        assert result == {}


# --- T006: TestPostToolUseHook ---


class TestPostToolUseHook:
    async def test_ends_span_and_pops_from_context(self, tracer_provider, span_exporter):
        tracer = tracer_provider.get_tracer("test")
        hooks = build_instrumentation_hooks(tracer=tracer, capture_content=False)
        pre_cb = _get_callback(hooks, "PreToolUse")
        post_cb = _get_callback(hooks, "PostToolUse")

        parent_span = tracer.start_span("invoke_agent test-agent")
        ctx = InvocationContext(invocation_span=parent_span, capture_content=False)
        set_invocation_context(ctx)

        try:
            input_data = MockPreToolUseHookInput(tool_name="Bash")
            await pre_cb(input_data, "toolu_end", MockHookContext())

            post_input = MockPostToolUseHookInput(tool_name="Bash", tool_response="hello")
            await post_cb(post_input, "toolu_end", MockHookContext())

            # Tool span should be popped from context
            assert "toolu_end" not in ctx.active_tool_spans

            # Span should be ended (visible in exporter)
            tool_spans = [s for s in span_exporter.get_finished_spans() if s.name.startswith("execute_tool")]
            assert len(tool_spans) == 1
            assert tool_spans[0].status.status_code != StatusCode.ERROR
        finally:
            parent_span.end()
            set_invocation_context(None)

    async def test_captures_result_when_enabled(self, tracer_provider, span_exporter):
        tracer = tracer_provider.get_tracer("test")
        hooks = build_instrumentation_hooks(tracer=tracer, capture_content=True)
        pre_cb = _get_callback(hooks, "PreToolUse")
        post_cb = _get_callback(hooks, "PostToolUse")

        parent_span = tracer.start_span("invoke_agent test-agent")
        ctx = InvocationContext(invocation_span=parent_span, capture_content=True)
        set_invocation_context(ctx)

        try:
            await pre_cb(MockPreToolUseHookInput(tool_name="Bash"), "toolu_res", MockHookContext())
            await post_cb(
                MockPostToolUseHookInput(tool_name="Bash", tool_response="hello world"),
                "toolu_res",
                MockHookContext(),
            )

            tool_spans = [s for s in span_exporter.get_finished_spans() if s.name.startswith("execute_tool")]
            attrs = dict(tool_spans[0].attributes or {})
            assert GEN_AI_TOOL_CALL_RESULT in attrs
            assert "hello world" in attrs[GEN_AI_TOOL_CALL_RESULT]
        finally:
            parent_span.end()
            set_invocation_context(None)

    async def test_no_result_when_capture_disabled(self, tracer_provider, span_exporter):
        tracer = tracer_provider.get_tracer("test")
        hooks = build_instrumentation_hooks(tracer=tracer, capture_content=False)
        pre_cb = _get_callback(hooks, "PreToolUse")
        post_cb = _get_callback(hooks, "PostToolUse")

        parent_span = tracer.start_span("invoke_agent test-agent")
        ctx = InvocationContext(invocation_span=parent_span, capture_content=False)
        set_invocation_context(ctx)

        try:
            await pre_cb(MockPreToolUseHookInput(tool_name="Bash"), "toolu_nores", MockHookContext())
            await post_cb(
                MockPostToolUseHookInput(tool_name="Bash", tool_response="hello"),
                "toolu_nores",
                MockHookContext(),
            )

            tool_spans = [s for s in span_exporter.get_finished_spans() if s.name.startswith("execute_tool")]
            attrs = dict(tool_spans[0].attributes or {})
            assert GEN_AI_TOOL_CALL_RESULT not in attrs
        finally:
            parent_span.end()
            set_invocation_context(None)

    async def test_unknown_tool_use_id_graceful(self, tracer_provider, span_exporter):
        tracer = tracer_provider.get_tracer("test")
        hooks = build_instrumentation_hooks(tracer=tracer, capture_content=False)
        post_cb = _get_callback(hooks, "PostToolUse")

        parent_span = tracer.start_span("invoke_agent test-agent")
        ctx = InvocationContext(invocation_span=parent_span, capture_content=False)
        set_invocation_context(ctx)

        try:
            post_input = MockPostToolUseHookInput(tool_name="Bash")
            result = await post_cb(post_input, "toolu_nonexistent", MockHookContext())

            # Should not raise
            assert result == {}
        finally:
            parent_span.end()
            set_invocation_context(None)


# --- T007: TestPostToolUseFailureHook ---


class TestPostToolUseFailureHook:
    async def test_ends_span_with_error(self, tracer_provider, span_exporter):
        tracer = tracer_provider.get_tracer("test")
        hooks = build_instrumentation_hooks(tracer=tracer, capture_content=False)
        pre_cb = _get_callback(hooks, "PreToolUse")
        fail_cb = _get_callback(hooks, "PostToolUseFailure")

        parent_span = tracer.start_span("invoke_agent test-agent")
        ctx = InvocationContext(invocation_span=parent_span, capture_content=False)
        set_invocation_context(ctx)

        try:
            await pre_cb(MockPreToolUseHookInput(tool_name="Bash"), "toolu_fail", MockHookContext())

            fail_input = MockPostToolUseFailureHookInput(tool_name="Bash", error="Command failed with exit code 1")
            await fail_cb(fail_input, "toolu_fail", MockHookContext())

            assert "toolu_fail" not in ctx.active_tool_spans

            tool_spans = [s for s in span_exporter.get_finished_spans() if s.name.startswith("execute_tool")]
            assert len(tool_spans) == 1
            assert tool_spans[0].status.status_code == StatusCode.ERROR
            attrs = dict(tool_spans[0].attributes or {})
            assert attrs[ERROR_TYPE] == "Command failed with exit code 1"
        finally:
            parent_span.end()
            set_invocation_context(None)

    async def test_unknown_tool_use_id_graceful(self, tracer_provider, span_exporter):
        tracer = tracer_provider.get_tracer("test")
        hooks = build_instrumentation_hooks(tracer=tracer, capture_content=False)
        fail_cb = _get_callback(hooks, "PostToolUseFailure")

        parent_span = tracer.start_span("invoke_agent test-agent")
        ctx = InvocationContext(invocation_span=parent_span, capture_content=False)
        set_invocation_context(ctx)

        try:
            fail_input = MockPostToolUseFailureHookInput(tool_name="Bash", error="fail")
            result = await fail_cb(fail_input, "toolu_missing", MockHookContext())
            assert result == {}
        finally:
            parent_span.end()
            set_invocation_context(None)


# --- T008: TestToolSpanCleanupOnCrash ---


class TestToolSpanCleanupOnCrash:
    async def test_unclosed_spans_cleaned_up_with_error(self, tracer_provider, span_exporter):
        """PreToolUse without Post → cleanup_unclosed_spans() ends with ERROR."""
        tracer = tracer_provider.get_tracer("test")
        hooks = build_instrumentation_hooks(tracer=tracer, capture_content=False)
        pre_cb = _get_callback(hooks, "PreToolUse")

        parent_span = tracer.start_span("invoke_agent test-agent")
        ctx = InvocationContext(invocation_span=parent_span, capture_content=False)
        set_invocation_context(ctx)

        try:
            await pre_cb(MockPreToolUseHookInput(tool_name="Bash"), "toolu_orphan1", MockHookContext())
            assert len(ctx.active_tool_spans) == 1

            # Simulate crash cleanup (no PostToolUse received)
            ctx.cleanup_unclosed_spans()

            assert len(ctx.active_tool_spans) == 0

            tool_spans = [s for s in span_exporter.get_finished_spans() if s.name.startswith("execute_tool")]
            assert len(tool_spans) == 1
            assert tool_spans[0].status.status_code == StatusCode.ERROR
        finally:
            parent_span.end()
            set_invocation_context(None)

    async def test_multiple_unclosed_all_cleaned(self, tracer_provider, span_exporter):
        tracer = tracer_provider.get_tracer("test")
        hooks = build_instrumentation_hooks(tracer=tracer, capture_content=False)
        pre_cb = _get_callback(hooks, "PreToolUse")

        parent_span = tracer.start_span("invoke_agent test-agent")
        ctx = InvocationContext(invocation_span=parent_span, capture_content=False)
        set_invocation_context(ctx)

        try:
            await pre_cb(MockPreToolUseHookInput(tool_name="Bash"), "toolu_a", MockHookContext())
            await pre_cb(MockPreToolUseHookInput(tool_name="Read"), "toolu_b", MockHookContext())
            assert len(ctx.active_tool_spans) == 2

            ctx.cleanup_unclosed_spans()

            assert len(ctx.active_tool_spans) == 0
            tool_spans = [s for s in span_exporter.get_finished_spans() if s.name.startswith("execute_tool")]
            assert len(tool_spans) == 2
            for ts in tool_spans:
                assert ts.status.status_code == StatusCode.ERROR
        finally:
            parent_span.end()
            set_invocation_context(None)

    async def test_cleanup_idempotent(self, tracer_provider, span_exporter):
        tracer = tracer_provider.get_tracer("test")
        hooks = build_instrumentation_hooks(tracer=tracer, capture_content=False)
        pre_cb = _get_callback(hooks, "PreToolUse")

        parent_span = tracer.start_span("invoke_agent test-agent")
        ctx = InvocationContext(invocation_span=parent_span, capture_content=False)
        set_invocation_context(ctx)

        try:
            await pre_cb(MockPreToolUseHookInput(tool_name="Bash"), "toolu_idem", MockHookContext())
            ctx.cleanup_unclosed_spans()
            ctx.cleanup_unclosed_spans()  # Should not raise or double-end

            tool_spans = [s for s in span_exporter.get_finished_spans() if s.name.startswith("execute_tool")]
            assert len(tool_spans) == 1
        finally:
            parent_span.end()
            set_invocation_context(None)


# --- T009: TestBuildInstrumentationHooks ---


class TestBuildInstrumentationHooks:
    def test_with_tracer_returns_all_hook_keys(self, tracer_provider):
        tracer = tracer_provider.get_tracer("test")
        hooks = build_instrumentation_hooks(tracer=tracer, capture_content=False)

        assert "Stop" in hooks
        assert "PreToolUse" in hooks
        assert "PostToolUse" in hooks
        assert "PostToolUseFailure" in hooks

        # Each key has at least one callback
        for key in ["Stop", "PreToolUse", "PostToolUse", "PostToolUseFailure"]:
            assert len(hooks[key]) >= 1

    def test_without_tracer_returns_only_stop(self):
        hooks = build_instrumentation_hooks()

        assert "Stop" in hooks
        assert "PreToolUse" not in hooks
        assert "PostToolUse" not in hooks
        assert "PostToolUseFailure" not in hooks

    def test_merge_user_hooks_before_instrumentation(self, tracer_provider):
        """User hooks should execute before instrumentation hooks."""
        from opentelemetry.instrumentation.claude_agent_sdk._hooks import merge_hooks

        tracer = tracer_provider.get_tracer("test")

        user_hook_matcher = {"matcher": None, "hooks": [lambda *a, **k: {}]}
        user_hooks: dict[str, list[Any]] = {
            "PreToolUse": [user_hook_matcher],
        }
        inst_hooks = build_instrumentation_hooks(tracer=tracer, capture_content=False)

        merged = merge_hooks(user_hooks, inst_hooks)

        # User hook matcher should be first, instrumentation matcher second
        assert len(merged["PreToolUse"]) == 2
        assert merged["PreToolUse"][0] is user_hook_matcher


# --- T010: TestToolUseIdCorrelation ---


class TestToolUseIdCorrelation:
    async def test_two_concurrent_tools_correlated(self, tracer_provider, span_exporter):
        """Two concurrent tool calls should be tracked independently by tool_use_id."""
        tracer = tracer_provider.get_tracer("test")
        hooks = build_instrumentation_hooks(tracer=tracer, capture_content=False)
        pre_cb = _get_callback(hooks, "PreToolUse")
        post_cb = _get_callback(hooks, "PostToolUse")

        parent_span = tracer.start_span("invoke_agent test-agent")
        ctx = InvocationContext(invocation_span=parent_span, capture_content=False)
        set_invocation_context(ctx)

        try:
            # Start two tool calls
            await pre_cb(MockPreToolUseHookInput(tool_name="Bash"), "toolu_1", MockHookContext())
            await pre_cb(MockPreToolUseHookInput(tool_name="Read"), "toolu_2", MockHookContext())

            assert len(ctx.active_tool_spans) == 2

            # End only the first
            await post_cb(MockPostToolUseHookInput(tool_name="Bash"), "toolu_1", MockHookContext())

            # Second should still be active
            assert "toolu_1" not in ctx.active_tool_spans
            assert "toolu_2" in ctx.active_tool_spans

            # End the second
            await post_cb(MockPostToolUseHookInput(tool_name="Read"), "toolu_2", MockHookContext())

            assert len(ctx.active_tool_spans) == 0

            tool_spans = [s for s in span_exporter.get_finished_spans() if s.name.startswith("execute_tool")]
            assert len(tool_spans) == 2

            names = {s.name for s in tool_spans}
            assert "execute_tool Bash" in names
            assert "execute_tool Read" in names
        finally:
            parent_span.end()
            set_invocation_context(None)

    async def test_ending_one_does_not_affect_other(self, tracer_provider, span_exporter):
        tracer = tracer_provider.get_tracer("test")
        hooks = build_instrumentation_hooks(tracer=tracer, capture_content=False)
        pre_cb = _get_callback(hooks, "PreToolUse")
        post_cb = _get_callback(hooks, "PostToolUse")

        parent_span = tracer.start_span("invoke_agent test-agent")
        ctx = InvocationContext(invocation_span=parent_span, capture_content=False)
        set_invocation_context(ctx)

        try:
            await pre_cb(MockPreToolUseHookInput(tool_name="Bash"), "toolu_x", MockHookContext())
            await pre_cb(MockPreToolUseHookInput(tool_name="Read"), "toolu_y", MockHookContext())

            await post_cb(MockPostToolUseHookInput(tool_name="Bash"), "toolu_x", MockHookContext())

            # toolu_y should still be tracked
            assert "toolu_y" in ctx.active_tool_spans

            # Clean up
            await post_cb(MockPostToolUseHookInput(tool_name="Read"), "toolu_y", MockHookContext())
        finally:
            parent_span.end()
            set_invocation_context(None)

    async def test_unknown_id_graceful_in_post(self, tracer_provider, span_exporter):
        tracer = tracer_provider.get_tracer("test")
        hooks = build_instrumentation_hooks(tracer=tracer, capture_content=False)
        post_cb = _get_callback(hooks, "PostToolUse")

        parent_span = tracer.start_span("invoke_agent test-agent")
        ctx = InvocationContext(invocation_span=parent_span, capture_content=False)
        set_invocation_context(ctx)

        try:
            result = await post_cb(MockPostToolUseHookInput(tool_name="Bash"), "toolu_unknown", MockHookContext())
            assert result == {}
        finally:
            parent_span.end()
            set_invocation_context(None)
