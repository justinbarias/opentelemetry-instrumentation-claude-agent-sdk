"""Integration tests for histogram metrics with real Claude API calls."""

from __future__ import annotations

import pytest

from opentelemetry.instrumentation.claude_agent_sdk._constants import (
    ERROR_TYPE,
    GEN_AI_CLIENT_OPERATION_DURATION,
    GEN_AI_CLIENT_TOKEN_USAGE,
    GEN_AI_TOKEN_TYPE,
)
from tests.integration.conftest import get_metric_data_points, make_cheap_options, requires_auth

pytestmark = [pytest.mark.integration, requires_auth]


class TestMetricsIntegration:
    async def test_token_usage_histogram_recorded(self, instrumentor, metric_reader):
        """gen_ai.client.token.usage should have input + output data points."""
        import claude_agent_sdk

        async for _ in claude_agent_sdk.query(
            prompt="What is 2+2? Reply with just the number.", options=make_cheap_options()
        ):
            pass

        points = get_metric_data_points(metric_reader, GEN_AI_CLIENT_TOKEN_USAGE)
        assert len(points) >= 2  # at least input + output

        token_types = {dict(dp.attributes).get(GEN_AI_TOKEN_TYPE) for dp in points}
        assert "input" in token_types
        assert "output" in token_types

    async def test_operation_duration_histogram_recorded(self, instrumentor, metric_reader):
        """gen_ai.client.operation.duration should have a value > 0."""
        import claude_agent_sdk

        async for _ in claude_agent_sdk.query(
            prompt="What is 2+2? Reply with just the number.", options=make_cheap_options()
        ):
            pass

        points = get_metric_data_points(metric_reader, GEN_AI_CLIENT_OPERATION_DURATION)
        assert len(points) >= 1
        # Histogram sum should be > 0 (time elapsed)
        assert points[0].sum > 0

    async def test_duration_no_error_type_on_success(self, instrumentor, metric_reader):
        """Successful operations should not have error.type on duration metric."""
        import claude_agent_sdk

        async for _ in claude_agent_sdk.query(
            prompt="What is 2+2? Reply with just the number.", options=make_cheap_options()
        ):
            pass

        points = get_metric_data_points(metric_reader, GEN_AI_CLIENT_OPERATION_DURATION)
        assert len(points) >= 1
        for dp in points:
            attrs = dict(dp.attributes)
            assert ERROR_TYPE not in attrs
