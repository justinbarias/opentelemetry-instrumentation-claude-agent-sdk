# opentelemetry-instrumentation-claude-agent-sdk

OpenTelemetry instrumentation for the [Anthropic Claude Agent SDK](https://github.com/anthropics/claude-agent-sdk).

This package provides automatic tracing for Claude Agent SDK operations following the [OpenTelemetry GenAI Semantic Conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/).

## Status

**Alpha** - Under active development.

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

### Common Commands

```bash
make help           # Show all available commands
make test           # Run tests
make test-coverage  # Run tests with coverage
make lint           # Run linter
make format         # Format code
make type-check     # Run mypy
make security       # Run security checks
make ci             # Full CI pipeline locally
make build          # Build distribution packages
```

### Project Structure

```
src/opentelemetry/instrumentation/claude_agent_sdk/
    __init__.py         # Package init
    version.py          # Dynamic version from package metadata
tests/
    test_smoke.py       # Smoke tests
```

## License

MIT
