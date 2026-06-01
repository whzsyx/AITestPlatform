"""Task 9.5 — AssertionJudge 单测。"""

from __future__ import annotations

import pytest

from app.modules.ui_automation.assertion_judge import (
    AssertionJudge,
    AssertionLLMConfig,
)


@pytest.mark.asyncio
async def test_no_expected_passes() -> None:
    judge = AssertionJudge()
    v = await judge.judge(expected=None, snapshot="anything")
    assert v.passed is True
    assert v.method == "no_expected"

    v2 = await judge.judge(expected="   ", snapshot="anything")
    assert v2.passed is True
    assert v2.method == "no_expected"


@pytest.mark.asyncio
async def test_no_snapshot_fails() -> None:
    judge = AssertionJudge()
    v = await judge.judge(expected="登录成功", snapshot=None)
    assert v.passed is False
    assert v.method == "skipped"

    v2 = await judge.judge(expected="登录成功", snapshot="")
    assert v2.passed is False
    assert v2.method == "skipped"


@pytest.mark.asyncio
async def test_full_text_match_passes() -> None:
    judge = AssertionJudge()
    v = await judge.judge(
        expected="跳转到首页",
        snapshot="- main\n  - heading 'Welcome'\n  - text '跳转到首页 已完成'",
    )
    assert v.passed is True
    assert v.method == "text_search"
    assert "跳转到首页" in v.reason


@pytest.mark.asyncio
async def test_multi_keyword_match_passes() -> None:
    judge = AssertionJudge()
    v = await judge.judge(
        expected="登录成功，欢迎回来",
        snapshot="- main\n  - heading '登录成功！'\n  - text '欢迎回来 admin'",
    )
    assert v.passed is True
    assert v.method == "text_search"


@pytest.mark.asyncio
async def test_page_loaded_without_console_errors_passes_without_llm() -> None:
    async def should_not_call_llm(**_):
        raise AssertionError("页面加载/无报错类断言应由确定性规则处理")

    judge = AssertionJudge(completion_fn=should_not_call_llm)
    v = await judge.judge(
        expected="列表页面正常加载，无报错",
        snapshot=(
            "## Accessibility 快照\n"
            "### Page\n"
            "- Page URL: https://example.com/list\n"
            "- Page Title: 通用列表页\n"
            "- Console: 0 errors, 8 warnings\n"
            "### Snapshot\n"
            "- table\n"
        ),
        llm_config=AssertionLLMConfig(provider="openai", model="x"),
    )
    assert v.passed is True
    assert v.method == "text_search"
    assert "0 errors" in v.evidence


@pytest.mark.asyncio
async def test_page_loaded_passes_without_explicit_no_error_phrase() -> None:
    async def should_not_call_llm(**_):
        raise AssertionError("列表正常加载类断言应由页面元信息和表格证据处理")

    judge = AssertionJudge(completion_fn=should_not_call_llm)
    v = await judge.judge(
        expected="列表页面正常加载",
        snapshot=(
            "## Accessibility 快照\n"
            "### Page\n"
            "- Page URL: https://example.com/list\n"
            "- Page Title: 通用列表页\n"
            "### Snapshot\n"
            "- table\n"
            "## 工具证据 1: browser_evaluate\n"
            "```text\n"
            '{"totalRows": 20, "totalColumns": 12, "pagination": "共 20 条"}\n'
            "```"
        ),
        llm_config=AssertionLLMConfig(provider="openai", model="x"),
    )
    assert v.passed is True
    assert v.method == "text_search"
    assert "列表" in v.reason


@pytest.mark.asyncio
async def test_ordered_table_columns_pass_without_llm() -> None:
    async def should_not_call_llm(**_):
        raise AssertionError("列顺序断言应由 browser_evaluate 证据直接处理")

    judge = AssertionJudge(completion_fn=should_not_call_llm)
    v = await judge.judge(
        expected=(
            "在“锚点列”列之前，依次展示：字段A、字段B、字段C、"
            "字段D，顺序完全一致"
        ),
        snapshot=(
            "## 工具证据 2: browser_evaluate\n"
            "```text\n"
            "[\n"
            '  {"index": 10, "text": "字段A"},\n'
            '  {"index": 11, "text": "字段B"},\n'
            '  {"index": 12, "text": "字段C"},\n'
            '  {"index": 13, "text": "字段D"},\n'
            '  {"index": 14, "text": "锚点列"}\n'
            "]\n"
            "```"
        ),
        llm_config=AssertionLLMConfig(provider="openai", model="x"),
    )
    assert v.passed is True
    assert v.method == "text_search"
    assert "按顺序" in v.reason


@pytest.mark.asyncio
async def test_table_display_and_style_pass_without_llm() -> None:
    async def should_not_call_llm(**_):
        raise AssertionError("数据展示/样式类断言应由工具证据直接处理")

    judge = AssertionJudge(completion_fn=should_not_call_llm)
    v = await judge.judge(
        expected="新增列数据展示正常，样式与原有列保持一致，无错位或显示异常",
        snapshot=(
            "## 工具证据 1: browser_evaluate\n"
            "```text\n"
            '{"totalRows": 20, "totalColumns": 8, '
            '"newColRows": [{"cells": [{"t": "A001", "w": 80, "v": true}]}], '
            '"newColStyles": [{"text": "字段A", "width": 80, "height": "40px"}]}\n'
            "```"
        ),
        llm_config=AssertionLLMConfig(provider="openai", model="x"),
    )
    assert v.passed is True
    assert v.method == "text_search"
    assert "展示" in v.reason


@pytest.mark.asyncio
async def test_readonly_or_not_editable_passes_without_llm() -> None:
    async def should_not_call_llm(**_):
        raise AssertionError("不可编辑/只读类断言应由 DOM 证据直接处理")

    judge = AssertionJudge(completion_fn=should_not_call_llm)
    v = await judge.judge(
        expected="新增字段为只读状态或不可见，无法进行手动输入或修改",
        snapshot=(
            "## 工具证据 1: browser_evaluate\n"
            "```text\n"
            '{"hasInput": false, "hasTextarea": false, "hasSelect": false, '
            '"contentEditable": null, "editableControls": 0}\n'
            "```"
        ),
        llm_config=AssertionLLMConfig(provider="openai", model="x"),
    )
    assert v.passed is True
    assert v.method == "text_search"
    assert "不可编辑" in v.reason


@pytest.mark.asyncio
async def test_download_link_ready_passes_without_llm() -> None:
    async def should_not_call_llm(**_):
        raise AssertionError("下载入口存在类断言应由 DOM 证据直接处理")

    judge = AssertionJudge(completion_fn=should_not_call_llm)
    v = await judge.judge(
        expected="等待 2 秒文件下载本地成功",
        snapshot=(
            "## 工具证据 1: browser_evaluate\n"
            "```text\n"
            '{"cells": [{"text": "已生成"}], "hasButton": true, "hasLink": true, '
            '"linkHref": "https://example.com/export/result.zip"}\n'
            "```"
        ),
        llm_config=AssertionLLMConfig(provider="openai", model="x"),
    )
    assert v.passed is True
    assert v.method == "text_search"
    assert "下载" in v.reason


@pytest.mark.asyncio
async def test_structured_table_columns_pass_without_llm() -> None:
    async def should_not_call_llm(**_):
        raise AssertionError("结构化表格列断言应由规则处理")

    judge = AssertionJudge(completion_fn=should_not_call_llm)
    v = await judge.judge(
        expected="验证列表列名包含店铺ID、店铺名称、平台",
        snapshot="snapshot 中没有这些完整列名，必须依赖 structured_evidence",
        structured_evidence={
            "table_schema": {
                "columns": ["店铺ID", "店铺名称", "平台"],
                "visible_columns": ["店铺ID", "店铺名称"],
                "total_columns": 3,
            },
        },
        llm_config=AssertionLLMConfig(provider="openai", model="x"),
    )

    assert v.passed is True
    assert v.method == "text_search"
    assert "表格列" in v.reason


@pytest.mark.asyncio
async def test_structured_form_readonly_pass_without_llm() -> None:
    async def should_not_call_llm(**_):
        raise AssertionError("结构化表单只读断言应由规则处理")

    judge = AssertionJudge(completion_fn=should_not_call_llm)
    v = await judge.judge(
        expected="店铺ID字段只读，不能手动编辑",
        snapshot="snapshot 未展示 disabled 属性",
        structured_evidence={
            "form_fields": {
                "fields": [
                    {
                        "label": "店铺ID",
                        "name": "storeId",
                        "value": "S001",
                        "readonly": True,
                        "disabled": False,
                    }
                ],
            },
        },
        llm_config=AssertionLLMConfig(provider="openai", model="x"),
    )

    assert v.passed is True
    assert "只读" in v.reason


@pytest.mark.asyncio
async def test_text_miss_without_llm_fails_text_search() -> None:
    judge = AssertionJudge()
    v = await judge.judge(
        expected="找不到的文本",
        snapshot="- main\n  - link '其他东西'",
    )
    assert v.passed is False
    assert v.method == "text_search"


@pytest.mark.asyncio
async def test_llm_fallback_when_text_miss() -> None:
    captured = {}

    async def fake_complete(*, provider, model, messages, api_key, base_url, temperature, max_tokens):  # noqa: ANN001
        captured["called"] = True
        captured["provider"] = provider
        captured["model"] = model
        return '{"passed": true, "reason": "页面内容语义匹配", "evidence": "Welcome user"}'

    judge = AssertionJudge(completion_fn=fake_complete)
    v = await judge.judge(
        expected="用户登录成功并欢迎",
        snapshot="- main\n  - heading 'Welcome user'",
        step_description="点击登录",
        llm_config=AssertionLLMConfig(provider="openai", model="gpt-4o-mini"),
    )
    assert captured["called"] is True
    assert v.passed is True
    assert v.method == "llm"
    assert v.evidence == "Welcome user"


@pytest.mark.asyncio
async def test_llm_returns_invalid_json_marks_unavailable() -> None:
    async def fake_complete(**_):
        return "随便输出一段不是 JSON 的话"

    judge = AssertionJudge(completion_fn=fake_complete)
    v = await judge.judge(
        expected="特定内容",
        snapshot="不相关的 snapshot",
        llm_config=AssertionLLMConfig(provider="openai", model="x"),
    )
    assert v.passed is False
    assert v.method == "llm_unavailable"
    # 非空内容应原样回显（前 200 字符），方便调试
    assert "随便输出" in v.reason


@pytest.mark.asyncio
async def test_llm_returns_truncated_json_with_passed_true_is_salvaged() -> None:
    async def fake_complete(**_):
        return '{"passed": true, "reason": "页面URL指向目标列表页，控制台无报错，且存在分'

    judge = AssertionJudge(completion_fn=fake_complete)
    v = await judge.judge(
        expected="页面加载正常",
        snapshot="- main\n  - text 'unrelated'",
        llm_config=AssertionLLMConfig(provider="openai", model="x"),
    )
    assert v.passed is True
    assert v.method == "llm"
    assert "JSON 被截断" in v.reason
    assert "passed=true" in v.reason


@pytest.mark.asyncio
async def test_llm_returns_truncated_json_with_passed_false_is_salvaged() -> None:
    async def fake_complete(**_):
        return '{"passed": false, "reason": "快照中未包含目标表格列名'

    judge = AssertionJudge(completion_fn=fake_complete)
    v = await judge.judge(
        expected="包含新增列",
        snapshot="- main\n  - text 'unrelated'",
        llm_config=AssertionLLMConfig(provider="openai", model="x"),
    )
    assert v.passed is False
    assert v.method == "llm"
    assert "JSON 被截断" in v.reason
    assert "passed=false" in v.reason


@pytest.mark.asyncio
async def test_llm_returns_empty_content_gives_explicit_reason() -> None:
    """**关键回归（修复 #f6513ebb）**：thinking 模式下 ``content=""`` 是常见
    症状（reasoning_content 把 max_tokens 用光），早期实现把空串拼到 reason
    里给用户看到的就是 ``"LLM 输出无法解析为 JSON："`` 后面光秃秃 —— 完全没
    诊断价值。修复后应给出明确的"返回空内容 / 检查 max_tokens"提示。"""
    async def empty_complete(**_):
        return ""

    judge = AssertionJudge(completion_fn=empty_complete)
    # expected 在 snapshot 里**不**直接命中，强制走到 LLM 兜底分支
    v = await judge.judge(
        expected="模型必须深度判断的内容",
        snapshot="- main\n  - text 'unrelated'",
        llm_config=AssertionLLMConfig(provider="openai", model="x"),
    )
    assert v.passed is False
    assert v.method == "llm_unavailable"
    # reason 必须明确指出空 content 的常见根因 + 解决方向
    assert "空内容" in v.reason
    assert "max_tokens" in v.reason
    # 不能再是早期那种"LLM 输出无法解析为 JSON：" + 空串的截断式错误
    assert not v.reason.endswith("无法解析为 JSON：")


@pytest.mark.asyncio
async def test_llm_returns_whitespace_only_content_treated_as_empty() -> None:
    """全是空白字符（thinking 模式偶尔会返回 "  \\n  "）也按"空 content"处理。"""
    async def whitespace_complete(**_):
        return "   \n  \t  "

    judge = AssertionJudge(completion_fn=whitespace_complete)
    v = await judge.judge(
        expected="模型必须深度判断的内容",
        snapshot="- main\n  - text 'unrelated'",
        llm_config=AssertionLLMConfig(provider="openai", model="x"),
    )
    assert v.passed is False
    assert "空内容" in v.reason


def test_assertion_llm_config_default_max_tokens_is_thinking_friendly() -> None:
    """``max_tokens`` 默认值应足以覆盖 thinking 模式（GLM / doubao thinking-pro
    等）的内部思考 + final JSON 输出 —— 512 太小会导致空 content 故障。"""
    cfg = AssertionLLMConfig(provider="openai", model="x")
    assert cfg.max_tokens >= 2048, (
        f"AssertionLLMConfig.max_tokens={cfg.max_tokens} 太小，thinking 模式下"
        "容易 reasoning 用满 → final content 被截空，详见 #f6513ebb"
    )


@pytest.mark.asyncio
async def test_llm_assertion_uses_deterministic_temperature_and_large_token_cap() -> None:
    captured = {}

    async def fake_complete(**kwargs):
        captured.update(kwargs)
        return '{"passed": false, "reason": "未命中", "evidence": ""}'

    judge = AssertionJudge(completion_fn=fake_complete)
    await judge.judge(
        expected="需要 LLM 判断",
        snapshot="- main",
        llm_config=AssertionLLMConfig(
            provider="openai",
            model="x",
            temperature=0.9,
            max_tokens=131072,
        ),
    )
    assert captured["temperature"] == 0.0
    assert captured["max_tokens"] >= 8192


@pytest.mark.asyncio
async def test_llm_call_exception_falls_back_to_unavailable() -> None:
    async def boom(**_):
        raise RuntimeError("network down")

    judge = AssertionJudge(completion_fn=boom)
    v = await judge.judge(
        expected="特定内容",
        snapshot="不相关的 snapshot",
        llm_config=AssertionLLMConfig(provider="openai", model="x"),
    )
    assert v.passed is False
    assert v.method == "llm_unavailable"
    assert "RuntimeError" in v.reason


@pytest.mark.asyncio
async def test_llm_extracts_json_from_markdown_fence() -> None:
    async def fake_complete(**_):
        return '```json\n{"passed": false, "reason": "未找到", "evidence": ""}\n```'

    judge = AssertionJudge(completion_fn=fake_complete)
    v = await judge.judge(
        expected="找不到的文本",
        snapshot="- main",
        llm_config=AssertionLLMConfig(provider="openai", model="x"),
    )
    assert v.passed is False
    assert v.method == "llm"
    assert v.reason == "未找到"


@pytest.mark.asyncio
async def test_llm_extracts_object_buried_in_text() -> None:
    async def fake_complete(**_):
        return '一些前导的废话\n{"passed": true, "reason": "OK"}\n后续无关'

    judge = AssertionJudge(completion_fn=fake_complete)
    v = await judge.judge(
        expected="某种内容",
        snapshot="- main\n  - other",
        llm_config=AssertionLLMConfig(provider="openai", model="x"),
    )
    assert v.passed is True
    assert v.method == "llm"


# ─── Phase 15.2: AssertionJudge 不接受 reasoning 作为判定输入 ──────────


def test_judge_signature_does_not_accept_reasoning_field() -> None:
    """Phase 15.2 不变量: AssertionJudge.judge() 不接受 reasoning / ai_reasoning
    类参数, 防止未来重构把 StepRunResult.reasoning 误注入到判定上下文.
    模型自己写的 reasoning 是 "主观解读", 不能作为客观判定依据 ——
    一切判定必须基于 snapshot + tool_call results + structured_evidence.
    """
    import inspect
    sig = inspect.signature(AssertionJudge.judge)
    params = set(sig.parameters)
    forbidden = {"reasoning", "ai_reasoning", "model_reasoning", "step_reasoning"}
    leaked = params & forbidden
    assert not leaked, f"AssertionJudge.judge() 不应接收 reasoning 类参数, 实际泄漏: {leaked}"


@pytest.mark.asyncio
async def test_reasoning_like_text_in_snapshot_does_not_falsely_pass() -> None:
    """如果模型在 reasoning 里写 "我已点击成功" 但 snapshot 里实际没有
    "成功" 字样, 判定必须失败 —— 即便 reasoning 听起来很 plausible.

    这对应 Phase 15.2 历史问题: AI 在 reasoning 里完整模拟操作但快照其实是
    操作前的状态, AssertionJudge 当时仍要按 snapshot 判, 不能被任何外部
    叙述影响.
    """
    judge = AssertionJudge()
    v = await judge.judge(
        expected="提交成功提示已出现",
        # 注: snapshot 里完全没有 "提交成功" 字样
        snapshot="- main\n  - form\n    - textbox 'username'\n    - button 'submit'",
    )
    assert v.passed is False
    assert v.method == "text_search"
