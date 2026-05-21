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
    """§15 — `max_turns` is an SDK turn-count cap, not a model stop reason.
    It must surface as `max_turns` so backends can tell it apart from the
    model-side `max_tokens` (which means the model hit its token limit).

    We force max_turns=1 with a prompt that requires tool use, so the SDK
    can't satisfy the request in one turn and emits `subtype=max_turns`.
    """

    async def test_max_turns_passes_through(self, instrumentor, span_exporter):
        import claude_agent_sdk

        options = make_cheap_options(
            max_turns=1,
            permission_mode="bypassPermissions",
            allowed_tools=["Bash"],
        )
        async for _ in claude_agent_sdk.query(
            prompt="Run `ls /` and then run `ls /tmp`. Tell me the file counts.",
            options=options,
        ):
            pass

        spans = get_invoke_agent_spans(span_exporter)
        attrs = dict(spans[0].attributes or {})
        reasons = attrs.get(GEN_AI_RESPONSE_FINISH_REASONS)
        # When max_turns is hit, the reason is "max_turns". When the model
        # happens to finish in a single turn anyway, it's "end_turn". The
        # *forbidden* outcome is the old buggy mapping to "max_tokens".
        if reasons is not None:
            assert "max_tokens" not in reasons, "max_turns must not be mapped to max_tokens"
