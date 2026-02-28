"""Shared test fixtures for OpenTelemetry Claude Agent SDK instrumentation tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest
from opentelemetry.sdk.metrics import MeterProvider as SDKMeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider as SDKTracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

# --- Mock SDK Dataclasses ---


def make_usage(
    input_tokens: int = 100,
    output_tokens: int = 50,
    cache_creation_input_tokens: int = 0,
    cache_read_input_tokens: int = 0,
) -> dict[str, int]:
    """Create a mock usage dict matching the real SDK's dict[str, Any] shape."""
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_creation_input_tokens": cache_creation_input_tokens,
        "cache_read_input_tokens": cache_read_input_tokens,
    }


@dataclass
class MockResultMessage:
    """Mock for claude_agent_sdk ResultMessage (no 'type' field, usage is a dict)."""

    usage: dict[str, int] | None = field(default_factory=make_usage)
    session_id: str = "test-session-123"
    subtype: str = "success"
    is_error: bool = False


@dataclass
class MockAssistantMessage:
    """Mock for claude_agent_sdk AssistantMessage (no 'type' field)."""

    model: str = "claude-sonnet-4-20250514"


@dataclass
class MockHookMatcher:
    """Mock for claude_agent_sdk HookMatcher (tool_name match + callback)."""

    tool_name: str | None = None
    callback: Any = None


@dataclass
class MockClaudeAgentOptions:
    """Mock for claude_agent_sdk ClaudeAgentOptions."""

    model: str | None = None
    hooks: dict[str, list[Any]] = field(default_factory=dict)
    system_prompt: str | None = None


# --- OTel Test Fixtures ---


@pytest.fixture()
def span_exporter() -> InMemorySpanExporter:
    """Create an in-memory span exporter for testing."""
    return InMemorySpanExporter()


@pytest.fixture()
def tracer_provider(span_exporter: InMemorySpanExporter) -> SDKTracerProvider:
    """Create a TracerProvider with in-memory exporter for testing."""
    provider = SDKTracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(span_exporter))
    return provider


@pytest.fixture()
def metric_reader() -> InMemoryMetricReader:
    """Create an in-memory metric reader for testing."""
    return InMemoryMetricReader()


@pytest.fixture()
def meter_provider(metric_reader: InMemoryMetricReader) -> SDKMeterProvider:
    """Create a MeterProvider with in-memory reader for testing."""
    return SDKMeterProvider(metric_readers=[metric_reader])
