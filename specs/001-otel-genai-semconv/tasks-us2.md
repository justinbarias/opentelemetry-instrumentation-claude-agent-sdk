# Tasks: OTel GenAI Semantic Conventions — User Story 2 (Hook-Driven Tool Execution Tracing)

**Input**: Design documents from `/specs/001-otel-genai-semconv/`
**Prerequisites**: plan.md, spec.md, data-model.md, contracts/public-api.md, research.md
**Scope**: User Story 2 (Hook-Driven Tool Execution Tracing) — P2
**Depends On**: User Story 1 (all US1 tasks complete and green)

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[US2]**: All implementation tasks belong to User Story 2

---

## Phase 1: Setup (US2-Specific Infrastructure)

**Purpose**: Extend the existing project skeleton with tool-specific constants and test fixtures required for US2.

- [ ] T001 [P] Add tool execution constants and fix US3 metric dimension bug in src/opentelemetry/instrumentation/claude_agent_sdk/_constants.py — add: OPERATION_EXECUTE_TOOL = "execute_tool", GEN_AI_TOOL_NAME = "gen_ai.tool.name", GEN_AI_TOOL_CALL_ID = "gen_ai.tool.call.id", GEN_AI_TOOL_TYPE = "gen_ai.tool.type", GEN_AI_TOOL_CALL_ARGUMENTS = "gen_ai.tool.call.arguments", GEN_AI_TOOL_CALL_RESULT = "gen_ai.tool.call.result"; add TOOL_TYPE_EXTENSION = "extension" and TOOL_TYPE_FUNCTION = "function" for tool type derivation; add MCP_TOOL_PREFIX = "mcp__". BUG FIX (FR-019/US3): add GEN_AI_PROVIDER_NAME = "gen_ai.provider.name" — the GenAI semconv uses gen_ai.provider.name for metric dimensions (not gen_ai.system, which is the span attribute). Then update the 4 metric_attrs dicts in src/opentelemetry/instrumentation/claude_agent_sdk/_instrumentor.py to use GEN_AI_PROVIDER_NAME instead of GEN_AI_SYSTEM for metric recording (lines ~199, ~221, ~354, ~377). Also update tests/unit/test_metrics.py and tests/integration/test_metrics_integration.py to assert gen_ai.provider.name on metric dimensions.
- [ ] T002 [P] Add tool-related mock types to tests/unit/conftest.py — add dataclass MockPreToolUseHookInput (fields: tool_name str, tool_input dict, session_id str|None), MockPostToolUseHookInput (fields: tool_name str, tool_input dict, tool_response str|dict, session_id str|None), MockPostToolUseFailureHookInput (fields: tool_name str, tool_input dict, error str, is_interrupt bool, session_id str|None), MockHookContext (fields: signal Any|None = None). NOTE: tool_use_id is NOT a field on the hook input — it is the second positional parameter to the callback per the SDK signature: callback(input_data, tool_use_id, context). Tests must pass it as a separate argument.
- [ ] T003 [P] Add tool-tracing fixtures to tests/integration/conftest.py — integration tests use real SDK types (not mocks); add a fixture that creates ClaudeAgentOptions with tools configured (e.g., allowed_tools=["Bash"]) via make_cheap_options(); add a get_execute_tool_spans(exporter) helper that returns finished spans whose name starts with "execute_tool"; no mock hook input types needed — integration tests exercise the real hook pipeline

---

## Phase 2: User Story 2 — Tests (Write First — Must FAIL)

**Purpose**: TDD red phase. All tests written before any US2 implementation. Tests MUST fail (ImportError or assertion failure) until the corresponding implementation tasks complete.

**FR Coverage**: FR-011, FR-012, FR-013, FR-014, FR-020 (tool content), FR-021

> **NOTE: Write these tests FIRST per Constitution V (test-first / red-green-refactor). Tests MUST fail until the corresponding implementation tasks complete. Create minimal module stubs if needed so tests can be parsed by pytest.**

### Unit Tests

- [ ] T004 [P] [US2] Write unit tests for tool span creation helpers in tests/unit/test_tool_spans.py — test create_execute_tool_span() produces INTERNAL span with name "execute_tool {tool_name}"; test required attributes: gen_ai.operation.name = "execute_tool", gen_ai.tool.name, gen_ai.tool.call.id from tool_use_id, gen_ai.tool.type; test tool type derivation: "mcp__server__action" → "extension", "Bash" → "function", "Read" → "function"; test span is child of invoke_agent parent span; test set_tool_error_attributes() sets error.type and ERROR status on tool span
- [ ] T005 [US2] Write unit tests for PreToolUse hook callback in tests/unit/test_tool_hooks.py — test _on_pre_tool_use() starts an execute_tool span and stores it in InvocationContext.active_tool_spans keyed by tool_use_id; test span has correct attributes (gen_ai.tool.name, gen_ai.tool.call.id, gen_ai.operation.name, gen_ai.tool.type); test when capture_content=True: gen_ai.tool.call.arguments is set from tool_input (JSON-serialized); test when capture_content=False: gen_ai.tool.call.arguments is NOT set; test when InvocationContext is None (no active invocation): hook returns {} without error
- [ ] T006 [US2] Write unit tests for PostToolUse hook callback in tests/unit/test_tool_hooks.py — test _on_post_tool_use() ends the tool span from active_tool_spans using tool_use_id correlation; test span status remains OK (not explicitly set); test tool span is removed from active_tool_spans after ending; test when capture_content=True: gen_ai.tool.call.result is set from tool_response (JSON-serialized); test when capture_content=False: gen_ai.tool.call.result is NOT set; test when tool_use_id not found in active_tool_spans: hook returns {} without error (graceful degradation)
- [ ] T007 [US2] Write unit tests for PostToolUseFailure hook callback in tests/unit/test_tool_hooks.py — test _on_post_tool_use_failure() ends the tool span with error.type set to the raw error string from the hook input; test span status set to ERROR with error string as status description; test tool span is removed from active_tool_spans after ending; test when tool_use_id not found in active_tool_spans: hook returns {} without error
- [ ] T008 [US2] Write unit tests for tool span cleanup on crash in tests/unit/test_tool_hooks.py — test that when PreToolUse fires but no matching PostToolUse/PostToolUseFailure follows (simulated by not calling post hook), cleanup_unclosed_spans() ends the tool span with ERROR status (validates US1-provided mechanism works for US2 tool spans); test multiple unclosed tool spans are all cleaned up; test cleanup is idempotent
- [ ] T009 [US2] Write unit tests for build_instrumentation_hooks() update in tests/unit/test_tool_hooks.py — test build_instrumentation_hooks(tracer, capture_content) returns dict with PreToolUse, PostToolUse, PostToolUseFailure keys (in addition to existing Stop key); test build_instrumentation_hooks() with no args returns only Stop (backward compat); test each key maps to a list containing the corresponding hook callback; test hook merge with user hooks: user PreToolUse hooks execute before instrumentation PreToolUse hooks
- [ ] T010 [US2] Write unit tests for tool_use_id correlation in tests/unit/test_tool_hooks.py — test that when two concurrent tool calls are in flight (tool_use_id "abc" and "def"), PreToolUse/PostToolUse correctly correlate by tool_use_id; test that ending tool "abc" does not affect tool "def"; test that tool span durations accurately reflect time between PreToolUse and PostToolUse (not wall clock from invocation start); test edge case: PostToolUse arrives with unknown tool_use_id that has no matching PreToolUse — verify graceful degradation (return {}, no span ended, no error raised)

### Integration Test

- [ ] T011 [US2] Write integration test for end-to-end tool tracing in tests/integration/test_tool_tracing.py — test full flow: instrument() → query() with tools → PreToolUse hook fires → PostToolUse hook fires → verify execute_tool span appears as child of invoke_agent span in exported spans; test span attributes match GenAI semconv (gen_ai.tool.name, gen_ai.tool.call.id, gen_ai.operation.name = "execute_tool", gen_ai.tool.type); test tool failure flow: PreToolUse → PostToolUseFailure → verify tool span has ERROR status and error.type; test content capture enabled: verify gen_ai.tool.call.arguments and gen_ai.tool.call.result appear; test content capture disabled (default): verify no content attributes; test multiple tool calls in single invocation produce multiple execute_tool child spans; test uncorrelated tool span (PreToolUse with no matching Post) is cleaned up with ERROR at invocation end

---

## Phase 3: User Story 2 — Implementation (Make Tests PASS)

**Purpose**: TDD green phase. Implement code to make all US2 tests pass.

### Implementation

- [ ] T012 [P] [US2] Implement tool span creation helpers in src/opentelemetry/instrumentation/claude_agent_sdk/_spans.py — add function create_execute_tool_span(tracer, tool_name, tool_use_id) that creates an INTERNAL span named "execute_tool {tool_name}" with attributes: gen_ai.operation.name = "execute_tool", gen_ai.tool.name = tool_name, gen_ai.tool.call.id = tool_use_id, gen_ai.tool.type = derive_tool_type(tool_name). No parent_context param needed — OTel auto-parents via the active context (invoke_agent span is already current when hooks fire). Add function derive_tool_type(tool_name) that returns "extension" if tool_name starts with "mcp__" else "function". Add function set_tool_error_attributes(span, error_message: str) that sets error.type to the raw error string and span status to ERROR with the error string as description
- [ ] T013 [P] [US2] Implement tool hook callbacks in src/opentelemetry/instrumentation/claude_agent_sdk/_hooks.py — all callbacks use `async def` to match the SDK's `Callable[..., Awaitable[HookJSONOutput]]` type. Hook callbacks receive tracer and capture_content via the closure created by build_instrumentation_hooks(tracer, capture_content) — they do NOT read tracer from InvocationContext. Add async _on_pre_tool_use(input_data, tool_use_id, context) that: retrieves InvocationContext from ContextVar, creates execute_tool span via create_execute_tool_span(tracer, tool_name, tool_use_id) where tracer comes from the closure, stores span in ctx.active_tool_spans[tool_use_id], if capture_content (from closure): sets gen_ai.tool.call.arguments from input_data["tool_input"] (JSON-serialized via json.dumps), returns {}; add async _on_post_tool_use(input_data, tool_use_id, context) that: retrieves InvocationContext, pops span from ctx.active_tool_spans[tool_use_id], if capture_content: sets gen_ai.tool.call.result from input_data["tool_response"] (JSON-serialized), ends span, returns {}; add async _on_post_tool_use_failure(input_data, tool_use_id, context) that: retrieves InvocationContext, pops span from ctx.active_tool_spans[tool_use_id], sets error.type to the raw error string from input_data["error"], sets span status to ERROR with error string as description, ends span, returns {}; all callbacks must gracefully handle missing InvocationContext or missing tool_use_id (return {} without error). Also update existing _on_stop to `async def` for consistency
- [ ] T014 [US2] Update build_instrumentation_hooks() in src/opentelemetry/instrumentation/claude_agent_sdk/_hooks.py — change signature to build_instrumentation_hooks(tracer=None, capture_content=False) with optional params and defaults. When tracer is None: return only Stop hook (preserves US1 backward compatibility, no breaking changes). When tracer is provided: return Stop + PreToolUse, PostToolUse, PostToolUseFailure entries, each mapping to a list containing the closure-captured callback. This ensures existing US1 call sites that pass no args continue to work unchanged.
- [ ] T015 [US2] Update instrumentor to pass tracer/capture_content to hook builder in src/opentelemetry/instrumentation/claude_agent_sdk/_instrumentor.py — update calls to build_instrumentation_hooks() in _instrumented_query and _wrap_client_init to pass self._tracer and self._capture_content; get_instrumentation_hooks() continues to work without instrument() being called first (build_instrumentation_hooks() with no args returns only Stop, which is valid). FR-025 traceability: verify that the existing cleanup_unclosed_spans() calls in the finally blocks of _instrumented_query() and _instrumented_receive_response() correctly end US2's tool spans — no code change expected since the mechanism is already in place from US1, but confirm it works for active_tool_spans populated by the new PreToolUse hooks.
- [ ] T016 Run full CI validation: make ci (lint + format-check + type-check + security + test-coverage) and ensure all checks pass with >= 80% coverage on new code

**Checkpoint**: User Story 2 is fully functional and testable. All tests pass (green). Tool calls during Claude invocations produce `execute_tool` child spans with correct attributes, correlation, and error handling.

---

## Phase 4: Polish & Cross-Cutting Concerns

**Purpose**: Final validation and cleanup for US2

- [ ] T017 [P] Validate tool tracing against spec acceptance scenarios — verify each of the 5 acceptance scenarios from spec.md US2 is covered by tests: (1) PreToolUse creates span with correct attributes, (2) PostToolUse ends span with OK, (3) PostToolUseFailure ends span with ERROR, (4) content capture enabled records arguments/results, (5) content capture disabled omits arguments/results
- [ ] T018 [P] Validate FR coverage — verify FR-011 (PreToolUse/PostToolUse/PostToolUseFailure hooks registered), FR-012 (tool_use_id correlation), FR-013 (tool span attributes), FR-014 (PostToolUseFailure error handling), FR-020 (tool content capture), FR-021 (content capture gated by flag) are all implemented and tested
- [ ] T019 Update quickstart.md expected trace structure if needed — verify the tool span section in specs/001-otel-genai-semconv/quickstart.md matches the actual span names and attributes produced

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies beyond US1 completion — can start immediately
- **US2 Tests (Phase 2)**: Depends on Phase 1 completion (constants and mocks exist). Tests are written first and MUST FAIL.
- **US2 Implementation (Phase 3)**: Depends on Phase 2 (tests exist and fail). Implementation makes tests pass.
- **Polish (Phase 4)**: Depends on Phase 3 completion (all tests green).

### Task Dependencies (Within Phases)

```
Phase 1 — all can run in parallel:
T001 (constants) | T002 (unit conftest) | T003 (integration conftest)
                          │
                          ▼
Phase 2 — Tests (write first, must FAIL):
┌─────────────────────────────────────────────────────────┐
│ T004 (test_tool_spans.py)      [P] — separate file      │
│ T005-T010 (test_tool_hooks.py) — sequential, same file  │
│   T005 (PreToolUse)                                     │
│   T006 (PostToolUse)                                    │
│   T007 (PostToolUseFailure)                             │
│   T008 (crash cleanup)                                  │
│   T009 (build_hooks update)                             │
│   T010 (tool_use_id correlation)                        │
└─────────────────────────────────────────────────────────┘
         │
         ▼
T011 (integration test) — depends on unit test patterns being established
         │
         ▼
Phase 3 — Implementation (make tests PASS):
┌─────────────────────────────────────────────────────────┐
│ T012 (tool span helpers) ──┐                            │
│                             ├──► T014 (build_hooks)     │
│ T013 (hook callbacks) ─────┘         │                  │
│                                      ▼                  │
│                              T015 (instrumentor update) │
└─────────────────────────────────────────────────────────┘
         │
         ▼
  T016 (CI validation)
         │
         ▼
  T017-T019 (polish, can run in parallel)
```

### Within User Story 2

1. **Constants + mocks first** (T001-T003): Setup phase
2. **Tests next** (T004-T011): Write all tests; they MUST fail (red phase)
3. Span helpers (T012) and hook callbacks (T013) can run in parallel — different files
4. Hook builder update (T014) depends on T012 + T013
5. Instrumentor update (T015) depends on T014
6. CI validation (T016) confirms everything passes
7. Polish (T017-T019) validates against spec

### Parallel Opportunities

```bash
# Phase 1 — all can run in parallel:
T001 (constants) | T002 (unit conftest) | T003 (integration conftest)

# Phase 2 — T004 runs in parallel with T005-T010 (different files):
T004 (test_tool_spans.py) | T005→T006→T007→T008→T009→T010 (test_tool_hooks.py — sequential, same file)
# T011 (integration) can run in parallel with unit tests

# Phase 3 — span helpers and hook callbacks in parallel:
T012 (tool span helpers) | T013 (hook callbacks)
# T014-T015 are sequential (depend on T012+T013)

# Phase 4 — polish can run in parallel:
T017 | T018 | T019
```

---

## Implementation Strategy

### Incremental Delivery

1. Complete Phase 1: Setup (T001-T003) — constants and mocks
2. Complete Phase 2: Tests (T004-T011) — write all tests, verify they FAIL (red)
3. Complete Phase 3: Implementation (T012-T015) — write code to make tests PASS (green)
4. Complete Phase 3: CI (T016) — run `make ci` to confirm all checks pass
5. Complete Phase 4: Polish (T017-T019) — validate against spec artifacts
6. **STOP and VALIDATE**: Full CI green, US2 independently functional, US1 not broken

### What US2 Delivers

- `execute_tool {tool_name}` INTERNAL child spans for every tool call
- PreToolUse/PostToolUse/PostToolUseFailure hook callbacks
- tool_use_id correlation for accurate tool execution duration
- gen_ai.tool.name, gen_ai.tool.call.id, gen_ai.tool.type attributes
- Tool type derivation (mcp__* → "extension", others → "function")
- Opt-in content capture: gen_ai.tool.call.arguments and gen_ai.tool.call.result
- Error handling: PostToolUseFailure sets error.type and ERROR status
- Crash cleanup: unclosed tool spans ended with ERROR at invocation finalization
- Integration test proving end-to-end tool tracing flow

### What US2 Does NOT Deliver (Deferred)

- Subagent lifecycle tracing (US4 — SubagentStart/SubagentStop hooks)
- Content capture for agent-level attributes (US6 — gen_ai.system_instructions, gen_ai.input.messages, gen_ai.output.messages)
- Metric-specific dashboard scenarios (US3)

### Key Design Decisions

- **Hook callbacks access tracer via closure**: `build_instrumentation_hooks(tracer, capture_content)` creates closures that capture the tracer and capture_content, avoiding global state
- **Tool type derivation is best-effort**: Uses prefix matching (mcp__* → extension), defaults to "function" per data-model.md
- **JSON serialization for tool arguments/results**: `json.dumps()` for content capture attributes, matching the GenAI semconv expectation of string-typed attributes
- **Graceful degradation**: All hook callbacks handle missing InvocationContext or missing tool_use_id without raising exceptions

---

## Summary

| Metric | Value |
|--------|-------|
| Total tasks | 19 |
| Setup tasks | 3 (T001-T003) |
| US2 unit test tasks | 7 (T004-T010) |
| US2 integration test tasks | 1 (T011) |
| US2 implementation tasks | 4 (T012-T015) |
| CI validation | 1 (T016) |
| Polish tasks | 3 (T017-T019) |
| Max parallelism (Phase 1) | 3 tasks |
| Max parallelism (Phase 2) | 2 tracks (T004 ∥ T005-T010 block + T011) |
| Max parallelism (Phase 3) | 2 tasks (T012 ∥ T013) |
| FR coverage | FR-011, FR-012, FR-013, FR-014, FR-019 (bug fix), FR-020 (tool content), FR-021 |

---

## Notes

- [P] tasks = different files, no dependencies on each other
- [US2] label maps task to User Story 2 for traceability
- All SDK hook input types in tests use mock dataclasses from conftest.py — no network access required
- Tests are written FIRST and must FAIL before implementation begins (Constitution V)
- The `_hooks.py` module gains three new `async def` callbacks (_on_pre_tool_use, _on_post_tool_use, _on_post_tool_use_failure) and existing _on_stop is updated to `async def` for consistency. `build_instrumentation_hooks()` signature changes to `build_instrumentation_hooks(tracer=None, capture_content=False)` — optional params preserve backward compatibility
- T005-T010 all live in the same test file (test_tool_hooks.py) and are sequential (NOT parallel). T004 is in a separate file and CAN run in parallel with T005-T010
- T004 is in a separate file (test_tool_spans.py) and is fully independent
- Content capture for tool arguments/results uses json.dumps() for serialization
- The integration test (T011) uses the in-memory OTel exporter from conftest.py to verify span hierarchy and attributes end-to-end
- US2 modifies _constants.py, _spans.py, _hooks.py, and _instrumentor.py — all files that exist from US1
- Commit after each task or logical group
- Hook callbacks access tracer via closure (not InvocationContext or module-level ref)
- tool_use_id is a callback parameter, not a field on hook input dataclasses
- error.type for tool failures uses the raw error string from the hook input
- build_instrumentation_hooks() uses optional params (tracer=None, capture_content=False) for backward compat

---

## Remediations Applied

| ID | Severity | Change |
|----|----------|--------|
| C1 | CRITICAL | Removed tool_use_id from mock hook input dataclasses in T002; it is a callback parameter, not an input field |
| C2 | CRITICAL | Added FR-025 traceability note to T015; verify existing cleanup_unclosed_spans() works for US2 tool spans |
| H1 | HIGH | Changed T014: build_instrumentation_hooks(tracer=None, capture_content=False) with optional params; no breaking changes to US1 call sites |
| H2 | HIGH | Fixed T013: hook callbacks receive tracer via closure from build_instrumentation_hooks(), not from InvocationContext |
| H3 | HIGH | Removed [P] markers from T005-T010 (same file test_tool_hooks.py); T004 remains [P] (separate file) |
| H4 | HIGH | Added PostToolUse-with-unknown-tool_use_id edge case test to T010 |
| M1 | MEDIUM | Changed T013: all hook callbacks use `async def` to match SDK type hint; update _on_stop to async for consistency |
| M2 | MEDIUM | Removed parent_context param from create_execute_tool_span() in T012; OTel auto-parents via active context |
| M3 | MEDIUM | Specified in T012/T013/T007: error.type set to raw error string from hook input |
| M4 | MEDIUM | Kept minimal mock fields (only what callbacks read); no BaseHookInput extras added |
| L2 | LOW | Removed [US2] label from T016 (CI validation task, not story task) |
| L3 | LOW | Clarified T003: integration tests use real SDK types, not mocks; added get_execute_tool_spans() helper |
