"""Task 12.2 — safe_run_tool 第二道闸。"""

from __future__ import annotations

import json
import uuid

import pytest

from app.modules.skills import safe_invoke


@pytest.mark.asyncio
async def test_platform_denied_without_system_skill() -> None:
    raw = await safe_invoke.safe_run_tool(
        AsyncMockSession(),
        "platform_run_ui_execution",
        "{}",
        active_system_skill_slugs=set(),
        skill_id_by_tool_name={},
        allowed_platform_tools=frozenset({"platform_run_ui_execution"}),
        session_id=None,
        project_id=uuid.uuid4(),
    )
    data = json.loads(raw)
    assert "error" in data


@pytest.mark.asyncio
async def test_platform_denied_when_not_in_tools_required() -> None:
    raw = await safe_invoke.safe_run_tool(
        AsyncMockSession(),
        "platform_run_ui_execution",
        "{}",
        active_system_skill_slugs={"system_x"},
        skill_id_by_tool_name={},
        allowed_platform_tools=frozenset({"platform_search_testcases"}),
        session_id=None,
        project_id=uuid.uuid4(),
    )
    data = json.loads(raw)
    assert "error" in data


@pytest.mark.asyncio
async def test_web_search_unaffected(monkeypatch: pytest.MonkeyPatch) -> None:
    called: dict[str, bool] = {}

    async def fake_run_tool(name: str, arguments_json: str) -> str:
        called["name"] = name
        assert name == "web_search"
        return '{"ok":true}'

    monkeypatch.setattr(safe_invoke, "run_tool", fake_run_tool)

    raw = await safe_invoke.safe_run_tool(
        AsyncMockSession(),
        "web_search",
        '{"query":"ping"}',
        active_system_skill_slugs=set(),
        skill_id_by_tool_name={},
        allowed_platform_tools=frozenset(),
        session_id=None,
        project_id=None,
    )
    assert json.loads(raw) == {"ok": True}
    assert called["name"] == "web_search"


class AsyncMockSession:
    """最小占位（safe_run_tool 在 skill/web_search 分支可能不用 db）。"""

    async def execute(self, *_args, **_kwargs):  # pragma: no cover
        raise NotImplementedError


@pytest.mark.asyncio
async def test_skill_invoke_unknown_tool_returns_error() -> None:
    raw = await safe_invoke.safe_run_tool(
        AsyncMockSession(),
        "skill_nope__invoke",
        "{}",
        active_system_skill_slugs=set(),
        skill_id_by_tool_name={},
        allowed_platform_tools=frozenset(),
        session_id=None,
        project_id=None,
    )
    assert "unknown skill" in json.loads(raw)["error"]


@pytest.mark.asyncio
async def test_failure_diagnosis_system_tool_requires_active_slug(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_run_tool(name: str, arguments_json: str) -> str:
        return json.dumps({"called": name, "args": arguments_json})

    monkeypatch.setattr(safe_invoke, "run_tool", fake_run_tool)

    denied = await safe_invoke.safe_run_tool(
        AsyncMockSession(),
        "system__failure_diagnosis__get_execution_detail",
        "{}",
        active_system_skill_slugs=set(),
        skill_id_by_tool_name={},
        allowed_platform_tools=frozenset(),
        session_id=None,
        project_id=uuid.uuid4(),
    )
    assert "system_failure_diagnosis" in json.loads(denied)["error"]

    allowed = await safe_invoke.safe_run_tool(
        AsyncMockSession(),
        "system__failure_diagnosis__get_execution_detail",
        '{"task_id":"x"}',
        active_system_skill_slugs={"system_failure_diagnosis"},
        skill_id_by_tool_name={},
        allowed_platform_tools=frozenset(),
        session_id=None,
        project_id=uuid.uuid4(),
    )
    assert json.loads(allowed)["called"] == "system__failure_diagnosis__get_execution_detail"
