"""Integration tests for instrument/uninstrument lifecycle with real SDK."""

from __future__ import annotations

import pytest

from opentelemetry.instrumentation.claude_agent_sdk._instrumentor import ClaudeAgentSdkInstrumentor
from opentelemetry.sdk.metrics import MeterProvider as SDKMeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider as SDKTracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from tests.integration.conftest import get_invoke_agent_spans, make_cheap_options, requires_auth

pytestmark = [pytest.mark.integration, requires_auth]


class TestInstrumentationLifecycle:
    def test_instrument_then_uninstrument_restores_originals(self):
        """After uninstrument(), SDK functions should be restored to originals."""
        import claude_agent_sdk

        original_query = claude_agent_sdk.query
        original_client_init = claude_agent_sdk.ClaudeSDKClient.__init__

        instrumentor = ClaudeAgentSdkInstrumentor()
        instrumentor.instrument()

        # Functions should be wrapped (different from original)
        assert claude_agent_sdk.query is not original_query

        instrumentor.uninstrument()

        # Functions should be restored
        assert claude_agent_sdk.query is original_query
        assert claude_agent_sdk.ClaudeSDKClient.__init__ is original_client_init

    async def test_uninstrumented_query_produces_no_spans(self):
        """After uninstrument(), query() should produce 0 spans."""
        import claude_agent_sdk

        exporter = InMemorySpanExporter()
        tp = SDKTracerProvider()
        tp.add_span_processor(SimpleSpanProcessor(exporter))
        reader = InMemoryMetricReader()
        mp = SDKMeterProvider(metric_readers=[reader])

        instrumentor = ClaudeAgentSdkInstrumentor()
        instrumentor.instrument(tracer_provider=tp, meter_provider=mp)
        instrumentor.uninstrument()

        async for _ in claude_agent_sdk.query(
            prompt="What is 2+2? Reply with just the number.", options=make_cheap_options()
        ):
            pass

        spans = get_invoke_agent_spans(exporter)
        assert len(spans) == 0

    async def test_reinstrument_after_uninstrument(self):
        """Re-instrumentation after uninstrument should work correctly."""
        import claude_agent_sdk

        exporter = InMemorySpanExporter()
        tp = SDKTracerProvider()
        tp.add_span_processor(SimpleSpanProcessor(exporter))
        reader = InMemoryMetricReader()
        mp = SDKMeterProvider(metric_readers=[reader])

        instrumentor = ClaudeAgentSdkInstrumentor()

        # First: instrument then uninstrument
        instrumentor.instrument(tracer_provider=tp, meter_provider=mp)
        instrumentor.uninstrument()

        # Second: re-instrument
        instrumentor.instrument(tracer_provider=tp, meter_provider=mp)

        try:
            async for _ in claude_agent_sdk.query(
                prompt="What is 2+2? Reply with just the number.", options=make_cheap_options()
            ):
                pass

            spans = get_invoke_agent_spans(exporter)
            assert len(spans) >= 1
        finally:
            instrumentor.uninstrument()
