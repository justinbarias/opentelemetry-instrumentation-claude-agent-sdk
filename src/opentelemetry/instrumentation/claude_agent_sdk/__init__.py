"""OpenTelemetry instrumentation for the Anthropic Claude Agent SDK."""

from opentelemetry.instrumentation.claude_agent_sdk._instrumentor import ClaudeAgentSdkInstrumentor
from opentelemetry.instrumentation.claude_agent_sdk.version import __version__

__all__ = ["ClaudeAgentSdkInstrumentor", "__version__"]
