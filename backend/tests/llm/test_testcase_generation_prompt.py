from __future__ import annotations

from app.modules.llm.prompts.testcase_gen import (
    TESTCASE_GEN_SYSTEM_PROMPT,
    build_testcase_gen_user_prompt,
)
from app.modules.prompts.built_in import BUILT_IN_PROMPTS


def test_testcase_generation_prompt_guides_ui_automation_friendly_steps() -> None:
    prompt = TESTCASE_GEN_SYSTEM_PROMPT

    assert "UI 自动化友好" in prompt
    assert "每步只允许一个原子动作" in prompt
    assert "在「字段名」输入框输入 {{semantic_key}}" in prompt
    assert "点击「按钮名」按钮" in prompt
    assert "表格列名" in prompt
    assert "横向滚动" in prompt
    assert "{{semantic_key}}" in prompt
    assert "避免写死" in prompt
    assert "不可观测" in prompt
    assert "自包含" in prompt
    assert "结果页验证" in prompt
    assert "输入关键词" in prompt
    assert "点击搜索" in prompt


def test_testcase_generation_user_prompt_reinforces_machine_executable_output() -> None:
    prompt = build_testcase_gen_user_prompt(
        "商城需求.md",
        "后台支持按店铺 ID 查询，并在列表展示店铺名称、渠道、状态。",
    )

    assert "优先生成适合 UI 自动化直接执行的步骤" in prompt
    assert "控件名称" in prompt
    assert "可观测断言" in prompt
    assert "不能依赖上一条用例" in prompt


def test_built_in_generation_prompts_match_ui_automation_guidance() -> None:
    generation_prompts = [
        item for item in BUILT_IN_PROMPTS if item.get("category") == "generation"
    ]

    assert generation_prompts
    for item in generation_prompts:
        content = item["content"]
        assert "UI 自动化友好" in content
        assert "每步只允许一个原子动作" in content
        assert "{{semantic_key}}" in content
        assert "可观测断言" in content
        assert "自包含" in content
