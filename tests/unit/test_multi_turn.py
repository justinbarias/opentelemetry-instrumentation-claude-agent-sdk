"""Tests for ClaudeSDKClient multi-turn wrapper (T011)."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from types import ModuleType
from typing import TYPE_CHECKING, Any

import pytest
from opentelemetry.sdk.metrics import MeterProvider as SDKMeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider as SDKTracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind

from opentelemetry.instrumentation.claude_agent_sdk._constants import (
    GEN_AI_CONVERSATION_ID,
    GEN_AI_OPERATION_NAME,
    GEN_AI_SYSTEM,
    OPERATION_INVOKE_AGENT,
    SYSTEM_ANTHROPIC,
)
from opentelemetry.instrumentation.claude_agent_sdk._instrumentor import ClaudeAgentSdkInstrumentor
from tests.unit.conftest import make_usage

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


def _create_mock_sdk() -> ModuleType:
    """Create mock SDK with ClaudeSDKClient for multi-turn testing."""
    mock_module = ModuleType("claude_agent_sdk")

    @dataclass
    class AssistantMessage:
        model: str = "claude-sonnet-4-20250514"

    @dataclass
    class ResultMessage:
        usage: dict[str, int] | None = field(default_factory=make_usage)
        session_id: str = "multi-turn-session"
        subtype: str = "success"
        is_error: bool = False

    messages: list[Any] = [AssistantMessage(), ResultMessage()]

    @dataclass
    class ClaudeAgentOptions:
        model: str | None = None
        hooks: dict[str, list[Any]] = field(default_factory=dict)
        system_prompt: str | None = None

    class ClaudeSDKClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.options = kwargs.get("options", ClaudeAgentOptions())
            self._conversation: list[Any] = []

        async def query(self, prompt: str, **kwargs: Any) -> None:
            self._conversation.append({"role": "user", "content": prompt})

        async def receive_response(self, **kwargs: Any) -> AsyncIterator[Any]:
            for msg in messages:
                yield msg

    async def mock_query(*args: Any, **kwargs: Any) -> AsyncIterator[Any]:
        for msg in messages:
            yield msg

    mock_module.query = mock_query  # type: ignore[attr-defined]
    mock_module.ClaudeSDKClient = ClaudeSDKClient  # type: ignore[attr-defined]
    mock_module.ClaudeAgentOptions = ClaudeAgentOptions  # type: ignore[attr-defined]
    mock_module.AssistantMessage = AssistantMessage  # type: ignore[attr-defined]
    mock_module.ResultMessage = ResultMessage  # type: ignore[attr-defined]

    return mock_module


@pytest.fixture()
def mock_sdk():
    mock_module = _create_mock_sdk()
    original = sys.modules.get("claude_agent_sdk")
    sys.modules["claude_agent_sdk"] = mock_module
    yield mock_module
    if original is not None:
        sys.modules["claude_agent_sdk"] = original
    else:
        sys.modules.pop("claude_agent_sdk", None)


@pytest.fixture()
def otel_setup():
    exporter = InMemorySpanExporter()
    tp = SDKTracerProvider()
    tp.add_span_processor(SimpleSpanProcessor(exporter))
    reader = InMemoryMetricReader()
    mp = SDKMeterProvider(metric_readers=[reader])
    return tp, mp, exporter, reader


class TestClaudeSDKClientWrapper:
    async def test_init_injects_hooks(self, mock_sdk, otel_setup):
        """__init__ should inject instrumentation hooks into options."""
        tp, mp, _exporter, _reader = otel_setup
        instrumentor = ClaudeAgentSdkInstrumentor()
        instrumentor.instrument(tracer_provider=tp, meter_provider=mp)

        try:
            import claude_agent_sdk

            client = claude_agent_sdk.ClaudeSDKClient()
            # Should have hooks injected
            assert hasattr(client, "options")
            assert isinstance(client.options.hooks, dict)
            # Should have Stop hook
            assert "Stop" in client.options.hooks
        finally:
            instrumentor.uninstrument()

    async def test_multi_turn_produces_per_turn_spans(self, mock_sdk, otel_setup):
        """Each query()/receive_response() pair should produce a span."""
        tp, mp, exporter, _reader = otel_setup
        instrumentor = ClaudeAgentSdkInstrumentor()
        instrumentor.instrument(tracer_provider=tp, meter_provider=mp)

        try:
            import claude_agent_sdk

            client = claude_agent_sdk.ClaudeSDKClient()

            # Turn 1
            await client.query("Hello")
            async for _ in client.receive_response():
                pass

            # Turn 2
            await client.query("Follow up")
            async for _ in client.receive_response():
                pass

            spans = exporter.get_finished_spans()
            invoke_spans = [s for s in spans if s.name.startswith("invoke_agent")]
            assert len(invoke_spans) == 2

            for span in invoke_spans:
                assert span.kind == SpanKind.CLIENT
                attrs = dict(span.attributes or {})
                assert attrs[GEN_AI_OPERATION_NAME] == OPERATION_INVOKE_AGENT
                assert attrs[GEN_AI_SYSTEM] == SYSTEM_ANTHROPIC
        finally:
            instrumentor.uninstrument()

    async def test_shared_conversation_id(self, mock_sdk, otel_setup):
        """All turns should share the same conversation.id."""
        tp, mp, exporter, _reader = otel_setup
        instrumentor = ClaudeAgentSdkInstrumentor()
        instrumentor.instrument(tracer_provider=tp, meter_provider=mp)

        try:
            import claude_agent_sdk

            client = claude_agent_sdk.ClaudeSDKClient()

            # Turn 1
            await client.query("Hello")
            async for _ in client.receive_response():
                pass

            # Turn 2
            await client.query("Follow up")
            async for _ in client.receive_response():
                pass

            spans = exporter.get_finished_spans()
            invoke_spans = [s for s in spans if s.name.startswith("invoke_agent")]
            conversation_ids = set()
            for span in invoke_spans:
                attrs = dict(span.attributes or {})
                if GEN_AI_CONVERSATION_ID in attrs:
                    conversation_ids.add(attrs[GEN_AI_CONVERSATION_ID])

            # All spans should have the same conversation.id
            assert len(conversation_ids) == 1
            assert "multi-turn-session" in conversation_ids
        finally:
            instrumentor.uninstrument()

    async def test_hook_merge_preserves_user_hooks(self, mock_sdk, otel_setup):
        """User hooks should be preserved when instrumentation hooks are injected."""
        tp, mp, _exporter, _reader = otel_setup
        instrumentor = ClaudeAgentSdkInstrumentor()
        instrumentor.instrument(tracer_provider=tp, meter_provider=mp)

        try:
            import claude_agent_sdk

            user_callback = lambda *args, **kwargs: {}  # noqa: E731
            user_hooks = {"Stop": [user_callback]}
            options = claude_agent_sdk.ClaudeAgentOptions(hooks=user_hooks)
            client = claude_agent_sdk.ClaudeSDKClient(options=options)

            # User callback should still be first in the list
            stop_hooks = client.options.hooks.get("Stop", [])
            assert len(stop_hooks) >= 2  # user + instrumentation
            assert stop_hooks[0] is user_callback
        finally:
            instrumentor.uninstrument()
