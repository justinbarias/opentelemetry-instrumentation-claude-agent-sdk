"""Regression test for issue #26.

Callers that did::

    from claude_agent_sdk import query

BEFORE ``ClaudeAgentSdkInstrumentor.instrument()`` ran hold a frozen
reference to the unwrapped top-level ``query`` function. Wrapping only
``claude_agent_sdk.query`` rebinds the module attribute but cannot touch
that local binding, so every call through the frozen reference would
silently bypass the wrapper.

The fix is a structural one: we also wrap
``claude_agent_sdk._internal.client.InternalClient.process_query``, which
is the deeper layer the top-level ``query()`` always delegates to at
call time. This test simulates the failure mode with a mock SDK that
mirrors the real SDK's two-layer structure and asserts that the frozen
reference still produces a span.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from types import ModuleType
from typing import TYPE_CHECKING, Any

import pytest

from opentelemetry.instrumentation.claude_agent_sdk._instrumentor import ClaudeAgentSdkInstrumentor
from tests.unit.conftest import make_usage

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from opentelemetry.sdk.trace import TracerProvider as SDKTracerProvider
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter


def _install_two_layer_mock_sdk() -> tuple[ModuleType, dict[str, ModuleType | None]]:
    """Install a mock claude_agent_sdk that mirrors the real two-layer structure.

    The top-level ``query()`` delegates to ``InternalClient.process_query()`` —
    exactly the relationship that makes the deeper wrap the right safety net.
    Returns the installed top-level module and a snapshot of original
    sys.modules entries for teardown.
    """
    top = ModuleType("claude_agent_sdk")
    internal = ModuleType("claude_agent_sdk._internal")
    client_mod = ModuleType("claude_agent_sdk._internal.client")

    @dataclass
    class AssistantMessage:
        model: str = "claude-sonnet-4-20250514"

    @dataclass
    class UserMessage:
        content: Any = None

    @dataclass
    class ResultMessage:
        usage: dict[str, int] | None = field(default_factory=make_usage)
        session_id: str = "frozen-import-session"
        subtype: str = "success"
        is_error: bool = False

    @dataclass
    class ClaudeAgentOptions:
        model: str | None = None
        hooks: dict[str, list[Any]] = field(default_factory=dict)
        system_prompt: str | None = None

    messages: list[Any] = [AssistantMessage(), ResultMessage()]

    class InternalClient:
        async def process_query(
            self,
            prompt: Any,
            options: Any,
            transport: Any = None,
        ) -> AsyncIterator[Any]:
            for msg in messages:
                yield msg

    async def query(
        *,
        prompt: Any,
        options: Any = None,
        transport: Any = None,
    ) -> AsyncIterator[Any]:
        # Mirror the real SDK: instantiate InternalClient at call time and
        # delegate. The wrap on InternalClient.process_query catches every
        # call regardless of how the caller imported `query`.
        client = InternalClient()
        async for msg in client.process_query(
            prompt=prompt,
            options=options if options is not None else ClaudeAgentOptions(),
            transport=transport,
        ):
            yield msg

    class ClaudeSDKClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.options = kwargs.get("options", ClaudeAgentOptions())

        async def query(self, prompt: str, **kwargs: Any) -> None:
            return None

        async def receive_response(self, **kwargs: Any) -> AsyncIterator[Any]:
            for msg in messages:
                yield msg

    top.query = query  # type: ignore[attr-defined]
    top.ClaudeSDKClient = ClaudeSDKClient  # type: ignore[attr-defined]
    top.ClaudeAgentOptions = ClaudeAgentOptions  # type: ignore[attr-defined]
    top.AssistantMessage = AssistantMessage  # type: ignore[attr-defined]
    top.UserMessage = UserMessage  # type: ignore[attr-defined]
    top.ResultMessage = ResultMessage  # type: ignore[attr-defined]
    internal.client = client_mod  # type: ignore[attr-defined]
    client_mod.InternalClient = InternalClient  # type: ignore[attr-defined]

    originals: dict[str, ModuleType | None] = {}
    for name, mod in (
        ("claude_agent_sdk", top),
        ("claude_agent_sdk._internal", internal),
        ("claude_agent_sdk._internal.client", client_mod),
    ):
        originals[name] = sys.modules.get(name)
        sys.modules[name] = mod

    return top, originals


def _restore_modules(originals: dict[str, ModuleType | None]) -> None:
    for name, orig in originals.items():
        if orig is not None:
            sys.modules[name] = orig
        else:
            sys.modules.pop(name, None)


@pytest.fixture()
def frozen_import_sdk():
    """Install the two-layer mock SDK for one test, tear it down after."""
    _top, originals = _install_two_layer_mock_sdk()
    try:
        yield originals
    finally:
        _restore_modules(originals)


class TestFrozenQueryImport:
    """Issue #26 — the import-by-name pitfall."""

    async def test_frozen_query_reference_still_produces_span(
        self,
        frozen_import_sdk,
        span_exporter: InMemorySpanExporter,
        tracer_provider: SDKTracerProvider,
    ) -> None:
        """A caller that bound ``query`` before instrument() ran must still
        produce a span via the deeper InternalClient.process_query wrap."""
        import claude_agent_sdk

        # Freeze the reference BEFORE instrument() runs — this is the bug shape.
        frozen_query = claude_agent_sdk.query

        instrumentor = ClaudeAgentSdkInstrumentor()
        instrumentor.instrument(tracer_provider=tracer_provider)
        try:
            # The local binding still points to the original unwrapped function.
            assert not hasattr(frozen_query, "__wrapped__")
            # But the module attribute is now wrapped.
            assert hasattr(claude_agent_sdk.query, "__wrapped__")
            # Pre-fix, this call would yield zero spans. With the deeper wrap
            # on InternalClient.process_query, it produces one.
            async for _ in frozen_query(prompt="hi"):
                pass

            invoke_spans = [s for s in span_exporter.get_finished_spans() if s.name.startswith("invoke_agent")]
            assert len(invoke_spans) == 1, (
                "frozen `from claude_agent_sdk import query` reference should still produce a span "
                "via the deeper InternalClient.process_query wrap (issue #26)"
            )
        finally:
            instrumentor.uninstrument()

    async def test_module_attr_query_not_double_instrumented(
        self,
        frozen_import_sdk,
        span_exporter: InMemorySpanExporter,
        tracer_provider: SDKTracerProvider,
    ) -> None:
        """When both wraps are active, calling ``claude_agent_sdk.query``
        must NOT produce two spans — the inner wrap's re-entrancy guard
        passes through when the outer wrap already set the context."""
        import claude_agent_sdk

        instrumentor = ClaudeAgentSdkInstrumentor()
        instrumentor.instrument(tracer_provider=tracer_provider)
        try:
            async for _ in claude_agent_sdk.query(prompt="hi"):
                pass

            invoke_spans = [s for s in span_exporter.get_finished_spans() if s.name.startswith("invoke_agent")]
            assert len(invoke_spans) == 1, "outer query() wrap + inner process_query wrap must coalesce to one span"
        finally:
            instrumentor.uninstrument()
