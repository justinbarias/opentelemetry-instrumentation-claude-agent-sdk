"""Shared fixtures for integration tests against the real Claude Agent SDK."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from dotenv import load_dotenv
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter, SimpleLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider as SDKMeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader, PeriodicExportingMetricReader
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


# --- Optional OTLP forwarding ---
#
# When ``OTEL_INTEGRATION_OTLP_ENDPOINT`` is set, every provider in this
# conftest mirrors its telemetry to an OTLP/gRPC collector in addition to
# the in-memory exporters used for assertions. This lets the same
# integration suite verify behaviour locally and stream signals to a real
# collector (e.g. ``localhost:4317``) in the same run.
_OTLP_ENDPOINT = os.environ.get("OTEL_INTEGRATION_OTLP_ENDPOINT")


def _otlp_span_processor() -> Any:
    if not _OTLP_ENDPOINT:
        return None
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    return BatchSpanProcessor(OTLPSpanExporter(endpoint=_OTLP_ENDPOINT, insecure=True))


def _otlp_metric_reader() -> Any:
    if not _OTLP_ENDPOINT:
        return None
    from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter

    return PeriodicExportingMetricReader(OTLPMetricExporter(endpoint=_OTLP_ENDPOINT, insecure=True))


def _otlp_log_processor() -> Any:
    if not _OTLP_ENDPOINT:
        return None
    from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
    from opentelemetry.sdk._logs.export import BatchLogRecordProcessor

    return BatchLogRecordProcessor(OTLPLogExporter(endpoint=_OTLP_ENDPOINT, insecure=True))


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
    otlp = _otlp_span_processor()
    if otlp is not None:
        provider.add_span_processor(otlp)
    yield provider
    # Flush OTLP before tearing the provider down so spans actually leave the
    # process before the next test resets fixtures.
    provider.shutdown()


@pytest.fixture()
def metric_reader() -> InMemoryMetricReader:
    return InMemoryMetricReader()


@pytest.fixture()
def meter_provider(metric_reader: InMemoryMetricReader) -> SDKMeterProvider:
    readers: list[Any] = [metric_reader]
    otlp = _otlp_metric_reader()
    if otlp is not None:
        readers.append(otlp)
    provider = SDKMeterProvider(metric_readers=readers)
    yield provider
    provider.shutdown()


@pytest.fixture()
def log_record_exporter() -> InMemoryLogRecordExporter:
    return InMemoryLogRecordExporter()


@pytest.fixture()
def logger_provider(log_record_exporter: InMemoryLogRecordExporter) -> LoggerProvider:
    provider = LoggerProvider()
    provider.add_log_record_processor(SimpleLogRecordProcessor(log_record_exporter))
    otlp = _otlp_log_processor()
    if otlp is not None:
        provider.add_log_record_processor(otlp)
    yield provider
    provider.shutdown()


@pytest.fixture()
def instrumentor(tracer_provider: SDKTracerProvider, meter_provider: SDKMeterProvider) -> ClaudeAgentSdkInstrumentor:
    """Instrument before the test, uninstrument after."""
    inst = ClaudeAgentSdkInstrumentor()
    inst.instrument(tracer_provider=tracer_provider, meter_provider=meter_provider)
    yield inst  # type: ignore[misc]
    inst.uninstrument()


@pytest.fixture()
def instrumentor_with_logs(
    tracer_provider: SDKTracerProvider,
    meter_provider: SDKMeterProvider,
    logger_provider: LoggerProvider,
) -> ClaudeAgentSdkInstrumentor:
    """Instrument with all three providers (tracer, meter, logger)."""
    inst = ClaudeAgentSdkInstrumentor()
    inst.instrument(
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
        logger_provider=logger_provider,
    )
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
