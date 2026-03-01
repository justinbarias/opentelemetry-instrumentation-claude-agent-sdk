"""Integration tests for hook-driven tool execution tracing (T011 / US2)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

import pytest
from opentelemetry.trace import SpanKind, StatusCode

from opentelemetry.instrumentation.claude_agent_sdk._constants import (
    GEN_AI_OPERATION_NAME,
    GEN_AI_SYSTEM,
    GEN_AI_TOOL_CALL_ARGUMENTS,
    GEN_AI_TOOL_CALL_ID,
    GEN_AI_TOOL_CALL_RESULT,
    GEN_AI_TOOL_NAME,
    GEN_AI_TOOL_TYPE,
    OPERATION_EXECUTE_TOOL,
    SYSTEM_ANTHROPIC,
)
from tests.integration.conftest import (
    get_execute_tool_spans,
    get_invoke_agent_spans,
    make_cheap_options,
    requires_auth,
)

pytestmark = [pytest.mark.integration, requires_auth]

# Use a prompt that reliably triggers tool use (Bash).
TOOL_PROMPT = "Use the Bash tool to run: echo hello_otel_test"


async def _streaming_prompt(text: str) -> AsyncIterator[dict[str, Any]]:
    """Wrap a string prompt as an AsyncIterable so the SDK keeps stdin open for hooks.

    When hooks are registered, the SDK's ``stream_input()`` waits for the first
    result before closing stdin, allowing bidirectional hook communication.
    A plain string prompt calls ``end_input()`` immediately, which closes stdin
    before the CLI can dispatch hook callbacks.
    """
    yield {
        "type": "user",
        "session_id": "",
        "message": {"role": "user", "content": text},
        "parent_tool_use_id": None,
    }


class TestToolTracingEndToEnd:
    async def test_execute_tool_span_appears(self, instrumentor, span_exporter):
        """A query that calls a tool should produce an execute_tool span."""
        import claude_agent_sdk

        async for _ in claude_agent_sdk.query(
            prompt=_streaming_prompt(TOOL_PROMPT),
            options=make_cheap_options(allowed_tools=["Bash"], permission_mode="bypassPermissions", max_turns=3),
        ):
            pass

        tool_spans = get_execute_tool_spans(span_exporter)
        assert len(tool_spans) >= 1, "Expected at least one execute_tool span"

    async def test_tool_span_is_child_of_invoke_agent(self, instrumentor, span_exporter):
        """execute_tool span should be a child of the invoke_agent span."""
        import claude_agent_sdk

        async for _ in claude_agent_sdk.query(
            prompt=_streaming_prompt(TOOL_PROMPT),
            options=make_cheap_options(allowed_tools=["Bash"], permission_mode="bypassPermissions", max_turns=3),
        ):
            pass

        invoke_spans = get_invoke_agent_spans(span_exporter)
        tool_spans = get_execute_tool_spans(span_exporter)

        assert len(invoke_spans) >= 1
        assert len(tool_spans) >= 1

        parent_span_id = invoke_spans[0].context.span_id
        for ts in tool_spans:
            assert ts.parent is not None, "Tool span should have a parent"
            assert ts.parent.span_id == parent_span_id, "Tool span parent should be the invoke_agent span"

    async def test_tool_span_kind_is_internal(self, instrumentor, span_exporter):
        """execute_tool spans should have span_kind = INTERNAL."""
        import claude_agent_sdk

        async for _ in claude_agent_sdk.query(
            prompt=_streaming_prompt(TOOL_PROMPT),
            options=make_cheap_options(allowed_tools=["Bash"], permission_mode="bypassPermissions", max_turns=3),
        ):
            pass

        tool_spans = get_execute_tool_spans(span_exporter)
        assert len(tool_spans) >= 1
        for ts in tool_spans:
            assert ts.kind == SpanKind.INTERNAL

    async def test_tool_span_has_required_attributes(self, instrumentor, span_exporter):
        """execute_tool span should carry gen_ai.tool.name, .call.id, .type, operation.name."""
        import claude_agent_sdk

        async for _ in claude_agent_sdk.query(
            prompt=_streaming_prompt(TOOL_PROMPT),
            options=make_cheap_options(allowed_tools=["Bash"], permission_mode="bypassPermissions", max_turns=3),
        ):
            pass

        tool_spans = get_execute_tool_spans(span_exporter)
        assert len(tool_spans) >= 1

        attrs = dict(tool_spans[0].attributes or {})
        assert attrs[GEN_AI_OPERATION_NAME] == OPERATION_EXECUTE_TOOL
        assert attrs[GEN_AI_SYSTEM] == SYSTEM_ANTHROPIC
        assert GEN_AI_TOOL_NAME in attrs
        assert GEN_AI_TOOL_CALL_ID in attrs
        assert GEN_AI_TOOL_TYPE in attrs

    async def test_tool_span_name_includes_tool_name(self, instrumentor, span_exporter):
        """Span name should be 'execute_tool {tool_name}'."""
        import claude_agent_sdk

        async for _ in claude_agent_sdk.query(
            prompt=_streaming_prompt(TOOL_PROMPT),
            options=make_cheap_options(allowed_tools=["Bash"], permission_mode="bypassPermissions", max_turns=3),
        ):
            pass

        tool_spans = get_execute_tool_spans(span_exporter)
        assert len(tool_spans) >= 1
        # The span name should start with "execute_tool " followed by the tool name
        assert tool_spans[0].name.startswith("execute_tool ")

    async def test_tool_span_status_ok_on_success(self, instrumentor, span_exporter):
        """Successful tool calls should not have ERROR status."""
        import claude_agent_sdk

        async for _ in claude_agent_sdk.query(
            prompt=_streaming_prompt(TOOL_PROMPT),
            options=make_cheap_options(allowed_tools=["Bash"], permission_mode="bypassPermissions", max_turns=3),
        ):
            pass

        tool_spans = get_execute_tool_spans(span_exporter)
        assert len(tool_spans) >= 1
        for ts in tool_spans:
            assert ts.status.status_code != StatusCode.ERROR

    async def test_tool_span_has_positive_duration(self, instrumentor, span_exporter):
        """Tool spans should have non-zero duration (end > start)."""
        import claude_agent_sdk

        async for _ in claude_agent_sdk.query(
            prompt=_streaming_prompt(TOOL_PROMPT),
            options=make_cheap_options(allowed_tools=["Bash"], permission_mode="bypassPermissions", max_turns=3),
        ):
            pass

        tool_spans = get_execute_tool_spans(span_exporter)
        assert len(tool_spans) >= 1
        for ts in tool_spans:
            assert ts.end_time > ts.start_time, "Tool span duration should be > 0"


class TestToolContentCapture:
    async def test_content_capture_enabled_records_arguments(self, instrumentor_with_content_capture, span_exporter):
        """With capture_content=True, gen_ai.tool.call.arguments should be set."""
        import claude_agent_sdk

        async for _ in claude_agent_sdk.query(
            prompt=_streaming_prompt(TOOL_PROMPT),
            options=make_cheap_options(allowed_tools=["Bash"], permission_mode="bypassPermissions", max_turns=3),
        ):
            pass

        tool_spans = get_execute_tool_spans(span_exporter)
        assert len(tool_spans) >= 1

        attrs = dict(tool_spans[0].attributes or {})
        assert GEN_AI_TOOL_CALL_ARGUMENTS in attrs, "Arguments should be captured when content capture is enabled"

    async def test_content_capture_enabled_records_result(self, instrumentor_with_content_capture, span_exporter):
        """With capture_content=True, gen_ai.tool.call.result should be set."""
        import claude_agent_sdk

        async for _ in claude_agent_sdk.query(
            prompt=_streaming_prompt(TOOL_PROMPT),
            options=make_cheap_options(allowed_tools=["Bash"], permission_mode="bypassPermissions", max_turns=3),
        ):
            pass

        tool_spans = get_execute_tool_spans(span_exporter)
        assert len(tool_spans) >= 1

        attrs = dict(tool_spans[0].attributes or {})
        assert GEN_AI_TOOL_CALL_RESULT in attrs, "Result should be captured when content capture is enabled"

    async def test_content_capture_disabled_no_arguments(self, instrumentor, span_exporter):
        """With capture_content=False (default), gen_ai.tool.call.arguments should NOT be set."""
        import claude_agent_sdk

        async for _ in claude_agent_sdk.query(
            prompt=_streaming_prompt(TOOL_PROMPT),
            options=make_cheap_options(allowed_tools=["Bash"], permission_mode="bypassPermissions", max_turns=3),
        ):
            pass

        tool_spans = get_execute_tool_spans(span_exporter)
        assert len(tool_spans) >= 1

        attrs = dict(tool_spans[0].attributes or {})
        assert GEN_AI_TOOL_CALL_ARGUMENTS not in attrs, "Arguments should NOT be captured by default"
        assert GEN_AI_TOOL_CALL_RESULT not in attrs, "Result should NOT be captured by default"
