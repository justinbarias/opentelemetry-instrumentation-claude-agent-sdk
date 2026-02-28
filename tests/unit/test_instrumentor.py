"""Tests for ClaudeAgentSdkInstrumentor lifecycle (T009 + T012)."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from types import ModuleType
from typing import Any

import pytest
from opentelemetry.sdk.metrics import MeterProvider as SDKMeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider as SDKTracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from opentelemetry.instrumentation.claude_agent_sdk._instrumentor import ClaudeAgentSdkInstrumentor

# --- Mock SDK module ---


def _create_mock_sdk_module() -> ModuleType:
    """Create a mock claude_agent_sdk module for testing."""
    mock_module = ModuleType("claude_agent_sdk")

    @dataclass
    class MockClaudeAgentOptions:
        model: str | None = None
        hooks: dict[str, list[Any]] = field(default_factory=dict)
        system_prompt: str | None = None

    class MockClaudeSDKClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.options = kwargs.get("options", MockClaudeAgentOptions())

        async def query(self, *args: Any, **kwargs: Any) -> Any:
            pass

        async def receive_response(self, *args: Any, **kwargs: Any) -> Any:
            yield  # async generator
            pass

    async def mock_query(*args: Any, **kwargs: Any) -> Any:
        yield  # async generator
        pass

    @dataclass
    class AssistantMessage:
        model: str = "claude-sonnet-4-20250514"

    @dataclass
    class ResultMessage:
        usage: dict[str, int] | None = None
        session_id: str = "test-session"
        subtype: str = "success"
        is_error: bool = False

    mock_module.query = mock_query  # type: ignore[attr-defined]
    mock_module.ClaudeSDKClient = MockClaudeSDKClient  # type: ignore[attr-defined]
    mock_module.ClaudeAgentOptions = MockClaudeAgentOptions  # type: ignore[attr-defined]
    mock_module.AssistantMessage = AssistantMessage  # type: ignore[attr-defined]
    mock_module.ResultMessage = ResultMessage  # type: ignore[attr-defined]

    return mock_module


@pytest.fixture()
def mock_sdk_module():
    """Install a mock claude_agent_sdk module for testing."""
    mock_module = _create_mock_sdk_module()
    original = sys.modules.get("claude_agent_sdk")
    sys.modules["claude_agent_sdk"] = mock_module
    yield mock_module
    if original is not None:
        sys.modules["claude_agent_sdk"] = original
    else:
        sys.modules.pop("claude_agent_sdk", None)


class TestInstrumentorLifecycle:
    def test_instrument_applies_patches(self, mock_sdk_module, tracer_provider, meter_provider):
        import claude_agent_sdk

        original_query = claude_agent_sdk.query
        instrumentor = ClaudeAgentSdkInstrumentor()
        instrumentor.instrument(tracer_provider=tracer_provider, meter_provider=meter_provider)

        try:
            # query should be wrapped (different from original)
            assert claude_agent_sdk.query is not original_query
        finally:
            instrumentor.uninstrument()

    def test_uninstrument_removes_patches(self, mock_sdk_module, tracer_provider, meter_provider):
        import claude_agent_sdk

        original_query = claude_agent_sdk.query
        instrumentor = ClaudeAgentSdkInstrumentor()
        instrumentor.instrument(tracer_provider=tracer_provider, meter_provider=meter_provider)
        instrumentor.uninstrument()

        # After uninstrument, query should be restored
        assert claude_agent_sdk.query is original_query

    def test_idempotent_instrument(self, mock_sdk_module, tracer_provider, meter_provider):
        instrumentor = ClaudeAgentSdkInstrumentor()
        instrumentor.instrument(tracer_provider=tracer_provider, meter_provider=meter_provider)
        # Second instrument should not raise
        instrumentor.instrument(tracer_provider=tracer_provider, meter_provider=meter_provider)
        instrumentor.uninstrument()

    def test_idempotent_uninstrument(self, mock_sdk_module, tracer_provider, meter_provider):
        instrumentor = ClaudeAgentSdkInstrumentor()
        instrumentor.instrument(tracer_provider=tracer_provider, meter_provider=meter_provider)
        instrumentor.uninstrument()
        # Second uninstrument should not raise
        instrumentor.uninstrument()

    def test_custom_tracer_provider(self, mock_sdk_module):
        custom_provider = SDKTracerProvider()
        exporter = InMemorySpanExporter()
        custom_provider.add_span_processor(SimpleSpanProcessor(exporter))

        instrumentor = ClaudeAgentSdkInstrumentor()
        instrumentor.instrument(tracer_provider=custom_provider)
        instrumentor.uninstrument()

    def test_custom_meter_provider(self, mock_sdk_module):
        reader = InMemoryMetricReader()
        custom_provider = SDKMeterProvider(metric_readers=[reader])

        instrumentor = ClaudeAgentSdkInstrumentor()
        instrumentor.instrument(meter_provider=custom_provider)
        instrumentor.uninstrument()

    def test_capture_content_kwarg(self, mock_sdk_module, tracer_provider, meter_provider):
        instrumentor = ClaudeAgentSdkInstrumentor()
        instrumentor.instrument(
            tracer_provider=tracer_provider,
            meter_provider=meter_provider,
            capture_content=True,
        )
        instrumentor.uninstrument()

    def test_agent_name_kwarg(self, mock_sdk_module, tracer_provider, meter_provider):
        instrumentor = ClaudeAgentSdkInstrumentor()
        instrumentor.instrument(
            tracer_provider=tracer_provider,
            meter_provider=meter_provider,
            agent_name="my-agent",
        )
        instrumentor.uninstrument()

    def test_instrumentation_dependencies(self):
        instrumentor = ClaudeAgentSdkInstrumentor()
        deps = instrumentor.instrumentation_dependencies()
        assert "claude-agent-sdk >= 0.1.37" in deps

    def test_get_instrumentation_hooks(self, mock_sdk_module, tracer_provider, meter_provider):
        instrumentor = ClaudeAgentSdkInstrumentor()
        instrumentor.instrument(tracer_provider=tracer_provider, meter_provider=meter_provider)

        try:
            hooks = instrumentor.get_instrumentation_hooks()
            assert isinstance(hooks, dict)
            # Should have Stop hook event at minimum
            assert "Stop" in hooks
        finally:
            instrumentor.uninstrument()


class TestZeroOverhead:
    """T012: Zero-overhead when no TracerProvider/MeterProvider configured."""

    def test_instrument_succeeds_without_providers(self, mock_sdk_module):
        """instrument() should succeed even without explicit providers."""
        instrumentor = ClaudeAgentSdkInstrumentor()
        instrumentor.instrument()
        instrumentor.uninstrument()

    async def test_query_works_without_providers(self, mock_sdk_module):
        """query() should work normally when instrumented without providers."""
        import claude_agent_sdk

        instrumentor = ClaudeAgentSdkInstrumentor()
        instrumentor.instrument()

        try:
            # Call the wrapped query — should not raise
            async for _ in claude_agent_sdk.query("test prompt"):
                pass
        finally:
            instrumentor.uninstrument()
