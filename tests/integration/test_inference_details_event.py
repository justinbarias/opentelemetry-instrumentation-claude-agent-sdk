"""Integration tests for the gen_ai.client.inference.operation.details event
(issue #22 Phase 3) against the real Claude Agent SDK + API.

These assertions intentionally stay loose about *content* (the model's
exact response is non-deterministic) and focus on the event's shape:
event name, required attributes, opt-in gating of content fields, and the
structured payload format.
"""

from __future__ import annotations

from typing import Any

import pytest

from opentelemetry.instrumentation.claude_agent_sdk._constants import (
    ENV_CAPTURE_MESSAGE_CONTENT,
    EVENT_GEN_AI_CLIENT_INFERENCE_OPERATION_DETAILS,
    GEN_AI_CONVERSATION_ID,
    GEN_AI_INPUT_MESSAGES,
    GEN_AI_OPERATION_NAME,
    GEN_AI_OUTPUT_MESSAGES,
    GEN_AI_PROVIDER_NAME,
    GEN_AI_RESPONSE_FINISH_REASONS,
    GEN_AI_SYSTEM_INSTRUCTIONS,
    GEN_AI_TOOL_DEFINITIONS,
    GEN_AI_USAGE_INPUT_TOKENS,
    GEN_AI_USAGE_OUTPUT_TOKENS,
    OPERATION_INVOKE_AGENT,
    SYSTEM_ANTHROPIC,
)
from tests.integration.conftest import make_cheap_options, requires_auth

pytestmark = [pytest.mark.integration, requires_auth]


def _normalize(value: Any) -> Any:
    """Recursively coerce tuples back to lists.

    The OTel SDK stores list-valued log attributes as tuples in-memory.
    Normalizing lets assertions compare against literal Python lists.
    """
    if isinstance(value, (tuple, list)):
        return [_normalize(v) for v in value]
    if isinstance(value, dict):
        return {k: _normalize(v) for k, v in value.items()}
    return value


def _details_events(log_exporter: Any) -> list[Any]:
    return [
        r
        for r in log_exporter.get_finished_logs()
        if r.log_record.event_name == EVENT_GEN_AI_CLIENT_INFERENCE_OPERATION_DETAILS
    ]


class TestInferenceDetailsEventEmission:
    """The event fires exactly once per invoke_agent invocation with the
    required GenAI attributes attached, regardless of capture-content state."""

    async def test_event_emitted_with_required_attrs(self, instrumentor_with_logs, log_record_exporter):
        import claude_agent_sdk

        async for _ in claude_agent_sdk.query(
            prompt="What is 2+2? Reply with just the number.", options=make_cheap_options()
        ):
            pass

        events = _details_events(log_record_exporter)
        assert len(events) == 1, "exactly one details event per invoke_agent invocation"

        attrs = _normalize(dict(events[0].log_record.attributes or {}))
        # Spec-required.
        assert attrs[GEN_AI_OPERATION_NAME] == OPERATION_INVOKE_AGENT
        assert attrs[GEN_AI_PROVIDER_NAME] == SYSTEM_ANTHROPIC
        # Conversation id from the SDK's session_id.
        assert isinstance(attrs.get(GEN_AI_CONVERSATION_ID), str)
        # Finish reason should be the normalised mapping, not the SDK subtype.
        finish_reasons = attrs.get(GEN_AI_RESPONSE_FINISH_REASONS)
        assert finish_reasons is not None
        assert finish_reasons[0] in {"end_turn", "max_turns", "error"}
        # Usage tokens come back from the real API.
        assert attrs.get(GEN_AI_USAGE_INPUT_TOKENS, 0) >= 0
        assert attrs.get(GEN_AI_USAGE_OUTPUT_TOKENS, 0) >= 0


class TestContentGatingDisabled:
    """When the env var is not set and the instrumentor is configured with the
    default ``capture_content=False``, the opt-in content payloads MUST NOT
    appear on the event — the event itself still emits with the required
    non-content attributes."""

    async def test_no_content_attrs_when_opted_out(self, instrumentor_with_logs, log_record_exporter, monkeypatch):
        monkeypatch.delenv(ENV_CAPTURE_MESSAGE_CONTENT, raising=False)
        import claude_agent_sdk

        async for _ in claude_agent_sdk.query(
            prompt="What is 2+2? Reply with just the number.", options=make_cheap_options()
        ):
            pass

        events = _details_events(log_record_exporter)
        assert len(events) == 1
        attrs = dict(events[0].log_record.attributes or {})
        # Content-bearing fields must be absent.
        assert GEN_AI_INPUT_MESSAGES not in attrs
        assert GEN_AI_OUTPUT_MESSAGES not in attrs
        assert GEN_AI_SYSTEM_INSTRUCTIONS not in attrs
        assert GEN_AI_TOOL_DEFINITIONS not in attrs


class TestContentGatingViaEnvVar:
    """With ``OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=true`` set
    *before* instrumentation, the content payloads must be attached and
    follow the structured-parts shape from the GenAI events spec."""

    async def test_content_attrs_attached_when_env_opted_in(
        self, instrumentor_with_logs, log_record_exporter, monkeypatch
    ):
        # ``capture_content_enabled`` reads the env at emit time, so setting
        # the var on the active fixture is sufficient.
        monkeypatch.setenv(ENV_CAPTURE_MESSAGE_CONTENT, "true")
        import claude_agent_sdk

        options = make_cheap_options()
        options.system_prompt = "Reply with just a number, no words."
        async for _ in claude_agent_sdk.query(prompt="What is 2+2?", options=options):
            pass

        events = _details_events(log_record_exporter)
        assert len(events) == 1
        attrs = _normalize(dict(events[0].log_record.attributes or {}))

        # The user's prompt landed as the first input message.
        input_msgs = attrs.get(GEN_AI_INPUT_MESSAGES)
        assert input_msgs is not None and len(input_msgs) >= 1
        first = input_msgs[0]
        assert first["role"] == "user"
        assert any(p.get("type") == "text" and "2+2" in p.get("content", "") for p in first["parts"])

        # The model produced at least one output message with a text part.
        output_msgs = attrs.get(GEN_AI_OUTPUT_MESSAGES)
        assert output_msgs is not None and len(output_msgs) >= 1
        assert any(
            p.get("type") == "text" for m in output_msgs for p in m.get("parts", [])
        ), "expected at least one text part in output"

        # System prompt becomes a single-entry instructions list.
        assert attrs[GEN_AI_SYSTEM_INSTRUCTIONS] == [{"type": "text", "content": "Reply with just a number, no words."}]


class TestStructuredToolPayload:
    """When the model calls a tool, the request/response flow round-trips as
    ``tool_call`` / ``tool_call_response`` parts on the structured payload."""

    TOOL_PROMPT = "Use the Bash tool to run: echo hello_otel_inference"

    async def test_tool_call_round_trip(self, instrumentor_with_logs, log_record_exporter, monkeypatch):
        monkeypatch.setenv(ENV_CAPTURE_MESSAGE_CONTENT, "true")
        import claude_agent_sdk

        options = make_cheap_options(allowed_tools=["Bash"], permission_mode="bypassPermissions", max_turns=3)

        async def _streaming_prompt():
            # Wrap in an async iterator so the SDK keeps stdin open for hooks.
            yield {
                "type": "user",
                "session_id": "",
                "message": {"role": "user", "content": self.TOOL_PROMPT},
                "parent_tool_use_id": None,
            }

        async for _ in claude_agent_sdk.query(prompt=_streaming_prompt(), options=options):
            pass

        events = _details_events(log_record_exporter)
        assert len(events) == 1
        attrs = _normalize(dict(events[0].log_record.attributes or {}))

        # Tool definitions echo back the configured surface.
        tool_defs = attrs.get(GEN_AI_TOOL_DEFINITIONS) or []
        assert any(d.get("name") == "Bash" for d in tool_defs)

        # Output messages should contain at least one tool_call part.
        output_msgs = attrs.get(GEN_AI_OUTPUT_MESSAGES) or []
        tool_calls = [p for m in output_msgs for p in m.get("parts", []) if p.get("type") == "tool_call"]
        if not tool_calls:
            pytest.skip("model did not invoke a tool on this run")
        assert tool_calls[0]["name"] == "Bash"
        assert "id" in tool_calls[0]

        # Input messages should contain the matching tool_call_response.
        input_msgs = attrs.get(GEN_AI_INPUT_MESSAGES) or []
        tool_responses = [p for m in input_msgs for p in m.get("parts", []) if p.get("type") == "tool_call_response"]
        assert tool_responses, "expected a tool_call_response in input messages"
        # The id must match the prior tool_call's id.
        assert tool_responses[0]["id"] in {tc["id"] for tc in tool_calls}
