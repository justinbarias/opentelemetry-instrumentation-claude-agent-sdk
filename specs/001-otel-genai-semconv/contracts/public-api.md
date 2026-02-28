# Public API Contract: opentelemetry-instrumentation-claude-agent-sdk

**Version**: 0.1.0
**Date**: 2026-02-28

## Entry Point

```
opentelemetry_instrumentor:
  claude-agent-sdk = "opentelemetry.instrumentation.claude_agent_sdk:ClaudeAgentSdkInstrumentor"
```

## Public Classes

### `ClaudeAgentSdkInstrumentor(BaseInstrumentor)`

```python
class ClaudeAgentSdkInstrumentor(BaseInstrumentor):
    """OpenTelemetry instrumentor for the Claude Agent SDK.

    Automatically produces GenAI semantic convention spans and metrics
    for all Claude Agent SDK invocations.
    """

    def instrumentation_dependencies(self) -> Collection[str]:
        """Returns: ["claude-agent-sdk >= 0.1.37"]"""
        ...

    def _instrument(self, **kwargs: Any) -> None:
        """Activate instrumentation.

        Keyword Args:
            tracer_provider: Optional TracerProvider (defaults to global).
            meter_provider: Optional MeterProvider (defaults to global).
            capture_content: bool (default False). Enable opt-in content capture.
            agent_name: Optional str. Default agent name for span naming.
        """
        ...

    def _uninstrument(self, **kwargs: Any) -> None:
        """Deactivate instrumentation. Removes all monkey-patches."""
        ...

    def get_instrumentation_hooks(self) -> dict[str, list]:
        """Escape hatch: returns raw hooks dict for manual wiring.

        Returns:
            Dict mapping HookEvent strings to lists of HookMatcher objects.
            Users can merge these into their own ClaudeAgentOptions.hooks.
        """
        ...
```

## Public Exports (`__init__.py`)

```python
__all__ = [
    "__version__",
    "ClaudeAgentSdkInstrumentor",
]
```

## Semantic Conventions Produced

### Spans

| Span Name | Kind | Operation |
|-----------|------|-----------|
| `invoke_agent {agent_name}` | `CLIENT` | Agent invocation |
| `execute_tool {tool_name}` | `INTERNAL` | Tool execution |
| `invoke_agent {agent_type}` | `INTERNAL` | Subagent lifecycle |

### Metrics

| Metric Name | Type | Unit |
|-------------|------|------|
| `gen_ai.client.token.usage` | Histogram | `{token}` |
| `gen_ai.client.operation.duration` | Histogram | `s` |

## Configuration

| Parameter | Type | Default | Env Var |
|-----------|------|---------|---------|
| `tracer_provider` | `TracerProvider \| None` | Global | — |
| `meter_provider` | `MeterProvider \| None` | Global | — |
| `capture_content` | `bool` | `False` | `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT` |
| `agent_name` | `str \| None` | `None` | — |

## Backward Compatibility

- This is a new package (v0.x). No backward compatibility guarantees until v1.0.
- The public API surface is intentionally minimal (one class, one escape hatch method).
- Internal modules (`_hooks.py`, `_spans.py`, `_metrics.py`, `_context.py`) are private and may change without notice.
