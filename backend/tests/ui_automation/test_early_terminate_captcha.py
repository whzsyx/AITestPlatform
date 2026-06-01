"""Phase 15.8 — failure_triage 命中外部反爬时, 把 verdict 标 early_terminate=True.

直接覆盖 ``triage_step_failure`` 在以下场景的契约:
- captcha / 安全验证 / 滑块验证 / verify you are human 命中 -> early_terminate=True
- 关 ``UI_EARLY_TERMINATE_ON_CAPTCHA`` 后退化为只改写 reason 不带 early_terminate
- 没命中外部反爬 (例如普通"未找到元素"错误) -> early_terminate=False (默认)
- ``AssertionVerdict.to_dict`` 输出在 early_terminate=True 时含 reason

不依赖 Playwright / DB / LLM, 走纯 dataclass 路径; engine 侧的 "剩余 step skipped"
集成测试由 test_engine.py 覆盖, 这里只守住 failure_triage 自己的边界.
"""

from __future__ import annotations

import pytest

from app.modules.ui_automation.assertion_judge import AssertionVerdict
from app.modules.ui_automation.failure_triage import triage_step_failure
from app.modules.ui_automation.step_runner import StepRunResult


def _make_run_result(*, snapshot_text: str = "", final_message: str = "") -> StepRunResult:
    return StepRunResult(
        success=True,
        iterations=1,
        tokens_used=100,
        reasoning="",
        final_message=final_message,
        tool_calls=[],
        last_snapshot_text=snapshot_text,
        last_clipped=None,
        error=None,
        error_kind=None,
    )


def test_triage_marks_early_terminate_on_captcha() -> None:
    verdict = AssertionVerdict(passed=False, reason="原始失败", method="text_search")
    run_result = _make_run_result(
        snapshot_text="Page Title: 百度安全验证\n请完成下方验证后继续访问"
    )
    out = triage_step_failure(
        verdict=verdict,
        run_result=run_result,
        step_description="搜索北京天气",
        expected="跳转到搜索结果页",
        target_url="https://www.baidu.com",
    )
    assert out.passed is False
    assert out.early_terminate is True
    assert out.early_terminate_reason == "external_verification_blocked"
    payload = out.to_dict()
    assert payload["early_terminate"] is True
    assert payload["early_terminate_reason"] == "external_verification_blocked"


@pytest.mark.parametrize(
    "needle",
    [
        "captcha",
        "verify you are human",
        "滑块验证",
        "人机验证",
        "请完成下方验证",
    ],
)
def test_triage_recognises_each_external_verification_term(needle: str) -> None:
    verdict = AssertionVerdict(passed=False, reason="找不到元素")
    run_result = _make_run_result(snapshot_text=f"some line\n{needle}\nnoise")
    out = triage_step_failure(
        verdict=verdict,
        run_result=run_result,
        step_description="点击查询按钮",
        expected="结果页加载",
        target_url=None,
    )
    assert out.early_terminate is True
    assert out.early_terminate_reason == "external_verification_blocked"


def test_triage_disables_early_terminate_when_setting_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """关 UI_EARLY_TERMINATE_ON_CAPTCHA 后, verdict 仍重写但不带 early_terminate.

    用于运维"先不动作只观察"场景, 类比 ChatOps 的 dry-run.
    """
    from app.config import settings

    monkeypatch.setattr(settings, "UI_EARLY_TERMINATE_ON_CAPTCHA", False)
    verdict = AssertionVerdict(passed=False, reason="原始失败")
    run_result = _make_run_result(snapshot_text="captcha challenge appeared")
    out = triage_step_failure(
        verdict=verdict,
        run_result=run_result,
        step_description="点击搜索",
        expected="结果页",
        target_url=None,
    )
    assert out.passed is False
    assert out.early_terminate is False
    assert out.early_terminate_reason is None
    # 仍把 reason 改写成更友好的描述
    assert "外部安全验证" in out.reason or "captcha" in out.reason.lower() or "验证码" in out.reason


def test_triage_no_early_terminate_for_unrelated_failure() -> None:
    """普通"找不到元素"失败 -> early_terminate=False, 不影响下游 case 推进."""
    verdict = AssertionVerdict(passed=False, reason="locator_not_found")
    run_result = _make_run_result(
        snapshot_text="Page Title: Internal Admin\n[ref=e1] button \"保存\""
    )
    out = triage_step_failure(
        verdict=verdict,
        run_result=run_result,
        step_description="点击保存按钮",
        expected="保存成功提示",
        target_url="https://staging.example.com/users",
    )
    assert out.early_terminate is False
    assert out.early_terminate_reason is None
    payload = out.to_dict()
    assert "early_terminate" not in payload  # 默认 False 不写入 payload


def test_triage_keeps_passed_verdict_unchanged() -> None:
    """已通过的 verdict 不应被 triage 改写, 即便 snapshot 里偶然出现 captcha 字样."""
    verdict = AssertionVerdict(passed=True, reason="text_search_hit", evidence="OK")
    run_result = _make_run_result(snapshot_text="安全验证已完成, 跳转中...")
    out = triage_step_failure(
        verdict=verdict,
        run_result=run_result,
        step_description="完成验证后继续",
        expected="跳转到目标页",
        target_url=None,
    )
    assert out is verdict
    assert out.early_terminate is False
