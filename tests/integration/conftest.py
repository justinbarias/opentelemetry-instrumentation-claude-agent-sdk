"""Shared fixtures for integration tests against the real Claude Agent SDK."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from dotenv import load_dotenv
from opentelemetry.sdk.metrics import MeterProvider as SDKMeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider as SDKTracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from opentelemetry.instrumentation.claude_agent_sdk._instrumentor import ClaudeAgentSdkInstrumentor

# Load .env from tests/integration/.env
_ENV_PATH = Path(__file__).parent / ".env"
load_dotenv(_ENV_PATH)

# Unset CLAUDECODE env var to prevent nested-session detection when running
# integration tests from within a Claude Code session.
os.environ.pop("CLAUDECODE", None)

# --- Auth skip marker ---
requires_auth = pytest.mark.skipif(
    not os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"),
    reason="CLAUDE_CODE_OAUTH_TOKEN not set — skipping integration test",
)


# --- OTel fixtures ---


@pytest.fixture()
def span_exporter() -> InMemorySpanExporter:
    return InMemorySpanExporter()


@pytest.fixture()
def tracer_provider(span_exporter: InMemorySpanExporter) -> SDKTracerProvider:
    provider = SDKTracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(span_exporter))
    return provider


@pytest.fixture()
def metric_reader() -> InMemoryMetricReader:
    return InMemoryMetricReader()


@pytest.fixture()
def meter_provider(metric_reader: InMemoryMetricReader) -> SDKMeterProvider:
    return SDKMeterProvider(metric_readers=[metric_reader])


@pytest.fixture()
def instrumentor(tracer_provider: SDKTracerProvider, meter_provider: SDKMeterProvider) -> ClaudeAgentSdkInstrumentor:
    """Instrument before the test, uninstrument after."""
    inst = ClaudeAgentSdkInstrumentor()
    inst.instrument(tracer_provider=tracer_provider, meter_provider=meter_provider)
    yield inst  # type: ignore[misc]
    inst.uninstrument()


@pytest.fixture()
def instrumentor_with_content_capture(
    tracer_provider: SDKTracerProvider, meter_provider: SDKMeterProvider
) -> ClaudeAgentSdkInstrumentor:
    """Instrument with capture_content=True."""
    inst = ClaudeAgentSdkInstrumentor()
    inst.instrument(tracer_provider=tracer_provider, meter_provider=meter_provider, capture_content=True)
    yield inst  # type: ignore[misc]
    inst.uninstrument()


@pytest.fixture()
def instrumentor_with_name(
    tracer_provider: SDKTracerProvider, meter_provider: SDKMeterProvider
) -> ClaudeAgentSdkInstrumentor:
    """Instrument with agent_name='integration-test-agent'."""
    inst = ClaudeAgentSdkInstrumentor()
    inst.instrument(tracer_provider=tracer_provider, meter_provider=meter_provider, agent_name="integration-test-agent")
    yield inst  # type: ignore[misc]
    inst.uninstrument()


# --- Helpers ---


def get_invoke_agent_spans(exporter: InMemorySpanExporter) -> list[Any]:
    """Return finished spans whose name starts with 'invoke_agent'."""
    return [s for s in exporter.get_finished_spans() if s.name.startswith("invoke_agent")]


def get_execute_tool_spans(exporter: InMemorySpanExporter) -> list[Any]:
    """Return finished spans whose name starts with 'execute_tool'."""
    return [s for s in exporter.get_finished_spans() if s.name.startswith("execute_tool")]


def get_metric_data_points(reader: InMemoryMetricReader, metric_name: str) -> list[Any]:
    """Extract histogram data points for a given metric name."""
    metrics_data = reader.get_metrics_data()
    points: list[Any] = []
    for rm in metrics_data.resource_metrics:
        for sm in rm.scope_metrics:
            for metric in sm.metrics:
                if metric.name == metric_name:
                    points.extend(metric.data.data_points)
    return points


def make_cheap_options(**overrides: Any) -> Any:
    """Create ClaudeAgentOptions with minimal cost settings."""
    from claude_agent_sdk import ClaudeAgentOptions

    defaults = {
        "max_turns": 1,
        "permission_mode": "plan",
    }
    defaults.update(overrides)
    return ClaudeAgentOptions(**defaults)
