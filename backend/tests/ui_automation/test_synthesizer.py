"""DataSynthesizer：启发式精确 / 模糊 / LLM 推断桩。"""

from __future__ import annotations

import json

import pytest

from app.modules.ui_automation.data_synthesizer import HEURISTIC_RULES, DataSynthesizer


@pytest.mark.asyncio
async def test_heuristic_exact_phone_starts_with_138() -> None:
    s = DataSynthesizer()
    out = await s.synthesize("phone", "", "string")
    assert out.source == "heuristic_exact"
    assert out.value.startswith("138")
    assert len(out.value) == 11


@pytest.mark.asyncio
async def test_heuristic_fuzzy_user_phone() -> None:
    s = DataSynthesizer()
    out = await s.synthesize("buyer_phone_number", "", "string")
    assert out.source.startswith("heuristic_fuzzy:")
    assert out.value.startswith("138")


@pytest.mark.asyncio
async def test_heuristic_understands_creator_placeholders() -> None:
    s = DataSynthesizer()

    creator_id = await s.synthesize("existing_creator_id", "", "string")
    creator_name = await s.synthesize("existing_creator_name", "", "string")
    name_keyword = await s.synthesize("name_keyword", "", "string")

    assert creator_id.source.startswith("heuristic_fuzzy:creator_id")
    assert creator_id.value.isdigit()
    assert creator_name.source.startswith("heuristic_fuzzy:creator_name")
    assert "创作者" in creator_name.value
    assert name_keyword.source == "heuristic_exact"
    assert name_keyword.value == "测试"


@pytest.mark.asyncio
async def test_name_keyword_does_not_echo_long_placeholder_hint() -> None:
    s = DataSynthesizer()
    out = await s.synthesize(
        "name_keyword",
        "验证同时通过创作者ID和创作者名称查询：在「创作者名称」输入框输入 {{name_keyword}}；"
        "查询结果中至少有一行数据",
        "string",
    )

    assert out.value == "测试"
    assert "{{" not in out.value
    assert len(out.value) <= 20


@pytest.mark.asyncio
async def test_search_keyword_does_not_echo_long_placeholder_hint() -> None:
    s = DataSynthesizer()
    out = await s.synthesize(
        "search_keyword",
        "验证搜索框输入后点击搜索按钮触发搜索：在「搜索框」输入「{{search_keyword}}」；"
        "搜索框内显示「{{search_keyword}}」；搜索结果页面至少显示一条包含「{{search_keyword}}」的标题或片段",
        "string",
    )

    assert out.source.startswith("heuristic_fuzzy:keyword")
    assert out.value == "测试"
    assert "{{" not in out.value


@pytest.mark.asyncio
async def test_infer_fn_override_before_llm() -> None:
    async def infer_stub(key: str, hint: str, vt: str) -> str:
        assert key == "weird_xxx"
        return "COUPON-ZZZ"

    s = DataSynthesizer(infer_fn=infer_stub)
    out = await s.synthesize("weird_xxx", "下单时的优惠券码", "string")
    assert out.value == "COUPON-ZZZ"
    assert out.source == "ai_inferred"


@pytest.mark.asyncio
async def test_fallback_when_no_db_and_no_infer() -> None:
    s = DataSynthesizer()
    out = await s.synthesize("totally_unknown_field_xx", "", "string")
    assert out.source == "fallback_no_llm"
    assert "test_totally_unknown_field_xx_" in out.value


@pytest.mark.asyncio
async def test_dataset_fallback_is_json_array() -> None:
    s = DataSynthesizer()
    out = await s.synthesize("unknown_ds", "note", "dataset")
    assert out.source == "fallback_no_llm"
    parsed = json.loads(out.value)
    assert isinstance(parsed, list)


def test_heuristic_rules_coverage_task_minimum() -> None:
    assert len(HEURISTIC_RULES) >= 17
