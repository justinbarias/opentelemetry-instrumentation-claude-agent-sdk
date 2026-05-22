# opentelemetry-instrumentation-claude-agent-sdk

OpenTelemetry instrumentation for the [Anthropic Claude Agent SDK](https://github.com/anthropics/claude-agent-sdk).

This package provides automatic tracing and metrics for Claude Agent SDK operations following the [OpenTelemetry GenAI Semantic Conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/).

## Status

**Alpha** - Under active development.

## Features

- Automatic span creation for `query()` and `ClaudeSDKClient` operations
- Hook-driven `execute_tool` child spans for every tool call (PreToolUse/PostToolUse/PostToolUseFailure)
- Optional tool content capture (arguments and results) via `capture_content=True`
- Token usage tracking (input, output, cache creation, cache read)
- Operation duration histograms
- Conversation ID propagation across multi-turn interactions
- Response model and finish reason capture
- Zero overhead when no TracerProvider/MeterProvider is configured
- Follows the standard OTel `Instrumentor` pattern (`instrument()`/`uninstrument()`)

## Installation

The package is published on PyPI as **`otel-instrumentation-claude-agent-sdk`** (the import path remains `opentelemetry.instrumentation.claude_agent_sdk`):

```bash
pip install otel-instrumentation-claude-agent-sdk
```

With the Claude Agent SDK (if not already installed):

```bash
pip install "otel-instrumentation-claude-agent-sdk[instruments]"
```

## Requirements

- Python >= 3.10
- opentelemetry-api >= 1.12
- opentelemetry-instrumentation >= 0.50b0
- claude-agent-sdk >= 0.1.44 (hooks support in `query()` requires >= 0.1.44)

## Quick Start

### Basic Instrumentation

```python
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, ConsoleSpanExporter
from opentelemetry.instrumentation.claude_agent_sdk import ClaudeAgentSdkInstrumentor

# Set up OTel tracing
provider = TracerProvider()
provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))

# Instrument the Claude Agent SDK
instrumentor = ClaudeAgentSdkInstrumentor()
instrumentor.instrument(tracer_provider=provider)

# Now all query() and ClaudeSDKClient calls are automatically traced
import claude_agent_sdk

async for message in claude_agent_sdk.query(prompt="Hello, Claude!"):
    pass  # Spans are created and exported automatically

# To remove instrumentation
instrumentor.uninstrument()
```

### With Metrics

```python
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import ConsoleMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, ConsoleSpanExporter
from opentelemetry.instrumentation.claude_agent_sdk import ClaudeAgentSdkInstrumentor

# Set up tracing
tracer_provider = TracerProvider()
tracer_provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))

# Set up metrics
meter_provider = MeterProvider(metric_readers=[ConsoleMetricReader()])

# Instrument with both
instrumentor = ClaudeAgentSdkInstrumentor()
instrumentor.instrument(
    tracer_provider=tracer_provider,
    meter_provider=meter_provider,
)
```

### With Agent Name

Setting an agent name adds it to span names and attributes, useful for distinguishing multiple agents:

```python
instrumentor.instrument(
    tracer_provider=tracer_provider,
    agent_name="my-research-agent",
)
# Span names become: "invoke_agent my-research-agent"
```

### Multi-Turn with ClaudeSDKClient

The instrumentor automatically traces `ClaudeSDKClient` multi-turn conversations, creating one span per query/receive_response cycle:

```python
import claude_agent_sdk

client = claude_agent_sdk.ClaudeSDKClient(options=claude_agent_sdk.ClaudeAgentOptions())
await client.connect()

# Turn 1 — creates span 1
await client.query("What is quantum computing?")
async for message in client.receive_response():
    pass

# Turn 2 — creates span 2 (shares conversation ID with span 1)
await client.query("Explain it simpler.")
async for message in client.receive_response():
    pass

await client.disconnect()
```

## Telemetry Reference

### Spans

Each `query()` call or `ClaudeSDKClient.query()`/`receive_response()` cycle produces one `invoke_agent` span with kind `CLIENT`. When tools are used, each tool call produces an `execute_tool` child span with kind `INTERNAL`.

All telemetry is emitted under schema URL `https://opentelemetry.io/schemas/gen-ai/1.42.0`.

#### invoke_agent span (CLIENT)

| Attribute | Type | Description |
|-----------|------|-------------|
| `gen_ai.operation.name` | string | Always `"invoke_agent"` |
| `gen_ai.provider.name` | string | Always `"anthropic"` |
| `gen_ai.agent.name` | string | Agent name (if configured) |
| `gen_ai.request.model` | string | Requested model (from options) |
| `gen_ai.response.model` | string | Actual model used (from response) |
| `gen_ai.usage.input_tokens` | int | Total input tokens (including cache) |
| `gen_ai.usage.output_tokens` | int | Output tokens |
| `gen_ai.usage.cache_creation.input_tokens` | int | Cache creation tokens (if > 0) |
| `gen_ai.usage.cache_read.input_tokens` | int | Cache read tokens (if > 0) |
| `gen_ai.response.finish_reasons` | string[] | e.g. `["end_turn"]`, `["error"]`, `["max_turns"]` |
| `gen_ai.conversation.id` | string | Session ID (shared across multi-turn) |
| `error.type` | string | Exception class (on error only) |

#### execute_tool span (INTERNAL, child of invoke_agent)

| Attribute | Type | Description |
|-----------|------|-------------|
| `gen_ai.operation.name` | string | Always `"execute_tool"` |
| `gen_ai.provider.name` | string | Always `"anthropic"` |
| `gen_ai.tool.name` | string | Tool name (e.g., `"Bash"`, `"Read"`) |
| `gen_ai.tool.call.id` | string | Unique tool use ID for correlation |
| `gen_ai.tool.type` | string | `"function"` for built-in tools, `"extension"` for MCP tools (`mcp__*`) |
| `gen_ai.tool.call.arguments` | string | Tool input (only when `capture_content=True`) |
| `gen_ai.tool.call.result` | string | Tool output (only when `capture_content=True`) |
| `error.type` | string | `"_OTHER"` on tool failure (raw error preserved on span status description) |

### Metrics

| Metric | Type | Unit | Description |
|--------|------|------|-------------|
| `gen_ai.client.token.usage` | Histogram | `{token}` | Token counts with `gen_ai.token.type` dimension (`"input"` or `"output"`) |
| `gen_ai.client.operation.duration` | Histogram | `s` | Operation wall-clock duration |

Both metrics include `gen_ai.operation.name`, `gen_ai.provider.name`, and `gen_ai.request.model` as dimensions. The duration metric includes `error.type` on failure.

### Events (log records)

The instrumentation emits two GenAI events as log records when a `LoggerProvider` is configured via `instrument(logger_provider=...)` (or set globally):

#### `gen_ai.client.inference.operation.details`

Severity `INFO`. Emitted once per `invoke_agent` invocation with the operation's request/response metadata. Carries (when available):

- `gen_ai.operation.name`, `gen_ai.provider.name`
- `gen_ai.request.model`, `gen_ai.response.model`
- `gen_ai.response.finish_reasons`
- `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, plus cache variants
- `gen_ai.conversation.id`
- `error.type` on failure

The content-bearing payloads are **opt-in** per the GenAI events spec — they are attached only when `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=true` is set, or when the instrumentor is configured with `capture_content=True`:

- `gen_ai.input.messages` — user prompts and tool results, as structured `parts` arrays
- `gen_ai.output.messages` — assistant turns (text + tool calls), as structured `parts` arrays
- `gen_ai.system_instructions` — system prompt text
- `gen_ai.tool.definitions` — tool surface configured on the agent (names only — the SDK doesn't expose schemas)

When content capture is opted in, the same four payloads are *also* mirrored onto the `invoke_agent` span as JSON-string attributes. Dashboards that don't yet consume the events form (e.g. the [.NET Aspire dashboard](https://aspire.dev/dashboard/explore/#genai-telemetry-visualization), Microsoft.Extensions.AI consumers) read them off the span instead.

#### `gen_ai.client.operation.exception`

Severity `WARN`. Emitted on the agent error path alongside the standard OTel `exception` span event (via `span.record_exception(exc)`). Carries `exception.type` / `exception.message` / `exception.stacktrace` plus a copy of the operation's identifying span attributes (`gen_ai.operation.name`, `gen_ai.provider.name`, `gen_ai.request.model`, `gen_ai.conversation.id`) so backends can correlate without a span join.

## Configuration Options

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `tracer_provider` | `TracerProvider` | Global | Custom tracer provider |
| `meter_provider` | `MeterProvider` | Global | Custom meter provider |
| `logger_provider` | `LoggerProvider` | Global | Custom logger provider — used to emit `gen_ai.client.operation.exception` and `gen_ai.client.inference.operation.details` events |
| `agent_name` | `str` | `None` | Agent name for span names and attributes |
| `capture_content` | `bool` | `False` | Opt in to recording prompt/completion content and tool arguments/results. See [Capturing message content](#capturing-message-content). |

### Environment variables

| Variable | Effect |
|----------|--------|
| `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT` | When set to `true` / `1` / `yes`, opts in to recording GenAI message content on spans and events. Read at emit time, so it can be toggled without re-instrumenting. |

### Capturing message content

Prompt/completion content is **opt-in** per the [GenAI semconv](https://opentelemetry.io/docs/specs/semconv/gen-ai/) because it often contains sensitive data. Enable it via either signal:

**Environment variable** (recommended for ops-controlled deployments):

```bash
export OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=true
```

**Instrumentor config** (recommended for in-code control):

```python
instrumentor.instrument(
    tracer_provider=tracer_provider,
    logger_provider=logger_provider,   # required for the events form
    capture_content=True,
)
```

Either signal turns on all four GenAI content payloads — `gen_ai.input.messages`, `gen_ai.output.messages`, `gen_ai.system_instructions`, `gen_ai.tool.definitions` — and the instrumentation emits them in **both** places:

- As JSON-string attributes on the `invoke_agent` span (read by the [.NET Aspire dashboard](https://aspire.dev/dashboard/explore/#genai-telemetry-visualization), Microsoft.Extensions.AI consumers, and older OTel-aware backends).
- As structured attributes on the `gen_ai.client.inference.operation.details` log record (read by newer events-aware consumers per the GenAI events spec).

A note on the `capture_content` parameter specifically: it also turns on `gen_ai.tool.call.arguments` / `gen_ai.tool.call.result` on `execute_tool` spans. The env var only governs the GenAI message payloads — it does not enable tool argument/result capture. If you want both, set `capture_content=True`.

## Development

### Prerequisites

- [uv](https://docs.astral.sh/uv/) (Python package manager)
- Python 3.10+

### Setup

```bash
# Full initialization (install deps + pre-commit hooks)
make init

# Or step by step:
make install-dev
make install-hooks
```

### Running Tests

```bash
make test            # Run all tests (unit + integration)
make test-unit       # Run unit tests only (58 tests)
make test-integration # Run integration tests (requires API token)
make test-coverage   # Run tests with coverage (80% threshold)
```

#### Integration Tests

Integration tests make real API calls to Claude. To run them:

1. Copy the env template:
   ```bash
   cp tests/integration/.env.example tests/integration/.env
   ```
2. Add your OAuth token to `tests/integration/.env`:
   ```
   CLAUDE_CODE_OAUTH_TOKEN=your-token-here
   ```
3. Run:
   ```bash
   make test-integration
   ```

Integration tests use `max_turns=3` and `permission_mode="bypassPermissions"` for tool tracing tests, or `max_turns=1` for basic span/metric tests.

### Code Quality

```bash
make lint            # Ruff linter
make lint-fix        # Ruff with auto-fix
make format          # Black + isort formatting
make type-check      # mypy (strict mode)
make security        # bandit + pip-audit
make ci              # Full CI pipeline locally
make ci-fast         # Quick check: lint + test only
```

### Project Structure

```
src/opentelemetry/instrumentation/claude_agent_sdk/
    __init__.py          # Package entry point, exports ClaudeAgentSdkInstrumentor
    version.py           # Dynamic version from package metadata
    _instrumentor.py     # Core instrumentor (wraps query, ClaudeSDKClient)
    _spans.py            # Span creation and attribute helpers
    _metrics.py          # Histogram creation and recording helpers
    _events.py           # GenAI log-record event helpers (exception event)
    _hooks.py            # SDK hook callbacks and merge utility
    _context.py          # Per-invocation context via contextvars
    _constants.py        # GenAI semantic convention constants
tests/
    unit/                # Unit tests (mock SDK, 89 tests)
    integration/         # Integration tests (real API, 28 tests)
```

## License

MIT
