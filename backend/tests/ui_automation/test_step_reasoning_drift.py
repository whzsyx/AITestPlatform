"""Phase 15.2 — StepRunner reasoning_drift 防护单测.

覆盖 4 类核心分支:

a) 正常: 首轮即有 toolcall, 不触发 drift recovery, loop_break_reason=None.
b) 首轮 0 toolcall + reasoning 不含动作词: 走原 break, loop_break_reason=None.
c) 首轮 0 toolcall + reasoning 含动作词: 触发强制重试, 第二轮调工具成功 ->
   loop_break_reason="reasoning_drift_recovered".
d) 触发后第二轮仍 0 toolcall: loop_break_reason="reasoning_drift_unrecoverable".

外加:
- 第二轮的 tool_choice 必须是 "required" (强制).
- 触发 recovery 时, messages 里追加了 user 提醒 + 模型上一轮 reasoning_content.
- _looks_like_action_intent 单元覆盖中文 / 英文 / false-positive.
- 配置开关 UI_REASONING_DRIFT_RECOVERY=False 时回到原 break 行为.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.ui_automation.security import TokenBudget
from app.modules.ui_automation.step_runner import (
    _ACTION_INTENT_PATTERN,
    ChatRound,
    StepRunner,
    ToolCallEmit,
    _looks_like_action_intent,
)

# ─── helpers (与 test_step_runner.py 风格一致, 局部复制简化) ───────────


def make_env(**kw: Any) -> SimpleNamespace:
    return SimpleNamespace(
        base_url="https://app.example.com",
        allowed_hosts=["app.example.com"],
        token_budget=50_000,
        enable_browser_evaluate=False,
        **kw,
    )


def make_llm() -> SimpleNamespace:
    return SimpleNamespace(
        provider="openai",
        model="gpt-4o-mini",
        temperature=0.0,
        max_tokens=2048,
        base_url=None,
        api_key="sk-test",
    )


def chat_rounds(*rounds: ChatRound):
    queue = list(rounds)
    captured: list[dict[str, Any]] = []

    async def fn(*, messages, tools, tool_choice):
        captured.append(
            {
                "messages": list(messages),
                "tools": list(tools or []),
                "tool_choice": tool_choice,
            }
        )
        if not queue:
            raise AssertionError("chat_round_fn called more times than expected")
        return queue.pop(0)

    return fn, captured


@dataclass
class FakeTool:
    handlers: dict[str, Any]

    async def __call__(self, name: str, args_json: str) -> str:
        if name not in self.handlers:
            return json.dumps({"error": f"unknown tool {name}"})
        result = self.handlers[name](json.loads(args_json or "{}"))
        return json.dumps(result, ensure_ascii=False)


# ─── _looks_like_action_intent: 词典覆盖 ──────────────────────────────


def test_action_intent_pattern_matches_chinese_verbs() -> None:
    assert _looks_like_action_intent("我已点击登录按钮，进入下一步")
    assert _looks_like_action_intent("已经在搜索框输入 9999")
    assert _looks_like_action_intent("点选第一个结果项")


def test_action_intent_pattern_matches_english_verbs() -> None:
    assert _looks_like_action_intent("I clicked the login button.")
    assert _looks_like_action_intent("Typed 'admin' into the username field.")
    assert _looks_like_action_intent("Submitted the form successfully.")
    assert _looks_like_action_intent("Navigating to /cart now.")


def test_action_intent_pattern_does_not_match_observation_text() -> None:
    # 纯阅读 / 观察类描述不应触发 drift recovery
    assert not _looks_like_action_intent("我看到页面顶部有 logo 与导航栏。")
    assert not _looks_like_action_intent("This page shows a list of items.")
    assert not _looks_like_action_intent("")
    assert not _looks_like_action_intent(None)


def test_action_intent_regex_compiled_once() -> None:
    # 防止后续误改成函数级编译, 拖慢循环 (StepRunner.run_one 高频调用)
    assert _ACTION_INTENT_PATTERN.search("点击")


# ─── 分支 a) 正常: 首轮就有 toolcall ───────────────────────────────


@pytest.mark.asyncio
async def test_drift_a_normal_first_round_has_toolcall_no_recovery() -> None:
    exec_id = uuid.uuid4()
    fn, captured = chat_rounds(
        ChatRound(
            tool_calls=[
                ToolCallEmit(
                    id="c1",
                    name=f"{exec_id}__browser_click",
                    arguments_json='{"ref": "e1"}',
                ),
            ],
            finish_reason="tool_calls",
            usage_total=20,
        ),
        ChatRound(content="完成。", finish_reason="stop", usage_total=10),
    )
    runner = StepRunner(
        llm=make_llm(),
        environment=make_env(),
        budget=TokenBudget(limit=10_000),
        execution_id=exec_id,
        chat_round_fn=fn,
        tool_runner=FakeTool({f"{exec_id}__browser_click": lambda _: {"ok": True}}),
    )
    out = await runner.run_one(step_description="点击登录按钮")
    assert out.success is True
    assert out.loop_break_reason is None
    # 第一轮 tool_choice 不应被设为 "required" (普通流程)
    assert captured[0]["tool_choice"] is None


# ─── 分支 b) 首轮 0 tc + 无动作词: 走原 break ────────────────────────


@pytest.mark.asyncio
async def test_drift_b_first_round_zero_tc_without_action_words() -> None:
    """模型只是观察一下页面就 0 toolcall 收尾, 这是合法的, 不该触发救场."""
    exec_id = uuid.uuid4()
    fn, captured = chat_rounds(
        ChatRound(
            content="我看到页面已经是登录态, 无需进一步操作.",
            reasoning="观察后判断步骤已完成",
            finish_reason="stop",
            usage_total=10,
        ),
    )
    runner = StepRunner(
        llm=make_llm(),
        environment=make_env(),
        budget=TokenBudget(limit=10_000),
        execution_id=exec_id,
        chat_round_fn=fn,
        tool_runner=FakeTool({}),
    )
    out = await runner.run_one(step_description="确认当前已登录")
    assert out.success is True
    # 没触发 drift recovery
    assert out.loop_break_reason is None
    # 只调了一次 LLM (没有强制再跑一轮)
    assert len(captured) == 1


# ─── 分支 c) 首轮 0 tc + 动作词 → 触发救场 → 第二轮成功 ──────────────


@pytest.mark.asyncio
async def test_drift_c_action_intent_triggers_recovery_and_second_round_succeeds() -> None:
    exec_id = uuid.uuid4()
    fn, captured = chat_rounds(
        # 首轮: 模型在 reasoning 里描述"我已点击..."但没真调工具
        ChatRound(
            content="我已点击查询按钮, 等待结果加载中.",
            reasoning="第一步是点击查询按钮",
            finish_reason="stop",
            usage_total=15,
        ),
        # 第二轮: 被强制 tool_choice=required 后真调了工具
        ChatRound(
            tool_calls=[
                ToolCallEmit(
                    id="c1",
                    name=f"{exec_id}__browser_click",
                    arguments_json='{"ref": "e3"}',
                ),
            ],
            finish_reason="tool_calls",
            usage_total=20,
        ),
        # 第三轮: 收尾
        ChatRound(content="点击完成.", finish_reason="stop", usage_total=8),
    )
    runner = StepRunner(
        llm=make_llm(),
        environment=make_env(),
        budget=TokenBudget(limit=10_000),
        execution_id=exec_id,
        chat_round_fn=fn,
        tool_runner=FakeTool({f"{exec_id}__browser_click": lambda _: {"ok": True}}),
    )
    out = await runner.run_one(step_description="点击查询按钮")
    assert out.success is True
    assert out.loop_break_reason == "reasoning_drift_recovered"
    # 工具被真的调过一次
    assert len(out.tool_calls) == 1
    # 第二轮的 tool_choice 必须是 "required"
    assert captured[1]["tool_choice"] == "required"
    # messages 里应当包含 drift 提醒 user 消息 (\u4e0d\u4f1a\u771f\u7684\u4ea7\u751f\u6d4f\u89c8\u5668\u52a8\u4f5c)
    user_msgs = [
        m for m in captured[1]["messages"] if m["role"] == "user"
    ]
    assert any("没真正调用工具" in m["content"] for m in user_msgs)
    # 模型上一轮的 reasoning_content 应当被回填到 assistant 消息里
    assistant_msgs = [
        m for m in captured[1]["messages"] if m["role"] == "assistant"
    ]
    assert any(m.get("reasoning_content") == "第一步是点击查询按钮" for m in assistant_msgs)


# ─── 分支 d) 救场后第二轮仍 0 tc → unrecoverable ──────────────────


@pytest.mark.asyncio
async def test_drift_d_recovery_attempted_but_second_round_still_no_toolcall() -> None:
    exec_id = uuid.uuid4()
    fn, captured = chat_rounds(
        ChatRound(
            content="我已经输入用户名了.",
            reasoning="决定输入测试账号 test_user",
            finish_reason="stop",
            usage_total=10,
        ),
        # 第二轮被强制 required, 但模型不知怎么还是 0 tc (协议层面 OpenAI 兼容
        # 网关有时会拒绝 required, fallback 到 stop). 这是 unrecoverable 路径.
        ChatRound(
            content="抱歉, 我无法找到合适的输入框.",
            reasoning="重新检查后还是没法操作",
            finish_reason="stop",
            usage_total=12,
        ),
    )
    runner = StepRunner(
        llm=make_llm(),
        environment=make_env(),
        budget=TokenBudget(limit=10_000),
        execution_id=exec_id,
        chat_round_fn=fn,
        tool_runner=FakeTool({}),
    )
    out = await runner.run_one(step_description="输入用户名 admin")
    assert out.success is True  # 循环正常退出 (是否通过由 AssertionJudge 判)
    assert out.loop_break_reason == "reasoning_drift_unrecoverable"
    # 没产生任何工具调用
    assert out.tool_calls == []
    # 重要: reasoning 应当**保留**给审计 (不能因为救场失败就丢失上下文)
    assert "决定输入测试账号 test_user" in out.reasoning


# ─── 配置开关: UI_REASONING_DRIFT_RECOVERY=False 时回到原 break ──────


@pytest.mark.asyncio
async def test_drift_recovery_can_be_disabled_via_settings(monkeypatch) -> None:
    """关掉开关后, 即使 reasoning 命中动作词, 也直接 break, 不再救场."""
    from app.config import settings

    monkeypatch.setattr(settings, "UI_REASONING_DRIFT_RECOVERY", False)

    exec_id = uuid.uuid4()
    fn, captured = chat_rounds(
        ChatRound(
            content="我已点击查询按钮.",
            reasoning="点击查询",
            finish_reason="stop",
            usage_total=10,
        ),
    )
    runner = StepRunner(
        llm=make_llm(),
        environment=make_env(),
        budget=TokenBudget(limit=10_000),
        execution_id=exec_id,
        chat_round_fn=fn,
        tool_runner=FakeTool({}),
    )
    out = await runner.run_one(step_description="点击查询按钮")
    assert out.success is True
    # 关关后即使命中动作词也不该写 loop_break_reason
    assert out.loop_break_reason is None
    # 只跑一轮 LLM (没有救场)
    assert len(captured) == 1
