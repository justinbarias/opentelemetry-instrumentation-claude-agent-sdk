# Research: OTel GenAI Semantic Conventions for Claude Agent SDK

**Feature**: `001-otel-genai-semconv`
**Date**: 2026-02-28
**Status**: Complete

## 1. Claude Agent SDK Hook System

### Decision: Use SDK hook registration via `ClaudeAgentOptions.hooks`

**Rationale**: The Claude Agent SDK provides a first-class hook system via `ClaudeAgentOptions.hooks: dict[HookEvent, list[HookMatcher]]`. This is the canonical way to intercept agent lifecycle events without modifying internal SDK code. Combined with monkey-patching `query()` and `ClaudeSDKClient.__init__()` for span lifecycle management, this gives complete observability coverage.

**Alternatives considered**:
- **Post-hoc response stream parsing**: Rejected — cannot provide accurate tool timing (only sees results after-the-fact), misses crash scenarios, and requires complex state machine parsing.
- **Subprocess environment variable injection**: Rejected — provides subprocess-internal traces (complementary but different scope), not caller-level agent observability.

### Hook Callback Signature

```python
HookCallback = Callable[
    [HookInput, str | None, HookContext],
    Awaitable[HookJSONOutput]
]
```

Three arguments:
1. `input_data: HookInput` — Strongly-typed TypedDict with event-specific fields
2. `tool_use_id: str | None` — Correlates Pre/Post events for the same tool call
3. `context: HookContext` — Reserved (`signal: Any | None`)

### Available Hook Events (Python SDK)

| Event | Input Type | Key Fields |
|-------|-----------|------------|
| `PreToolUse` | `PreToolUseHookInput` | `tool_name`, `tool_input`, `tool_use_id` |
| `PostToolUse` | `PostToolUseHookInput` | `tool_name`, `tool_input`, `tool_response`, `tool_use_id` |
| `PostToolUseFailure` | `PostToolUseFailureHookInput` | `tool_name`, `tool_input`, `tool_use_id`, `error`, `is_interrupt` |
| `SubagentStart` | `SubagentStartHookInput` | `agent_id`, `agent_type` |
| `SubagentStop` | `SubagentStopHookInput` | `agent_id`, `agent_type`, `stop_hook_active` |
| `Stop` | `StopHookInput` | `stop_hook_active` |
| `Notification` | `NotificationHookInput` | `message`, `notification_type` |
| `UserPromptSubmit` | `UserPromptSubmitHookInput` | `prompt` |
| `PreCompact` | `PreCompactHookInput` | `trigger`, `custom_instructions` |
| `PermissionRequest` | `PermissionRequestHookInput` | `tool_name`, `tool_input` |

All inputs inherit from `BaseHookInput`: `session_id`, `transcript_path`, `cwd`, `permission_mode`.

**Note**: `SessionStart`/`SessionEnd` are TypeScript-only. Python hooks cover the lifecycle via `Stop` + monkey-patched `query()` boundaries.

### Hook Output for Instrumentation

Instrumentation hooks should return `{}` (empty dict) for non-blocking observation, or `{"async_": True}` for fire-and-forget telemetry. For span lifecycle management (start/end), synchronous return (`{}`) is preferred to ensure spans are properly started before tool execution begins.

### Hook Merge Strategy

`ClaudeAgentOptions.hooks` is `dict[HookEvent, list[HookMatcher]]`. To append instrumentation hooks after user hooks:

```python
for event, matchers in instrumentation_hooks.items():
    existing = user_options.hooks.get(event, [])
    user_options.hooks[event] = existing + matchers
```

Instrumentation hooks use `matcher=None` (match all tools) to observe all tool calls without filtering.

## 2. OTel GenAI Semantic Conventions

### Decision: Follow GenAI semconv v0.x (Development status)

**Rationale**: The GenAI semantic conventions are the only standardized approach for LLM/agent observability in the OTel ecosystem. While still in "Development" status, they are actively maintained and used by official instrumentations (OpenAI v2, AWS Bedrock). Using them ensures compatibility with community dashboards and backends.

**Alternatives considered**:
- **Custom attribute namespace**: Rejected — loses ecosystem compatibility, forces custom dashboards.
- **Traceloop/OpenLLMetry conventions**: Rejected — non-standard, predates official OTel GenAI semconv.

### Agent Span: `invoke_agent`

| Aspect | Value |
|--------|-------|
| **Span name** | `invoke_agent {gen_ai.agent.name}` (or just `invoke_agent` if name unavailable) |
| **Span kind** | `CLIENT` (Claude SDK uses subprocess, treated as remote service) |
| **Required attrs** | `gen_ai.operation.name = "invoke_agent"`, `gen_ai.provider.name = "anthropic"` |
| **Conditionally required** | `error.type` (on error), `gen_ai.agent.name`, `gen_ai.conversation.id`, `gen_ai.request.model` |
| **Recommended** | `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, `gen_ai.usage.cache_creation.input_tokens`, `gen_ai.usage.cache_read.input_tokens`, `gen_ai.response.finish_reasons`, `gen_ai.response.model` |
| **Opt-in** | `gen_ai.system_instructions`, `gen_ai.input.messages`, `gen_ai.output.messages`, `gen_ai.tool.definitions` |

### Tool Span: `execute_tool`

| Aspect | Value |
|--------|-------|
| **Span name** | `execute_tool {gen_ai.tool.name}` |
| **Span kind** | `INTERNAL` |
| **Required attrs** | `gen_ai.operation.name = "execute_tool"` |
| **Conditionally required** | `error.type` (on failure) |
| **Recommended** | `gen_ai.tool.name`, `gen_ai.tool.call.id`, `gen_ai.tool.type` |
| **Opt-in** | `gen_ai.tool.call.arguments`, `gen_ai.tool.call.result` |

### Metrics

**`gen_ai.client.token.usage`** (Histogram, unit: `{token}`):
- Dimensions: `gen_ai.operation.name`, `gen_ai.provider.name`, `gen_ai.token.type` ("input"/"output"), `gen_ai.request.model`
- Buckets: `[1, 4, 16, 64, 256, 1024, 4096, 16384, 65536, 262144, 1048576, 4194304, 16777216, 67108864]`
- Two records per invocation: one for input tokens, one for output tokens.

**`gen_ai.client.operation.duration`** (Histogram, unit: `s`):
- Dimensions: `gen_ai.operation.name`, `gen_ai.provider.name`, `gen_ai.request.model`, `error.type` (on failure)
- Buckets: `[0.01, 0.02, 0.04, 0.08, 0.16, 0.32, 0.64, 1.28, 2.56, 5.12, 10.24, 20.48, 40.96, 81.92]`

### Content Capture Configuration

- **Environment variable**: `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT` (standard)
- **Programmatic**: `instrument(capture_content=True)` kwarg
- **Default**: Disabled (no sensitive data in traces)

### Stability Opt-In

Consumer applications should set:
```bash
export OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_latest_experimental
```

## 3. Token Usage Mapping

### Decision: Map SDK `ResultMessage.usage` fields to OTel GenAI attributes

**Rationale**: Direct 1:1 mapping from the SDK's usage dict to semconv attributes. The one caveat is that the SDK's `input_tokens` field excludes cached tokens, so `gen_ai.usage.input_tokens` must be computed as the sum.

| SDK Field (`ResultMessage.usage`) | OTel Attribute | Notes |
|---|---|---|
| `input_tokens` + `cache_creation_input_tokens` + `cache_read_input_tokens` | `gen_ai.usage.input_tokens` | Sum of all input types per semconv spec |
| `output_tokens` | `gen_ai.usage.output_tokens` | Direct mapping |
| `cache_creation_input_tokens` | `gen_ai.usage.cache_creation.input_tokens` | When present |
| `cache_read_input_tokens` | `gen_ai.usage.cache_read.input_tokens` | When present |

**For metrics** (`gen_ai.client.token.usage`):
- `gen_ai.token.type = "input"` → Record the total input tokens (sum of all input types)
- `gen_ai.token.type = "output"` → Record `output_tokens`

**Alternatives considered**:
- **Use SDK's `input_tokens` directly**: Rejected — semconv spec says `gen_ai.usage.input_tokens` SHOULD include all token types including cached.
- **Emit separate metric records for cache tokens**: Rejected — not part of the semconv metric spec. Cache breakdown is span-level only.

## 4. Monkey-Patching Strategy

### Decision: Wrap `query()` at module level and `ClaudeSDKClient.__init__()`

**Rationale**: This is the standard OTel approach (used by opentelemetry-instrumentation-openai-v2). Wrapping `query()` provides the span lifecycle for standalone invocations. Wrapping `ClaudeSDKClient.__init__()` allows injecting hooks at client creation time.

**Implementation approach**:
- Use `wrapt.wrap_function_wrapper()` for monkey-patching
- Use `wrapt.unwrap()` in `_uninstrument()`
- `query()` wrapper: Creates `invoke_agent` span, injects hooks into options, iterates response to capture `ResultMessage`, finalizes span
- `ClaudeSDKClient.__init__()` wrapper: Injects hooks into the options before passing to original `__init__`
- `ClaudeSDKClient.query()` wrapper: Creates per-turn `invoke_agent` span

**Alternatives considered**:
- **Decorator-based wrapping**: Rejected — less standard, harder to uninstrument.
- **Subclass proxy**: Rejected — fragile across SDK version changes, harder to maintain.

## 5. Invocation Context Design

### Decision: Thread-safe per-invocation context using `contextvars`

**Rationale**: Each `query()` call or `ClaudeSDKClient.query()` turn needs its own context to track active tool/subagent spans. Python's `contextvars` module provides async-safe context isolation that integrates naturally with asyncio and OTel's own context propagation.

**Design**:
- `InvocationContext` dataclass holds: parent span, active tool spans (keyed by `tool_use_id`), active subagent spans (keyed by `agent_id`), model name (captured from first `AssistantMessage`)
- A `ContextVar[InvocationContext | None]` stores the current invocation context
- Hook callbacks access the context var to find/update active spans
- On invocation completion or crash, all unclosed tool/subagent spans are force-ended with ERROR status

**Alternatives considered**:
- **Global dict keyed by session_id**: Rejected — not async-safe without locks, harder to clean up.
- **Span-attached storage**: Rejected — OTel span attributes are write-once; need mutable state for tracking.

## 6. Model Name Extraction

### Decision: Extract from `AssistantMessage.model` at response time, fall back to `ClaudeAgentOptions.model`

**Rationale**: The model may be resolved by the SDK (e.g., `claude-sonnet-4-20250514` when `options.model` was `None`). The `AssistantMessage.model` field carries the actual model used, which is more accurate than the requested model.

**Mapping**:
- `gen_ai.request.model` ← `ClaudeAgentOptions.model` (set at span start, may be `None`)
- `gen_ai.response.model` ← `AssistantMessage.model` (set when first `AssistantMessage` arrives)

## 7. Finish Reason Mapping

### Decision: Derive from `ResultMessage.subtype` and `ResultMessage.is_error`, with passthrough for unknown values

**Rationale**: The Claude Agent SDK's `ResultMessage.subtype` indicates why the invocation ended. Map known values to GenAI finish reason strings. For unknown subtypes, pass the raw `subtype` value through as-is — this is future-proof and useful for debugging.

| `ResultMessage.subtype` | `gen_ai.response.finish_reasons` | Notes |
|---|---|---|
| `"success"` | `["end_turn"]` | Normal completion |
| `"error"` / error subtypes | `["error"]` | When `is_error=True` |
| `"max_turns"` | `["max_tokens"]` | Agent hit max turns limit |
| Any other value | `["{subtype}"]` | Passthrough: raw subtype used as finish reason |

**Alternatives considered**:
- **Omit for unknown subtypes**: Rejected — passthrough is more useful for debugging than omission, and the GenAI semconv allows arbitrary finish reason strings.

## 8. Package Dependencies

### Decision: Minimal runtime dependencies per OTel conventions

| Dependency | Version | Role |
|---|---|---|
| `opentelemetry-api` | `~= 1.12` | Tracing and metrics API (no-op without SDK) |
| `opentelemetry-instrumentation` | `>= 0.50b0` | `BaseInstrumentor` base class |
| `opentelemetry-semantic-conventions` | `>= 0.50b0` | GenAI attribute constants (if available) |
| `wrapt` | `>= 1.0.0, < 2.0.0` | Function wrapping for monkey-patching |

**NOT a runtime dependency**: `opentelemetry-sdk` (dev/test only), `claude-agent-sdk` (optional extra under `[instruments]`).

## Sources

- [Claude Agent SDK Python docs](https://platform.claude.com/docs/en/agent-sdk/python)
- [Claude Agent SDK hooks guide](https://platform.claude.com/docs/en/agent-sdk/hooks)
- [Claude Agent SDK cost tracking](https://platform.claude.com/docs/en/agent-sdk/cost-tracking)
- [claude-agent-sdk-python GitHub](https://github.com/anthropics/claude-agent-sdk-python)
- [OTel GenAI agent spans spec](https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-agent-spans/)
- [OTel GenAI spans spec](https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-spans/)
- [OTel GenAI metrics spec](https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-metrics/)
- [OTel GenAI attributes registry](https://opentelemetry.io/docs/specs/semconv/registry/attributes/gen-ai/)
- [opentelemetry-instrumentation-openai-v2 (reference)](https://github.com/open-telemetry/opentelemetry-python-contrib/tree/main/instrumentation-genai/opentelemetry-instrumentation-openai-v2)
- [BaseInstrumentor source](https://github.com/open-telemetry/opentelemetry-python-contrib/blob/main/opentelemetry-instrumentation/src/opentelemetry/instrumentation/instrumentor.py)
