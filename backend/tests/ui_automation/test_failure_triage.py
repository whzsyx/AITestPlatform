from __future__ import annotations

from app.modules.ui_automation.assertion_judge import AssertionVerdict
from app.modules.ui_automation.failure_triage import triage_step_failure
from app.modules.ui_automation.step_runner import StepRunResult, ToolCallRecord


def _run_result(
    snapshot: str,
    *,
    final_message: str = "",
    tool_calls: list[ToolCallRecord] | None = None,
) -> StepRunResult:
    return StepRunResult(
        success=True,
        iterations=1,
        tokens_used=0,
        reasoning="",
        final_message=final_message,
        tool_calls=tool_calls or [],
        last_snapshot_text=snapshot,
        last_clipped=None,
    )


def test_triage_auto_heals_when_page_load_expectation_is_already_satisfied() -> None:
    verdict = AssertionVerdict(
        passed=False,
        reason="无法定位浏览器地址栏输入框，导致未执行输入网址及导航操作",
        evidence="locator not found for '浏览器地址'",
        method="deterministic",
    )
    result = _run_result(
        """
        ### Page
        - Page URL: https://www.baidu.com/
        - Page Title: 百度一下，你就知道
        ### Snapshot
        - textbox "热搜词"
        - button "百度一下"
        """,
    )

    healed = triage_step_failure(
        verdict=verdict,
        run_result=result,
        step_description="在浏览器地址栏输入 https://www.baidu.com 并回车",
        expected="页面加载完成，标题包含“百度一下，你就知道”或“百度一下”，且页面存在「搜索框」和「百度一下」按钮",
        target_url="https://www.baidu.com",
    )

    assert healed.passed is True
    assert "自愈通过" in healed.reason
    assert "页面已满足预期" in healed.evidence


def test_triage_reports_external_verification_instead_of_plain_assertion_failure() -> None:
    verdict = AssertionVerdict(
        passed=False,
        reason="页面中未出现天气信息模块",
        evidence="",
        method="llm",
    )
    result = _run_result(
        """
        ### Page
        - Page URL: https://www.baidu.com/s?wd=北京天气
        - Page Title: 百度安全验证
        ### Snapshot
        百度安全验证
        请完成下方验证后继续操作
        """,
    )

    diagnosed = triage_step_failure(
        verdict=verdict,
        run_result=result,
        step_description="滚动查看页面顶部区域",
        expected="页面中出现天气信息模块，包含“北京”和温度数值",
        target_url="https://www.baidu.com",
    )

    assert diagnosed.passed is False
    assert "外部安全验证" in diagnosed.reason
    assert "验证码" in diagnosed.reason
    assert "百度安全验证" in diagnosed.evidence


def test_triage_reports_missing_precondition_for_dependent_single_step() -> None:
    verdict = AssertionVerdict(
        passed=False,
        reason="页面内未发现包含“北京天气”字样的显著标题",
        evidence="Page Title: 百度一下，你就知道",
        method="llm",
    )
    result = _run_result(
        """
        ### Page
        - Page URL: https://www.baidu.com/
        - Page Title: 百度一下，你就知道
        ### Snapshot
        - textbox "热搜词"
        - button "百度一下"
        """,
    )

    diagnosed = triage_step_failure(
        verdict=verdict,
        run_result=result,
        step_description="查看浏览器标签页标题或页面主标题区域",
        expected="标题或页面内显著标题包含“北京天气”字样",
        target_url="https://www.baidu.com",
    )

    assert diagnosed.passed is False
    assert "缺少前置操作" in diagnosed.reason
    assert "同一条用例" in diagnosed.reason


def test_triage_rewrites_empty_llm_after_successful_deterministic_action() -> None:
    verdict = AssertionVerdict(
        passed=False,
        reason="LLM 返回空内容（可能是 thinking 模式 max_tokens 不够，或 LLM 网关限流）",
        evidence="",
        method="llm_unavailable",
    )
    result = _run_result(
        "### Page\n- Page URL: https://example.com/form\n### Snapshot\n- button \"保存\"",
        tool_calls=[
            ToolCallRecord(
                name="deterministic_runner",
                raw_name="deterministic_runner",
                arguments={},
                result={
                    "execution_path": "deterministic",
                    "success": True,
                    "action_kind": "click",
                    "message": "clicked 保存",
                },
            ),
        ],
    )

    diagnosed = triage_step_failure(
        verdict=verdict,
        run_result=result,
        step_description="点击保存按钮",
        expected="页面保存成功",
        target_url="https://example.com/form",
    )

    assert diagnosed.passed is False
    assert "断言模型空响应" in diagnosed.reason
    assert "动作已完成" in diagnosed.reason
