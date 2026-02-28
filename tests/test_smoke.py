"""Smoke tests to verify the package is importable and correctly configured."""


def test_import_succeeds():
    from opentelemetry.instrumentation.claude_agent_sdk import __version__

    assert __version__ is not None


def test_version_is_string():
    from opentelemetry.instrumentation.claude_agent_sdk import __version__

    assert isinstance(__version__, str)
    assert len(__version__) > 0
