"""Integration tests covering the GenAI semconv compliance fixes from
issues #21 and #22. These run against the real SDK + Claude API, so the
assertions focus on telemetry shape — not on response content.

Each test deliberately uses make_cheap_options() to keep API cost minimal.
"""

from __future__ import annotations

import pytest

from opentelemetry.instrumentation.claude_agent_sdk._constants import (
    GEN_AI_PROVIDER_NAME,
    GEN_AI_RESPONSE_FINISH_REASONS,
    GEN_AI_USAGE_CACHE_CREATION_INPUT_TOKENS,
    GEN_AI_USAGE_CACHE_READ_INPUT_TOKENS,
    SCHEMA_URL,
    SYSTEM_ANTHROPIC,
)
from tests.integration.conftest import get_invoke_agent_spans, make_cheap_options, requires_auth

pytestmark = [pytest.mark.integration, requires_auth]


class TestSchemaURL:
    """§14 — Tracer/meter/logger must be created with the GenAI semconv schema URL
    so consumers can tell which version of the conventions this instrumentation
    is targeting."""

    async def test_span_carries_schema_url(self, instrumentor, span_exporter):
        import claude_agent_sdk

        async for _ in claude_agent_sdk.query(
            prompt="What is 2+2? Reply with just the number.", options=make_cheap_options()
        ):
            pass

        spans = get_invoke_agent_spans(span_exporter)
        assert len(spans) >= 1
        scope = spans[0].instrumentation_scope
        assert scope.schema_url == SCHEMA_URL


class TestProviderNameSemantics:
    """§1 — `gen_ai.provider.name` replaces the deprecated `gen_ai.system` on
    spans. Metrics were already on the new key. This test pins both that the
    new key is set and that the old key is absent — otherwise downstream
    backends double-count or miss the provider entirely."""

    async def test_invoke_agent_span_uses_provider_name(self, instrumentor, span_exporter):
        import claude_agent_sdk

        async for _ in claude_agent_sdk.query(
            prompt="What is 2+2? Reply with just the number.", options=make_cheap_options()
        ):
            pass

        spans = get_invoke_agent_spans(span_exporter)
        attrs = dict(spans[0].attributes or {})
        assert attrs[GEN_AI_PROVIDER_NAME] == SYSTEM_ANTHROPIC
        assert "gen_ai.system" not in attrs, "deprecated key must not be emitted"


class TestCacheTokenAttributeNames:
    """§2 — Cache token attributes use the dotted form
    (`gen_ai.usage.cache_creation.input_tokens`) per spec. The earlier
    underscore form (`...cache_creation_input_tokens`) MUST NOT appear on
    any span. We can't deterministically force cache hits in a cheap
    integration run, so we assert absence of the bad form."""

    async def test_no_underscore_form_cache_keys(self, instrumentor, span_exporter):
        import claude_agent_sdk

        async for _ in claude_agent_sdk.query(
            prompt="What is 2+2? Reply with just the number.", options=make_cheap_options()
        ):
            pass

        for span in get_invoke_agent_spans(span_exporter):
            attrs = dict(span.attributes or {})
            assert "gen_ai.usage.cache_creation_input_tokens" not in attrs
            assert "gen_ai.usage.cache_read_input_tokens" not in attrs
            # If a cache attribute IS present, it must use the dotted form
            # (sanity check — won't fire when usage is zero).
            for key in attrs:
                if "cache" in key and key.startswith("gen_ai.usage."):
                    assert key in {
                        GEN_AI_USAGE_CACHE_CREATION_INPUT_TOKENS,
                        GEN_AI_USAGE_CACHE_READ_INPUT_TOKENS,
                    }, f"unexpected cache attribute {key!r} on span"


class TestFinishReasonMaxTurns:
    """§15 — historically the SDK delivered ``ResultMessage(subtype="max_turns")``
    when the orchestration-level turn cap was hit, and we mapped it through
    ``FINISH_REASON_MAP`` to ensure it never got confused with the model-side
    ``max_tokens`` stop reason.

    From claude-agent-sdk 0.2.x onward the SDK raises an exception instead of
    surfacing a max_turns result. Our instrumentation catches that on the
    error path: ``span.record_exception`` fires, ``error.type`` is set, and
    the span carries ERROR status. This test now verifies that exception
    path. The ``FINISH_REASON_MAP['max_turns']`` entry stays in place as
    defensive code in case a future SDK version reverts.
    """

    async def test_max_turns_surfaces_on_error_path(self, instrumentor, span_exporter):
        import claude_agent_sdk
        from opentelemetry.trace import StatusCode

        from opentelemetry.instrumentation.claude_agent_sdk._constants import ERROR_TYPE

        options = make_cheap_options(
            max_turns=1,
            permission_mode="bypassPermissions",
            allowed_tools=["Bash"],
        )
        with pytest.raises(Exception, match=r"(?i)max.*turns|maximum number of turns"):
            async for _ in claude_agent_sdk.query(
                prompt="Run `ls /` and then run `ls /tmp`. Tell me the file counts.",
                options=options,
            ):
                pass

        spans = get_invoke_agent_spans(span_exporter)
        assert len(spans) == 1
        span = spans[0]
        assert span.status.status_code == StatusCode.ERROR
        attrs = dict(span.attributes or {})
        # error.type must be the exception class qualname (low-cardinality).
        assert ERROR_TYPE in attrs
        # The forbidden outcome remains: never let `max_turns` become `max_tokens`.
        finish_reasons = attrs.get(GEN_AI_RESPONSE_FINISH_REASONS)
        if finish_reasons is not None:
            assert "max_tokens" not in finish_reasons
        # The standard OTel exception event must be recorded on the span.
        assert any(e.name == "exception" for e in span.events)
