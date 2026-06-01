"""Phase 15.4b — _try_self_heal 端到端单测.

覆盖 6 类核心分支:

a) retry_with_locator + 候选成功 -> execution_path="ai_fallback_self_heal";
b) retry_with_locator + 候选全部失败 -> 保留 deterministic 原 verdict;
c) wait_and_retry + 重试成功 -> execution_path="ai_fallback_self_heal_wait";
d) confirm_external_blocked -> execution_path="triage_external";
e) mark_unsupported -> 返 None (让 caller 走 15.4a 旧 fallback);
f) step_runner 没 llm -> 直接返 None (兼容 mock 测试 / 异常构造).

测试不直连 LLM, 通过 monkeypatch 替换 decide_self_heal_action.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.modules.ui_automation import execution_engine
from app.modules.ui_automation.action_plan import UIActionKind, UIActionStep
from app.modules.ui_automation.deterministic_runner import (
    ActionEvidence,
    DeterministicRunResult,
)
from app.modules.ui_automation.security import TokenBudget
from app.modules.ui_automation.step_runner import SelfHealDecision

# ─── helpers ──────────────────────────────────────────────────────────


def _make_inputs(strategy: str = "hybrid_lightweight_with_fallback") -> Any:
    return SimpleNamespace(
        execution_id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        environment_id=uuid.uuid4(),
        testcase_ids=[],
        llm_config_id=uuid.uuid4(),
        triggered_by=uuid.uuid4(),
        execution_strategy=strategy,
    )


def _make_step(kind: UIActionKind = UIActionKind.CLICK) -> UIActionStep:
    return UIActionStep(
        kind=kind,
        target={"role": "button", "name": "保存"},
        source_step_number=1,
        source_text="点击保存按钮",
        risk_level="low",
    )


def _failed_deterministic(
    *, error_kind: str = "locator_not_found", message: str = "no element"
) -> DeterministicRunResult:
    return DeterministicRunResult(
        success=False,
        fallback_recommended=True,
        evidence=ActionEvidence(
            action_kind=UIActionKind.CLICK,
            execution_path="deterministic",
            success=False,
            error_kind=error_kind,
            message=message,
            details={},
        ),
    )


def _ok_deterministic() -> DeterministicRunResult:
    return DeterministicRunResult(
        success=True,
        fallback_recommended=False,
        evidence=ActionEvidence(
            action_kind=UIActionKind.CLICK,
            execution_path="deterministic",
            success=True,
            details={},
        ),
    )


@dataclass
class _FakePage:
    async def content(self) -> str:
        return "<html><body><button>保存</button></body></html>"

    async def wait_for_timeout(self, ms: int) -> None:
        return None


class _FakeBundle:
    def __init__(self, page: _FakePage) -> None:
        self._page = page

    def get_primary_page(self) -> _FakePage:
        return self._page


class _FakeDeterministicRunner:
    """用 results 队列预设连续两次 run_step 的返回."""

    def __init__(self, results: list[DeterministicRunResult]) -> None:
        self._results = list(results)
        self.calls: list[dict[str, Any]] = []

    async def run_step(
        self,
        page: Any,
        step: UIActionStep,
        *,
        extra_locator_candidates: list[dict[str, Any]] | None = None,
        # Phase 15.9: engine 调 run_step 时新增 preferred 候选 (信任 locator).
        # 本测试聚焦 self-heal extra 候选, 接但忽略 -- 与生产 runner 行为对齐:
        # extra 是 "AI 自愈兜底", preferred 是 "历史成功记忆", 两者独立.
        preferred_locator_candidates: list[dict[str, Any]] | None = None,
    ) -> DeterministicRunResult:
        self.calls.append({
            "step_kind": step.kind.value,
            "extra_candidates": list(extra_locator_candidates or []),
            "preferred_candidates": list(preferred_locator_candidates or []),
        })
        return self._results.pop(0)


def _make_step_runner_with_llm() -> Any:
    """模拟一个最小 StepRunner stub: 只需要 llm 字段非空."""
    return SimpleNamespace(
        llm=SimpleNamespace(
            provider="openai",
            model="gpt-4o-mini",
            temperature=0.0,
            max_tokens=1024,
            base_url=None,
            api_key="sk-test",
        )
    )


# ─── 测试: a) retry_with_locator + 二次执行成功 ────────────────────────


@pytest.mark.asyncio
async def test_self_heal_retry_with_locator_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = _FakePage()
    bundle = _FakeBundle(page)
    failing = _failed_deterministic()
    runner = _FakeDeterministicRunner(results=[_ok_deterministic()])
    decision = SelfHealDecision(
        decision="retry_with_locator",
        candidate_locators=[{"strategy": "css", "value": "button.save", "rationale": "x"}],
        rationale="按钮 css class",
    )
    monkeypatch.setattr(
        execution_engine,
        "decide_self_heal_action",
        AsyncMock(return_value=decision),
    )

    out = await execution_engine._try_self_heal(
        inputs=_make_inputs(),
        bundle=bundle,
        step_runner=_make_step_runner_with_llm(),
        deterministic_runner=runner,
        compiled_step=_make_step(),
        step_description="点击保存按钮",
        expected="保存成功",
        deterministic_result=failing,
        budget=TokenBudget(limit=10_000),
    )

    assert out is not None
    step_result, execution_path = out
    assert execution_path == "ai_fallback_self_heal"
    # 二次执行确实带上了 LLM 推荐候选
    assert len(runner.calls) == 1
    assert runner.calls[0]["extra_candidates"] == [
        {"strategy": "css", "value": "button.save", "rationale": "x"},
    ]


# ─── 测试: b) retry 候选全部失败 -> 保留 deterministic ──────────────────


@pytest.mark.asyncio
async def test_self_heal_retry_failure_keeps_deterministic_verdict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _FakeBundle(_FakePage())
    failing = _failed_deterministic()
    runner = _FakeDeterministicRunner(results=[_failed_deterministic()])
    decision = SelfHealDecision(
        decision="retry_with_locator",
        candidate_locators=[{"strategy": "css", "value": "button.bad"}],
        rationale="错的候选",
    )
    monkeypatch.setattr(
        execution_engine,
        "decide_self_heal_action",
        AsyncMock(return_value=decision),
    )

    out = await execution_engine._try_self_heal(
        inputs=_make_inputs(),
        bundle=bundle,
        step_runner=_make_step_runner_with_llm(),
        deterministic_runner=runner,
        compiled_step=_make_step(),
        step_description="点击保存按钮",
        expected="保存成功",
        deterministic_result=failing,
        budget=TokenBudget(limit=10_000),
    )

    assert out is not None
    step_result, execution_path = out
    assert execution_path == "deterministic"
    # 保留原 deterministic verdict, 自愈尝试落 evidence.details
    details = failing.evidence.details
    assert details["self_heal_attempted"] is True
    assert details["self_heal_decision"] == "retry_with_locator"


# ─── 测试: c) wait_and_retry + 重试成功 ────────────────────────────────


@pytest.mark.asyncio
async def test_self_heal_wait_and_retry_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = _FakePage()
    bundle = _FakeBundle(page)
    failing = _failed_deterministic(
        error_kind="data_unstable", message="表格未刷新"
    )
    runner = _FakeDeterministicRunner(results=[_ok_deterministic()])
    decision = SelfHealDecision(
        decision="wait_and_retry",
        candidate_locators=[],
        rationale="等待数据刷新",
    )
    monkeypatch.setattr(
        execution_engine,
        "decide_self_heal_action",
        AsyncMock(return_value=decision),
    )

    out = await execution_engine._try_self_heal(
        inputs=_make_inputs(),
        bundle=bundle,
        step_runner=_make_step_runner_with_llm(),
        deterministic_runner=runner,
        compiled_step=_make_step(),
        step_description="点击查询",
        expected="出现表格",
        deterministic_result=failing,
        budget=TokenBudget(limit=10_000),
    )

    assert out is not None
    _step_result, execution_path = out
    assert execution_path == "ai_fallback_self_heal_wait"
    # 没传 extra_candidates (wait 路径不带)
    assert runner.calls[0]["extra_candidates"] == []


# ─── 测试: d) confirm_external_blocked ──────────────────────────────────


@pytest.mark.asyncio
async def test_self_heal_confirm_external_blocked_returns_triage_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _FakeBundle(_FakePage())
    failing = _failed_deterministic(error_kind="captcha")
    runner = _FakeDeterministicRunner(results=[])  # 不应再调
    decision = SelfHealDecision(
        decision="confirm_external_blocked",
        candidate_locators=[],
        rationale="碰到验证码",
    )
    monkeypatch.setattr(
        execution_engine,
        "decide_self_heal_action",
        AsyncMock(return_value=decision),
    )

    out = await execution_engine._try_self_heal(
        inputs=_make_inputs(),
        bundle=bundle,
        step_runner=_make_step_runner_with_llm(),
        deterministic_runner=runner,
        compiled_step=_make_step(),
        step_description="点击下一页",
        expected="表格分页",
        deterministic_result=failing,
        budget=TokenBudget(limit=10_000),
    )

    assert out is not None
    _step_result, execution_path = out
    assert execution_path == "triage_external"
    assert runner.calls == []
    assert failing.evidence.details["fallback_reason"] == "external_blocked"


# ─── 测试: e) mark_unsupported -> 返 None 让 caller 兜底 ───────────────


@pytest.mark.asyncio
async def test_self_heal_mark_unsupported_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _FakeBundle(_FakePage())
    failing = _failed_deterministic()
    runner = _FakeDeterministicRunner(results=[])
    decision = SelfHealDecision(
        decision="mark_unsupported",
        candidate_locators=[],
        rationale="复杂场景",
    )
    monkeypatch.setattr(
        execution_engine,
        "decide_self_heal_action",
        AsyncMock(return_value=decision),
    )

    out = await execution_engine._try_self_heal(
        inputs=_make_inputs(),
        bundle=bundle,
        step_runner=_make_step_runner_with_llm(),
        deterministic_runner=runner,
        compiled_step=_make_step(),
        step_description="...",
        expected="...",
        deterministic_result=failing,
        budget=TokenBudget(limit=10_000),
    )

    assert out is None
    # 决策仍要落 evidence 用于审计
    assert failing.evidence.details["self_heal_decision"] == "mark_unsupported"
    assert runner.calls == []


# ─── 测试: f) step_runner 没 llm 时跳过 ─────────────────────────────────


@pytest.mark.asyncio
async def test_self_heal_skips_when_step_runner_has_no_llm() -> None:
    bundle = _FakeBundle(_FakePage())
    failing = _failed_deterministic()
    runner = _FakeDeterministicRunner(results=[])
    step_runner_without_llm = SimpleNamespace()  # 没有 llm 属性

    out = await execution_engine._try_self_heal(
        inputs=_make_inputs(),
        bundle=bundle,
        step_runner=step_runner_without_llm,
        deterministic_runner=runner,
        compiled_step=_make_step(),
        step_description="...",
        expected="...",
        deterministic_result=failing,
        budget=TokenBudget(limit=10_000),
    )

    assert out is None
    assert runner.calls == []


# ─── 测试: g) 自愈开关 OFF -> 走旧 fallback ─────────────────────────────


@pytest.mark.asyncio
async def test_self_heal_disabled_via_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Phase 15.4b 回退口径: UI_AI_FALLBACK_SELF_HEAL=False 时, _try_self_heal
    本身仍然可调 (本测) -- 但 _run_step_with_strategy 在调用前会先 check 开关."""
    from app.config import settings

    monkeypatch.setattr(settings, "UI_AI_FALLBACK_SELF_HEAL", False)
    # 直接调 _try_self_heal 不受开关影响 (开关在 caller 层判);
    # 这里仅验证 _try_self_heal 在被调到时仍按决策语义工作.
    bundle = _FakeBundle(_FakePage())
    failing = _failed_deterministic()
    runner = _FakeDeterministicRunner(results=[_ok_deterministic()])
    decision = SelfHealDecision(
        decision="retry_with_locator",
        candidate_locators=[{"strategy": "css", "value": ".save"}],
    )
    monkeypatch.setattr(
        execution_engine,
        "decide_self_heal_action",
        AsyncMock(return_value=decision),
    )

    out = await execution_engine._try_self_heal(
        inputs=_make_inputs(),
        bundle=bundle,
        step_runner=_make_step_runner_with_llm(),
        deterministic_runner=runner,
        compiled_step=_make_step(),
        step_description="...",
        expected="...",
        deterministic_result=failing,
        budget=TokenBudget(limit=10_000),
    )

    assert out is not None
    _, execution_path = out
    assert execution_path == "ai_fallback_self_heal"
