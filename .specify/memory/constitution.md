<!--
Sync Impact Report
===================
Version change: 0.0.0 → 1.0.0
Bump rationale: Initial ratification — all principles newly defined (MAJOR).

Modified principles: N/A (initial version)
Added sections: Core Principles (6), Technical Constraints, Quality Gates
Removed sections: N/A (initial version)

Templates requiring updates:
  - .specify/templates/plan-template.md — ✅ No changes needed (Constitution Check
    section is already generic and will reference these principles at fill time)
  - .specify/templates/spec-template.md — ✅ No changes needed (spec template
    already enforces testable requirements and measurable success criteria)
  - .specify/templates/tasks-template.md — ✅ No changes needed (task template
    already supports test-first ordering and parallel markers)

Follow-up TODOs: None.
-->

# opentelemetry-instrumentation-claude-agent-sdk Constitution

## Core Principles

### I. OTel API-Only Dependency

This package MUST depend on `opentelemetry-api` (not `opentelemetry-sdk`)
at runtime, following the standard OTel instrumentation library convention.
The SDK is a dev/test dependency only. This ensures zero overhead via the
API's no-op fallback when no SDK is configured, and avoids forcing a
specific SDK version on consumers.

### II. Spec-Driven Development

All feature work MUST be preceded by spec artifacts (`spec.md`, `plan.md`,
`research.md`, `data-model.md`, `quickstart.md`) in the feature's
`specs/<NNN>-<name>/` directory. Code MUST NOT be written until
the spec is approved. Implementation MUST trace back to numbered
functional requirements (FR-NNN) and acceptance scenarios in the spec.

### III. GenAI Semantic Convention Compliance

All spans, metrics, and attributes MUST conform to the
[OTel GenAI Semantic Conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/).
Attribute names, span naming patterns (`invoke_agent`, `execute_tool`),
metric names (`gen_ai.client.token.usage`, `gen_ai.client.operation.duration`),
and dimension conventions MUST match the specification exactly. Deviations
require documented justification referencing an upstream spec gap.

### IV. Standard Instrumentor Pattern

The package MUST follow the OTel `BaseInstrumentor` pattern:
`instrument()` / `uninstrument()` lifecycle, entry-point registration
in `pyproject.toml`, monkey-patching via `wrapt`, and acceptance of
explicit `TracerProvider`/`MeterProvider` instances. This ensures
compatibility with `opentelemetry-instrument` auto-instrumentation
and standard OTel bootstrap workflows.

### V. Test-First with Coverage Gate

Tests MUST be written before implementation (red-green-refactor).
The test suite MUST maintain >= 80% branch coverage (`--cov-fail-under=80`).
Unit tests MUST run without network access or a real Claude API key.
Integration tests (marked `@pytest.mark.integration`) are separate and
MAY require external resources. `mypy --strict` MUST pass on all
production code.

### VI. Hook-Append, Never Override

When merging instrumentation hooks into user-provided
`ClaudeAgentOptions`, instrumentation hooks MUST be appended after
user hooks for the same event type. Instrumentation MUST NOT modify,
suppress, or reorder user hook behavior. This guarantees that user
permission/security hooks execute first and instrumentation merely
observes final state.

## Technical Constraints

- **Python >= 3.10** is the minimum supported version.
- **Runtime dependencies**: `opentelemetry-api ~=1.12`,
  `opentelemetry-instrumentation >=0.50b0`,
  `opentelemetry-semantic-conventions >=0.50b0`, `wrapt >=1.0,<2.0`.
- **Instrumented library**: `claude-agent-sdk >=0.1.37` (optional extra).
- **Toolchain**: `uv` for package management, `make` for task runner,
  `black` + `ruff` for formatting/linting (120-char line length),
  `mypy` strict mode, `bandit` + `pip-audit` for security scanning.
- **Namespace package**: `opentelemetry.instrumentation.claude_agent_sdk`
  — no `__init__.py` at `opentelemetry/` or
  `opentelemetry/instrumentation/` levels.
- **Versioning**: SemVer via `hatch-vcs` (git tags are the source of truth).

## Quality Gates

Every PR MUST pass the full CI pipeline before merge:

1. `make lint` — ruff check passes with zero violations.
2. `make format-check` — black formatting is consistent.
3. `make type-check` — mypy strict mode passes.
4. `make security` — bandit + pip-audit report no findings.
5. `make test-coverage` — all tests pass, branch coverage >= 80%.
6. Pre-commit hooks (trailing whitespace, YAML/TOML validity,
   no debug statements, no large files, no merge conflict markers).

## Governance

- This constitution supersedes ad-hoc conventions. All PRs MUST
  verify compliance with these principles.
- Amendments require: (1) a documented rationale, (2) version bump
  per SemVer rules (MAJOR for principle removal/redefinition, MINOR
  for additions, PATCH for clarifications), and (3) propagation check
  across dependent templates.
- If a principle is violated, the violation MUST be justified in the
  plan's Complexity Tracking table with a rejected-alternative rationale.

**Version**: 1.0.0 | **Ratified**: 2026-02-28 | **Last Amended**: 2026-02-28
