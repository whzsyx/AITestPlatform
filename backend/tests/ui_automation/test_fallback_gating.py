"""Phase 15.4a — AI fallback 默认关闭 + 触发条件收敛 单测.

覆盖矩阵 (来自 docs/SMART_UI_AUTOMATION_RELIABILITY_FIX_PLAN.md §15.4a):

A. ``_ai_fallback_allowed`` 白名单单测
   - 仅 CLICK / FILL 才能放行; ASSERT_TEXT / NAVIGATE / PRESS_KEY 一律拒绝.
   - risk_level="high" 一律拒绝 (即便 click + locator_not_found).
   - error_kind != "locator_not_found" 一律拒绝 (locator_ambiguous /
     action_failed / dangerous_action_blocked).
   - source_text 含 hedging 词 (若有 / 尝试 / 可能 / 如果 ...) 一律拒绝.
   - 全部 4 条同时满足才 True (CLICK + low risk + locator_not_found + 无 hedging).

B. 默认策略 (hybrid_lightweight) 下 fallback 整个被关闭
   - 即便 deterministic 失败 + 满足白名单全部条件, 也不进 step_runner;
     fallback_reason 落 \"fallback_strategy_disabled\".

C. 显式开启 (hybrid_lightweight_with_fallback) 下精细化拒绝原因
   - assert 类 -> action_kind_not_eligible
   - 探索性 click -> exploratory_step
   - high_risk click -> high_risk_action_no_ai_fallback

D. STEP_FALLBACK_TOKEN_BUDGET 上界 (token 焚化炉止血)
   - fallback 实际消耗 >= step cap 时, error_kind 改写为
     \"fallback_budget_exceeded\".

测试风格延续仓库现有约定: 复用 test_engine 的 helper 桩, 不引入新的 mock 框架.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.modules.ui_automation.action_plan import (
    ActionTarget,
    UIActionKind,
    UIActionStep,
)
from app.modules.ui_automation.deterministic_runner import (
    ActionEvidence,
    DeterministicRunResult,
)
from app.modules.ui_automation.execution_engine import (
    EngineDeps,
    ExecutionEngine,
    ExecutionInputs,
    _ai_fallback_allowed,
)
from tests.ui_automation.test_engine import (
    _FakePersistence,
    _FakeSessionContext,
    _FakeStepRunner,
    _FakeStreamHub,
    _make_resolver_stub,
    _patch_db_loaders,
    _patch_resolver,
    _Step,
    _step_run_ok,
    _Testcase,
)
from tests.ui_automation.test_hybrid_execution import (
    _BundleWithPage,
    _FakePage,
)

# ─── 工具: 组装一个 \"deterministic 失败\" 结果 ──────────────────────────


def _det_failure(
    *,
    error_kind: str = "locator_not_found",
    fallback_recommended: bool = True,
    action_kind: UIActionKind = UIActionKind.CLICK,
) -> DeterministicRunResult:
    return DeterministicRunResult(
        success=False,
        fallback_recommended=fallback_recommended,
        evidence=ActionEvidence(
            action_kind=action_kind,
            execution_path="deterministic",
            success=False,
            error_kind=error_kind,
            message=f"deterministic failed: {error_kind}",
            details={},
        ),
    )


def _step(
    *,
    kind: UIActionKind = UIActionKind.CLICK,
    risk_level: str = "medium",
    source_text: str = "点击保存按钮",
    target_name: str | None = "保存",
) -> UIActionStep:
    return UIActionStep(
        source_step_number=1,
        source_text=source_text,
        kind=kind,
        target=ActionTarget(role="button", name=target_name) if target_name else ActionTarget(),
        confidence=0.82,
        requires_evidence=["locator_match"],
        risk_level=risk_level,  # type: ignore[arg-type]
    )


# ─── A. _ai_fallback_allowed 白名单单测 ──────────────────────────────


def test_ai_fallback_allowed_when_click_locator_not_found_and_no_hedging() -> None:
    """白名单 4 条全部满足时 (CLICK + low risk + locator_not_found + 无 hedging),
    必须放行. 这是新规则下唯一的 True 路径."""
    assert _ai_fallback_allowed(_step(), _det_failure()) is True


def test_ai_fallback_allowed_when_fill_locator_not_found() -> None:
    fill_step = _step(
        kind=UIActionKind.FILL,
        source_text="在用户名输入框输入 admin",
        target_name=None,
    )
    fill_step.target.label = "用户名"
    assert _ai_fallback_allowed(fill_step, _det_failure()) is True


@pytest.mark.parametrize(
    "kind",
    [
        UIActionKind.ASSERT_TEXT,
        UIActionKind.ASSERT_URL,
        UIActionKind.ASSERT_PAGE_LOADED,
        UIActionKind.ASSERT_TABLE_COLUMNS,
        UIActionKind.ASSERT_TABLE_ROWS,
        UIActionKind.ASSERT_FORM_VALUES,
        UIActionKind.NAVIGATE,
        UIActionKind.PRESS_KEY,
        UIActionKind.SELECT,
        UIActionKind.WAIT_FOR_URL,
        UIActionKind.UNSUPPORTED,
    ],
)
def test_ai_fallback_rejected_for_non_click_or_fill_kinds(kind: UIActionKind) -> None:
    """断言 / 导航 / 按键 / select / wait / 不支持 -- 一律不进 fallback.

    Phase 15.4a 把 fallback 收成 \"显式 click / fill 目标\" 两个动作; 其余动作类
    型即便 deterministic 失败也不让 LLM 兜 (历史 6.7% 的通过率不值这个 token).
    """
    assert _ai_fallback_allowed(_step(kind=kind), _det_failure()) is False


def test_ai_fallback_rejected_for_high_risk_click() -> None:
    """high_risk = 用户 / 平台资源, 一律不让 AI 兜."""
    high_risk = _step(risk_level="high", source_text="点击删除按钮", target_name="删除")
    assert _ai_fallback_allowed(high_risk, _det_failure()) is False


@pytest.mark.parametrize(
    "error_kind",
    [
        "locator_ambiguous",
        "action_failed",
        "page_unavailable",
        "missing_target",
        "dangerous_action_blocked",
    ],
)
def test_ai_fallback_rejected_when_error_kind_is_not_locator_not_found(
    error_kind: str,
) -> None:
    """只有 locator_not_found 这一种确定性失败值得 LLM 再试; 其余直接落地."""
    assert _ai_fallback_allowed(_step(), _det_failure(error_kind=error_kind)) is False


@pytest.mark.parametrize(
    "source_text",
    [
        "若有保存按钮则点击",
        "如有提示弹窗, 点击关闭",
        "尝试点击保存按钮",
        "试试点击保存按钮",
        "可能存在的保存按钮请点击",
        "或许有保存按钮, 点击它",
        "也许需要点击保存按钮",
        "视情况点击保存",
        "看情况点击重置按钮",
        "建议点击保存按钮",
        "或者点击保存",
        "可以点击保存按钮",
        "如果没有错误就点击保存",
    ],
)
def test_ai_fallback_rejected_for_exploratory_hedging_steps(source_text: str) -> None:
    """探索性 / 试探性步骤的 hedging 词命中即拒绝.

    用例作者本意是 \"看一下 / 能就走\", 让 AI 兜反而越走越远. 给 deterministic
    not-found 的 verdict 才是真实情况.
    """
    assert _ai_fallback_allowed(_step(source_text=source_text), _det_failure()) is False


# ─── B/C. 端到端: 不同策略 / 不同 step 的 blocked_reason ──────────────


def _make_engine_for_step(
    monkeypatch: pytest.MonkeyPatch,
    *,
    step: _Step,
    page: _FakePage,
    runner: _FakeStepRunner | None = None,
) -> tuple[ExecutionEngine, _FakeStepRunner, _FakePersistence, _FakeStreamHub, _Testcase]:
    """组装一台只跑一个 step 的 engine 实例.

    与 test_hybrid_execution 的 helper 风格一致, 直接复用其 _FakePage / _BundleWithPage,
    只在这里集中拼装一次, 让每个用例只关心 step / page / strategy 三个维度.
    """
    resolver, _state = _make_resolver_stub()
    _patch_resolver(monkeypatch, lambda: resolver)
    tc = _Testcase(id=uuid.uuid4(), title="t", steps=[step])
    _patch_db_loaders(monkeypatch, testcases=[tc])
    bundle = _BundleWithPage(page)
    _runner = runner or _FakeStepRunner(results=[_step_run_ok(snapshot="不应被调到")])
    persistence = _FakePersistence()
    hub = _FakeStreamHub()
    deps = EngineDeps(
        db_session_factory=lambda: _FakeSessionContext(),
        open_browser_bundle=AsyncMock(return_value=bundle),
        step_runner_factory=lambda env, llm, budget, eid: _runner,
        persistence=persistence,
        stream_hub=hub,
    )
    return ExecutionEngine(deps=deps), _runner, persistence, hub, tc


def _make_inputs(
    *,
    tc: _Testcase,
    strategy: str = "hybrid_lightweight",
) -> ExecutionInputs:
    return ExecutionInputs(
        execution_id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        environment_id=uuid.uuid4(),
        testcase_ids=[tc.id],
        llm_config_id=None,
        triggered_by=uuid.uuid4(),
        execution_strategy=strategy,
    )


def _step_complete_event(hub: _FakeStreamHub, execution_id: Any) -> dict[str, Any]:
    return next(
        payload
        for event, payload in hub.streams[execution_id].events
        if event == "step_complete"
    )


@pytest.mark.asyncio
async def test_default_strategy_disables_fallback_even_when_all_conditions_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """B: 默认 hybrid_lightweight 下, 即使白名单 4 条全部满足, 也不进 fallback.

    这是 15.4a 止血的核心: fallback 默认关闭, 把 token 焚化炉路径整个堵上.
    """
    step = _Step(step_number=1, action="点击保存按钮", expected_result="保存成功")
    page = _FakePage(role_count=0, text_count=0)
    engine, runner, persistence, hub, tc = _make_engine_for_step(
        monkeypatch, step=step, page=page,
    )
    inputs = _make_inputs(tc=tc, strategy="hybrid_lightweight")

    await engine.run(inputs)

    assert runner.calls == [], "默认策略下 step_runner 不应被调到"
    event = _step_complete_event(hub, inputs.execution_id)
    assert event["execution_path"] == "deterministic"
    assert event["fallback_reason"] == "fallback_strategy_disabled"


@pytest.mark.asyncio
async def test_with_fallback_strategy_blocks_assert_step_with_action_kind_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C: with_fallback 下, assert 类不在白名单 -> blocked_reason=action_kind_not_eligible."""
    step = _Step(
        step_number=1,
        action="验证页面显示保存成功提示",
        expected_result="保存成功",
    )
    page = _FakePage(text_count=0)
    engine, runner, persistence, hub, tc = _make_engine_for_step(
        monkeypatch, step=step, page=page,
    )
    inputs = _make_inputs(tc=tc, strategy="hybrid_lightweight_with_fallback")

    await engine.run(inputs)

    assert runner.calls == [], "断言类不应进 fallback"
    event = _step_complete_event(hub, inputs.execution_id)
    assert event["execution_path"] == "deterministic"
    assert event["fallback_reason"] == "action_kind_not_eligible"


@pytest.mark.asyncio
async def test_with_fallback_strategy_blocks_exploratory_click_with_hedging_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C: with_fallback + 编译成 CLICK + locator_not_found, 但 source_text 含
    "尝试" 探索性词 -> blocked_reason=exploratory_step.

    必须用 "尝试点击 X 按钮" 这种语法, 才能让 plan_compiler 编译成 CLICK
    (而不是 UNSUPPORTED 直接走 ai_step_runner). hedging 拦截发生在白名单内部.
    """
    step = _Step(
        step_number=1,
        action="尝试点击保存按钮",
        expected_result="保存成功",
    )
    page = _FakePage(role_count=0, text_count=0)
    engine, runner, persistence, hub, tc = _make_engine_for_step(
        monkeypatch, step=step, page=page,
    )
    inputs = _make_inputs(tc=tc, strategy="hybrid_lightweight_with_fallback")

    await engine.run(inputs)

    assert runner.calls == [], "探索性步骤不进 fallback"
    event = _step_complete_event(hub, inputs.execution_id)
    assert event["execution_path"] == "deterministic"
    assert event["fallback_reason"] == "exploratory_step"


@pytest.mark.asyncio
async def test_with_fallback_strategy_blocks_high_risk_click_with_high_risk_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C: with_fallback + 高风险按钮 (\"删除\"等) -> high_risk_action_no_ai_fallback.

    与 test_engine_does_not_ai_fallback_for_high_risk_action (test_ai_fallback_policy.py)
    断言相同, 这里再覆盖一次以保证 15.4a 拒绝路径完整.
    """
    step = _Step(step_number=1, action="点击删除按钮", expected_result="删除成功")
    # 删除按钮被 plan_compiler 标 risk_level=high (DANGEROUS_WORDS)
    page = _FakePage(role_count=0, text_count=0)
    engine, runner, persistence, hub, tc = _make_engine_for_step(
        monkeypatch, step=step, page=page,
    )
    inputs = _make_inputs(tc=tc, strategy="hybrid_lightweight_with_fallback")

    await engine.run(inputs)

    assert runner.calls == [], "高风险步骤不进 fallback"
    event = _step_complete_event(hub, inputs.execution_id)
    assert event["execution_path"] == "deterministic"
    assert event["fallback_reason"] == "high_risk_action_no_ai_fallback"


# ─── D. STEP_FALLBACK_TOKEN_BUDGET ─────────────────────────────────


@pytest.mark.asyncio
async def test_with_fallback_strategy_marks_fallback_budget_exceeded_when_step_cap_exceeded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D: fallback 实际消耗超过 STEP_FALLBACK_TOKEN_BUDGET 时, error_kind 改写.

    实现路径: _run_step_with_strategy 在调 fallback 前临时把 budget.limit 降到
    \"已消耗 + step_cap\", step_runner 内置 over_limit 检查会触发 budget_exceeded;
    返回后再依据增量是否 >= step_cap 把 error_kind 改成 fallback_budget_exceeded.
    """
    # 把 step_cap 调到 100 tokens, 让 \"模拟 fallback 用了 200\" 必然超额
    from app.config import settings as _settings

    monkeypatch.setattr(_settings, "STEP_FALLBACK_TOKEN_BUDGET", 100)

    step = _Step(step_number=1, action="点击保存按钮", expected_result="保存成功")
    page = _FakePage(role_count=0, text_count=0)

    # 构造一个 fake step_runner 桩, 让它返回 budget_exceeded + 200 tokens (超 cap=100)
    from app.modules.ui_automation.step_runner import StepRunResult

    class _OverBudgetRunner:
        def __init__(self, base_budget: int) -> None:
            self.calls: list[dict[str, Any]] = []
            self.base_budget = base_budget

        async def run_one(self, **kwargs: Any) -> StepRunResult:
            self.calls.append(kwargs)
            return StepRunResult(
                success=False,
                iterations=1,
                tokens_used=self.base_budget + 200,  # 把 budget 推到超 step cap
                reasoning="",
                final_message="",
                last_snapshot_text="",
                tool_calls=[],
                error="(模拟) fallback 内部已超 step 级 token cap",
                error_kind="budget_exceeded",
            )

    resolver, _state = _make_resolver_stub()
    _patch_resolver(monkeypatch, lambda: resolver)
    tc = _Testcase(id=uuid.uuid4(), title="t", steps=[step])
    _patch_db_loaders(monkeypatch, testcases=[tc])
    bundle = _BundleWithPage(page)

    captured_runner: _OverBudgetRunner | None = None

    def _factory(env: Any, llm: Any, budget: Any, eid: Any) -> _OverBudgetRunner:
        nonlocal captured_runner
        # 在 factory 里同步推 budget.consumed, 模拟 \"fallback 内部 LLM 烧 token\".
        # 这里是 fake 实现, 不能等 step_runner 自己加 (因为我们不调真实 run_one).
        runner = _OverBudgetRunner(base_budget=budget.consumed)

        # 把 budget.add hook 进 _OverBudgetRunner.run_one: 先把 consumed 推过 cap
        original_run_one = runner.run_one

        async def _patched_run_one(**kwargs: Any) -> StepRunResult:
            budget.add(200)  # 让全局 budget.consumed 实际增长 200, 触发 fallback_budget_exceeded
            return await original_run_one(**kwargs)

        runner.run_one = _patched_run_one  # type: ignore[method-assign]
        captured_runner = runner
        return runner  # type: ignore[return-value]

    persistence = _FakePersistence()
    hub = _FakeStreamHub()
    deps = EngineDeps(
        db_session_factory=lambda: _FakeSessionContext(),
        open_browser_bundle=AsyncMock(return_value=bundle),
        step_runner_factory=_factory,
        persistence=persistence,
        stream_hub=hub,
    )
    engine = ExecutionEngine(deps=deps)
    inputs = _make_inputs(tc=tc, strategy="hybrid_lightweight_with_fallback")

    await engine.run(inputs)

    assert captured_runner is not None and len(captured_runner.calls) == 1, (
        "fallback 应当被触发一次"
    )
    flushed = persistence.steps_flushed[0]
    # error_message 在持久化层来自 run_result.error; 应包含 step 级 cap 提示
    assert "step 级 token 上限" in (flushed.get("error_message") or "")
