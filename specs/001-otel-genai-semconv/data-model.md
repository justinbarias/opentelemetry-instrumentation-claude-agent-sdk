# Data Model: OTel GenAI Semantic Conventions for Claude Agent SDK

**Feature**: `001-otel-genai-semconv`
**Date**: 2026-02-28
**Status**: Complete

## Entity Definitions

### 1. ClaudeAgentSdkInstrumentor

The public entry point of the instrumentation package. Singleton that manages the lifecycle of monkey-patches and hook registration.

| Field | Type | Description |
|-------|------|-------------|
| `_tracer` | `Tracer` | OTel tracer instance for creating spans |
| `_meter` | `Meter` | OTel meter instance for creating metrics |
| `_token_usage_histogram` | `Histogram` | `gen_ai.client.token.usage` instrument |
| `_duration_histogram` | `Histogram` | `gen_ai.client.operation.duration` instrument |
| `_capture_content` | `bool` | Whether to record opt-in content attributes |
| `_is_instrumented_by_opentelemetry` | `bool` | Inherited from `BaseInstrumentor` |

**Methods**:
- `instrumentation_dependencies() -> Collection[str]` — Returns `["claude-agent-sdk >= 0.1.37"]`
- `_instrument(**kwargs)` — Monkey-patches `query()` and `ClaudeSDKClient.__init__()`, creates tracer/meter/histograms
- `_uninstrument(**kwargs)` — Removes monkey-patches via `wrapt.unwrap()`
- `get_instrumentation_hooks() -> dict[str, list[HookMatcher]]` — Escape hatch: returns raw hooks dict for manual wiring

**State transitions**:
```
UNINSTRUMENTED --(instrument())--> INSTRUMENTED --(uninstrument())--> UNINSTRUMENTED
```

### 2. InvocationContext

Per-invocation mutable state stored in a `ContextVar`. Tracks active tool/subagent spans for cleanup on completion or crash.

| Field | Type | Description |
|-------|------|-------------|
| `invocation_span` | `Span` | The `invoke_agent` span for this invocation |
| `active_tool_spans` | `dict[str, Span]` | Tool spans keyed by `tool_use_id` |
| `active_subagent_spans` | `dict[str, Span]` | Subagent spans keyed by `agent_id` |
| `model` | `str \| None` | Model name from first `AssistantMessage.model` |
| `session_id` | `str \| None` | Session ID from `BaseHookInput.session_id` or `ResultMessage.session_id` |
| `start_time` | `float` | Monotonic timestamp for duration calculation |
| `capture_content` | `bool` | Whether content capture is enabled for this invocation |

**State transitions**:
```
CREATED --(query() called)--> ACTIVE
ACTIVE --(tool hooks fire)--> ACTIVE (tool spans opened/closed)
ACTIVE --(ResultMessage received)--> FINALIZING
FINALIZING --(cleanup unclosed spans)--> COMPLETED
ACTIVE --(exception/crash)--> FINALIZING (error path, cleanup unclosed spans)
```

### 3. HookCallbackSet

The set of async hook callbacks that the instrumentor registers with the Claude Agent SDK. Not a stored entity — created fresh on each `instrument()` call, referencing the instrumentor's tracer/meter.

| Hook Event | Callback | Span Action |
|------------|----------|-------------|
| `PreToolUse` | `_on_pre_tool_use` | Start `execute_tool {tool_name}` span |
| `PostToolUse` | `_on_post_tool_use` | End tool span (OK status) |
| `PostToolUseFailure` | `_on_post_tool_use_failure` | End tool span (ERROR status) |
| `SubagentStart` | `_on_subagent_start` | Start subagent child span |
| `SubagentStop` | `_on_subagent_stop` | End subagent span |
| `Stop` | `_on_stop` | Record stop reason on invocation span |

Each callback:
1. Retrieves the current `InvocationContext` from the context var
2. Performs span operations (start/end/set attributes)
3. Returns `{}` (synchronous, non-blocking)

### 4. GenAI Span (invoke_agent)

A trace span conforming to the OTel GenAI agent span specification.

| Attribute | Source | When Set |
|-----------|--------|----------|
| `gen_ai.operation.name` | Constant `"invoke_agent"` | Span start |
| `gen_ai.provider.name` | Constant `"anthropic"` | Span start |
| `gen_ai.request.model` | `ClaudeAgentOptions.model` | Span start (if available) |
| `gen_ai.agent.name` | Instrumentor config or options | Span start (if available) |
| `gen_ai.conversation.id` | `ResultMessage.session_id` | Span end |
| `gen_ai.response.model` | `AssistantMessage.model` | First AssistantMessage |
| `gen_ai.usage.input_tokens` | Sum of all input token fields | Span end (from ResultMessage) |
| `gen_ai.usage.output_tokens` | `ResultMessage.usage["output_tokens"]` | Span end |
| `gen_ai.usage.cache_creation.input_tokens` | `ResultMessage.usage["cache_creation_input_tokens"]` | Span end (if present) |
| `gen_ai.usage.cache_read.input_tokens` | `ResultMessage.usage["cache_read_input_tokens"]` | Span end (if present) |
| `gen_ai.response.finish_reasons` | Derived from `ResultMessage.subtype` | Span end |
| `error.type` | Exception type or `ResultMessage.subtype` | Span end (on error) |
| `gen_ai.system_instructions` | `ClaudeAgentOptions.system_prompt` | Span start (opt-in) |
| `gen_ai.input.messages` | `prompt` parameter | Span start (opt-in) |
| `gen_ai.output.messages` | Collected `AssistantMessage` content | Span end (opt-in) |
| `gen_ai.tool.definitions` | `ClaudeAgentOptions.tools` / `allowed_tools` | Span start (opt-in) |

**Span kind**: `CLIENT`
**Span name**: `invoke_agent {gen_ai.agent.name}` or `invoke_agent`

### 5. GenAI Span (execute_tool)

A trace span for individual tool executions, created/ended by hook callbacks.

| Attribute | Source | When Set |
|-----------|--------|----------|
| `gen_ai.operation.name` | Constant `"execute_tool"` | Span start |
| `gen_ai.tool.name` | `PreToolUseHookInput.tool_name` | Span start |
| `gen_ai.tool.call.id` | `tool_use_id` parameter | Span start |
| `gen_ai.tool.type` | Derived from tool name prefix | Span start |
| `gen_ai.tool.call.arguments` | `PreToolUseHookInput.tool_input` (JSON) | Span start (opt-in) |
| `gen_ai.tool.call.result` | `PostToolUseHookInput.tool_response` (JSON) | Span end (opt-in) |
| `error.type` | `PostToolUseFailureHookInput.error` | Span end (on failure) |

**Span kind**: `INTERNAL`
**Span name**: `execute_tool {tool_name}`

### 6. GenAI Span (subagent)

A trace span for subagent lifecycles.

| Attribute | Source | When Set |
|-----------|--------|----------|
| `gen_ai.operation.name` | Constant `"invoke_agent"` | Span start |
| `gen_ai.agent.id` | `SubagentStartHookInput.agent_id` | Span start |
| `gen_ai.provider.name` | Constant `"anthropic"` | Span start |

**Span kind**: `INTERNAL`
**Span name**: `invoke_agent {agent_type}`

### 7. GenAI Metrics

**`gen_ai.client.token.usage`** (Histogram):

| Dimension | Source |
|-----------|--------|
| `gen_ai.operation.name` | `"invoke_agent"` |
| `gen_ai.provider.name` | `"anthropic"` |
| `gen_ai.token.type` | `"input"` or `"output"` |
| `gen_ai.request.model` | `ClaudeAgentOptions.model` |
| `gen_ai.response.model` | `AssistantMessage.model` |

Two records emitted per invocation.

**`gen_ai.client.operation.duration`** (Histogram):

| Dimension | Source |
|-----------|--------|
| `gen_ai.operation.name` | `"invoke_agent"` |
| `gen_ai.provider.name` | `"anthropic"` |
| `gen_ai.request.model` | `ClaudeAgentOptions.model` |
| `gen_ai.response.model` | `AssistantMessage.model` |
| `error.type` | Exception type (on failure only) |

One record emitted per invocation.

## Relationships

```
ClaudeAgentSdkInstrumentor (singleton)
  ├── creates → Tracer, Meter, Histograms
  ├── registers → HookCallbackSet (on instrument())
  └── wraps → query(), ClaudeSDKClient.__init__(), ClaudeSDKClient.query()

query() / ClaudeSDKClient.query() (wrapped)
  ├── creates → InvocationContext (stored in ContextVar)
  ├── starts → invoke_agent Span
  ├── emits → token.usage Metrics (on ResultMessage)
  ├── emits → operation.duration Metrics (on completion)
  └── finalizes → cleanup unclosed child spans

InvocationContext
  ├── holds → invoke_agent Span (parent)
  ├── tracks → execute_tool Spans (via tool_use_id)
  └── tracks → subagent Spans (via agent_id)

HookCallbackSet
  ├── PreToolUse → starts execute_tool Span (child of invoke_agent)
  ├── PostToolUse → ends execute_tool Span (OK)
  ├── PostToolUseFailure → ends execute_tool Span (ERROR)
  ├── SubagentStart → starts subagent Span (child of invoke_agent)
  ├── SubagentStop → ends subagent Span
  └── Stop → records stop reason on invoke_agent Span
```

## Validation Rules

1. `gen_ai.operation.name` MUST be one of the well-known values (`"invoke_agent"`, `"execute_tool"`)
2. `gen_ai.provider.name` MUST be `"anthropic"` on all `invoke_agent` spans
3. `gen_ai.tool.call.id` on `execute_tool` spans MUST match the `tool_use_id` from the SDK
4. Token usage attributes MUST be omitted (not set to 0) when `ResultMessage.usage` is `None`
5. `gen_ai.usage.input_tokens` MUST be the sum of `input_tokens` + `cache_creation_input_tokens` + `cache_read_input_tokens`
6. Content capture attributes MUST NOT be set unless `capture_content` is `True`
7. All unclosed tool/subagent spans MUST be ended with ERROR status when the parent `invoke_agent` span completes
8. `gen_ai.conversation.id` MUST be consistent across all turns in a multi-turn `ClaudeSDKClient` session

## Tool Type Derivation

The `gen_ai.tool.type` attribute is derived from the tool name prefix using a **best-effort heuristic**. The fallback default is `"function"`. This heuristic may need updating if the SDK introduces new tool name prefixes.

| Tool Name Pattern | `gen_ai.tool.type` |
|---|---|
| `mcp__*` (e.g., `mcp__server__action`) | `"extension"` |
| All other tools (built-in, custom, etc.) | `"function"` (default) |

## Agent Name Default

When `agent_name` is not provided to `instrument()`, `gen_ai.agent.name` is omitted from the span attributes and the span name is the bare `invoke_agent` (no suffix). This is valid per the GenAI semconv spec, which states the agent name is conditionally required "when available." Users who want named spans pass `agent_name="my-agent"` to `instrument()`.
