"""Phase 15.4b — decide_self_heal_action / SelfHealDecision 解析单测.

覆盖矩阵:
- a) LLM 返回标准 retry_with_locator JSON -> 完整解析候选;
- b) LLM 返回 markdown 包裹的 JSON -> 仍能解析;
- c) LLM 返回纯文本无 JSON -> mark_unsupported + parse_error;
- d) decision 非白名单 -> mark_unsupported + parse_error;
- e) retry 但无 candidate -> mark_unsupported + parse_error;
- f) candidate 含 evaluate / 空 value -> 被过滤;
- g) wait_and_retry / confirm_external_blocked / mark_unsupported 直通;
- h) LLM 调用抛错 -> mark_unsupported + parse_error 含异常类型;
- i) 强制 tool_choice="none" / tools=None 透传给 chat_round_fn.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.ui_automation.step_runner import (
    ChatRound,
    SelfHealDecision,
    _parse_self_heal_response,
    decide_self_heal_action,
)


def _llm() -> SimpleNamespace:
    return SimpleNamespace(
        provider="openai",
        model="gpt-4o-mini",
        temperature=0.0,
        max_tokens=1024,
        base_url=None,
        api_key="sk-test",
    )


def _make_chat(content: str):
    captured: dict[str, Any] = {}

    async def fn(*, messages, tools, tool_choice):
        captured["messages"] = list(messages)
        captured["tools"] = tools
        captured["tool_choice"] = tool_choice
        return ChatRound(content=content, finish_reason="stop", usage_total=10)

    return fn, captured


# ─── _parse_self_heal_response ────────────────────────────────────────


def test_parse_retry_with_two_locators() -> None:
    raw = json.dumps(
        {
            "decision": "retry_with_locator",
            "candidate_locators": [
                {"strategy": "css", "value": "button.save", "rationale": "css class"},
                {"strategy": "role", "value": "button:保存", "rationale": "name role"},
            ],
            "rationale": "看到一个紧邻的按钮",
        },
        ensure_ascii=False,
    )
    d = _parse_self_heal_response(raw)
    assert d.decision == "retry_with_locator"
    assert d.is_retry_with_locator
    assert len(d.candidate_locators) == 2
    assert d.candidate_locators[0]["strategy"] == "css"
    assert d.parse_error is None


def test_parse_handles_markdown_fence() -> None:
    raw = "```json\n" + json.dumps(
        {
            "decision": "wait_and_retry",
            "candidate_locators": [],
            "rationale": "loading",
        }
    ) + "\n```"
    d = _parse_self_heal_response(raw)
    assert d.decision == "wait_and_retry"
    assert d.candidate_locators == []
    assert d.parse_error is None


def test_parse_plain_text_falls_back_to_unsupported() -> None:
    d = _parse_self_heal_response("我也不知道, 帮你 retry 一下吧.")
    assert d.decision == "mark_unsupported"
    assert d.parse_error and d.parse_error.startswith("json_parse_failed")


def test_parse_unknown_decision_falls_back() -> None:
    raw = json.dumps({"decision": "give_up", "rationale": "x"})
    d = _parse_self_heal_response(raw)
    assert d.decision == "mark_unsupported"
    assert d.parse_error and "unknown_decision" in d.parse_error


def test_parse_retry_without_candidate_falls_back() -> None:
    raw = json.dumps({"decision": "retry_with_locator", "candidate_locators": []})
    d = _parse_self_heal_response(raw)
    assert d.decision == "mark_unsupported"
    assert d.parse_error == "retry_without_candidate"


def test_parse_filters_invalid_strategy_and_empty_value() -> None:
    # evaluate 不在白名单; 空 value 被丢; 合法的 css 保留
    raw = json.dumps(
        {
            "decision": "retry_with_locator",
            "candidate_locators": [
                {"strategy": "evaluate", "value": "page.evaluate()"},
                {"strategy": "css", "value": ""},
                {"strategy": "css", "value": "input.search"},
            ],
            "rationale": "x",
        }
    )
    d = _parse_self_heal_response(raw)
    assert d.decision == "retry_with_locator"
    # 只有 1 个合法候选保留
    assert len(d.candidate_locators) == 1
    assert d.candidate_locators[0]["value"] == "input.search"


def test_parse_truncates_excess_candidates() -> None:
    raw = json.dumps(
        {
            "decision": "retry_with_locator",
            "candidate_locators": [
                {"strategy": "css", "value": f"#a{i}"} for i in range(10)
            ],
        }
    )
    d = _parse_self_heal_response(raw)
    # 协议规定最多保留 5 条
    assert len(d.candidate_locators) <= 5


def test_parse_passthrough_for_other_decisions() -> None:
    for kind in ("wait_and_retry", "confirm_external_blocked", "mark_unsupported"):
        raw = json.dumps({"decision": kind, "rationale": "x"})
        d = _parse_self_heal_response(raw)
        assert d.decision == kind
        assert d.parse_error is None


# ─── decide_self_heal_action ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_decide_passes_strict_args_to_chat() -> None:
    fn, captured = _make_chat(
        json.dumps(
            {
                "decision": "retry_with_locator",
                "candidate_locators": [{"strategy": "css", "value": ".save"}],
                "rationale": "x",
            }
        )
    )
    d = await decide_self_heal_action(
        llm=_llm(),
        step_description="点击保存按钮",
        expected="表格出现新行",
        deterministic_message="locator_not_found: button:保存",
        deterministic_evidence={"error_kind": "locator_not_found", "selector": "button:保存"},
        snapshot_text="<html><body>...</body></html>",
        chat_round_fn=fn,
    )
    assert isinstance(d, SelfHealDecision)
    assert d.is_retry_with_locator
    # 严格不让传 tools / 强制 tool_choice="none"
    assert captured["tool_choice"] == "none"
    assert captured["tools"] is None
    # user message 里包含 step / expected / evidence / snapshot
    user = next(m for m in captured["messages"] if m["role"] == "user")
    assert "点击保存按钮" in user["content"]
    assert "表格出现新行" in user["content"]
    assert "locator_not_found" in user["content"]
    assert "<body>" in user["content"]


@pytest.mark.asyncio
async def test_decide_handles_chat_exception_gracefully() -> None:
    async def boom(*, messages, tools, tool_choice):
        raise RuntimeError("network down")

    d = await decide_self_heal_action(
        llm=_llm(),
        step_description="...",
        expected=None,
        deterministic_message="x",
        deterministic_evidence=None,
        snapshot_text=None,
        chat_round_fn=boom,
    )
    assert d.decision == "mark_unsupported"
    assert d.parse_error and "llm_call_failed" in d.parse_error
    assert "RuntimeError" in d.parse_error


@pytest.mark.asyncio
async def test_decide_truncates_oversize_snapshot() -> None:
    # 不希望模型 prompt 被几十万字符塞爆 -> 内部裁到 6000
    huge = "x" * 30_000
    fn, captured = _make_chat(
        json.dumps({"decision": "mark_unsupported", "rationale": "x"})
    )
    await decide_self_heal_action(
        llm=_llm(),
        step_description="...",
        expected=None,
        deterministic_message="x",
        deterministic_evidence=None,
        snapshot_text=huge,
        chat_round_fn=fn,
    )
    user = next(m for m in captured["messages"] if m["role"] == "user")
    # snapshot 段落整体应当 ≤ 6000 + 一点描述, 不会原样回灌 30K
    assert len(user["content"]) < 12_000
