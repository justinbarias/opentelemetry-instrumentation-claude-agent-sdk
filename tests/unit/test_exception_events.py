"""Tests for the gen_ai.client.operation.exception event and span.record_exception
wiring on agent error paths (#22 Phase 1 + Phase 2)."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from types import ModuleType
from typing import TYPE_CHECKING, Any

import pytest
from opentelemetry._logs import SeverityNumber
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter, SimpleLogRecordProcessor
from opentelemetry.sdk.trace import TracerProvider as SDKTracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from opentelemetry.instrumentation.claude_agent_sdk._constants import (
    EVENT_GEN_AI_CLIENT_OPERATION_EXCEPTION,
    EXCEPTION_MESSAGE,
    EXCEPTION_STACKTRACE,
    EXCEPTION_TYPE,
    GEN_AI_OPERATION_NAME,
    GEN_AI_PROVIDER_NAME,
    OPERATION_INVOKE_AGENT,
    SCHEMA_URL,
    SYSTEM_ANTHROPIC,
)
from opentelemetry.instrumentation.claude_agent_sdk._events import emit_operation_exception_event
from opentelemetry.instrumentation.claude_agent_sdk._instrumentor import ClaudeAgentSdkInstrumentor

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


class TestEmitOperationExceptionEvent:
    def test_no_op_when_logger_none(self):
        # Must not raise.
        emit_operation_exception_event(None, ValueError("x"))

    def test_emits_event_with_required_attrs(self):
        exporter = InMemoryLogRecordExporter()
        provider = LoggerProvider()
        provider.add_log_record_processor(SimpleLogRecordProcessor(exporter))
        logger = provider.get_logger("test")

        emit_operation_exception_event(
            logger,
            ValueError("boom"),
            {GEN_AI_OPERATION_NAME: OPERATION_INVOKE_AGENT, GEN_AI_PROVIDER_NAME: SYSTEM_ANTHROPIC},
        )
        provider.force_flush()

        records = exporter.get_finished_logs()
        assert len(records) == 1
        record = records[0].log_record
        assert record.event_name == EVENT_GEN_AI_CLIENT_OPERATION_EXCEPTION
        assert record.severity_number == SeverityNumber.WARN
        attrs = dict(record.attributes or {})
        assert attrs[EXCEPTION_TYPE] == "ValueError"
        assert attrs[EXCEPTION_MESSAGE] == "boom"
        assert EXCEPTION_STACKTRACE in attrs
        # span attribute copy
        assert attrs[GEN_AI_OPERATION_NAME] == OPERATION_INVOKE_AGENT
        assert attrs[GEN_AI_PROVIDER_NAME] == SYSTEM_ANTHROPIC


# --- End-to-end: agent error paths wire both record_exception and the event ---


def _create_mock_sdk_that_raises() -> ModuleType:
    """Mock claude_agent_sdk whose query() async generator raises."""
    mock_module = ModuleType("claude_agent_sdk")

    @dataclass
    class AssistantMessage:
        model: str = "claude-sonnet-4-20250514"

    @dataclass
    class ResultMessage:
        subtype: str = "success"
        session_id: str = "sess-1"
        usage: Any = None

    @dataclass
    class ClaudeAgentOptions:
        model: str | None = None
        hooks: dict | None = None

    async def _raising_query(*args: Any, **kwargs: Any) -> AsyncIterator[Any]:
        raise RuntimeError("upstream blew up")
        yield  # pragma: no cover — make this an async generator

    class ClaudeSDKClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.options = kwargs.get("options") or ClaudeAgentOptions()

        async def query(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def receive_response(self, *args: Any, **kwargs: Any) -> AsyncIterator[Any]:
            raise RuntimeError("upstream blew up")
            yield  # pragma: no cover — make this an async generator

    mock_module.AssistantMessage = AssistantMessage
    mock_module.ResultMessage = ResultMessage
    mock_module.ClaudeAgentOptions = ClaudeAgentOptions
    mock_module.ClaudeSDKClient = ClaudeSDKClient
    mock_module.query = _raising_query
    return mock_module


@pytest.fixture
def mock_sdk_raising(monkeypatch):
    mock = _create_mock_sdk_that_raises()
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", mock)
    # also stub the types submodule HookMatcher import used by _hooks._make_hook_matcher
    types_mod = ModuleType("claude_agent_sdk.types")

    @dataclass
    class HookMatcher:
        matcher: str | None = None
        hooks: list[Any] | None = None

    types_mod.HookMatcher = HookMatcher
    monkeypatch.setitem(sys.modules, "claude_agent_sdk.types", types_mod)
    return mock


class TestStandaloneQueryErrorPath:
    async def test_records_exception_and_emits_event(self, mock_sdk_raising):
        span_exporter = InMemorySpanExporter()
        tracer_provider = SDKTracerProvider()
        tracer_provider.add_span_processor(SimpleSpanProcessor(span_exporter))

        log_exporter = InMemoryLogRecordExporter()
        logger_provider = LoggerProvider()
        logger_provider.add_log_record_processor(SimpleLogRecordProcessor(log_exporter))

        instrumentor = ClaudeAgentSdkInstrumentor()
        instrumentor.instrument(
            tracer_provider=tracer_provider,
            logger_provider=logger_provider,
        )
        try:
            with pytest.raises(RuntimeError, match="upstream blew up"):
                async for _ in mock_sdk_raising.query(prompt="hi"):
                    pass
        finally:
            instrumentor.uninstrument()

        # Phase 1: span.record_exception produced the standard "exception" event
        spans = span_exporter.get_finished_spans()
        assert len(spans) == 1
        span_event_names = [e.name for e in spans[0].events]
        assert "exception" in span_event_names
        # §14 — schema URL surfaces on the instrumentation scope
        assert spans[0].instrumentation_scope.schema_url == SCHEMA_URL

        # Phase 2: a separate gen_ai.client.operation.exception log record
        logger_provider.force_flush()
        log_records = log_exporter.get_finished_logs()
        gen_ai_events = [r for r in log_records if r.log_record.event_name == EVENT_GEN_AI_CLIENT_OPERATION_EXCEPTION]
        assert len(gen_ai_events) == 1
        attrs = dict(gen_ai_events[0].log_record.attributes or {})
        assert attrs[EXCEPTION_TYPE] == "RuntimeError"
        assert attrs[EXCEPTION_MESSAGE] == "upstream blew up"
        assert attrs[GEN_AI_PROVIDER_NAME] == SYSTEM_ANTHROPIC


class TestClientReceiveResponseErrorPath:
    async def test_records_exception_and_emits_event(self, mock_sdk_raising):
        span_exporter = InMemorySpanExporter()
        tracer_provider = SDKTracerProvider()
        tracer_provider.add_span_processor(SimpleSpanProcessor(span_exporter))

        log_exporter = InMemoryLogRecordExporter()
        logger_provider = LoggerProvider()
        logger_provider.add_log_record_processor(SimpleLogRecordProcessor(log_exporter))

        instrumentor = ClaudeAgentSdkInstrumentor()
        instrumentor.instrument(
            tracer_provider=tracer_provider,
            logger_provider=logger_provider,
        )
        try:
            import claude_agent_sdk

            client = claude_agent_sdk.ClaudeSDKClient(options=claude_agent_sdk.ClaudeAgentOptions())
            await client.query("hi")
            with pytest.raises(RuntimeError, match="upstream blew up"):
                async for _ in client.receive_response():
                    pass
        finally:
            instrumentor.uninstrument()

        # Phase 1: span got the standard "exception" event from record_exception
        spans = span_exporter.get_finished_spans()
        assert len(spans) == 1
        assert "exception" in [e.name for e in spans[0].events]

        # Phase 2: a gen_ai.client.operation.exception log record was emitted
        logger_provider.force_flush()
        gen_ai_events = [
            r
            for r in log_exporter.get_finished_logs()
            if r.log_record.event_name == EVENT_GEN_AI_CLIENT_OPERATION_EXCEPTION
        ]
        assert len(gen_ai_events) == 1
        attrs = dict(gen_ai_events[0].log_record.attributes or {})
        assert attrs[EXCEPTION_TYPE] == "RuntimeError"
        assert attrs[GEN_AI_PROVIDER_NAME] == SYSTEM_ANTHROPIC
