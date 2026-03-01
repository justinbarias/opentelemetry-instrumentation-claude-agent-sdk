"""Tests for tool span creation helpers (T004)."""

from __future__ import annotations

from opentelemetry.trace import SpanKind, StatusCode

from opentelemetry.instrumentation.claude_agent_sdk._constants import (
    ERROR_TYPE,
    GEN_AI_OPERATION_NAME,
    GEN_AI_SYSTEM,
    GEN_AI_TOOL_CALL_ID,
    GEN_AI_TOOL_NAME,
    GEN_AI_TOOL_TYPE,
    OPERATION_EXECUTE_TOOL,
    SYSTEM_ANTHROPIC,
    TOOL_TYPE_EXTENSION,
    TOOL_TYPE_FUNCTION,
)
from opentelemetry.instrumentation.claude_agent_sdk._spans import (
    create_execute_tool_span,
    derive_tool_type,
    set_tool_error_attributes,
)


class TestDeriveToolType:
    def test_mcp_tool_returns_extension(self):
        assert derive_tool_type("mcp__server__action") == TOOL_TYPE_EXTENSION

    def test_mcp_prefix_only_returns_extension(self):
        assert derive_tool_type("mcp__anything") == TOOL_TYPE_EXTENSION

    def test_builtin_returns_function(self):
        assert derive_tool_type("Bash") == TOOL_TYPE_FUNCTION

    def test_another_builtin_returns_function(self):
        assert derive_tool_type("Read") == TOOL_TYPE_FUNCTION

    def test_empty_string_returns_function(self):
        assert derive_tool_type("") == TOOL_TYPE_FUNCTION


class TestCreateExecuteToolSpan:
    def test_creates_span_with_correct_name_and_kind(self, tracer_provider, span_exporter):
        tracer = tracer_provider.get_tracer("test")
        span = create_execute_tool_span(tracer, tool_name="Bash", tool_use_id="toolu_123")
        span.end()

        spans = span_exporter.get_finished_spans()
        assert len(spans) == 1
        assert spans[0].name == "execute_tool Bash"
        assert spans[0].kind == SpanKind.INTERNAL

    def test_sets_required_attributes(self, tracer_provider, span_exporter):
        tracer = tracer_provider.get_tracer("test")
        span = create_execute_tool_span(tracer, tool_name="Bash", tool_use_id="toolu_456")
        span.end()

        spans = span_exporter.get_finished_spans()
        attrs = dict(spans[0].attributes or {})
        assert attrs[GEN_AI_OPERATION_NAME] == OPERATION_EXECUTE_TOOL
        assert attrs[GEN_AI_SYSTEM] == SYSTEM_ANTHROPIC
        assert attrs[GEN_AI_TOOL_NAME] == "Bash"
        assert attrs[GEN_AI_TOOL_CALL_ID] == "toolu_456"
        assert attrs[GEN_AI_TOOL_TYPE] == TOOL_TYPE_FUNCTION

    def test_mcp_tool_gets_extension_type(self, tracer_provider, span_exporter):
        tracer = tracer_provider.get_tracer("test")
        span = create_execute_tool_span(tracer, tool_name="mcp__server__action", tool_use_id="toolu_789")
        span.end()

        spans = span_exporter.get_finished_spans()
        attrs = dict(spans[0].attributes or {})
        assert attrs[GEN_AI_TOOL_TYPE] == TOOL_TYPE_EXTENSION
        assert spans[0].name == "execute_tool mcp__server__action"

    def test_span_is_child_of_invoke_agent(self, tracer_provider, span_exporter):
        tracer = tracer_provider.get_tracer("test")

        # Create a parent invoke_agent span
        with tracer.start_as_current_span("invoke_agent test-agent"):
            child = create_execute_tool_span(tracer, tool_name="Bash", tool_use_id="toolu_abc")
            child.end()

        spans = span_exporter.get_finished_spans()
        tool_spans = [s for s in spans if s.name.startswith("execute_tool")]
        parent_spans = [s for s in spans if s.name.startswith("invoke_agent")]

        assert len(tool_spans) == 1
        assert len(parent_spans) == 1
        assert tool_spans[0].parent is not None
        assert tool_spans[0].parent.span_id == parent_spans[0].context.span_id


class TestSetToolErrorAttributes:
    def test_sets_error_type_and_status(self, tracer_provider, span_exporter):
        tracer = tracer_provider.get_tracer("test")
        span = tracer.start_span("test")

        set_tool_error_attributes(span, "Command failed with exit code 1")
        span.end()

        spans = span_exporter.get_finished_spans()
        attrs = dict(spans[0].attributes or {})
        assert attrs[ERROR_TYPE] == "Command failed with exit code 1"
        assert spans[0].status.status_code == StatusCode.ERROR

    def test_error_type_is_raw_string(self, tracer_provider, span_exporter):
        tracer = tracer_provider.get_tracer("test")
        span = tracer.start_span("test")

        set_tool_error_attributes(span, "Permission denied: /etc/shadow")
        span.end()

        spans = span_exporter.get_finished_spans()
        attrs = dict(spans[0].attributes or {})
        assert attrs[ERROR_TYPE] == "Permission denied: /etc/shadow"
