from delfhos.errors import (
    AgentConfirmationError,
    ConnectionConfigurationError,
    ConnectionFileNotFoundError,
    DelfhosConfigError,
    EnvironmentKeyError,
    ModelConfigurationError,
    OptionalDependencyError,
    ToolDefinitionError,
    ToolExecutionError,
)


def test_error_message_includes_code_message_hint():
    exc = ToolExecutionError(tool_name="web_search", detail="network timeout")
    text = str(exc)

    assert "ERR-TOOL-001" in text
    assert "Delfhos Error" in text
    assert "Message:" in text
    assert "Hint:" in text
    assert "network timeout" in text
    assert "By default" in text
    assert "@tool(handle_error=True)" not in text


def test_error_manual_message_override():
    exc = DelfhosConfigError(message="Manual override message")
    text = str(exc)
    assert "Manual override message" in text


def test_template_formatting_is_resilient_when_kwargs_missing():
    # No model_name provided on purpose.
    exc = ModelConfigurationError()
    text = str(exc)

    assert "Internal error formatting 'ModelConfigurationError'" in text
    assert "missing template key 'model_name'" in text


def test_error_compatibility_inheritance_for_existing_callers():
    assert issubclass(ToolDefinitionError, TypeError)
    assert issubclass(ConnectionConfigurationError, ValueError)
    assert issubclass(ConnectionFileNotFoundError, FileNotFoundError)


def test_error_codes_are_exposed_in_output():
    errors = [
        AgentConfirmationError(confirm="write"),
        EnvironmentKeyError(key="GEMINI_API_KEY"),
        OptionalDependencyError(package="openpyxl", detail="Needed for XLSX"),
    ]

    for err in errors:
        rendered = str(err)
        assert "ERR-" in rendered
        assert "Hint:" in rendered
