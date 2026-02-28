# Quickstart: OTel GenAI Instrumentation for Claude Agent SDK

## Installation

```bash
pip install opentelemetry-instrumentation-claude-agent-sdk
```

For development (with OTel SDK for local export):

```bash
pip install opentelemetry-instrumentation-claude-agent-sdk opentelemetry-sdk opentelemetry-exporter-otlp
```

## Basic Usage (Auto-Instrumentation)

The simplest way to activate instrumentation — zero code changes to your application:

```bash
opentelemetry-instrument python my_agent_app.py
```

This works because the package registers an entry point under `opentelemetry_instrumentor`.

## Programmatic Instrumentation

```python
import asyncio
from claude_agent_sdk import query, ClaudeAgentOptions
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor
from opentelemetry.instrumentation.claude_agent_sdk import ClaudeAgentSdkInstrumentor

# 1. Configure OTel SDK (your application's responsibility)
provider = TracerProvider()
provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
trace.set_tracer_provider(provider)

# 2. Activate instrumentation (one line)
ClaudeAgentSdkInstrumentor().instrument()

# 3. Use Claude Agent SDK as normal — spans and metrics are automatic
async def main():
    options = ClaudeAgentOptions(
        system_prompt="You are a helpful assistant.",
        max_turns=3,
    )
    async for message in query(prompt="What is 2+2?", options=options):
        print(message)

asyncio.run(main())
```

**Output**: An `invoke_agent` span with GenAI semantic convention attributes is automatically created, including token usage, model name, and operation duration.

## With Content Capture (Opt-In)

```python
# Enable content capture for debugging
ClaudeAgentSdkInstrumentor().instrument(capture_content=True)
```

Or via environment variable:

```bash
export OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=True
python my_agent_app.py
```

This records `gen_ai.system_instructions`, `gen_ai.input.messages`, `gen_ai.output.messages`, and tool arguments/results in span attributes.

## Multi-Turn Sessions

```python
from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions

ClaudeAgentSdkInstrumentor().instrument()

async def chat():
    async with ClaudeSDKClient(options=ClaudeAgentOptions()) as client:
        # Turn 1
        await client.query("What is Python?")
        async for msg in client.receive_response():
            pass  # Each turn produces its own invoke_agent span

        # Turn 2 — same gen_ai.conversation.id as Turn 1
        await client.query("Show me a hello world example")
        async for msg in client.receive_response():
            pass
```

## Custom Tracer/Meter Providers

For testing or multi-tenant scenarios:

```python
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.metrics import MeterProvider

custom_tracer_provider = TracerProvider()
custom_meter_provider = MeterProvider()

ClaudeAgentSdkInstrumentor().instrument(
    tracer_provider=custom_tracer_provider,
    meter_provider=custom_meter_provider,
)
```

## Manual Hook Wiring (Escape Hatch)

If you need full control over hook registration (e.g., you manage `ClaudeAgentOptions.hooks` yourself):

```python
from claude_agent_sdk import ClaudeAgentOptions, HookMatcher
from opentelemetry.instrumentation.claude_agent_sdk import ClaudeAgentSdkInstrumentor

instrumentor = ClaudeAgentSdkInstrumentor()
otel_hooks = instrumentor.get_instrumentation_hooks()

# Define your own hooks (these run first — instrumentation observes final state)
async def my_pre_tool_hook(input_data, tool_use_id, context):
    print(f"Tool called: {input_data['tool_name']}")
    return {}

my_hooks = [HookMatcher(hooks=[my_pre_tool_hook])]

# Merge: user hooks first, then instrumentation hooks (per Constitution VI)
my_options = ClaudeAgentOptions(
    hooks={
        "PreToolUse": my_hooks + otel_hooks.get("PreToolUse", []),
        "PostToolUse": otel_hooks.get("PostToolUse", []),
        "PostToolUseFailure": otel_hooks.get("PostToolUseFailure", []),
        "SubagentStart": otel_hooks.get("SubagentStart", []),
        "SubagentStop": otel_hooks.get("SubagentStop", []),
        "Stop": otel_hooks.get("Stop", []),
    }
)
```

## Uninstrumenting

```python
ClaudeAgentSdkInstrumentor().uninstrument()
```

## Expected Trace Structure

```
[invoke_agent claude-agent]  (CLIENT span)
├── [execute_tool Bash]       (INTERNAL span)
├── [execute_tool Read]       (INTERNAL span)
├── [execute_tool Write]      (INTERNAL span)
└── [invoke_agent subagent]   (INTERNAL span, if subagents used)
```

## Expected Metrics

| Metric | Type | Unit | Description |
|--------|------|------|-------------|
| `gen_ai.client.token.usage` | Histogram | `{token}` | Input/output token counts per invocation |
| `gen_ai.client.operation.duration` | Histogram | `s` | Invocation duration in seconds |
