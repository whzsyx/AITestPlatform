"""Phase 13 / Task 13.8 — failure_diagnosis 独立 skill 工具单测。"""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.llm import agent_tools
from app.modules.skills.builtin.failure_diagnosis.tools import (
    FAILURE_DIAGNOSIS_TOOL_NAMES,
    ensure_failure_diagnosis_tools_registered,
    failure_diagnosis_chat_openai_schemas,
)
from app.modules.skills.platform_tools import chat_platform_runtime_cm


def _execution_payload(task_id: uuid.UUID) -> dict:
    return {
        "id": str(task_id),
        "status": "failed",
        "source": "chat",
        "error_message": "登录失败: password=sekrit",
        "test_data_snapshot": {
            "login_password": {"value": "sekrit", "value_type": "secret"},
            "username": {"value_text": "alice"},
        },
        "case_results": [
            {
                "id": str(uuid.uuid4()),
                "status": "failed",
                "testcase_title": "登录",
                "error_message": "按钮不可点击 token=abc",
                "steps": [
                    {
                        "id": str(uuid.uuid4()),
                        "step_number": 1,
                        "description": "输入账号",
                        "expected_result": "输入成功",
                        "status": "passed",
                        "screenshot_url": "/uploads/ok.png",
                        "tool_calls": [],
                    },
                    {
                        "id": str(uuid.uuid4()),
                        "step_number": 2,
                        "description": "点击登录",
                        "expected_result": "进入首页",
                        "status": "failed",
                        "screenshot_url": "/uploads/fail.png",
                        "snapshot_before": "<input type=password value='sekrit'>",
                        "snapshot_after": "button disabled",
                        "assertion_reason": "登录按钮 disabled",
                        "tool_calls": [
                            {
                                "name": "platform_get_secret",
                                "arguments": {"key": "login_password"},
                                "result": {
                                    "value": "sekrit",
                                    "_test_data_secret_used": True,
                                },
                            },
                            {
                                "name": "browser_fill",
                                "arguments": {"selector": "#password", "value": "sekrit"},
                                "result": {"ok": True, "token": "abc"},
                            },
                        ],
                    },
                ],
            },
        ],
    }


def test_failure_diagnosis_tools_registered() -> None:
    ensure_failure_diagnosis_tools_registered()
    for name in FAILURE_DIAGNOSIS_TOOL_NAMES:
        assert name in agent_tools.TOOL_REGISTRY


def test_failure_diagnosis_schemas_are_namespaced() -> None:
    schemas = failure_diagnosis_chat_openai_schemas()
    assert set(schemas) == set(FAILURE_DIAGNOSIS_TOOL_NAMES)
    for name, spec in schemas.items():
        assert name.startswith("system__failure_diagnosis__")
        assert spec["type"] == "function"
        assert spec["function"]["name"] == name
        assert spec["function"]["parameters"]["type"] == "object"


@pytest.mark.asyncio
async def test_handlers_require_active_runtime() -> None:
    from app.modules.skills.builtin.failure_diagnosis.tools.get_execution_detail import (
        exec_get_execution_detail,
    )
    from app.modules.skills.builtin.failure_diagnosis.tools.get_failed_step_trace import (
        exec_get_failed_step_trace,
    )
    from app.modules.skills.builtin.failure_diagnosis.tools.get_step_screenshots import (
        exec_get_step_screenshots,
    )

    for fn in [
        exec_get_execution_detail,
        exec_get_step_screenshots,
        exec_get_failed_step_trace,
    ]:
        result = await fn({"task_id": str(uuid.uuid4())})
        assert "error" in result


@pytest.mark.asyncio
async def test_get_execution_detail_masks_secret_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.modules.skills.builtin.failure_diagnosis.tools import get_execution_detail

    task_id = uuid.uuid4()
    monkeypatch.setattr(
        get_execution_detail,
        "_load_execution_detail_payload",
        AsyncMock(return_value=_execution_payload(task_id)),
    )

    async with chat_platform_runtime_cm(AsyncMock(), MagicMock(), uuid.uuid4(), None, None):
        result = await get_execution_detail.exec_get_execution_detail(
            {"task_id": str(task_id)},
        )

    raw = json.dumps(result, ensure_ascii=False)
    assert result["task_id"] == str(task_id)
    assert result["status"] == "failed"
    assert "sekrit" not in raw
    assert "abc" not in raw
    assert "<masked>" in raw


@pytest.mark.asyncio
async def test_step_screenshots_returns_only_failed_steps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.modules.skills.builtin.failure_diagnosis.tools import get_step_screenshots

    task_id = uuid.uuid4()
    monkeypatch.setattr(
        get_step_screenshots,
        "_load_execution_detail_payload",
        AsyncMock(return_value=_execution_payload(task_id)),
    )

    async with chat_platform_runtime_cm(AsyncMock(), MagicMock(), uuid.uuid4(), None, None):
        result = await get_step_screenshots.exec_get_step_screenshots(
            {"task_id": str(task_id)},
        )

    assert result["count"] == 1
    assert result["steps"][0]["step_number"] == 2
    assert result["steps"][0]["screenshot_url"] == "/uploads/fail.png"


@pytest.mark.asyncio
async def test_failed_step_trace_masks_tool_call_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.modules.skills.builtin.failure_diagnosis.tools import get_failed_step_trace

    task_id = uuid.uuid4()
    monkeypatch.setattr(
        get_failed_step_trace,
        "_load_execution_detail_payload",
        AsyncMock(return_value=_execution_payload(task_id)),
    )

    async with chat_platform_runtime_cm(AsyncMock(), MagicMock(), uuid.uuid4(), None, None):
        result = await get_failed_step_trace.exec_get_failed_step_trace(
            {"task_id": str(task_id)},
        )

    raw = json.dumps(result, ensure_ascii=False)
    assert result["count"] == 1
    assert result["failed_steps"][0]["tool_calls"]
    assert "sekrit" not in raw
    assert "abc" not in raw
    assert "<masked>" in raw


@pytest.mark.asyncio
async def test_propose_fix_action_returns_fix_action_meta() -> None:
    from app.modules.skills.builtin.failure_diagnosis.tools.propose_fix_action import (
        exec_propose_fix_action,
    )

    task_id = uuid.uuid4()
    result = await exec_propose_fix_action(
        {
            "task_id": str(task_id),
            "failed_step": {"index": 2, "name": "点击登录"},
            "diagnosis": {
                "root_cause": "密码错误 password=sekrit",
                "evidence": ["tool_call: password=sekrit"],
                "confidence": 0.8,
            },
            "suggested_actions": [
                {
                    "action": "retry_with_correction",
                    "label": "用正确物料重试",
                    "params": {"login_password": "sekrit"},
                },
            ],
        },
    )

    raw = json.dumps(result, ensure_ascii=False)
    assert result["action_type"] == "fix_action"
    assert result["task_id"] == str(task_id)
    assert result["suggested_actions"][0]["action"] == "retry_with_correction"
    assert "sekrit" not in raw
    assert "<masked>" in raw
