"""GenAI event emission helpers.

OpenTelemetry's GenAI semantic conventions model agent telemetry not just as
spans + metrics but also as discrete log records ("events"). Backends that
sample or retain logs and traces separately rely on these to surface things
like exceptions independently of the span. See
``docs/gen-ai/gen-ai-exceptions.md`` in ``open-telemetry/semantic-conventions-genai``.

We use ``opentelemetry._logs`` rather than the older ``opentelemetry._events``
``EventLogger``: the latter is deprecated as of opentelemetry-api 1.39 in
favor of representing events as log records with ``event_name`` set.
"""

from __future__ import annotations

import traceback
from typing import TYPE_CHECKING, Any

from opentelemetry._logs import LogRecord, SeverityNumber

from opentelemetry.instrumentation.claude_agent_sdk._constants import (
    EVENT_GEN_AI_CLIENT_OPERATION_EXCEPTION,
    EXCEPTION_MESSAGE,
    EXCEPTION_STACKTRACE,
    EXCEPTION_TYPE,
)

if TYPE_CHECKING:
    from opentelemetry._logs import Logger


def emit_operation_exception_event(
    logger: Logger | None,
    exception: BaseException,
    span_attributes: dict[str, Any] | None = None,
) -> None:
    """Emit a ``gen_ai.client.operation.exception`` log record.

    Per spec the event MUST carry ``exception.type`` and/or ``exception.message``
    and SHOULD carry ``exception.stacktrace``. The instrumentation MAY copy the
    corresponding GenAI client span attributes onto the event — we do so to
    let downstream consumers correlate the event with the operation without
    a span join.

    No-op when ``logger`` is ``None`` (no log provider configured).
    """
    if logger is None:
        return

    attributes: dict[str, Any] = {
        EXCEPTION_TYPE: type(exception).__qualname__,
        EXCEPTION_MESSAGE: str(exception),
        EXCEPTION_STACKTRACE: "".join(traceback.format_exception(exception)),
    }
    if span_attributes:
        attributes.update(span_attributes)

    logger.emit(
        LogRecord(
            event_name=EVENT_GEN_AI_CLIENT_OPERATION_EXCEPTION,
            severity_number=SeverityNumber.WARN,
            attributes=attributes,
        )
    )
