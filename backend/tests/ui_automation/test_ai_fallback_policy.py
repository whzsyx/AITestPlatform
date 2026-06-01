from __future__ import annotations

import json
import logging
import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.modules.ui_automation.execution_engine import (
    EngineDeps,
    ExecutionEngine,
    ExecutionInputs,
)
from app.modules.ui_automation.security import TokenBudget
from app.modules.ui_automation.step_runner import (
    ChatRound,
    StepRunner,
    ToolCallEmit,
)
from tests.ui_automation.test_engine import (
    _FakePersistence,
    _FakeSessionContext,
    _FakeStepRunner,
    _FakeStreamHub,
    _make_llm_config_stub,
    _make_resolver_stub,
    _patch_db_loaders,
    _patch_resolver,
    _Step,
    _step_run_ok,
    _Testcase,
)


def _env(*, enable_browser_evaluate: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        base_url="https://app.example.com",
        allowed_hosts=["app.example.com"],
        token_budget=50_000,
        enable_browser_evaluate=enable_browser_evaluate,
    )


def _llm() -> SimpleNamespace:
    return SimpleNamespace(
        provider="openai",
        model="gpt-4o-mini",
        temperature=0.0,
        max_tokens=2048,
        base_url=None,
        api_key="sk-test",
    )


def _tool_spec(name: str) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": name,
            "parameters": {"type": "object", "properties": {}},
        },
    }


class _CountingToolRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def __call__(self, name: str, args_json: str) -> str:
        self.calls.append((name, args_json))
        return json.dumps({"ok": True}, ensure_ascii=False)


def _fallback_context() -> dict[str, Any]:
    return {
        "source_step_number": 1,
        "source_text": "点击查询按钮",
        "fallback_reason": "locator_not_found",
        "action_plan_step": {
            "kind": "click",
            "source_text": "点击查询按钮",
            "target": {"role": "button", "name": "查询"},
        },
        "deterministic_evidence": {
            "error_kind": "locator_not_found",
            "message": "locator not found for '查询'",
        },
    }


@pytest.mark.asyncio
async def test_fallback_prompt_includes_plan_evidence_and_limits_visible_tools() -> None:
    exec_id = uuid.uuid4()
    captured: dict[str, Any] = {}

    async def chat_round(*, messages, tools, tool_choice):  # noqa: ANN001
        captured["system_prompt"] = messages[0]["content"]
        captured["tools"] = list(tools or [])
        captured["tool_choice"] = tool_choice
        return ChatRound(
            content="依据用例步骤 1：点击查询按钮，建议候选 locator 后交由 Runner 验证。",
            finish_reason="stop",
            usage_total=20,
        )

    runner = StepRunner(
        llm=_llm(),
        environment=_env(enable_browser_evaluate=True),
        budget=TokenBudget(limit=10_000),
        execution_id=exec_id,
        chat_round_fn=chat_round,
        tool_runner=_CountingToolRunner(),
    )

    result = await runner.run_one(
        step_description="点击查询按钮",
        expected="列表刷新",
        mcp_tool_specs=[
            _tool_spec(f"{exec_id}__browser_click"),
            _tool_spec(f"{exec_id}__browser_snapshot"),
            _tool_spec(f"{exec_id}__browser_evaluate"),
            _tool_spec(f"{exec_id}__browser_network_requests"),
        ],
        fallback_context=_fallback_context(),
    )

    assert result.success is True
    assert "AI 兜底模式" in captured["system_prompt"]
    assert "locator_not_found" in captured["system_prompt"]
    assert "点击查询按钮" in captured["system_prompt"]
    raw_tool_names = {
        spec["function"]["name"].split("__", 1)[-1]
        for spec in captured["tools"]
    }
    assert "browser_snapshot" in raw_tool_names
    assert "browser_network_requests" in raw_tool_names
    assert "browser_click" not in raw_tool_names
    assert "browser_evaluate" not in raw_tool_names


@pytest.mark.asyncio
async def test_fallback_policy_blocks_hidden_mutating_tool_call() -> None:
    exec_id = uuid.uuid4()
    tool_runner = _CountingToolRunner()
    rounds = [
        ChatRound(
            tool_calls=[
                ToolCallEmit(
                    id="call_1",
                    name=f"{exec_id}__browser_click",
                    arguments_json='{"ref":"e1"}',
                ),
            ],
            finish_reason="tool_calls",
            usage_total=10,
        ),
        ChatRound(
            content="依据用例步骤 1：候选点击动作未被 fallback policy 允许执行。",
            finish_reason="stop",
            usage_total=10,
        ),
    ]

    async def chat_round(*, messages, tools, tool_choice):  # noqa: ANN001
        return rounds.pop(0)

    runner = StepRunner(
        llm=_llm(),
        environment=_env(enable_browser_evaluate=True),
        budget=TokenBudget(limit=10_000),
        execution_id=exec_id,
        chat_round_fn=chat_round,
        tool_runner=tool_runner,
    )

    result = await runner.run_one(
        step_description="点击查询按钮",
        expected="列表刷新",
        fallback_context=_fallback_context(),
    )

    assert result.tool_calls[0].blocked is True
    assert result.tool_calls[0].result["error_kind"] == "fallback_policy"
    assert "fallback" in (result.tool_calls[0].error or "")
    assert tool_runner.calls == []


class _RoleLocator:
    async def count(self) -> int:
        return 0


class _RolePage:
    url = "https://app.example.com/admin"

    def get_by_role(self, role: str, *, name: str) -> _RoleLocator:
        return _RoleLocator()


class _BundleWithPage:
    def __init__(self, page: Any) -> None:
        self.execution_id = uuid.uuid4()
        self.mcp_unavailable = True
        self.closed = False
        self.page = page

    async def register_mcp_tools_for_agent(self) -> list[dict[str, Any]]:
        return []

    def get_primary_page(self) -> Any:
        return self.page

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_engine_does_not_ai_fallback_for_high_risk_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolver, _state = _make_resolver_stub()
    _patch_resolver(monkeypatch, lambda: resolver)
    tc = _Testcase(
        id=uuid.uuid4(),
        title="删除按钮",
        steps=[_Step(step_number=1, action="点击删除按钮", expected_result="删除成功")],
    )
    _patch_db_loaders(monkeypatch, testcases=[tc], llm_config=_make_llm_config_stub())

    runner = _FakeStepRunner(results=[_step_run_ok(snapshot="不应调用 AI fallback")])
    persistence = _FakePersistence()
    hub = _FakeStreamHub()
    deps = EngineDeps(
        db_session_factory=lambda: _FakeSessionContext(),
        open_browser_bundle=AsyncMock(return_value=_BundleWithPage(_RolePage())),
        step_runner_factory=lambda env, llm, budget, eid: runner,
        persistence=persistence,
        stream_hub=hub,
    )
    engine = ExecutionEngine(deps=deps)
    inputs = ExecutionInputs(
        execution_id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        environment_id=uuid.uuid4(),
        testcase_ids=[tc.id],
        llm_config_id=None,
        triggered_by=uuid.uuid4(),
        # Phase 15.4a: 显式开启 fallback 策略, 才能验证 high_risk 被拦截
        # (默认 hybrid_lightweight 策略下 fallback 整个被关掉, blocked_reason
        # 会落在 fallback_strategy_disabled, 是另一条路径).
        execution_strategy="hybrid_lightweight_with_fallback",
    )

    outcome = await engine.run(inputs)

    assert outcome.failed == 1
    assert runner.calls == []
    step_event = [
        payload
        for event, payload in hub.streams[inputs.execution_id].events
        if event == "step_complete"
    ][0]
    assert step_event["execution_path"] == "deterministic"
    assert step_event["fallback_reason"] == "high_risk_action_no_ai_fallback"


@pytest.mark.asyncio
async def test_engine_ai_fallback_passes_scoped_context_and_logs_reason(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="app.modules.ui_automation.execution_engine")
    resolver, _state = _make_resolver_stub()
    _patch_resolver(monkeypatch, lambda: resolver)
    tc = _Testcase(
        id=uuid.uuid4(),
        title="查询按钮",
        steps=[_Step(step_number=1, action="点击查询按钮", expected_result="查询成功")],
    )
    _patch_db_loaders(monkeypatch, testcases=[tc], llm_config=_make_llm_config_stub())

    runner = _FakeStepRunner(results=[_step_run_ok(snapshot="查询成功", tokens=30)])
    persistence = _FakePersistence()
    hub = _FakeStreamHub()
    deps = EngineDeps(
        db_session_factory=lambda: _FakeSessionContext(),
        open_browser_bundle=AsyncMock(return_value=_BundleWithPage(_RolePage())),
        step_runner_factory=lambda env, llm, budget, eid: runner,
        persistence=persistence,
        stream_hub=hub,
    )
    engine = ExecutionEngine(deps=deps)
    inputs = ExecutionInputs(
        execution_id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        environment_id=uuid.uuid4(),
        testcase_ids=[tc.id],
        llm_config_id=None,
        triggered_by=uuid.uuid4(),
        # Phase 15.4a: 显式开启 fallback 才能验证 fallback_context 透传; 默认
        # hybrid_lightweight 已不再触发 fallback.
        execution_strategy="hybrid_lightweight_with_fallback",
    )

    outcome = await engine.run(inputs)

    assert outcome.passed == 1
    fallback_context = runner.calls[0]["fallback_context"]
    assert fallback_context["fallback_reason"] == "locator_not_found"
    assert fallback_context["source_text"] == "点击查询按钮"
    assert fallback_context["action_plan_step"]["kind"] == "click"
    assert fallback_context["deterministic_evidence"]["error_kind"] == "locator_not_found"
    step_event = [
        payload
        for event, payload in hub.streams[inputs.execution_id].events
        if event == "step_complete"
    ][0]
    assert step_event["execution_path"] == "ai_fallback"
    assert step_event["fallback_reason"] == "locator_not_found"
    assert "AI fallback triggered" in caplog.text
    assert "locator_not_found" in caplog.text
