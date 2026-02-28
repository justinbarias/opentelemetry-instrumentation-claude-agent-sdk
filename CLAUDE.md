# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

OpenTelemetry instrumentation library for the Anthropic Claude Agent SDK. This is a **standalone Python package** that auto-instruments Claude Agent SDK calls to produce GenAI semantic convention spans and metrics. The project is in early development (skeleton bootstrapped, implementation not yet started).

**Status**: Pre-implementation. The project follows a spec-driven development workflow (speckit). Always consult the spec artifacts before writing code.

## Spec-Driven Development (speckit)

This project uses speckit for structured feature development. Before implementing anything, read the relevant spec artifacts in the feature's `specs/` directory:

- `specs/<NNN>-<name>/spec.md` - Feature specification (requirements, acceptance criteria, edge cases)
- `specs/<NNN>-<name>/plan.md` - Implementation plan (technical approach, phases, architecture)
- `specs/<NNN>-<name>/research.md` - Research findings and technology decisions
- `specs/<NNN>-<name>/data-model.md` - Entity definitions, relationships, state transitions
- `specs/<NNN>-<name>/quickstart.md` - Quick-start guide for the feature

The active feature spec is at: `specs/001-otel-genai-semconv/spec.md`

Branch naming supports both `NNN-name` and `feature/NNN-name` patterns (e.g., `feature/001-claude-otel`).

## Build & Development Commands

All commands use `uv` as the package manager and are wrapped via `make`:

```bash
make init            # Full setup: install deps + pre-commit hooks
make install-dev     # Install with dev dependencies (uv sync --all-extras)
make test            # Run all tests
make test-unit       # Run unit tests only (excludes @integration marker)
make test-coverage   # Run tests with coverage (fails under 80%)
make lint            # Ruff linter
make lint-fix        # Ruff with auto-fix
make format          # Black + isort formatting
make type-check      # mypy (strict mode)
make security        # bandit + pip-audit
make ci              # Full local CI: lint + format-check + type-check + security + test-coverage
make ci-fast         # Quick check: lint + test only
```

Run a single test: `uv run pytest tests/test_smoke.py::test_import_succeeds -v`

## Package Structure

```
src/opentelemetry/instrumentation/claude_agent_sdk/
    __init__.py     # Package entry point (will contain ClaudeAgentSdkInstrumentor)
    version.py      # Dynamic version from package metadata
```

OTel namespace package: follows `opentelemetry.instrumentation.*` convention. The entry point is registered in `pyproject.toml` under `[project.entry-points.opentelemetry_instrumentor]`.

## Key Technical Constraints

- **Python >= 3.10** (target version for ruff, mypy, black)
- **Depends on `opentelemetry-api` only** (not `-sdk`), following OTel instrumentation library conventions
- `claude-agent-sdk` is an optional dependency (under `[instruments]` extra)
- Uses monkey-patching via the standard OTel `Instrumentor` pattern (`instrument()`/`uninstrument()`)
- Line length: 120 chars (black + ruff)
- mypy: strict mode enabled, namespace packages
- Coverage threshold: 80%
- asyncio_mode = "auto" in pytest (no need for `@pytest.mark.asyncio`)

## Pre-commit Hooks

Active hooks: trailing-whitespace, end-of-file-fixer, check-yaml, check-toml, check-added-large-files, check-merge-conflict, debug-statements, black, ruff (with auto-fix).

## Active Technologies
- Python >= 3.10 + `opentelemetry-api ~=1.12`, `opentelemetry-instrumentation >=0.50b0`, `opentelemetry-semantic-conventions >=0.50b0`, `wrapt >=1.0,<2.0` (feature/001-claude-otel)
- N/A (in-memory span/metric state only) (feature/001-claude-otel)

## Recent Changes
- feature/001-claude-otel: Added Python >= 3.10 + `opentelemetry-api ~=1.12`, `opentelemetry-instrumentation >=0.50b0`, `opentelemetry-semantic-conventions >=0.50b0`, `wrapt >=1.0,<2.0`
