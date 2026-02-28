# Tasks: OTel GenAI Semantic Conventions — User Story 1 Only

**Input**: Design documents from `/specs/001-otel-genai-semconv/`
**Prerequisites**: plan.md, spec.md, data-model.md, contracts/public-api.md, research.md
**Scope**: User Story 1 (Standalone GenAI Instrumentation Package) — P1 MVP

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[US1]**: All implementation tasks belong to User Story 1

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Ensure the project skeleton supports the new source modules and test infrastructure needed for US1.

- [ ] T001 Create test fixture infrastructure in tests/conftest.py with mock Claude Agent SDK types using dataclasses (not MagicMock) for mypy strict compatibility: MockResultMessage (fields: .usage dict with input_tokens, output_tokens, cache_creation_input_tokens, cache_read_input_tokens; .session_id str; .subtype str; .is_error bool), MockAssistantMessage (fields: .model str), MockClaudeAgentOptions (fields: .model str|None, .hooks dict, .system_prompt str|None), MockHookMatcher; also create in-memory OTel span exporter and in-memory OTel metrics reader fixtures
- [ ] T002 [P] Create GenAI semantic convention attribute constants module in src/opentelemetry/instrumentation/claude_agent_sdk/_constants.py defining all GenAI attribute keys (gen_ai.operation.name, gen_ai.provider.name, gen_ai.request.model, gen_ai.response.model, gen_ai.agent.name, gen_ai.conversation.id, gen_ai.usage.input_tokens, gen_ai.usage.output_tokens, gen_ai.usage.cache_creation.input_tokens, gen_ai.usage.cache_read.input_tokens, gen_ai.response.finish_reasons, gen_ai.system_instructions, gen_ai.input.messages, gen_ai.output.messages, gen_ai.tool.definitions, error.type), histogram names, and bucket boundaries

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core modules that the Instrumentor and query wrapper depend on. MUST complete before US1 implementation tasks.

**CRITICAL**: No US1 implementation work can begin until this phase is complete.

- [ ] T003 [P] Implement InvocationContext dataclass and ContextVar management in src/opentelemetry/instrumentation/claude_agent_sdk/_context.py — fields: invocation_span, active_tool_spans (dict[str, Span]), active_subagent_spans (dict[str, Span]), model (str|None, set-once from first AssistantMessage.model — subsequent AssistantMessages must not overwrite), session_id (str|None), start_time (float), capture_content (bool); include cleanup_unclosed_spans() method that ends all active tool/subagent spans with ERROR status
- [ ] T004 [P] Implement span creation helpers in src/opentelemetry/instrumentation/claude_agent_sdk/_spans.py — functions: create_invoke_agent_span(tracer: Tracer, agent_name: str|None, request_model: str|None, options: ClaudeAgentOptions|None) that creates a CLIENT span with required/conditional attributes (capture_content is handled by the caller/wrapper, not by span creation); set_result_attributes(span, result_message) for token usage, finish reason, conversation_id; set_error_attributes(span, exception) for error.type and ERROR status
- [ ] T005 [P] Implement metrics helpers in src/opentelemetry/instrumentation/claude_agent_sdk/_metrics.py — functions: create_token_usage_histogram(meter) with correct bucket boundaries; create_duration_histogram(meter) with correct bucket boundaries; record_token_usage(histogram, input_tokens, output_tokens, attributes) that emits two histogram records; record_duration(histogram, duration_seconds, attributes, error_type)

**Checkpoint**: Foundation modules ready — InvocationContext, span helpers, and metrics helpers are independently testable.

---

## Phase 3: User Story 1 — Standalone GenAI Instrumentation Package (Priority: P1) MVP

**Goal**: A Python developer installs the package, calls `ClaudeAgentSdkInstrumentor().instrument()`, and all `query()` / `ClaudeSDKClient` usage automatically produces GenAI semantic convention `invoke_agent` spans and metrics.

**Independent Test**: Install the package, run a Claude Agent SDK `query()` call with an in-memory OTel exporter, assert exported spans conform to GenAI semantic conventions (correct span name, required attributes, token usage, error handling).

**FR Coverage**: FR-001, FR-002, FR-003, FR-004, FR-005, FR-006, FR-007, FR-008, FR-009, FR-010, FR-017, FR-018, FR-019, FR-022, FR-023, FR-024, FR-025, FR-026

### Tests for User Story 1 (Write First — Must FAIL)

> **NOTE: Write these tests FIRST per Constitution V (test-first / red-green-refactor). Tests MUST fail (ImportError or assertion failure) until the corresponding implementation tasks complete. Create minimal module stubs (empty files) if needed so tests can be parsed by pytest.**

- [ ] T006 [P] [US1] Write unit tests for InvocationContext in tests/test_context.py — test creation with all fields; test cleanup_unclosed_spans() ends tool and subagent spans with ERROR; test ContextVar isolation across concurrent async tasks; test cleanup is idempotent (calling twice does not error)
- [ ] T007 [P] [US1] Write unit tests for span helpers in tests/test_spans.py — test create_invoke_agent_span() produces correct span name and required attributes; test set_result_attributes() sets token usage, finish reason, conversation_id; test set_error_attributes() sets error.type and ERROR status; test span attributes are omitted (not zero) when usage is None; test cache token summing for gen_ai.usage.input_tokens
- [ ] T008 [P] [US1] Write unit tests for metrics helpers in tests/test_metrics.py — test create_token_usage_histogram() uses correct name/unit/buckets; test create_duration_histogram() uses correct name/unit/buckets; test record_token_usage() emits two records (input + output) with correct dimensions; test record_duration() includes error.type dimension on failure
- [ ] T009 [P] [US1] Write unit tests for instrumentor lifecycle in tests/test_instrumentor.py — test instrument() applies monkey-patches to query and ClaudeSDKClient; test uninstrument() removes monkey-patches; test idempotent instrument/uninstrument; test instrument() with custom tracer_provider and meter_provider; test instrument() with capture_content=True and agent_name; test get_instrumentation_hooks() returns dict with expected hook event keys and HookMatcher values that can be merged into user options per quickstart.md manual wiring example
- [ ] T010 [P] [US1] Write unit tests for invoke_agent span creation in tests/test_invoke_agent.py — test query() produces invoke_agent span with all required GenAI attributes; test span nests under active parent span (FR-022); test span becomes root span with no parent; test AssistantMessage model extraction sets gen_ai.response.model; test ResultMessage sets token usage attributes including cache tokens; test error handling sets error.type and ERROR status; test gen_ai.conversation.id is set from session_id; test finish reason mapping (success->end_turn, error, max_turns, passthrough)
- [ ] T011 [P] [US1] Write unit tests for ClaudeSDKClient wrappers in tests/test_multi_turn.py — test __init__ wrapper injects hooks into options; test query()/receive_response() produces per-turn invoke_agent spans; test all turns share same gen_ai.conversation.id; test hook merge preserves user hooks and appends instrumentation hooks after
- [ ] T012 [US1] Write unit tests for zero-overhead / no-op behavior in tests/test_instrumentor.py — test that when no TracerProvider/MeterProvider is configured, instrument() still succeeds, query() works normally, and no spans/metrics are exported (FR-024)

### Implementation for User Story 1

> **NOTE: Implement code to make the tests above PASS (green phase of red-green-refactor).**

- [ ] T013 [US1] Implement hook callback stubs in src/opentelemetry/instrumentation/claude_agent_sdk/_hooks.py — create async function: _on_stop(input_data, tool_use_id, context) that records stop reason on invocation span; create merge_hooks(user_hooks, instrumentation_hooks) utility that appends instrumentation hooks after user hooks per FR-002/Constitution VI; create build_instrumentation_hooks(tracer, meter, capture_content) that returns dict[str, list[HookMatcher]] containing only hook events with actual callbacks (in US1: only Stop has a callback — do NOT register empty-list placeholders for PreToolUse/PostToolUse/PostToolUseFailure/SubagentStart/SubagentStop; those are added in US2/US4 when their callbacks are implemented)
- [ ] T014 [US1] Implement ClaudeAgentSdkInstrumentor in src/opentelemetry/instrumentation/claude_agent_sdk/_instrumentor.py — subclass BaseInstrumentor; implement instrumentation_dependencies() returning ["claude-agent-sdk >= 0.1.37"]; implement _instrument(**kwargs) that: accepts tracer_provider, meter_provider, capture_content, agent_name kwargs; creates Tracer and Meter instances (from provided or global providers per FR-003); creates token_usage and duration histograms via _metrics.py; monkey-patches query(), ClaudeSDKClient.__init__(), ClaudeSDKClient.query(), and ClaudeSDKClient.receive_response() via wrapt.wrap_function_wrapper(); implement _uninstrument(**kwargs) that calls wrapt.unwrap() on all four targets: query(), ClaudeSDKClient.__init__(), ClaudeSDKClient.query(), and ClaudeSDKClient.receive_response(); implement get_instrumentation_hooks() escape hatch per FR-002
- [ ] T015 [US1] Implement async generator wrapper for standalone query() in src/opentelemetry/instrumentation/claude_agent_sdk/_instrumentor.py — the wrapper must: create InvocationContext and set it in ContextVar; start invoke_agent CLIENT span with gen_ai.operation.name, gen_ai.provider.name, gen_ai.request.model, gen_ai.agent.name; if options is None, construct a default ClaudeAgentOptions() so instrumentation hooks can be attached; inject instrumentation hooks into options.hooks (append after user hooks); call original query() and yield each message transparently; intercept AssistantMessage to capture gen_ai.response.model; intercept ResultMessage to set token usage attributes (input_tokens summed with cache tokens per research.md S3), gen_ai.conversation.id from session_id, gen_ai.response.finish_reasons from subtype; record token usage metrics and duration metric; on exception: set error.type and ERROR status; in finally: call cleanup_unclosed_spans() and end span
- [ ] T016 [US1] Implement ClaudeSDKClient.__init__() wrapper in src/opentelemetry/instrumentation/claude_agent_sdk/_instrumentor.py — the wrapper must: intercept the options parameter; call merge_hooks() to inject instrumentation hooks into options.hooks; call original __init__() with modified options; store instrumentor config as client._otel_config (containing tracer, meter, histograms, capture_content, agent_name) for use by query()/receive_response() wrappers
- [ ] T017 [US1] Implement ClaudeSDKClient.query() and receive_response() wrappers in src/opentelemetry/instrumentation/claude_agent_sdk/_instrumentor.py — query() wrapper: start new invoke_agent span per turn, create InvocationContext, store as client._otel_invocation_ctx; receive_response() wrapper: async generator that intercepts AssistantMessage/ResultMessage (same logic as standalone query wrapper), finalizes span on completion, cleanup in finally block
- [ ] T018 [US1] Update public exports in src/opentelemetry/instrumentation/claude_agent_sdk/__init__.py — add ClaudeAgentSdkInstrumentor to __all__ and import from _instrumentor module
- [ ] T019 [US1] Run full CI validation: make ci (lint + format-check + type-check + security + test-coverage) and ensure all checks pass with >= 80% coverage on new code

**Checkpoint**: User Story 1 is fully functional and testable. All tests pass (green). The package can be installed, instrument() called, and all query()/ClaudeSDKClient usage automatically produces GenAI semantic convention invoke_agent spans and metrics.

---

## Phase 4: Polish & Cross-Cutting Concerns

**Purpose**: Final validation and cleanup for US1 MVP

- [ ] T020 [P] Run quickstart.md validation — verify the programmatic instrumentation example from specs/001-otel-genai-semconv/quickstart.md compiles and works against the implemented API surface (adjust quickstart.md if API changed during implementation)
- [ ] T021 Validate contract compliance — verify the implemented ClaudeAgentSdkInstrumentor class matches the public API contract defined in specs/001-otel-genai-semconv/contracts/public-api.md (method signatures, kwargs, return types)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately
- **Foundational (Phase 2)**: Can run in parallel with Setup (T003-T005 are independent of T001-T002). However T003-T005 produce modules that tests and implementation depend on.
- **US1 Tests (Phase 3a)**: Depends on Phase 1 + Phase 2 completion. Tests are written first and MUST FAIL.
- **US1 Implementation (Phase 3b)**: Depends on Phase 3a (tests exist and fail). Implementation makes tests pass.
- **Polish (Phase 4)**: Depends on Phase 3 completion (all tests green).

### Task Dependencies (Within Phases)

```
T001 (conftest) ──────────────────────────────────────┐
T002 (constants) ─────────────────────────────────────┤
T003 (context) ───────────────────────────────────────┤
T004 (spans) ─────────────────────────────────────────┤
T005 (metrics) ───────────────────────────────────────┤
                                                      ▼
                              Phase 3a: Tests (write first, must FAIL)
                              ┌───────────────────────────────────────┐
                              │ T006 (test_context)      [P]         │
                              │ T007 (test_spans)        [P]         │
                              │ T008 (test_metrics)      [P]         │
                              │ T009 (test_instrumentor) [P]         │
                              │ T010 (test_invoke_agent) [P]         │
                              │ T011 (test_multi_turn)   [P]         │
                              │ T012 (test_noop) ← same file as T009 │
                              └───────────────────────────────────────┘
                                                      │
                                                      ▼
                              Phase 3b: Implementation (make tests PASS)
                              ┌───────────────────────────────────────┐
                              │ T013 (hooks) ──► T014 (instrumentor) │
                              │                    │                  │
                              │                    ├─► T015 (query)   │
                              │                    ├─► T016 (__init__)│
                              │                    └─► T017 (client)  │
                              │                          │            │
                              │               T018 (exports) ◄───────┘
                              └───────────────────────────────────────┘
                                                      │
                                                      ▼
                                               T019 (CI validation)
                                                      │
                                                      ▼
                                               T020-T021 (polish)
```

### Within User Story 1

1. **Tests first** (T006-T012): Write all tests; they MUST fail (red phase)
2. Hooks module (T013) before Instrumentor (T014) — instrumentor uses hooks
3. Instrumentor core (T014) before wrappers (T015, T016, T017) — wrappers live in instrumentor module
4. All implementation (T013-T017) before exports update (T018)
5. All tests should now PASS (green phase)
6. CI validation (T019) confirms everything

### Parallel Opportunities

```bash
# Phase 1+2 — all can run in parallel:
T001 (conftest) | T002 (constants) | T003 (context) | T004 (spans) | T005 (metrics)

# Phase 3a — tests can run in parallel (different files):
T006 (test_context) | T007 (test_spans) | T008 (test_metrics) | T009 (test_instrumentor) | T010 (test_invoke_agent) | T011 (test_multi_turn)
# T012 shares file with T009 — run after T009

# Phase 4 — polish can run in parallel:
T020 (quickstart) | T021 (contract validation)
```

---

## Implementation Strategy

### MVP Delivery (This Task List)

1. Complete Phase 1: Setup (T001-T002) — test fixtures and constants
2. Complete Phase 2: Foundational (T003-T005) — context, spans, metrics modules
3. Complete Phase 3a: Tests (T006-T012) — write all tests, verify they FAIL (red)
4. Complete Phase 3b: Implementation (T013-T018) — write code to make tests PASS (green)
5. Complete Phase 3: CI (T019) — run `make ci` to confirm all checks pass
6. Complete Phase 4: Polish (T020-T021) — validate against spec artifacts
7. **STOP and VALIDATE**: Full CI green, US1 independently functional

### What US1 Delivers

- `ClaudeAgentSdkInstrumentor` with `instrument()` / `uninstrument()` / `get_instrumentation_hooks()`
- Automatic `invoke_agent` span creation for `query()` and `ClaudeSDKClient` usage
- GenAI semantic convention compliance (span names, required attributes, token usage)
- `gen_ai.client.token.usage` and `gen_ai.client.operation.duration` histogram metrics
- Context propagation (parent span nesting)
- Multi-turn session correlation via `gen_ai.conversation.id`
- Error handling with `error.type` and ERROR status
- Zero overhead when no OTel SDK configured
- Hook merge strategy (append after user hooks)

### What US1 Does NOT Deliver (Deferred to Later User Stories)

- Tool execution tracing via PreToolUse/PostToolUse hooks (US2)
- GenAI client metrics dashboard-level concerns (US3 — metrics are emitted by US1 but US3 adds specific metric scenarios)
- Subagent lifecycle tracing via SubagentStart/SubagentStop hooks (US4)
- Multi-turn session edge cases (US5 — basic conversation.id correlation is in US1)
- Opt-in content capture (US6 — the `capture_content` flag plumbing is in US1 but content attribute recording is US6)

---

## Summary

| Metric | Value |
|--------|-------|
| Total tasks | 21 |
| Setup tasks | 2 (T001-T002) |
| Foundational tasks | 3 (T003-T005) |
| US1 test tasks | 7 (T006-T012) |
| US1 implementation tasks | 6 (T013-T018) |
| CI validation | 1 (T019) |
| Polish tasks | 2 (T020-T021) |
| Max parallelism (Phase 1+2) | 5 tasks |
| Max parallelism (Phase 3a tests) | 6 tasks |
| FR coverage | FR-001-FR-010, FR-017-FR-019, FR-022-FR-026 |
| FR deferred | FR-011-FR-016 (tool/subagent hooks), FR-020-FR-021 (content capture) |

---

## Notes

- [P] tasks = different files, no dependencies on each other
- [US1] label maps task to User Story 1 for traceability
- All SDK types in tests use mock dataclasses from conftest.py — no network access required
- Tests are written FIRST and must FAIL before implementation begins (Constitution V)
- The `_hooks.py` module in US1 only implements the `Stop` hook and the merge utility. Tool/subagent hook callbacks are added in US2/US4.
- Only hook events with actual callbacks are registered — no empty-list placeholders
- Content capture plumbing (the `capture_content` flag on InvocationContext and the kwarg on `instrument()`) is included in US1, but actual content attribute recording is deferred to US6.
- Client instance attributes: `_otel_config` for instrumentor config, `_otel_invocation_ctx` for per-turn InvocationContext
- Commit after each task or logical group

---

## Remediations Applied

| ID | Severity | Change |
|----|----------|--------|
| C1 | HIGH | Reordered Phase 3: tests sub-phase (T006-T012) now precedes implementation sub-phase (T013-T018) per Constitution V |
| C2 | HIGH | Added get_instrumentation_hooks() test coverage to T009 (test_instrumentor.py) |
| I1 | MEDIUM | Added _constants.py to plan.md project structure and module responsibilities table |
| I2 | MEDIUM | Added "set-once from first AssistantMessage" note to T003 model field |
| I3 | MEDIUM | Fixed T014: _uninstrument() unwraps four targets (query, __init__, query, receive_response) |
| U1 | MEDIUM | Specified dataclass mock design and required fields in T001 |
| U2 | MEDIUM | Added None-options handling to T015 (construct default ClaudeAgentOptions) |
| U3 | MEDIUM | Changed T013: only register hook events with actual callbacks, no empty-list placeholders |
| A1 | LOW | Clarified T004 parameter types, removed capture_content from span creation |
| A2 | LOW | Named client attributes: _otel_config (config) and _otel_invocation_ctx (per-turn context) in T016/T017 |
