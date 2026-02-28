"""Metrics helpers for GenAI semantic convention histograms."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from opentelemetry.instrumentation.claude_agent_sdk._constants import (
    DURATION_BUCKETS,
    ERROR_TYPE,
    GEN_AI_CLIENT_OPERATION_DURATION,
    GEN_AI_CLIENT_TOKEN_USAGE,
    GEN_AI_TOKEN_TYPE,
    TOKEN_USAGE_BUCKETS,
)

if TYPE_CHECKING:
    from opentelemetry.metrics import Histogram, Meter


def create_token_usage_histogram(meter: Meter) -> Histogram:
    """Create the gen_ai.client.token.usage histogram.

    Args:
        meter: OTel meter instance.

    Returns:
        A Histogram instrument for recording token usage.
    """
    return meter.create_histogram(
        name=GEN_AI_CLIENT_TOKEN_USAGE,
        description="Measures number of input and output tokens used",
        unit="{token}",
        explicit_bucket_boundaries_advisory=TOKEN_USAGE_BUCKETS,
    )


def create_duration_histogram(meter: Meter) -> Histogram:
    """Create the gen_ai.client.operation.duration histogram.

    Args:
        meter: OTel meter instance.

    Returns:
        A Histogram instrument for recording operation duration.
    """
    return meter.create_histogram(
        name=GEN_AI_CLIENT_OPERATION_DURATION,
        description="GenAI operation duration",
        unit="s",
        explicit_bucket_boundaries_advisory=DURATION_BUCKETS,
    )


def record_token_usage(
    histogram: Histogram,
    input_tokens: int,
    output_tokens: int,
    attributes: dict[str, Any],
) -> None:
    """Record input and output token usage as two histogram measurements.

    Args:
        histogram: The token usage histogram.
        input_tokens: Total input token count.
        output_tokens: Output token count.
        attributes: Base attributes (gen_ai.system, gen_ai.operation.name, etc.).
    """
    input_attrs = {**attributes, GEN_AI_TOKEN_TYPE: "input"}
    histogram.record(input_tokens, input_attrs)

    output_attrs = {**attributes, GEN_AI_TOKEN_TYPE: "output"}
    histogram.record(output_tokens, output_attrs)


def record_duration(
    histogram: Histogram,
    duration_seconds: float,
    attributes: dict[str, Any],
    error_type: str | None = None,
) -> None:
    """Record operation duration as a histogram measurement.

    Args:
        histogram: The duration histogram.
        duration_seconds: Duration in seconds.
        attributes: Base attributes.
        error_type: Optional error type to include as a dimension.
    """
    attrs = {**attributes}
    if error_type is not None:
        attrs[ERROR_TYPE] = error_type
    histogram.record(duration_seconds, attrs)
