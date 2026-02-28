# Implementation Plan: OTel GenAI Semantic Conventions for Claude Agent SDK

**Branch**: `feature/001-claude-otel` | **Date**: 2026-02-28 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `specs/001-otel-genai-semconv/spec.md`

## Summary

Build a standalone OpenTelemetry instrumentation package that auto-instruments the Claude Agent SDK to produce GenAI semantic convention spans and metrics. The package uses the standard `BaseInstrumentor` pattern: `instrument()` monkey-patches `query()` and `ClaudeSDKClient.__init__()` to inject hook callbacks that create `invoke_agent` and `execute_tool` spans, emit `gen_ai.client.token.usage` and `gen_ai.client.operation.duration` histogram metrics, and support opt-in content capture — all with zero overhead when no OTel SDK is configured.

## Technical Context

**Language/Version**: Python >= 3.10
**Primary Dependencies**: `opentelemetry-api ~=1.12`, `opentelemetry-instrumentation >=0.50b0`, `opentelemetry-semantic-conventions >=0.50b0`, `wrapt >=1.0,<2.0`
**Instrumented Library**: `claude-agent-sdk >=0.1.37` (optional extra)
**Storage**: N/A (in-memory span/metric state only)
**Testing**: pytest + pytest-asyncio (asyncio_mode="auto"), pytest-mock, pytest-cov (branch coverage >= 80%)
**Target Platform**: Any platform supporting Python >= 3.10 and the Claude Agent SDK
**Project Type**: Library (OTel instrumentation package)
**Performance Goals**: < 5% latency overhead on Claude invocations (SC-005)
**Constraints**: Zero overhead when no TracerProvider/MeterProvider configured (SC-006); runtime depends on `opentelemetry-api` only, not `-sdk` (Constitution I)
**Scale/Scope**: Single package, ~6 source modules, ~26 functional requirements

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Evidence |
|-----------|--------|----------|
| **I. OTel API-Only Dependency** | PASS | Runtime deps are `opentelemetry-api`, `opentelemetry-instrumentation`, `opentelemetry-semantic-conventions`, `wrapt`. No `opentelemetry-sdk` at runtime. |
| **II. Spec-Driven Development** | PASS | `spec.md` completed and quality-checked before this plan. All code traces to FR-NNN requirements. |
| **III. GenAI Semantic Convention Compliance** | PASS | Span names (`invoke_agent`, `execute_tool`), metric names (`gen_ai.client.token.usage`, `gen_ai.client.operation.duration`), and all attribute names match the OTel GenAI semconv spec exactly (verified in research.md). |
| **IV. Standard Instrumentor Pattern** | PASS | Uses `BaseInstrumentor` with `_instrument()`/`_uninstrument()`, `wrapt` monkey-patching, entry point in `pyproject.toml`. |
| **V. Test-First with Coverage Gate** | PASS | Plan follows red-green-refactor. Unit tests run without network access. Coverage >= 80%. mypy strict on all production code. |
| **VI. Hook-Append, Never Override** | PASS | Instrumentation hooks are appended after user hooks per FR-002 and research.md §1 hook merge strategy. |

**Post-Phase 1 Re-Check**: All principles still hold. No violations introduced during design.

## Project Structure

### Documentation (this feature)

```text
specs/001-otel-genai-semconv/
├── plan.md              # This file
├── research.md          # Phase 0: Technology decisions and SDK research
├── data-model.md        # Phase 1: Entity definitions and relationships
├── quickstart.md        # Phase 1: Usage guide
├── contracts/
│   └── public-api.md    # Phase 1: Public API surface contract
└── tasks.md             # Phase 2 output (created by /speckit.tasks)
```

### Source Code (repository root)

```text
src/opentelemetry/instrumentation/claude_agent_sdk/
├── __init__.py          # Public exports: ClaudeAgentSdkInstrumentor, __version__
├── version.py           # Dynamic version from package metadata (exists)
├── _instrumentor.py     # ClaudeAgentSdkInstrumentor class (BaseInstrumentor subclass)
├── _hooks.py            # Hook callback implementations (PreToolUse, PostToolUse, etc.)
├── _context.py          # InvocationContext dataclass + ContextVar management
├── _spans.py            # Span creation helpers, attribute constants, span naming
└── _metrics.py          # Histogram instrument creation and recording helpers

tests/
├── __init__.py          # (exists)
├── test_smoke.py        # (exists) Package import smoke tests
├── test_instrumentor.py # Instrumentor lifecycle (instrument/uninstrument/idempotency)
├── test_invoke_agent.py # invoke_agent span creation, attributes, error handling
├── test_tool_spans.py   # execute_tool spans via hook callbacks, correlation
├── test_metrics.py      # Token usage and duration histogram recording
├── test_content_capture.py  # Opt-in content capture (enabled/disabled)
├── test_multi_turn.py   # Multi-turn session conversation.id correlation
├── test_subagent.py     # Subagent lifecycle span creation
├── test_context.py      # InvocationContext lifecycle, cleanup, and concurrent invocation isolation
└── conftest.py          # Shared fixtures (mock SDK, in-memory OTel exporter)
```

**Structure Decision**: Single-project layout following the existing namespace package structure (`src/opentelemetry/instrumentation/claude_agent_sdk/`). Internal modules are prefixed with `_` to signal private API. Tests mirror source modules 1:1 for clear traceability.

## Architecture Overview

### Data Flow

```
Application Code
    │
    ▼
query(prompt, options)          ◄── Monkey-patched by wrapt
    │
    ├── 1. Start invoke_agent span (CLIENT)
    ├── 2. Inject hooks into options.hooks (append after user hooks)
    ├── 3. Call original query()
    │       │
    │       ├── PreToolUse hook fires ──► Start execute_tool span (INTERNAL)
    │       ├── PostToolUse hook fires ──► End execute_tool span (OK)
    │       ├── PostToolUseFailure    ──► End execute_tool span (ERROR)
    │       ├── SubagentStart         ──► Start subagent span (INTERNAL)
    │       ├── SubagentStop          ──► End subagent span
    │       ├── Stop hook fires       ──► Record stop reason
    │       │
    │       ├── AssistantMessage      ──► Capture model name
    │       └── ResultMessage         ──► Capture usage, session_id, finish reason
    │
    ├── 4. Set span attributes from ResultMessage
    ├── 5. Record token usage metrics
    ├── 6. Record operation duration metric
    ├── 7. Cleanup any unclosed child spans (crash safety)
    └── 8. End invoke_agent span
```

### Async Generator Wrapper Pattern

Both `query()` and `ClaudeSDKClient.receive_response()` return `AsyncIterator[Message]`.
The wrapper must transparently proxy messages while intercepting key message types:

```python
async def _wrapped_query(original, prompt, options, tracer, meter, capture_content):
    ctx = InvocationContext(...)
    _INVOCATION_CONTEXT.set(ctx)
    span = tracer.start_span("invoke_agent", kind=SpanKind.CLIENT, attributes={...})
    try:
        async for message in original(prompt=prompt, options=options):
            if isinstance(message, AssistantMessage) and ctx.model is None:
                ctx.model = message.model
                span.set_attribute("gen_ai.response.model", message.model)
            elif isinstance(message, ResultMessage):
                _finalize_from_result(span, ctx, message, meter)
            yield message  # always proxy to caller
    except Exception as exc:
        span.set_status(StatusCode.ERROR, str(exc))
        span.set_attribute("error.type", type(exc).__name__)
        raise
    finally:
        _cleanup_unclosed_spans(ctx)
        span.end()
        _INVOCATION_CONTEXT.set(None)
```

### ClaudeSDKClient Instrumentation Flow

`ClaudeSDKClient` has a split flow: `query()` sends the request, `receive_response()` yields messages.
The instrumentation wraps three methods:

1. **`__init__()`** — Inject instrumentation hooks into `options.hooks` (append after user hooks).
2. **`query()`** — Start a new `invoke_agent` span, create `InvocationContext`, store on client instance.
3. **`receive_response()`** — Async generator wrapper (same pattern as above): intercept `AssistantMessage`/`ResultMessage`, finalize span on completion.

```
client = ClaudeSDKClient(options)    ◄── __init__ wrapper injects hooks
    │
    ├── client.query("prompt")       ◄── query wrapper starts invoke_agent span
    │       └── stores span + ctx on client._otel_context
    │
    └── client.receive_response()    ◄── receive_response wrapper intercepts messages
            ├── AssistantMessage → capture model
            ├── ResultMessage → finalize span, record metrics
            └── finally → cleanup unclosed child spans, end span
```

### Module Responsibilities

| Module | Responsibility | FR Coverage |
|--------|---------------|-------------|
| `_instrumentor.py` | `BaseInstrumentor` lifecycle, monkey-patching, `get_instrumentation_hooks()`, query/client wrappers, content capture for agent spans, conversation.id | FR-001–FR-004, FR-020 (agent content), FR-023 |
| `_spans.py` | Span creation, attribute setting, naming, constants | FR-005–FR-010, FR-015–FR-016 |
| `_hooks.py` | Hook callback functions, hook merger, HookMatcher creation, tool content capture | FR-011–FR-014, FR-020 (tool content), FR-021, FR-026 |
| `_context.py` | `InvocationContext` dataclass, `ContextVar`, crash cleanup | FR-022, FR-024–FR-025 |
| `_metrics.py` | Histogram creation, token/duration recording | FR-017–FR-019 |
| `__init__.py` | Public exports (`ClaudeAgentSdkInstrumentor`, `__version__`) | — |

## Histogram Bucket Boundaries

Per the GenAI semconv (see research.md §2 for sources):

- **`gen_ai.client.token.usage`** (`{token}`): `[1, 4, 16, 64, 256, 1024, 4096, 16384, 65536, 262144, 1048576, 4194304, 16777216, 67108864]`
- **`gen_ai.client.operation.duration`** (`s`): `[0.01, 0.02, 0.04, 0.08, 0.16, 0.32, 0.64, 1.28, 2.56, 5.12, 10.24, 20.48, 40.96, 81.92]`

## Complexity Tracking

> No constitution violations. Table intentionally empty.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| — | — | — |
