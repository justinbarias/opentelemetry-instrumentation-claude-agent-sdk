"""Integration tests for ClaudeSDKClient multi-turn with real Claude API calls."""

from __future__ import annotations

import pytest
from opentelemetry.trace import SpanKind

from opentelemetry.instrumentation.claude_agent_sdk._constants import (
    GEN_AI_CONVERSATION_ID,
    GEN_AI_OPERATION_NAME,
    GEN_AI_SYSTEM,
    OPERATION_INVOKE_AGENT,
    SYSTEM_ANTHROPIC,
)
from tests.integration.conftest import get_invoke_agent_spans, make_cheap_options, requires_auth

pytestmark = [pytest.mark.integration, requires_auth]


class TestClientMultiTurn:
    async def test_client_single_turn_produces_span(self, instrumentor, span_exporter):
        """A single connect/query/receive_response cycle should produce 1 span."""
        import claude_agent_sdk

        client = claude_agent_sdk.ClaudeSDKClient(options=make_cheap_options())
        await client.connect()
        try:
            await client.query("What is 2+2? Reply with just the number.")
            async for _ in client.receive_response():
                pass
        finally:
            await client.disconnect()

        spans = get_invoke_agent_spans(span_exporter)
        assert len(spans) >= 1
        attrs = dict(spans[0].attributes or {})
        assert attrs[GEN_AI_OPERATION_NAME] == OPERATION_INVOKE_AGENT
        assert attrs[GEN_AI_SYSTEM] == SYSTEM_ANTHROPIC
        assert spans[0].kind == SpanKind.CLIENT

    async def test_client_two_turns_produces_two_spans(self, instrumentor, span_exporter):
        """Two query/receive_response cycles should produce 2 spans."""
        import claude_agent_sdk

        client = claude_agent_sdk.ClaudeSDKClient(options=make_cheap_options())
        await client.connect()
        try:
            # Turn 1
            await client.query("What is 2+2? Reply with just the number.")
            async for _ in client.receive_response():
                pass

            # Turn 2
            await client.query("Now add 1 to that. Reply with just the number.")
            async for _ in client.receive_response():
                pass
        finally:
            await client.disconnect()

        spans = get_invoke_agent_spans(span_exporter)
        assert len(spans) >= 2

    async def test_client_turns_share_conversation_id(self, instrumentor, span_exporter):
        """Both turns should share the same gen_ai.conversation.id."""
        import claude_agent_sdk

        client = claude_agent_sdk.ClaudeSDKClient(options=make_cheap_options())
        await client.connect()
        try:
            # Turn 1
            await client.query("What is 2+2? Reply with just the number.")
            async for _ in client.receive_response():
                pass

            # Turn 2
            await client.query("Now add 1 to that. Reply with just the number.")
            async for _ in client.receive_response():
                pass
        finally:
            await client.disconnect()

        spans = get_invoke_agent_spans(span_exporter)
        conversation_ids = set()
        for span in spans:
            attrs = dict(span.attributes or {})
            if GEN_AI_CONVERSATION_ID in attrs:
                conversation_ids.add(attrs[GEN_AI_CONVERSATION_ID])

        assert len(conversation_ids) == 1

    def test_client_preserves_user_hooks(self, instrumentor):
        """User hooks should be preserved after instrumentation."""
        import claude_agent_sdk

        user_hook = claude_agent_sdk.types.HookMatcher()
        options = make_cheap_options()
        options.hooks = {"Stop": [user_hook]}

        client = claude_agent_sdk.ClaudeSDKClient(options=options)
        stop_hooks = client.options.hooks.get("Stop", [])
        assert user_hook in stop_hooks
