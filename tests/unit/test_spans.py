"""Tests for span creation helpers (T007)."""

from __future__ import annotations

from opentelemetry.trace import SpanKind, StatusCode

from opentelemetry.instrumentation.claude_agent_sdk._constants import (
    ERROR_TYPE,
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
from opentelemetry.instrumentation.claude_agent_sdk._spans import (
    create_invoke_agent_span,
    set_error_attributes,
    set_response_model,
    set_result_attributes,
)
from tests.unit.conftest import MockClaudeAgentOptions, MockResultMessage, make_usage


class TestCreateInvokeAgentSpan:
    def test_creates_span_with_correct_name_and_kind(self, tracer_provider, span_exporter):
        tracer = tracer_provider.get_tracer("test")
        span = create_invoke_agent_span(tracer, agent_name="my-agent")
        span.end()

        spans = span_exporter.get_finished_spans()
        assert len(spans) == 1
        assert spans[0].name == "invoke_agent my-agent"
        assert spans[0].kind == SpanKind.CLIENT

    def test_creates_span_without_agent_name(self, tracer_provider, span_exporter):
        tracer = tracer_provider.get_tracer("test")
        span = create_invoke_agent_span(tracer)
        span.end()

        spans = span_exporter.get_finished_spans()
        assert spans[0].name == "invoke_agent"

    def test_sets_required_attributes(self, tracer_provider, span_exporter):
        tracer = tracer_provider.get_tracer("test")
        span = create_invoke_agent_span(tracer, agent_name="test-agent", request_model="claude-sonnet-4-20250514")
        span.end()

        spans = span_exporter.get_finished_spans()
        attrs = dict(spans[0].attributes or {})
        assert attrs[GEN_AI_OPERATION_NAME] == OPERATION_INVOKE_AGENT
        assert attrs[GEN_AI_SYSTEM] == SYSTEM_ANTHROPIC
        assert attrs[GEN_AI_AGENT_NAME] == "test-agent"
        assert attrs[GEN_AI_REQUEST_MODEL] == "claude-sonnet-4-20250514"

    def test_extracts_model_from_options(self, tracer_provider, span_exporter):
        tracer = tracer_provider.get_tracer("test")
        options = MockClaudeAgentOptions(model="claude-haiku-4-5-20251001")
        span = create_invoke_agent_span(tracer, options=options)
        span.end()

        spans = span_exporter.get_finished_spans()
        attrs = dict(spans[0].attributes or {})
        assert attrs[GEN_AI_REQUEST_MODEL] == "claude-haiku-4-5-20251001"

    def test_explicit_model_overrides_options(self, tracer_provider, span_exporter):
        tracer = tracer_provider.get_tracer("test")
        options = MockClaudeAgentOptions(model="claude-haiku-4-5-20251001")
        span = create_invoke_agent_span(tracer, request_model="claude-sonnet-4-20250514", options=options)
        span.end()

        spans = span_exporter.get_finished_spans()
        attrs = dict(spans[0].attributes or {})
        assert attrs[GEN_AI_REQUEST_MODEL] == "claude-sonnet-4-20250514"

    def test_omits_model_when_none(self, tracer_provider, span_exporter):
        tracer = tracer_provider.get_tracer("test")
        span = create_invoke_agent_span(tracer)
        span.end()

        spans = span_exporter.get_finished_spans()
        attrs = dict(spans[0].attributes or {})
        assert GEN_AI_REQUEST_MODEL not in attrs


class TestSetResultAttributes:
    def test_sets_token_usage(self, tracer_provider, span_exporter):
        tracer = tracer_provider.get_tracer("test")
        span = tracer.start_span("test")

        result = MockResultMessage(usage=make_usage(input_tokens=100, output_tokens=50))
        set_result_attributes(span, result)
        span.end()

        spans = span_exporter.get_finished_spans()
        attrs = dict(spans[0].attributes or {})
        assert attrs[GEN_AI_USAGE_INPUT_TOKENS] == 100
        assert attrs[GEN_AI_USAGE_OUTPUT_TOKENS] == 50

    def test_sums_cache_tokens_into_input(self, tracer_provider, span_exporter):
        tracer = tracer_provider.get_tracer("test")
        span = tracer.start_span("test")

        result = MockResultMessage(
            usage=make_usage(
                input_tokens=100,
                output_tokens=50,
                cache_creation_input_tokens=20,
                cache_read_input_tokens=30,
            )
        )
        set_result_attributes(span, result)
        span.end()

        spans = span_exporter.get_finished_spans()
        attrs = dict(spans[0].attributes or {})
        # input_tokens (100) + cache_creation (20) + cache_read (30) = 150
        assert attrs[GEN_AI_USAGE_INPUT_TOKENS] == 150
        assert attrs[GEN_AI_USAGE_OUTPUT_TOKENS] == 50
        assert attrs[GEN_AI_USAGE_CACHE_CREATION_INPUT_TOKENS] == 20
        assert attrs[GEN_AI_USAGE_CACHE_READ_INPUT_TOKENS] == 30

    def test_omits_cache_attrs_when_zero(self, tracer_provider, span_exporter):
        tracer = tracer_provider.get_tracer("test")
        span = tracer.start_span("test")

        result = MockResultMessage(
            usage=make_usage(
                input_tokens=100, output_tokens=50, cache_creation_input_tokens=0, cache_read_input_tokens=0
            )
        )
        set_result_attributes(span, result)
        span.end()

        spans = span_exporter.get_finished_spans()
        attrs = dict(spans[0].attributes or {})
        assert GEN_AI_USAGE_CACHE_CREATION_INPUT_TOKENS not in attrs
        assert GEN_AI_USAGE_CACHE_READ_INPUT_TOKENS not in attrs

    def test_sets_finish_reason_success(self, tracer_provider, span_exporter):
        tracer = tracer_provider.get_tracer("test")
        span = tracer.start_span("test")

        result = MockResultMessage(subtype="success")
        set_result_attributes(span, result)
        span.end()

        spans = span_exporter.get_finished_spans()
        attrs = dict(spans[0].attributes or {})
        assert attrs[GEN_AI_RESPONSE_FINISH_REASONS] == ("end_turn",)

    def test_sets_finish_reason_error(self, tracer_provider, span_exporter):
        tracer = tracer_provider.get_tracer("test")
        span = tracer.start_span("test")

        result = MockResultMessage(subtype="error")
        set_result_attributes(span, result)
        span.end()

        spans = span_exporter.get_finished_spans()
        attrs = dict(spans[0].attributes or {})
        assert attrs[GEN_AI_RESPONSE_FINISH_REASONS] == ("error",)

    def test_sets_finish_reason_max_turns(self, tracer_provider, span_exporter):
        tracer = tracer_provider.get_tracer("test")
        span = tracer.start_span("test")

        result = MockResultMessage(subtype="max_turns")
        set_result_attributes(span, result)
        span.end()

        spans = span_exporter.get_finished_spans()
        attrs = dict(spans[0].attributes or {})
        assert attrs[GEN_AI_RESPONSE_FINISH_REASONS] == ("max_tokens",)

    def test_passthrough_unknown_finish_reason(self, tracer_provider, span_exporter):
        tracer = tracer_provider.get_tracer("test")
        span = tracer.start_span("test")

        result = MockResultMessage(subtype="custom_reason")
        set_result_attributes(span, result)
        span.end()

        spans = span_exporter.get_finished_spans()
        attrs = dict(spans[0].attributes or {})
        assert attrs[GEN_AI_RESPONSE_FINISH_REASONS] == ("custom_reason",)

    def test_sets_conversation_id(self, tracer_provider, span_exporter):
        tracer = tracer_provider.get_tracer("test")
        span = tracer.start_span("test")

        result = MockResultMessage(session_id="session-abc-123")
        set_result_attributes(span, result)
        span.end()

        spans = span_exporter.get_finished_spans()
        attrs = dict(spans[0].attributes or {})
        assert attrs[GEN_AI_CONVERSATION_ID] == "session-abc-123"

    def test_omits_attrs_when_usage_is_none(self, tracer_provider, span_exporter):
        tracer = tracer_provider.get_tracer("test")
        span = tracer.start_span("test")

        result = MockResultMessage(usage=None)
        set_result_attributes(span, result)
        span.end()

        spans = span_exporter.get_finished_spans()
        attrs = dict(spans[0].attributes or {})
        assert GEN_AI_USAGE_INPUT_TOKENS not in attrs
        assert GEN_AI_USAGE_OUTPUT_TOKENS not in attrs


class TestSetErrorAttributes:
    def test_sets_error_type_and_status(self, tracer_provider, span_exporter):
        tracer = tracer_provider.get_tracer("test")
        span = tracer.start_span("test")

        exc = ValueError("something went wrong")
        set_error_attributes(span, exc)
        span.end()

        spans = span_exporter.get_finished_spans()
        attrs = dict(spans[0].attributes or {})
        assert attrs[ERROR_TYPE] == "ValueError"
        assert spans[0].status.status_code == StatusCode.ERROR

    def test_uses_qualname_for_nested_exceptions(self, tracer_provider, span_exporter):
        tracer = tracer_provider.get_tracer("test")
        span = tracer.start_span("test")

        exc = ConnectionError("network error")
        set_error_attributes(span, exc)
        span.end()

        spans = span_exporter.get_finished_spans()
        attrs = dict(spans[0].attributes or {})
        assert attrs[ERROR_TYPE] == "ConnectionError"


class TestSetResponseModel:
    def test_sets_response_model(self, tracer_provider, span_exporter):
        tracer = tracer_provider.get_tracer("test")
        span = tracer.start_span("test")

        set_response_model(span, "claude-sonnet-4-20250514")
        span.end()

        spans = span_exporter.get_finished_spans()
        attrs = dict(spans[0].attributes or {})
        assert attrs[GEN_AI_RESPONSE_MODEL] == "claude-sonnet-4-20250514"
