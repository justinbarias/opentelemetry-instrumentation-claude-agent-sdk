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

```bash
pip install opentelemetry-instrumentation-claude-agent-sdk
```

With the Claude Agent SDK (if not already installed):

```bash
pip install opentelemetry-instrumentation-claude-agent-sdk[instruments]
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

#### invoke_agent span (CLIENT)

| Attribute | Type | Description |
|-----------|------|-------------|
| `gen_ai.operation.name` | string | Always `"invoke_agent"` |
| `gen_ai.system` | string | Always `"anthropic"` |
| `gen_ai.agent.name` | string | Agent name (if configured) |
| `gen_ai.request.model` | string | Requested model (from options) |
| `gen_ai.response.model` | string | Actual model used (from response) |
| `gen_ai.usage.input_tokens` | int | Total input tokens (including cache) |
| `gen_ai.usage.output_tokens` | int | Output tokens |
| `gen_ai.usage.cache_creation_input_tokens` | int | Cache creation tokens (if > 0) |
| `gen_ai.usage.cache_read_input_tokens` | int | Cache read tokens (if > 0) |
| `gen_ai.response.finish_reasons` | string[] | e.g. `["end_turn"]`, `["error"]`, `["max_tokens"]` |
| `gen_ai.conversation.id` | string | Session ID (shared across multi-turn) |
| `error.type` | string | Exception type (on error only) |

#### execute_tool span (INTERNAL, child of invoke_agent)

| Attribute | Type | Description |
|-----------|------|-------------|
| `gen_ai.operation.name` | string | Always `"execute_tool"` |
| `gen_ai.system` | string | Always `"anthropic"` |
| `gen_ai.tool.name` | string | Tool name (e.g., `"Bash"`, `"Read"`) |
| `gen_ai.tool.call.id` | string | Unique tool use ID for correlation |
| `gen_ai.tool.type` | string | `"function"` for built-in tools, `"extension"` for MCP tools (`mcp__*`) |
| `gen_ai.tool.call.arguments` | string | Tool input (only when `capture_content=True`) |
| `gen_ai.tool.call.result` | string | Tool output (only when `capture_content=True`) |
| `error.type` | string | Error message (on tool failure only) |

### Metrics

| Metric | Type | Unit | Description |
|--------|------|------|-------------|
| `gen_ai.client.token.usage` | Histogram | `{token}` | Token counts with `gen_ai.token.type` dimension (`"input"` or `"output"`) |
| `gen_ai.client.operation.duration` | Histogram | `s` | Operation wall-clock duration |

Both metrics include `gen_ai.operation.name`, `gen_ai.system`, and `gen_ai.request.model` as dimensions. The duration metric includes `error.type` on failure.

## Configuration Options

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `tracer_provider` | `TracerProvider` | Global | Custom tracer provider |
| `meter_provider` | `MeterProvider` | Global | Custom meter provider |
| `agent_name` | `str` | `None` | Agent name for span names and attributes |
| `capture_content` | `bool` | `False` | Reserved for future content capture support |

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
    _hooks.py            # SDK hook callbacks and merge utility
    _context.py          # Per-invocation context via contextvars
    _constants.py        # GenAI semantic convention constants
tests/
    unit/                # Unit tests (mock SDK, 89 tests)
    integration/         # Integration tests (real API, 28 tests)
```

## License

MIT
