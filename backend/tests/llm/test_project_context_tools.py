from __future__ import annotations

from app.modules.llm.project_context_tools import (
    PROJECT_SEARCH_CONTEXT_TOOL_NAME,
    _redact_context_value,
    is_project_context_tool,
    project_context_tool_schemas,
)


def test_project_context_tool_schema_available() -> None:
    schemas = project_context_tool_schemas()
    names = {s["function"]["name"] for s in schemas}
    assert PROJECT_SEARCH_CONTEXT_TOOL_NAME in names
    spec = schemas[0]["function"]
    assert "当前项目" in spec["description"]
    assert "requirements" in spec["parameters"]["properties"]["scopes"]["items"]["enum"]
    assert "test_data" in spec["parameters"]["properties"]["scopes"]["items"]["enum"]


def test_is_project_context_tool() -> None:
    assert is_project_context_tool(PROJECT_SEARCH_CONTEXT_TOOL_NAME) is True
    assert is_project_context_tool("web_search") is False


def test_project_context_redacts_secret_values() -> None:
    assert _redact_context_value("secret", "abc123") == "<masked>"
    assert _redact_context_value("string", "normal") == "normal"
