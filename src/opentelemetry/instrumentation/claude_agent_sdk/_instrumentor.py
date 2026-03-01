"""ClaudeAgentSdkInstrumentor — OpenTelemetry instrumentation for Claude Agent SDK."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

import wrapt
from opentelemetry.instrumentation.instrumentor import BaseInstrumentor  # type: ignore[attr-defined]
from opentelemetry.metrics import get_meter_provider
from opentelemetry.trace import get_tracer_provider

from opentelemetry.instrumentation.claude_agent_sdk._constants import (
    GEN_AI_OPERATION_NAME,
    GEN_AI_PROVIDER_NAME,
    GEN_AI_REQUEST_MODEL,
    OPERATION_INVOKE_AGENT,
    SYSTEM_ANTHROPIC,
)
from opentelemetry.instrumentation.claude_agent_sdk._context import (
    InvocationContext,
    set_invocation_context,
)
from opentelemetry.instrumentation.claude_agent_sdk._hooks import (
    build_instrumentation_hooks,
    merge_hooks,
)
from opentelemetry.instrumentation.claude_agent_sdk._metrics import (
    create_duration_histogram,
    create_token_usage_histogram,
    record_duration,
    record_token_usage,
)
from opentelemetry.instrumentation.claude_agent_sdk._spans import (
    create_invoke_agent_span,
    set_error_attributes,
    set_response_model,
    set_result_attributes,
)
from opentelemetry.instrumentation.claude_agent_sdk.version import __version__

if TYPE_CHECKING:
    from collections.abc import Collection

_INSTRUMENTATION_NAME = "opentelemetry.instrumentation.claude_agent_sdk"


class ClaudeAgentSdkInstrumentor(BaseInstrumentor):  # type: ignore[misc]
    """OpenTelemetry instrumentor for the Anthropic Claude Agent SDK."""

    def instrumentation_dependencies(self) -> Collection[str]:
        return ["claude-agent-sdk >= 0.1.37"]

    def _instrument(self, **kwargs: Any) -> None:
        tracer_provider = kwargs.get("tracer_provider") or get_tracer_provider()
        meter_provider = kwargs.get("meter_provider") or get_meter_provider()
        capture_content = kwargs.get("capture_content", False)
        agent_name = kwargs.get("agent_name")

        tracer = tracer_provider.get_tracer(_INSTRUMENTATION_NAME, __version__)
        meter = meter_provider.get_meter(_INSTRUMENTATION_NAME, __version__)

        token_histogram = create_token_usage_histogram(meter)
        duration_histogram = create_duration_histogram(meter)

        # Store config for wrappers
        self._tracer = tracer
        self._meter = meter
        self._token_histogram = token_histogram
        self._duration_histogram = duration_histogram
        self._capture_content = capture_content
        self._agent_name = agent_name

        # Wrap standalone query()
        wrapt.wrap_function_wrapper(
            "claude_agent_sdk",
            "query",
            self._wrap_query,
        )

        # Wrap ClaudeSDKClient.__init__()
        wrapt.wrap_function_wrapper(
            "claude_agent_sdk",
            "ClaudeSDKClient.__init__",
            self._wrap_client_init,
        )

        # Wrap ClaudeSDKClient.query()
        wrapt.wrap_function_wrapper(
            "claude_agent_sdk",
            "ClaudeSDKClient.query",
            self._wrap_client_query,
        )

        # Wrap ClaudeSDKClient.receive_response()
        wrapt.wrap_function_wrapper(
            "claude_agent_sdk",
            "ClaudeSDKClient.receive_response",
            self._wrap_client_receive_response,
        )

    def _uninstrument(self, **kwargs: Any) -> None:
        import claude_agent_sdk

        unwrap_targets: list[tuple[Any, str]] = [
            (claude_agent_sdk, "query"),
            (claude_agent_sdk.ClaudeSDKClient, "__init__"),
            (claude_agent_sdk.ClaudeSDKClient, "query"),
            (claude_agent_sdk.ClaudeSDKClient, "receive_response"),
        ]

        for target, attr in unwrap_targets:
            try:
                func = getattr(target, attr, None)
                if func and hasattr(func, "__wrapped__"):
                    setattr(target, attr, func.__wrapped__)
            except (AttributeError, ValueError):
                pass

    def get_instrumentation_hooks(self) -> dict[str, list[Any]]:
        """Escape hatch returning raw hooks dict for manual wiring."""
        return build_instrumentation_hooks(
            tracer=getattr(self, "_tracer", None),
            capture_content=getattr(self, "_capture_content", False),
        )

    # --- Wrapper implementations ---

    def _wrap_query(
        self,
        wrapped: Any,
        instance: Any,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> Any:
        """Wrap standalone query() async generator."""
        return self._instrumented_query(wrapped, args, kwargs)

    async def _instrumented_query(
        self,
        wrapped: Any,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> Any:
        """Async generator wrapper for standalone query()."""
        # Extract model from options if available (query() uses keyword-only args)
        options = kwargs.get("options")
        request_model = getattr(options, "model", None) if options else None

        # Inject instrumentation hooks into options
        import claude_agent_sdk

        if options is None:
            options = claude_agent_sdk.ClaudeAgentOptions()
            kwargs["options"] = options

        instrumentation_hooks = build_instrumentation_hooks(tracer=self._tracer, capture_content=self._capture_content)
        options.hooks = merge_hooks(getattr(options, "hooks", None) or {}, instrumentation_hooks)

        span = create_invoke_agent_span(
            self._tracer,
            agent_name=self._agent_name,
            request_model=request_model,
            options=options,
        )

        ctx = InvocationContext(
            invocation_span=span,
            capture_content=self._capture_content,
        )
        set_invocation_context(ctx)

        error_occurred: BaseException | None = None
        try:
            from claude_agent_sdk import AssistantMessage, ResultMessage

            async for message in wrapped(*args, **kwargs):
                # Intercept AssistantMessage for model name
                if isinstance(message, AssistantMessage):
                    model = getattr(message, "model", None)
                    if model:
                        ctx.set_model(model)
                        set_response_model(span, model)

                # Intercept ResultMessage for finalization
                if isinstance(message, ResultMessage):
                    set_result_attributes(span, message)
                    session_id = getattr(message, "session_id", None)
                    if session_id:
                        ctx.session_id = session_id

                    # Record token metrics
                    usage = getattr(message, "usage", None)
                    if usage is not None:
                        input_tokens = (
                            (usage.get("input_tokens", 0) or 0)
                            + (usage.get("cache_creation_input_tokens", 0) or 0)
                            + (usage.get("cache_read_input_tokens", 0) or 0)
                        )
                        output_tokens = usage.get("output_tokens", 0) or 0

                        metric_attrs = {
                            GEN_AI_OPERATION_NAME: OPERATION_INVOKE_AGENT,
                            GEN_AI_PROVIDER_NAME: SYSTEM_ANTHROPIC,
                        }
                        if ctx.model:
                            metric_attrs[GEN_AI_REQUEST_MODEL] = ctx.model
                        record_token_usage(
                            self._token_histogram,
                            input_tokens=input_tokens,
                            output_tokens=output_tokens,
                            attributes=metric_attrs,
                        )

                yield message

        except BaseException as exc:
            error_occurred = exc
            set_error_attributes(span, exc)
            raise
        finally:
            # Record duration
            duration = time.monotonic() - ctx.start_time
            metric_attrs = {
                GEN_AI_OPERATION_NAME: OPERATION_INVOKE_AGENT,
                GEN_AI_PROVIDER_NAME: SYSTEM_ANTHROPIC,
            }
            if ctx.model:
                metric_attrs[GEN_AI_REQUEST_MODEL] = ctx.model
            error_type = type(error_occurred).__qualname__ if error_occurred else None
            record_duration(
                self._duration_histogram,
                duration_seconds=duration,
                attributes=metric_attrs,
                error_type=error_type,
            )

            ctx.cleanup_unclosed_spans()
            span.end()
            set_invocation_context(None)

    def _wrap_client_init(
        self,
        wrapped: Any,
        instance: Any,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> None:
        """Wrap ClaudeSDKClient.__init__() to inject hooks."""
        wrapped(*args, **kwargs)

        # Inject instrumentation hooks
        options = getattr(instance, "options", None)
        if options is not None:
            instrumentation_hooks = build_instrumentation_hooks(
                tracer=self._tracer, capture_content=self._capture_content
            )
            options.hooks = merge_hooks(getattr(options, "hooks", None) or {}, instrumentation_hooks)

        # Store OTel config on the client instance
        instance._otel_tracer = self._tracer
        instance._otel_meter = self._meter
        instance._otel_token_histogram = self._token_histogram
        instance._otel_duration_histogram = self._duration_histogram
        instance._otel_capture_content = self._capture_content
        instance._otel_agent_name = self._agent_name

    def _wrap_client_query(
        self,
        wrapped: Any,
        instance: Any,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> Any:
        """Wrap ClaudeSDKClient.query() to start a per-turn span."""
        # Extract model from client options
        options = getattr(instance, "options", None)
        request_model = getattr(options, "model", None) if options else None

        tracer = getattr(instance, "_otel_tracer", self._tracer)
        agent_name = getattr(instance, "_otel_agent_name", self._agent_name)
        capture_content = getattr(instance, "_otel_capture_content", self._capture_content)

        span = create_invoke_agent_span(
            tracer,
            agent_name=agent_name,
            request_model=request_model,
            options=options,
        )

        ctx = InvocationContext(
            invocation_span=span,
            capture_content=capture_content,
        )
        set_invocation_context(ctx)

        # Store context on instance for receive_response() to use
        instance._otel_invocation_ctx = ctx

        return wrapped(*args, **kwargs)

    def _wrap_client_receive_response(
        self,
        wrapped: Any,
        instance: Any,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> Any:
        """Wrap ClaudeSDKClient.receive_response() async generator."""
        return self._instrumented_receive_response(wrapped, instance, args, kwargs)

    async def _instrumented_receive_response(
        self,
        wrapped: Any,
        instance: Any,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> Any:
        """Async generator intercepting messages for span finalization."""
        ctx: InvocationContext | None = getattr(instance, "_otel_invocation_ctx", None)
        if ctx is None:
            # No context — just pass through
            async for message in wrapped(*args, **kwargs):
                yield message
            return

        span = ctx.invocation_span
        token_histogram = getattr(instance, "_otel_token_histogram", self._token_histogram)
        duration_histogram = getattr(instance, "_otel_duration_histogram", self._duration_histogram)

        error_occurred: BaseException | None = None
        try:
            from claude_agent_sdk import AssistantMessage, ResultMessage

            async for message in wrapped(*args, **kwargs):
                # Intercept AssistantMessage
                if isinstance(message, AssistantMessage):
                    model = getattr(message, "model", None)
                    if model:
                        ctx.set_model(model)
                        set_response_model(span, model)

                # Intercept ResultMessage
                if isinstance(message, ResultMessage):
                    set_result_attributes(span, message)
                    session_id = getattr(message, "session_id", None)
                    if session_id:
                        ctx.session_id = session_id

                    usage = getattr(message, "usage", None)
                    if usage is not None:
                        input_tokens = (
                            (usage.get("input_tokens", 0) or 0)
                            + (usage.get("cache_creation_input_tokens", 0) or 0)
                            + (usage.get("cache_read_input_tokens", 0) or 0)
                        )
                        output_tokens = usage.get("output_tokens", 0) or 0

                        metric_attrs = {
                            GEN_AI_OPERATION_NAME: OPERATION_INVOKE_AGENT,
                            GEN_AI_PROVIDER_NAME: SYSTEM_ANTHROPIC,
                        }
                        if ctx.model:
                            metric_attrs[GEN_AI_REQUEST_MODEL] = ctx.model
                        record_token_usage(
                            token_histogram,
                            input_tokens=input_tokens,
                            output_tokens=output_tokens,
                            attributes=metric_attrs,
                        )

                yield message

        except BaseException as exc:
            error_occurred = exc
            set_error_attributes(span, exc)
            raise
        finally:
            duration = time.monotonic() - ctx.start_time
            metric_attrs = {
                GEN_AI_OPERATION_NAME: OPERATION_INVOKE_AGENT,
                GEN_AI_PROVIDER_NAME: SYSTEM_ANTHROPIC,
            }
            if ctx.model:
                metric_attrs[GEN_AI_REQUEST_MODEL] = ctx.model
            error_type = type(error_occurred).__qualname__ if error_occurred else None
            record_duration(
                duration_histogram,
                duration_seconds=duration,
                attributes=metric_attrs,
                error_type=error_type,
            )

            ctx.cleanup_unclosed_spans()
            span.end()
            set_invocation_context(None)
            instance._otel_invocation_ctx = None
