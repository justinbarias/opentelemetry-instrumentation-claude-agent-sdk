"""Integration tests for standalone query() with real Claude API calls."""

from __future__ import annotations

import pytest

from opentelemetry.instrumentation.claude_agent_sdk._constants import (
    GEN_AI_AGENT_NAME,
    GEN_AI_CONVERSATION_ID,
    GEN_AI_OPERATION_NAME,
    GEN_AI_RESPONSE_FINISH_REASONS,
    GEN_AI_RESPONSE_MODEL,
    GEN_AI_SYSTEM,
    GEN_AI_USAGE_INPUT_TOKENS,
    GEN_AI_USAGE_OUTPUT_TOKENS,
    OPERATION_INVOKE_AGENT,
    SYSTEM_ANTHROPIC,
)
from opentelemetry.trace import SpanKind
from tests.integration.conftest import get_invoke_agent_spans, make_cheap_options, requires_auth

pytestmark = [pytest.mark.integration, requires_auth]


class TestStandaloneQuery:
    async def test_query_produces_invoke_agent_span(self, instrumentor, span_exporter):
        """A single query() call should produce 1 invoke_agent CLIENT span."""
        import claude_agent_sdk

        async for _ in claude_agent_sdk.query(
            prompt="What is 2+2? Reply with just the number.", options=make_cheap_options()
        ):
            pass

        spans = get_invoke_agent_spans(span_exporter)
        assert len(spans) >= 1
        span = spans[0]
        assert span.kind == SpanKind.CLIENT

        attrs = dict(span.attributes or {})
        assert attrs[GEN_AI_OPERATION_NAME] == OPERATION_INVOKE_AGENT
        assert attrs[GEN_AI_SYSTEM] == SYSTEM_ANTHROPIC

    async def test_query_captures_response_model(self, instrumentor, span_exporter):
        """The span should capture gen_ai.response.model starting with 'claude-'."""
        import claude_agent_sdk

        async for _ in claude_agent_sdk.query(
            prompt="What is 2+2? Reply with just the number.", options=make_cheap_options()
        ):
            pass

        spans = get_invoke_agent_spans(span_exporter)
        attrs = dict(spans[0].attributes or {})
        assert GEN_AI_RESPONSE_MODEL in attrs
        assert str(attrs[GEN_AI_RESPONSE_MODEL]).startswith("claude-")

    async def test_query_captures_token_usage(self, instrumentor, span_exporter):
        """Token usage attributes should be > 0."""
        import claude_agent_sdk

        async for _ in claude_agent_sdk.query(
            prompt="What is 2+2? Reply with just the number.", options=make_cheap_options()
        ):
            pass

        spans = get_invoke_agent_spans(span_exporter)
        attrs = dict(spans[0].attributes or {})
        assert attrs.get(GEN_AI_USAGE_INPUT_TOKENS, 0) > 0
        assert attrs.get(GEN_AI_USAGE_OUTPUT_TOKENS, 0) > 0

    async def test_query_captures_conversation_id(self, instrumentor, span_exporter):
        """The span should have a non-empty gen_ai.conversation.id."""
        import claude_agent_sdk

        async for _ in claude_agent_sdk.query(
            prompt="What is 2+2? Reply with just the number.", options=make_cheap_options()
        ):
            pass

        spans = get_invoke_agent_spans(span_exporter)
        attrs = dict(spans[0].attributes or {})
        assert GEN_AI_CONVERSATION_ID in attrs
        assert len(str(attrs[GEN_AI_CONVERSATION_ID])) > 0

    async def test_query_captures_finish_reason(self, instrumentor, span_exporter):
        """The span should include gen_ai.response.finish_reasons with 'end_turn'."""
        import claude_agent_sdk

        async for _ in claude_agent_sdk.query(
            prompt="What is 2+2? Reply with just the number.", options=make_cheap_options()
        ):
            pass

        spans = get_invoke_agent_spans(span_exporter)
        attrs = dict(spans[0].attributes or {})
        assert GEN_AI_RESPONSE_FINISH_REASONS in attrs
        assert "end_turn" in attrs[GEN_AI_RESPONSE_FINISH_REASONS]

    async def test_query_with_agent_name(self, instrumentor_with_name, span_exporter):
        """When agent_name is set, span name should include it and attribute should be set."""
        import claude_agent_sdk

        async for _ in claude_agent_sdk.query(
            prompt="What is 2+2? Reply with just the number.", options=make_cheap_options()
        ):
            pass

        spans = get_invoke_agent_spans(span_exporter)
        assert len(spans) >= 1
        assert spans[0].name == "invoke_agent integration-test-agent"
        attrs = dict(spans[0].attributes or {})
        assert attrs[GEN_AI_AGENT_NAME] == "integration-test-agent"

    async def test_query_span_nests_under_parent(self, instrumentor, span_exporter, tracer_provider):
        """invoke_agent span should nest under an explicitly created parent."""
        import claude_agent_sdk

        tracer = tracer_provider.get_tracer("test")
        with tracer.start_as_current_span("parent-op"):
            async for _ in claude_agent_sdk.query(
                prompt="What is 2+2? Reply with just the number.", options=make_cheap_options()
            ):
                pass

        all_spans = span_exporter.get_finished_spans()
        invoke_spans = [s for s in all_spans if s.name.startswith("invoke_agent")]
        parent_spans = [s for s in all_spans if s.name == "parent-op"]

        assert len(invoke_spans) >= 1
        assert len(parent_spans) == 1
        assert invoke_spans[0].parent is not None
        assert invoke_spans[0].parent.span_id == parent_spans[0].context.span_id

    async def test_query_is_root_span_when_no_parent(self, instrumentor, span_exporter):
        """invoke_agent span should be a root span when no parent exists."""
        import claude_agent_sdk

        async for _ in claude_agent_sdk.query(
            prompt="What is 2+2? Reply with just the number.", options=make_cheap_options()
        ):
            pass

        spans = get_invoke_agent_spans(span_exporter)
        assert len(spans) >= 1
        assert spans[0].parent is None
