"""Tests for the gen_ai.client.inference.operation.details event
(issue #22 Phase 3).

Covers the message-structuring helpers, the env-var / config gating for the
opt-in content payloads, and end-to-end emission through the instrumentor on
both the standalone ``query()`` and ``ClaudeSDKClient.receive_response()``
paths.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
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
    ENV_CAPTURE_MESSAGE_CONTENT,
    EVENT_GEN_AI_CLIENT_INFERENCE_OPERATION_DETAILS,
    GEN_AI_CONVERSATION_ID,
    GEN_AI_INPUT_MESSAGES,
    GEN_AI_OPERATION_NAME,
    GEN_AI_OUTPUT_MESSAGES,
    GEN_AI_PROVIDER_NAME,
    GEN_AI_REQUEST_MODEL,
    GEN_AI_RESPONSE_FINISH_REASONS,
    GEN_AI_RESPONSE_MODEL,
    GEN_AI_SYSTEM_INSTRUCTIONS,
    GEN_AI_TOOL_DEFINITIONS,
    GEN_AI_USAGE_INPUT_TOKENS,
    GEN_AI_USAGE_OUTPUT_TOKENS,
    OPERATION_INVOKE_AGENT,
    SYSTEM_ANTHROPIC,
)
from opentelemetry.instrumentation.claude_agent_sdk._events import (
    assistant_message_to_structured,
    capture_content_enabled,
    emit_inference_operation_details_event,
    options_to_tool_definitions,
    prompt_to_input_message,
    system_prompt_to_instructions,
    user_message_to_structured,
)
from opentelemetry.instrumentation.claude_agent_sdk._instrumentor import ClaudeAgentSdkInstrumentor

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


def _normalize(value: Any) -> Any:
    """Recursively convert tuples to lists.

    The OTel SDK stores list-valued attributes as tuples in-memory (they only
    become arrays at OTLP-serialization time). Normalize so test assertions
    can compare against literal lists.
    """
    if isinstance(value, tuple):
        return [_normalize(v) for v in value]
    if isinstance(value, list):
        return [_normalize(v) for v in value]
    if isinstance(value, dict):
        return {k: _normalize(v) for k, v in value.items()}
    return value


# ---------------------------------------------------------------------------
# Helper unit tests — structured payload conversion
# ---------------------------------------------------------------------------


@dataclass
class _TextBlock:
    text: str


@dataclass
class _ToolUseBlock:
    id: str
    name: str
    input: dict[str, Any]


@dataclass
class _ToolResultBlock:
    tool_use_id: str
    content: Any
    is_error: bool | None = None


@dataclass
class _ThinkingBlock:
    thinking: str
    signature: str = "sig"


@dataclass
class _UserMessage:
    content: Any


@dataclass
class _AssistantMessage:
    content: list[Any]
    model: str = "claude-sonnet-4-20250514"


class TestStructuredPayloadConversion:
    def test_text_block_to_part(self):
        msg = _AssistantMessage(content=[_TextBlock("hello")])
        out = assistant_message_to_structured(msg)
        assert out == {"role": "assistant", "parts": [{"type": "text", "content": "hello"}]}

    def test_tool_use_block_to_part(self):
        msg = _AssistantMessage(content=[_ToolUseBlock(id="t1", name="Bash", input={"command": "ls"})])
        out = assistant_message_to_structured(msg)
        assert out["parts"] == [
            {"type": "tool_call", "id": "t1", "name": "Bash", "arguments": {"command": "ls"}},
        ]

    def test_tool_result_block_to_part(self):
        msg = _UserMessage(content=[_ToolResultBlock(tool_use_id="t1", content="ok")])
        out = user_message_to_structured(msg)
        assert out["parts"] == [{"type": "tool_call_response", "id": "t1", "response": "ok"}]

    def test_user_message_with_string_content(self):
        msg = _UserMessage(content="hi there")
        assert user_message_to_structured(msg) == {
            "role": "user",
            "parts": [{"type": "text", "content": "hi there"}],
        }

    def test_thinking_block_dropped(self):
        # ThinkingBlock is intentionally excluded — no schema for it on the wire.
        msg = _AssistantMessage(content=[_ThinkingBlock("internal"), _TextBlock("answer")])
        out = assistant_message_to_structured(msg)
        assert out["parts"] == [{"type": "text", "content": "answer"}]

    def test_finish_reason_attached(self):
        msg = _AssistantMessage(content=[_TextBlock("done")])
        out = assistant_message_to_structured(msg, finish_reason="end_turn")
        assert out["finish_reason"] == "end_turn"

    def test_prompt_string_to_input_message(self):
        out = prompt_to_input_message("hello")
        assert out == {"role": "user", "parts": [{"type": "text", "content": "hello"}]}

    def test_prompt_streaming_returns_none(self):
        async def streaming_prompt() -> AsyncIterator[Any]:
            yield {"type": "user"}

        assert prompt_to_input_message(streaming_prompt()) is None

    def test_system_prompt_string(self):
        assert system_prompt_to_instructions("Be helpful.") == [{"type": "text", "content": "Be helpful."}]

    def test_system_prompt_preset_dict(self):
        assert system_prompt_to_instructions({"preset": "claude_code"}) == [
            {"type": "text", "content": "preset:claude_code"}
        ]

    def test_system_prompt_none(self):
        assert system_prompt_to_instructions(None) is None

    def test_tool_definitions_dedup(self):
        @dataclass
        class Opts:
            allowed_tools: list[str] = field(default_factory=lambda: ["Bash", "Read", "Bash"])
            tools: list[str] = field(default_factory=lambda: ["Read"])

        defs = options_to_tool_definitions(Opts())
        names = [d["name"] for d in (defs or [])]
        assert names == ["Bash", "Read"]
        assert all(d["type"] == "function" for d in (defs or []))

    def test_tool_definitions_empty(self):
        @dataclass
        class Opts:
            allowed_tools: list[str] = field(default_factory=list)
            tools: list[str] = field(default_factory=list)

        assert options_to_tool_definitions(Opts()) is None


# ---------------------------------------------------------------------------
# capture_content_enabled — env-var / config gating
# ---------------------------------------------------------------------------


class TestCaptureContentGating:
    def test_config_only(self, monkeypatch):
        monkeypatch.delenv(ENV_CAPTURE_MESSAGE_CONTENT, raising=False)
        assert capture_content_enabled(True) is True

    def test_neither(self, monkeypatch):
        monkeypatch.delenv(ENV_CAPTURE_MESSAGE_CONTENT, raising=False)
        assert capture_content_enabled(False) is False

    @pytest.mark.parametrize("value", ["true", "TRUE", "1", "yes", "Yes"])
    def test_env_truthy(self, monkeypatch, value):
        monkeypatch.setenv(ENV_CAPTURE_MESSAGE_CONTENT, value)
        assert capture_content_enabled(False) is True

    @pytest.mark.parametrize("value", ["false", "0", "no", "", "maybe"])
    def test_env_falsy(self, monkeypatch, value):
        monkeypatch.setenv(ENV_CAPTURE_MESSAGE_CONTENT, value)
        assert capture_content_enabled(False) is False


# ---------------------------------------------------------------------------
# emit_inference_operation_details_event — direct unit tests
# ---------------------------------------------------------------------------


def _make_logger_and_exporter():
    exporter = InMemoryLogRecordExporter()
    provider = LoggerProvider()
    provider.add_log_record_processor(SimpleLogRecordProcessor(exporter))
    return provider.get_logger("test"), provider, exporter


class TestEmitInferenceOperationDetails:
    def test_no_op_when_logger_none(self):
        # Must not raise.
        emit_inference_operation_details_event(
            None,
            base_attributes={GEN_AI_OPERATION_NAME: OPERATION_INVOKE_AGENT},
            input_messages=[{"role": "user", "parts": []}],
            output_messages=None,
            system_instructions=None,
            tool_definitions=None,
            include_content=True,
        )

    def test_emits_with_required_attrs_no_content(self):
        logger, provider, exporter = _make_logger_and_exporter()
        emit_inference_operation_details_event(
            logger,
            base_attributes={
                GEN_AI_OPERATION_NAME: OPERATION_INVOKE_AGENT,
                GEN_AI_PROVIDER_NAME: SYSTEM_ANTHROPIC,
                GEN_AI_REQUEST_MODEL: "claude-sonnet-4",
            },
            input_messages=[{"role": "user", "parts": [{"type": "text", "content": "hi"}]}],
            output_messages=[{"role": "assistant", "parts": []}],
            system_instructions=[{"type": "text", "content": "Be helpful."}],
            tool_definitions=[{"type": "function", "name": "Bash"}],
            include_content=False,
        )
        provider.force_flush()

        records = exporter.get_finished_logs()
        assert len(records) == 1
        record = records[0].log_record
        assert record.event_name == EVENT_GEN_AI_CLIENT_INFERENCE_OPERATION_DETAILS
        assert record.severity_number == SeverityNumber.INFO
        attrs = dict(record.attributes or {})
        assert attrs[GEN_AI_OPERATION_NAME] == OPERATION_INVOKE_AGENT
        assert attrs[GEN_AI_PROVIDER_NAME] == SYSTEM_ANTHROPIC
        # Content fields must be absent when not opted in.
        assert GEN_AI_INPUT_MESSAGES not in attrs
        assert GEN_AI_OUTPUT_MESSAGES not in attrs
        assert GEN_AI_SYSTEM_INSTRUCTIONS not in attrs
        assert GEN_AI_TOOL_DEFINITIONS not in attrs

    def test_emits_with_content_when_opted_in(self):
        logger, provider, exporter = _make_logger_and_exporter()
        emit_inference_operation_details_event(
            logger,
            base_attributes={GEN_AI_OPERATION_NAME: OPERATION_INVOKE_AGENT},
            input_messages=[{"role": "user", "parts": [{"type": "text", "content": "hi"}]}],
            output_messages=[{"role": "assistant", "parts": [{"type": "text", "content": "hello"}]}],
            system_instructions=[{"type": "text", "content": "Be helpful."}],
            tool_definitions=[{"type": "function", "name": "Bash"}],
            include_content=True,
        )
        provider.force_flush()

        attrs = _normalize(dict(exporter.get_finished_logs()[0].log_record.attributes or {}))
        assert attrs[GEN_AI_INPUT_MESSAGES] == [{"role": "user", "parts": [{"type": "text", "content": "hi"}]}]
        assert attrs[GEN_AI_OUTPUT_MESSAGES] == [{"role": "assistant", "parts": [{"type": "text", "content": "hello"}]}]
        assert attrs[GEN_AI_SYSTEM_INSTRUCTIONS] == [{"type": "text", "content": "Be helpful."}]
        assert attrs[GEN_AI_TOOL_DEFINITIONS] == [{"type": "function", "name": "Bash"}]


# ---------------------------------------------------------------------------
# End-to-end through the instrumentor with a mock SDK
# ---------------------------------------------------------------------------


def _make_mock_sdk(*, with_tool: bool = False) -> ModuleType:
    """Mock SDK whose query() yields user/assistant/result messages."""
    mock_module = ModuleType("claude_agent_sdk")

    @dataclass
    class TextBlock:
        text: str

    @dataclass
    class ToolUseBlock:
        id: str
        name: str
        input: dict[str, Any]

    @dataclass
    class ToolResultBlock:
        tool_use_id: str
        content: Any
        is_error: bool | None = None

    @dataclass
    class AssistantMessage:
        content: list[Any]
        model: str = "claude-sonnet-4-20250514"

    @dataclass
    class UserMessage:
        content: Any = None

    @dataclass
    class ResultMessage:
        subtype: str = "success"
        session_id: str = "sess-1"
        usage: dict[str, int] | None = None

    @dataclass
    class ClaudeAgentOptions:
        model: str | None = None
        hooks: dict | None = None
        system_prompt: str | None = None
        allowed_tools: list[str] = field(default_factory=list)
        tools: list[str] = field(default_factory=list)

    if with_tool:
        messages: list[Any] = [
            AssistantMessage(content=[ToolUseBlock(id="t1", name="Bash", input={"command": "ls"})]),
            UserMessage(content=[ToolResultBlock(tool_use_id="t1", content="file1\nfile2")]),
            AssistantMessage(content=[TextBlock("Found 2 files.")]),
            ResultMessage(usage={"input_tokens": 10, "output_tokens": 5}),
        ]
    else:
        messages = [
            AssistantMessage(content=[TextBlock("hello")]),
            ResultMessage(usage={"input_tokens": 3, "output_tokens": 1}),
        ]

    async def _query(*args: Any, **kwargs: Any) -> AsyncIterator[Any]:
        for m in messages:
            yield m

    class ClaudeSDKClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.options = kwargs.get("options") or ClaudeAgentOptions()

        async def query(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def receive_response(self, *args: Any, **kwargs: Any) -> AsyncIterator[Any]:
            for m in messages:
                yield m

    mock_module.TextBlock = TextBlock
    mock_module.ToolUseBlock = ToolUseBlock
    mock_module.ToolResultBlock = ToolResultBlock
    mock_module.AssistantMessage = AssistantMessage
    mock_module.UserMessage = UserMessage
    mock_module.ResultMessage = ResultMessage
    mock_module.ClaudeAgentOptions = ClaudeAgentOptions
    mock_module.ClaudeSDKClient = ClaudeSDKClient
    mock_module.query = _query
    return mock_module


@pytest.fixture
def mock_sdk(monkeypatch):
    mod = _make_mock_sdk()
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", mod)
    types_mod = ModuleType("claude_agent_sdk.types")

    @dataclass
    class HookMatcher:
        matcher: str | None = None
        hooks: list[Any] | None = None

    types_mod.HookMatcher = HookMatcher
    monkeypatch.setitem(sys.modules, "claude_agent_sdk.types", types_mod)
    return mod


@pytest.fixture
def mock_sdk_with_tool(monkeypatch):
    mod = _make_mock_sdk(with_tool=True)
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", mod)
    types_mod = ModuleType("claude_agent_sdk.types")

    @dataclass
    class HookMatcher:
        matcher: str | None = None
        hooks: list[Any] | None = None

    types_mod.HookMatcher = HookMatcher
    monkeypatch.setitem(sys.modules, "claude_agent_sdk.types", types_mod)
    return mod


def _setup_otel():
    span_exporter = InMemorySpanExporter()
    tracer_provider = SDKTracerProvider()
    tracer_provider.add_span_processor(SimpleSpanProcessor(span_exporter))

    log_exporter = InMemoryLogRecordExporter()
    logger_provider = LoggerProvider()
    logger_provider.add_log_record_processor(SimpleLogRecordProcessor(log_exporter))
    return span_exporter, tracer_provider, log_exporter, logger_provider


class TestEndToEndStandaloneQuery:
    async def test_emits_one_event_per_invocation(self, mock_sdk):
        _, tracer_provider, log_exporter, logger_provider = _setup_otel()
        inst = ClaudeAgentSdkInstrumentor()
        inst.instrument(tracer_provider=tracer_provider, logger_provider=logger_provider)
        try:
            options = mock_sdk.ClaudeAgentOptions(system_prompt="Be terse.")
            async for _ in mock_sdk.query(prompt="hi", options=options):
                pass
        finally:
            inst.uninstrument()

        logger_provider.force_flush()
        details = [
            r
            for r in log_exporter.get_finished_logs()
            if r.log_record.event_name == EVENT_GEN_AI_CLIENT_INFERENCE_OPERATION_DETAILS
        ]
        assert len(details) == 1
        attrs = _normalize(dict(details[0].log_record.attributes or {}))
        # Required.
        assert attrs[GEN_AI_OPERATION_NAME] == OPERATION_INVOKE_AGENT
        assert attrs[GEN_AI_PROVIDER_NAME] == SYSTEM_ANTHROPIC
        # Conversation + finish reason + tokens.
        assert attrs[GEN_AI_CONVERSATION_ID] == "sess-1"
        assert attrs[GEN_AI_RESPONSE_FINISH_REASONS] == ["end_turn"]
        assert attrs[GEN_AI_USAGE_INPUT_TOKENS] == 3
        assert attrs[GEN_AI_USAGE_OUTPUT_TOKENS] == 1
        # Response model copied from request when no override observed.
        assert attrs[GEN_AI_RESPONSE_MODEL] == "claude-sonnet-4-20250514"
        # No content by default.
        assert GEN_AI_INPUT_MESSAGES not in attrs
        assert GEN_AI_OUTPUT_MESSAGES not in attrs

    async def test_includes_content_when_opted_in(self, mock_sdk_with_tool, monkeypatch):
        monkeypatch.setenv(ENV_CAPTURE_MESSAGE_CONTENT, "true")
        _, tracer_provider, log_exporter, logger_provider = _setup_otel()
        inst = ClaudeAgentSdkInstrumentor()
        inst.instrument(tracer_provider=tracer_provider, logger_provider=logger_provider)
        try:
            options = mock_sdk_with_tool.ClaudeAgentOptions(
                system_prompt="Be terse.",
                allowed_tools=["Bash"],
            )
            async for _ in mock_sdk_with_tool.query(prompt="list files", options=options):
                pass
        finally:
            inst.uninstrument()

        logger_provider.force_flush()
        details = [
            r
            for r in log_exporter.get_finished_logs()
            if r.log_record.event_name == EVENT_GEN_AI_CLIENT_INFERENCE_OPERATION_DETAILS
        ]
        assert len(details) == 1
        attrs = _normalize(dict(details[0].log_record.attributes or {}))

        # Initial prompt was captured as the first input message.
        input_msgs = attrs[GEN_AI_INPUT_MESSAGES]
        assert input_msgs[0] == {"role": "user", "parts": [{"type": "text", "content": "list files"}]}
        # The tool-result UserMessage in the stream appears next.
        tool_response_part = input_msgs[1]["parts"][0]
        assert tool_response_part["type"] == "tool_call_response"
        assert tool_response_part["id"] == "t1"

        # Output captures the two assistant turns (tool_call then text).
        output_msgs = attrs[GEN_AI_OUTPUT_MESSAGES]
        assert output_msgs[0]["parts"][0] == {
            "type": "tool_call",
            "id": "t1",
            "name": "Bash",
            "arguments": {"command": "ls"},
        }
        assert output_msgs[1]["parts"][0] == {"type": "text", "content": "Found 2 files."}

        # System instructions + tool definitions.
        assert attrs[GEN_AI_SYSTEM_INSTRUCTIONS] == [{"type": "text", "content": "Be terse."}]
        assert attrs[GEN_AI_TOOL_DEFINITIONS] == [{"type": "function", "name": "Bash"}]


class TestEndToEndClientReceiveResponse:
    async def test_emits_event_via_client_path(self, mock_sdk, monkeypatch):
        monkeypatch.setenv(ENV_CAPTURE_MESSAGE_CONTENT, "true")
        _, tracer_provider, log_exporter, logger_provider = _setup_otel()
        inst = ClaudeAgentSdkInstrumentor()
        inst.instrument(tracer_provider=tracer_provider, logger_provider=logger_provider)
        try:
            client = mock_sdk.ClaudeSDKClient(options=mock_sdk.ClaudeAgentOptions())
            await client.query("hello from client")
            async for _ in client.receive_response():
                pass
        finally:
            inst.uninstrument()

        logger_provider.force_flush()
        details = [
            r
            for r in log_exporter.get_finished_logs()
            if r.log_record.event_name == EVENT_GEN_AI_CLIENT_INFERENCE_OPERATION_DETAILS
        ]
        assert len(details) == 1
        attrs = _normalize(dict(details[0].log_record.attributes or {}))
        assert attrs[GEN_AI_INPUT_MESSAGES][0] == {
            "role": "user",
            "parts": [{"type": "text", "content": "hello from client"}],
        }
