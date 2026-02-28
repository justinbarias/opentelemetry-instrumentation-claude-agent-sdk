"""Tests for metrics helpers (T008)."""

from __future__ import annotations

from opentelemetry.instrumentation.claude_agent_sdk._constants import (
    ERROR_TYPE,
    GEN_AI_CLIENT_OPERATION_DURATION,
    GEN_AI_CLIENT_TOKEN_USAGE,
    GEN_AI_OPERATION_NAME,
    GEN_AI_SYSTEM,
    GEN_AI_TOKEN_TYPE,
    OPERATION_INVOKE_AGENT,
    SYSTEM_ANTHROPIC,
)
from opentelemetry.instrumentation.claude_agent_sdk._metrics import (
    create_duration_histogram,
    create_token_usage_histogram,
    record_duration,
    record_token_usage,
)


class TestCreateTokenUsageHistogram:
    def test_histogram_name_and_unit(self, meter_provider, metric_reader):
        meter = meter_provider.get_meter("test")
        histogram = create_token_usage_histogram(meter)

        # Record something so we can inspect the metric
        histogram.record(42, {GEN_AI_TOKEN_TYPE: "input"})
        metrics = metric_reader.get_metrics_data()

        resource_metrics = metrics.resource_metrics
        assert len(resource_metrics) > 0
        scope_metrics = resource_metrics[0].scope_metrics
        assert len(scope_metrics) > 0
        metric = scope_metrics[0].metrics[0]
        assert metric.name == GEN_AI_CLIENT_TOKEN_USAGE
        assert metric.unit == "{token}"


class TestCreateDurationHistogram:
    def test_histogram_name_and_unit(self, meter_provider, metric_reader):
        meter = meter_provider.get_meter("test")
        histogram = create_duration_histogram(meter)

        histogram.record(1.5, {})
        metrics = metric_reader.get_metrics_data()

        resource_metrics = metrics.resource_metrics
        scope_metrics = resource_metrics[0].scope_metrics
        metric = scope_metrics[0].metrics[0]
        assert metric.name == GEN_AI_CLIENT_OPERATION_DURATION
        assert metric.unit == "s"


class TestRecordTokenUsage:
    def test_records_two_measurements(self, meter_provider, metric_reader):
        meter = meter_provider.get_meter("test")
        histogram = create_token_usage_histogram(meter)

        base_attrs = {
            GEN_AI_OPERATION_NAME: OPERATION_INVOKE_AGENT,
            GEN_AI_SYSTEM: SYSTEM_ANTHROPIC,
        }
        record_token_usage(histogram, input_tokens=100, output_tokens=50, attributes=base_attrs)

        metrics = metric_reader.get_metrics_data()
        resource_metrics = metrics.resource_metrics
        scope_metrics = resource_metrics[0].scope_metrics
        metric = scope_metrics[0].metrics[0]

        # Should have two data points: one for input, one for output
        data_points = metric.data.data_points
        assert len(data_points) == 2

        # Check token types
        token_types = set()
        for dp in data_points:
            attrs = dict(dp.attributes)
            token_types.add(attrs[GEN_AI_TOKEN_TYPE])

        assert "input" in token_types
        assert "output" in token_types


class TestRecordDuration:
    def test_records_duration(self, meter_provider, metric_reader):
        meter = meter_provider.get_meter("test")
        histogram = create_duration_histogram(meter)

        base_attrs = {
            GEN_AI_OPERATION_NAME: OPERATION_INVOKE_AGENT,
            GEN_AI_SYSTEM: SYSTEM_ANTHROPIC,
        }
        record_duration(histogram, duration_seconds=1.5, attributes=base_attrs)

        metrics = metric_reader.get_metrics_data()
        resource_metrics = metrics.resource_metrics
        scope_metrics = resource_metrics[0].scope_metrics
        metric = scope_metrics[0].metrics[0]

        data_points = metric.data.data_points
        assert len(data_points) == 1

    def test_records_duration_with_error_type(self, meter_provider, metric_reader):
        meter = meter_provider.get_meter("test")
        histogram = create_duration_histogram(meter)

        base_attrs = {
            GEN_AI_OPERATION_NAME: OPERATION_INVOKE_AGENT,
            GEN_AI_SYSTEM: SYSTEM_ANTHROPIC,
        }
        record_duration(histogram, duration_seconds=0.5, attributes=base_attrs, error_type="ValueError")

        metrics = metric_reader.get_metrics_data()
        resource_metrics = metrics.resource_metrics
        scope_metrics = resource_metrics[0].scope_metrics
        metric = scope_metrics[0].metrics[0]

        data_points = metric.data.data_points
        assert len(data_points) == 1
        attrs = dict(data_points[0].attributes)
        assert attrs[ERROR_TYPE] == "ValueError"
