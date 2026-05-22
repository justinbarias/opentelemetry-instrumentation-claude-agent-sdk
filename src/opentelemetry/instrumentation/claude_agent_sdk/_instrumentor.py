"""ClaudeAgentSdkInstrumentor — OpenTelemetry instrumentation for Claude Agent SDK."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

import wrapt
from opentelemetry._logs import get_logger_provider
from opentelemetry.instrumentation.instrumentor import BaseInstrumentor  # type: ignore[attr-defined]
from opentelemetry.metrics import get_meter_provider
from opentelemetry.trace import get_tracer_provider

from opentelemetry.instrumentation.claude_agent_sdk._constants import (
    ERROR_TYPE,
    FINISH_REASON_MAP,
    GEN_AI_CONVERSATION_ID,
    GEN_AI_OPERATION_NAME,
    GEN_AI_PROVIDER_NAME,
    GEN_AI_REQUEST_MODEL,
    GEN_AI_RESPONSE_FINISH_REASONS,
    GEN_AI_RESPONSE_MODEL,
    GEN_AI_USAGE_CACHE_CREATION_INPUT_TOKENS,
    GEN_AI_USAGE_CACHE_READ_INPUT_TOKENS,
    GEN_AI_USAGE_INPUT_TOKENS,
    GEN_AI_USAGE_OUTPUT_TOKENS,
    OPERATION_INVOKE_AGENT,
    SCHEMA_URL,
    SYSTEM_ANTHROPIC,
)
from opentelemetry.instrumentation.claude_agent_sdk._context import (
    InvocationContext,
    set_invocation_context,
)
from opentelemetry.instrumentation.claude_agent_sdk._events import (
    assistant_message_to_structured,
    capture_content_enabled,
    emit_inference_operation_details_event,
    emit_operation_exception_event,
    options_to_tool_definitions,
    prompt_to_input_message,
    system_prompt_to_instructions,
    user_message_to_structured,
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
    set_message_content_attributes,
    set_response_model,
    set_result_attributes,
)
from opentelemetry.instrumentation.claude_agent_sdk.version import __version__

if TYPE_CHECKING:
    from collections.abc import Collection

_INSTRUMENTATION_NAME = "opentelemetry.instrumentation.claude_agent_sdk"


def _inference_details_base_attrs(
    ctx: InvocationContext,
    *,
    result_message: Any = None,
    error: BaseException | None = None,
) -> dict[str, Any]:
    """Assemble the non-content base attributes for the inference details event.

    Mirrors the same set we put on the invoke_agent span so the event and span
    line up for join-by-attribute use cases. ``result_message`` is the SDK's
    terminal ``ResultMessage`` when available — used to pull usage tokens and
    finish reason.
    """
    attrs: dict[str, Any] = {
        GEN_AI_OPERATION_NAME: OPERATION_INVOKE_AGENT,
        GEN_AI_PROVIDER_NAME: SYSTEM_ANTHROPIC,
    }
    if ctx.model:
        attrs[GEN_AI_REQUEST_MODEL] = ctx.model
        attrs[GEN_AI_RESPONSE_MODEL] = ctx.model
    if ctx.session_id:
        attrs[GEN_AI_CONVERSATION_ID] = ctx.session_id
    if error is not None:
        attrs[ERROR_TYPE] = type(error).__qualname__

    if result_message is not None:
        subtype = getattr(result_message, "subtype", None)
        if subtype is not None:
            attrs[GEN_AI_RESPONSE_FINISH_REASONS] = [FINISH_REASON_MAP.get(subtype, subtype)]
        usage = getattr(result_message, "usage", None)
        if usage is not None:
            input_tokens = usage.get("input_tokens", 0) or 0
            cache_creation = usage.get("cache_creation_input_tokens", 0) or 0
            cache_read = usage.get("cache_read_input_tokens", 0) or 0
            output_tokens = usage.get("output_tokens", 0) or 0
            attrs[GEN_AI_USAGE_INPUT_TOKENS] = input_tokens + cache_creation + cache_read
            attrs[GEN_AI_USAGE_OUTPUT_TOKENS] = output_tokens
            if cache_creation > 0:
                attrs[GEN_AI_USAGE_CACHE_CREATION_INPUT_TOKENS] = cache_creation
            if cache_read > 0:
                attrs[GEN_AI_USAGE_CACHE_READ_INPUT_TOKENS] = cache_read

    return attrs


def _exception_event_span_attrs(ctx: InvocationContext) -> dict[str, Any]:
    """Build the subset of span attributes to copy onto an exception event.

    Per spec the instrumentation MAY include the operation's span attributes
    on the event. We only copy stable, low-cardinality identifiers so the
    event remains useful for correlation without bloating log records.
    """
    attrs: dict[str, Any] = {
        GEN_AI_OPERATION_NAME: OPERATION_INVOKE_AGENT,
        GEN_AI_PROVIDER_NAME: SYSTEM_ANTHROPIC,
    }
    if ctx.model:
        attrs[GEN_AI_REQUEST_MODEL] = ctx.model
    if ctx.session_id:
        attrs[GEN_AI_CONVERSATION_ID] = ctx.session_id
    return attrs


class ClaudeAgentSdkInstrumentor(BaseInstrumentor):  # type: ignore[misc]
    """OpenTelemetry instrumentor for the Anthropic Claude Agent SDK."""

    def instrumentation_dependencies(self) -> Collection[str]:
        return ["claude-agent-sdk >= 0.1.37"]

    def _instrument(self, **kwargs: Any) -> None:
        tracer_provider = kwargs.get("tracer_provider") or get_tracer_provider()
        meter_provider = kwargs.get("meter_provider") or get_meter_provider()
        logger_provider = kwargs.get("logger_provider") or get_logger_provider()
        capture_content = kwargs.get("capture_content", False)
        agent_name = kwargs.get("agent_name")

        tracer = tracer_provider.get_tracer(_INSTRUMENTATION_NAME, __version__, SCHEMA_URL)
        meter = meter_provider.get_meter(_INSTRUMENTATION_NAME, __version__, SCHEMA_URL)
        logger = logger_provider.get_logger(_INSTRUMENTATION_NAME, __version__, SCHEMA_URL)

        token_histogram = create_token_usage_histogram(meter)
        duration_histogram = create_duration_histogram(meter)

        # Store config for wrappers
        self._tracer = tracer
        self._meter = meter
        self._logger = logger
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
        # Seed inference-details payloads from the caller's inputs.
        ctx.system_instructions = system_prompt_to_instructions(getattr(options, "system_prompt", None))
        ctx.tool_definitions = options_to_tool_definitions(options)
        initial = prompt_to_input_message(kwargs.get("prompt") or (args[0] if args else None))
        if initial is not None:
            ctx.input_messages.append(initial)

        set_invocation_context(ctx)

        error_occurred: BaseException | None = None
        last_result_message: Any = None
        try:
            from claude_agent_sdk import AssistantMessage, ResultMessage, UserMessage

            async for message in wrapped(*args, **kwargs):
                # Intercept AssistantMessage for model name + output content
                if isinstance(message, AssistantMessage):
                    model = getattr(message, "model", None)
                    if model:
                        ctx.set_model(model)
                        set_response_model(span, model)
                    ctx.output_messages.append(assistant_message_to_structured(message))

                # Capture interleaved UserMessages (typically tool results).
                elif isinstance(message, UserMessage):
                    ctx.input_messages.append(user_message_to_structured(message))

                # Intercept ResultMessage for finalization
                if isinstance(message, ResultMessage):
                    last_result_message = message
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
            span.record_exception(exc)
            set_error_attributes(span, exc)
            emit_operation_exception_event(
                self._logger,
                exc,
                _exception_event_span_attrs(ctx),
            )
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

            include_content = capture_content_enabled(self._capture_content)
            if include_content:
                # Mirror onto the span so dashboards reading from spans (Aspire,
                # M.E.AI) can render the prompt/completion content alongside
                # the event-based emission below.
                set_message_content_attributes(
                    span,
                    input_messages=ctx.input_messages,
                    output_messages=ctx.output_messages,
                    system_instructions=ctx.system_instructions,
                    tool_definitions=ctx.tool_definitions,
                )
            emit_inference_operation_details_event(
                self._logger,
                base_attributes=_inference_details_base_attrs(
                    ctx, result_message=last_result_message, error=error_occurred
                ),
                input_messages=ctx.input_messages,
                output_messages=ctx.output_messages,
                system_instructions=ctx.system_instructions,
                tool_definitions=ctx.tool_definitions,
                include_content=include_content,
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

        # Inject instrumentation hooks — pass ``instance`` so hook closures
        # can fall back to ``instance._otel_invocation_ctx`` when the
        # ContextVar is empty (asyncio.gather / TaskGroup concurrency).
        options = getattr(instance, "options", None)
        if options is not None:
            instrumentation_hooks = build_instrumentation_hooks(
                tracer=self._tracer,
                capture_content=self._capture_content,
                instance=instance,
            )
            options.hooks = merge_hooks(getattr(options, "hooks", None) or {}, instrumentation_hooks)

        # Store OTel config on the client instance
        instance._otel_tracer = self._tracer
        instance._otel_meter = self._meter
        instance._otel_logger = self._logger
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
        ctx.system_instructions = system_prompt_to_instructions(getattr(options, "system_prompt", None))
        ctx.tool_definitions = options_to_tool_definitions(options)
        initial = prompt_to_input_message(kwargs.get("prompt") or (args[0] if args else None))
        if initial is not None:
            ctx.input_messages.append(initial)

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
        last_result_message: Any = None
        try:
            from claude_agent_sdk import AssistantMessage, ResultMessage, UserMessage

            async for message in wrapped(*args, **kwargs):
                # Intercept AssistantMessage
                if isinstance(message, AssistantMessage):
                    model = getattr(message, "model", None)
                    if model:
                        ctx.set_model(model)
                        set_response_model(span, model)
                    ctx.output_messages.append(assistant_message_to_structured(message))

                # Capture interleaved UserMessages (typically tool results).
                elif isinstance(message, UserMessage):
                    ctx.input_messages.append(user_message_to_structured(message))

                # Intercept ResultMessage
                if isinstance(message, ResultMessage):
                    last_result_message = message
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
            span.record_exception(exc)
            set_error_attributes(span, exc)
            emit_operation_exception_event(
                getattr(instance, "_otel_logger", self._logger),
                exc,
                _exception_event_span_attrs(ctx),
            )
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

            include_content = capture_content_enabled(ctx.capture_content)
            if include_content:
                set_message_content_attributes(
                    span,
                    input_messages=ctx.input_messages,
                    output_messages=ctx.output_messages,
                    system_instructions=ctx.system_instructions,
                    tool_definitions=ctx.tool_definitions,
                )
            emit_inference_operation_details_event(
                getattr(instance, "_otel_logger", self._logger),
                base_attributes=_inference_details_base_attrs(
                    ctx, result_message=last_result_message, error=error_occurred
                ),
                input_messages=ctx.input_messages,
                output_messages=ctx.output_messages,
                system_instructions=ctx.system_instructions,
                tool_definitions=ctx.tool_definitions,
                include_content=include_content,
            )

            ctx.cleanup_unclosed_spans()
            span.end()
            set_invocation_context(None)
            instance._otel_invocation_ctx = None
