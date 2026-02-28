# Feature Specification: OTel GenAI Semantic Conventions for Claude Backend

**Feature Branch**: `001-otel-genai-semconv`
**Created**: 2026-02-28
**Status**: Draft
**Input**: User description: "Create an OpenTelemetry instrumentation package for the Claude Agent SDK that conforms to GenAI semantic conventions for agent spans, Anthropic-specific conventions, GenAI metrics, and GenAI inference spans. The instrumentation must be shippable as a standalone package."

## Clarifications

### Session 2026-02-28

- Q: Where does the instrumentation package live (monorepo vs separate repo)? → A: Its own dedicated repository with its own `pyproject.toml`, published independently to PyPI.
- Q: How does the package intercept Claude Agent SDK calls (monkey-patch vs hook injection vs wrapper)? → A: Monkey-patch with auto-injected hooks (standard OTel Instrumentor pattern). `instrument()` wraps `query()` and `ClaudeSDKClient.__init__()` to automatically merge instrumentation hooks into user-provided `ClaudeAgentOptions`. Escape hatch: `get_instrumentation_hooks()` returns raw hooks dict for manual wiring.
- Q: What is the hook merge strategy when users already have hooks for the same event type? → A: Append after user hooks. Instrumentation hooks run last, observing final state after user modifications, never interfering with user permission/security decisions.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Standalone GenAI Instrumentation Package (Priority: P1)

A Python developer using the Claude Agent SDK installs a standalone instrumentation package (e.g., `opentelemetry-instrumentation-claude-agent-sdk`) and gets automatic, standards-compliant GenAI tracing and metrics for all Claude Agent SDK interactions. The package requires only the Claude Agent SDK and OpenTelemetry API as dependencies. The developer registers the instrumentor, and all `query()` and `ClaudeSDKClient` usage in their application automatically produces GenAI semantic convention spans and metrics.

**Why this priority**: Making the instrumentation an independent package maximizes its value. Any Claude Agent SDK user benefits. The instrumentation library cleanly owns GenAI semconv compliance as a reusable component.

**Independent Test**: Can be fully tested by installing the package in isolation, running a Claude Agent SDK `query()` call with an in-memory OTel exporter, and asserting that the exported spans conform to GenAI semantic conventions. Delivers immediate value to the entire Claude Agent SDK ecosystem.

**Acceptance Scenarios**:

1. **Given** a Python project that depends only on `claude-agent-sdk` and `opentelemetry-api`, **When** the developer installs and activates the instrumentation package, **Then** all `query()` calls produce `invoke_agent` spans with GenAI semantic convention attributes.
2. **Given** the instrumentation package is installed, **When** a `ClaudeSDKClient` is used for multi-turn sessions, **Then** each turn produces properly attributed spans with `gen_ai.conversation.id` correlation.
3. **Given** an application with an active parent span, **When** the instrumentation package is activated and a Claude invocation occurs, **Then** the `invoke_agent` span nests correctly under the caller's parent span.

---

### User Story 2 - Hook-Driven Tool Execution Tracing (Priority: P2)

A developer debugging agent behavior sees each tool call made during a Claude invocation as a distinct `execute_tool` child span under the `invoke_agent` span. The instrumentation package uses the Claude Agent SDK's `PreToolUse`, `PostToolUse`, and `PostToolUseFailure` hooks to capture precise tool execution timing, arguments, results, and failures — rather than reconstructing tool activity from the response stream after the fact. Each tool span carries the tool name, call ID, tool type, and — when content capture is enabled — the arguments and results.

**Why this priority**: Tool execution is where agents spend most of their time and where most debugging happens. The SDK hooks provide real-time visibility into tool execution as it happens (including precise start/end timing), which is superior to post-hoc reconstruction from the response stream.

**Independent Test**: Can be tested by running a Claude Agent SDK `query()` with tools configured, using an in-memory exporter, and verifying that `execute_tool {tool_name}` spans appear as children of the `invoke_agent` span with correct attributes and accurate durations.

**Acceptance Scenarios**:

1. **Given** a Claude invocation that calls tools, **When** the `PreToolUse` hook fires, **Then** an `execute_tool {tool_name}` span with `span_kind = INTERNAL` is started with `gen_ai.tool.name`, `gen_ai.tool.call.id` (from `tool_use_id`), and `gen_ai.operation.name = "execute_tool"` attributes set.
2. **Given** a tool call completes successfully, **When** the `PostToolUse` hook fires, **Then** the corresponding tool span is ended with the correct duration, and the span status remains OK.
3. **Given** a tool call fails, **When** the `PostToolUseFailure` hook fires, **Then** the corresponding tool span is ended with `error.type` set and span status set to ERROR.
4. **Given** content capture is enabled, **When** `PreToolUse` fires, **Then** `gen_ai.tool.call.arguments` is recorded; and **When** `PostToolUse` fires, **Then** `gen_ai.tool.call.result` is recorded.
5. **Given** content capture is disabled, **When** tools are called, **Then** tool arguments and results are NOT recorded in span attributes.

---

### User Story 3 - GenAI Client Metrics (Priority: P2)

A platform operator monitoring a fleet of agents in production sees standardized GenAI metrics flowing to their metrics backend. They can build dashboards showing token consumption histograms broken down by model and operation, operation duration distributions, and error rates — all using standard GenAI metric names that work with community dashboards and alerting templates.

**Why this priority**: Metrics provide aggregate visibility across many invocations. Without standardized metrics, operators cannot build alerts for token budget overruns, detect latency regressions, or track cost across agents.

**Independent Test**: Can be tested by running multiple `query()` calls with an in-memory metrics reader and verifying that `gen_ai.client.token.usage` and `gen_ai.client.operation.duration` metrics are emitted with correct attributes and dimensions.

**Acceptance Scenarios**:

1. **Given** a configured `MeterProvider`, **When** an invocation completes, **Then** `gen_ai.client.token.usage` histogram records are emitted for both `gen_ai.token.type = "input"` and `gen_ai.token.type = "output"`, with `gen_ai.operation.name`, `gen_ai.provider.name = "anthropic"`, and `gen_ai.request.model` as dimensions.
2. **Given** an invocation completes (success or failure), **When** the operation finishes, **Then** a `gen_ai.client.operation.duration` histogram record is emitted in seconds, with `error.type` included as a dimension if the operation failed.

---

### User Story 4 - Subagent Lifecycle Tracing (Priority: P3)

A developer running an agent configured with subagents sees each subagent's lifecycle as a distinct span under the parent `invoke_agent` span. The instrumentation uses the `SubagentStart` and `SubagentStop` SDK hooks to create spans that capture when subagents are spawned, how long they run, and their completion status.

**Why this priority**: Subagents represent a significant portion of agent execution cost and complexity. Without subagent-level tracing, operators cannot understand why an invocation is slow or expensive when multiple subagents are involved.

**Independent Test**: Can be tested by running an agent with subagents enabled and verifying that subagent spans appear as children of the `invoke_agent` span with correct lifecycle timing.

**Acceptance Scenarios**:

1. **Given** a Claude invocation spawns a subagent, **When** the `SubagentStart` hook fires, **Then** a child span is created with `gen_ai.agent.id` set to the subagent's `agent_id`.
2. **Given** a subagent completes, **When** the `SubagentStop` hook fires, **Then** the subagent span is ended with the correct duration.

---

### User Story 5 - Multi-Turn Session Tracing (Priority: P3)

A developer using multi-turn sessions sees each turn as a distinct `invoke_agent` span, all sharing the same `gen_ai.conversation.id`. This enables tracing the full conversation flow, correlating token usage across turns, and understanding how context accumulates.

**Why this priority**: Multi-turn sessions are a core capability, but without conversation-level tracing, operators cannot understand session-level behavior, cost accumulation, or performance degradation across turns.

**Independent Test**: Can be tested by creating a `ClaudeSDKClient`, sending multiple messages, and verifying that each turn produces an `invoke_agent` span with the same `gen_ai.conversation.id`.

**Acceptance Scenarios**:

1. **Given** a multi-turn session, **When** multiple messages are sent, **Then** each turn produces an `invoke_agent` span with `gen_ai.conversation.id` set to the SDK session ID.
2. **Given** a multi-turn session, **When** the session is closed, **Then** all turns share the same `gen_ai.conversation.id` and each span independently reports its token usage.

---

### User Story 6 - Opt-In Content Capture (Priority: P3)

A developer debugging prompt engineering issues opts into content capture and sees the system instructions, input messages, and output messages recorded in span attributes. When content capture is disabled (the default), none of this sensitive data appears in traces.

**Why this priority**: Content capture is essential for prompt debugging but must be strictly opt-in due to privacy and data sensitivity. This aligns with the GenAI semantic convention's "opt-in" attribute classification.

**Independent Test**: Can be tested by running with content capture enabled and verifying `gen_ai.system_instructions`, `gen_ai.input.messages`, and `gen_ai.output.messages` appear in spans, then running with it disabled and verifying they do not.

**Acceptance Scenarios**:

1. **Given** content capture is enabled, **When** a Claude invocation completes, **Then** `gen_ai.system_instructions`, `gen_ai.input.messages`, and `gen_ai.output.messages` are recorded as span attributes on the `invoke_agent` span.
2. **Given** content capture is disabled (default), **When** a Claude invocation completes, **Then** no content attributes are recorded in spans.
3. **Given** content capture is enabled and tools are configured, **When** the invocation begins, **Then** `gen_ai.tool.definitions` is recorded on the `invoke_agent` span.

---

### Edge Cases

- What happens when the Claude subprocess crashes mid-invocation? The `invoke_agent` span must still be finalized with `error.type` and ERROR status, even on retry.
- How are retries represented? Each retry attempt should be a separate child span under the parent `invoke_agent` span, so operators can see how many attempts were needed.
- What happens when token usage is not reported (e.g., subprocess crash before `ResultMessage`)? Token attributes should be omitted (not set to 0), following OTel conventions for missing data.
- What happens when observability is disabled or no `TracerProvider`/`MeterProvider` is configured? Zero overhead — the instrumentation package uses the OTel API's no-op fallback behavior.
- What happens if a `PreToolUse` hook fires but no matching `PostToolUse` or `PostToolUseFailure` follows (e.g., subprocess crash)? The tool span must be ended with ERROR status when the parent `invoke_agent` span is finalized.
- What happens when the `tool_use_id` from `PreToolUse` cannot be correlated with `PostToolUse`? The tool span should be ended with an "uncorrelated" marker at invocation cleanup.
- What happens when the instrumentation package is used with no parent span? The `invoke_agent` span becomes a root span, which is valid OTel behavior.

## Requirements *(mandatory)*

### Functional Requirements

**Package Independence**

- **FR-001**: The GenAI instrumentation MUST be shippable as an independent Python package. Its only required dependencies are the Claude Agent SDK and the OpenTelemetry API (`opentelemetry-api`). The package lives in its own repository with its own `pyproject.toml`.
- **FR-002**: The package MUST follow the standard OTel Instrumentor pattern: an `Instrumentor` class with `instrument()` / `uninstrument()` methods. `instrument()` monkey-patches `query()` and `ClaudeSDKClient.__init__()` to automatically merge instrumentation hooks into user-provided `ClaudeAgentOptions`. Instrumentation hooks MUST be appended after any user-provided hooks for the same event type, ensuring they observe final state and never interfere with user permission/security decisions. The package MUST also expose a `get_instrumentation_hooks()` escape hatch that returns the raw hooks dict for manual wiring. `instrument()` MUST accept configuration options for content capture, custom tracer/meter providers, and agent metadata.
- **FR-003**: The package MUST use the OTel API's global `TracerProvider` and `MeterProvider` by default but MUST accept explicit provider instances for testing and multi-tenant scenarios.
- **FR-004**: Consuming applications SHOULD use the instrumentation package as a dependency, passing their observability preferences at activation time. No GenAI semconv logic should live in the consuming application's codebase.

**Span Requirements (Traces)**

- **FR-005**: The package MUST create `invoke_agent {gen_ai.agent.name}` spans for every Claude Agent SDK invocation (`query()` and `ClaudeSDKClient.query()`) that conform to the OTel GenAI agent span specification.
- **FR-006**: The package MUST set `gen_ai.provider.name = "anthropic"` on all GenAI spans.
- **FR-007**: The package MUST populate all required attributes (`gen_ai.operation.name`, `gen_ai.provider.name`) and conditionally required attributes (`gen_ai.request.model`, `gen_ai.agent.name`, `gen_ai.conversation.id`, `error.type`) per the GenAI agent span specification.
- **FR-008**: The package MUST populate recommended token usage attributes (`gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`) from the SDK `ResultMessage.usage` dict.
- **FR-009**: The package MUST populate Anthropic-specific cache token attributes (`gen_ai.usage.cache_creation.input_tokens`, `gen_ai.usage.cache_read.input_tokens`) when present in the usage data.
- **FR-010**: The package MUST set span status to ERROR and populate `error.type` when invocations fail, including on retried attempts.

**Hook-Driven Tool Tracing**

- **FR-011**: The package MUST register `PreToolUse`, `PostToolUse`, and `PostToolUseFailure` hooks with the Claude Agent SDK to create `execute_tool {gen_ai.tool.name}` child spans with `span_kind = INTERNAL`.
- **FR-012**: The package MUST correlate `PreToolUse` and `PostToolUse`/`PostToolUseFailure` events using the `tool_use_id` parameter to accurately measure tool execution duration.
- **FR-013**: The package MUST set `gen_ai.tool.name`, `gen_ai.tool.call.id`, `gen_ai.tool.type`, and `gen_ai.operation.name = "execute_tool"` on each tool span.
- **FR-014**: The package MUST set span status to ERROR and `error.type` on tool spans when `PostToolUseFailure` fires.

**Hook-Driven Subagent Tracing**

- **FR-015**: The package MUST register `SubagentStart` and `SubagentStop` hooks to create child spans for subagent lifecycles, with `gen_ai.agent.id` set to the subagent's `agent_id`.
- **FR-016**: The package MUST correlate `SubagentStart` and `SubagentStop` using `tool_use_id` to accurately measure subagent duration.

**Metrics Requirements**

- **FR-017**: The package MUST emit `gen_ai.client.token.usage` histogram metrics with `gen_ai.token.type` dimension ("input" / "output") after each invocation.
- **FR-018**: The package MUST emit `gen_ai.client.operation.duration` histogram metrics in seconds for each invocation.
- **FR-019**: Metrics MUST include `gen_ai.operation.name`, `gen_ai.provider.name`, and `gen_ai.request.model` as dimensions, plus `error.type` on failure.

**Content Capture (Opt-In)**

- **FR-020**: The package MUST support opt-in content capture (`gen_ai.system_instructions`, `gen_ai.input.messages`, `gen_ai.output.messages`, `gen_ai.tool.call.arguments`, `gen_ai.tool.call.result`, `gen_ai.tool.definitions`) gated by a configuration flag.
- **FR-021**: Tool content capture (`gen_ai.tool.call.arguments` in `PreToolUse`, `gen_ai.tool.call.result` in `PostToolUse`) MUST also be gated by the content capture flag.

**Context and Lifecycle**

- **FR-022**: The package MUST participate in OTel context propagation so that spans created by the package are proper children of any active parent span in the calling code's context.
- **FR-023**: The package MUST use `gen_ai.conversation.id` to correlate multi-turn session spans.
- **FR-024**: The package MUST produce zero overhead (no spans, no metrics, no hook registrations) when no `TracerProvider` or `MeterProvider` is configured (OTel API no-op behavior).
- **FR-025**: The package MUST end all open tool/subagent spans when the parent `invoke_agent` span completes, even if correlating `PostToolUse`/`SubagentStop` hooks were never received (crash cleanup).
- **FR-026**: The package MUST register a `Stop` hook to capture agent execution stop events and record the stop reason on the `invoke_agent` span.


### Key Entities

- **Instrumentor**: The public entry point of the standalone package. Provides `instrument()` / `uninstrument()` methods that register/unregister SDK hooks and configure span/metric creation.
- **GenAI Span**: A trace span conforming to the OTel GenAI semantic conventions. Carries standardized attributes for provider, model, operation, token usage, and optional content.
- **GenAI Metric**: A histogram instrument conforming to the OTel GenAI metrics specification. Records token usage and operation duration with standardized dimensions.
- **Hook Callback**: An async function registered with the Claude Agent SDK that fires at specific lifecycle points (PreToolUse, PostToolUse, SubagentStart, etc.) and creates/ends OTel spans.
- **Invocation Context**: Per-invocation state maintained by the instrumentor to track active tool/subagent spans and ensure cleanup on completion or crash.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The instrumentation package can be installed and used in any Python project, producing valid GenAI semantic convention spans and metrics.
- **SC-002**: All Claude Agent SDK invocations produce spans that pass validation against the OTel GenAI agent span specification (correct span names, required attributes present, correct attribute types).
- **SC-003**: When used within an application that has an active parent span, Claude backend traces appear correctly nested under the caller's parent spans in any OTel-compatible tracing backend, with no orphaned spans.
- **SC-004**: Token usage metrics are queryable by `gen_ai.provider.name`, `gen_ai.request.model`, and `gen_ai.token.type` in any OTel-compatible metrics backend.
- **SC-005**: Enabling instrumentation adds less than 5% latency overhead to Claude invocations compared to uninstrumented usage.
- **SC-006**: When no `TracerProvider`/`MeterProvider` is configured, the instrumentation produces zero trace/metric exports and allocates no OTel span or metric objects.
- **SC-007**: Tool execution spans account for 100% of tool calls observed via hooks — no tool calls are missed.
- **SC-008**: Content capture attributes appear only when explicitly opted in; default configuration produces no sensitive data in traces.
- **SC-009**: Tool span durations accurately reflect the time between `PreToolUse` and `PostToolUse`/`PostToolUseFailure` hook events, not reconstructed estimates.

## Assumptions

- The Claude Agent SDK `ResultMessage.usage` dict provides `input_tokens` and `output_tokens` fields. Cache-specific fields (`cache_creation_input_tokens`, `cache_read_input_tokens`) may or may not be present depending on SDK version.
- The instrumentation package will use `opentelemetry-api` (not `opentelemetry-sdk`) as its dependency, following the standard OTel instrumentation library pattern where the API provides no-op behavior without an SDK.
- The `opentelemetry-semantic-conventions` package (or inline constants) will be used for GenAI attribute names if available; otherwise, attribute name strings will be defined as constants within the package.
- Finish reasons are available from `ResultMessage` or can be inferred from the message type (e.g., `end_turn`, `max_tokens`).
- If a consuming application uses env-var-based OTel configuration for subprocesses, that approach can coexist with this instrumentation package — they serve complementary purposes (subprocess-internal traces vs. caller-level agent traces).
- The Python SDK supports `PreToolUse`, `PostToolUse`, `PostToolUseFailure`, `SubagentStart`, `SubagentStop`, `Stop`, `Notification`, `UserPromptSubmit`, `PreCompact`, and `PermissionRequest` hooks. `SessionStart` and `SessionEnd` are TypeScript-only and not available as Python SDK callbacks.
- SDK hooks receive `tool_use_id` as the second parameter, which uniquely identifies a tool call across `PreToolUse` and `PostToolUse`/`PostToolUseFailure` events, enabling accurate span correlation.
- Hook callbacks can use async return (`{"async_": True}`) for fire-and-forget telemetry, but synchronous returns are preferred for span lifecycle management to ensure spans are properly started before tool execution begins.
- The package name and namespace will follow OTel instrumentation conventions (e.g., `opentelemetry-instrumentation-claude-agent-sdk` or similar).
