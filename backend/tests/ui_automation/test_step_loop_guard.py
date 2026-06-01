"""Phase 15.7 — StepRunner 循环检测 early-stop 单测.

覆盖矩阵 (与 docs §15.7 验收口径对齐):

a) 信号 a (repeated_tool_signature) — 同名工具同参数连续重复 N 次跳出;
b) 信号 b (snapshot_unchanged) — 连续 N 轮快照 diff% <= 阈值跳出;
c) 信号 c (step_token_soft_budget_exceeded) — 单步 token 软上限触发;
d) 复杂表单 5-6 轮 toolcall **不被误伤** -- 工具签名变化 / 快照增长 / token 在预算内;
e) ``UI_LOOP_GUARD_*`` 单独 disable 后退化为原行为;
f) tool_calls 末尾追加 ``_meta_loop_guard`` 节点, 内容含 break_reason / 历史统计;
g) ``estimated_total_steps`` 的软上限计算口径.

辅助验证:
- ``_tool_signature`` 同名同参数生成同 hash, 同名不同参数不同 hash;
- ``_snapshot_diff_pct`` 行级 set diff 归一化, 完全相同 -> 0, 完全无重叠 -> 1.
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
    ChatRound,
    StepRunner,
    ToolCallEmit,
    _estimate_step_token_soft_budget,
    _snapshot_diff_pct,
    _tool_signature,
)


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
        captured.append({"messages": list(messages), "tools": list(tools or []), "tool_choice": tool_choice})
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


# ─── helpers 单测 ─────────────────────────────────────────────────────


def test_tool_signature_same_args_same_hash() -> None:
    a = ToolCallEmit(id="x", name="ns__browser_click", arguments_json='{"ref":"e1"}')
    b = ToolCallEmit(id="y", name="ns__browser_click", arguments_json='{"ref":"e1"}')
    assert _tool_signature(a) == _tool_signature(b)


def test_tool_signature_diff_args_diff_hash() -> None:
    a = ToolCallEmit(id="x", name="ns__browser_click", arguments_json='{"ref":"e1"}')
    b = ToolCallEmit(id="y", name="ns__browser_click", arguments_json='{"ref":"e2"}')
    assert _tool_signature(a) != _tool_signature(b)


def test_tool_signature_strips_namespace() -> None:
    # ns 前缀不参与 hash, 同 raw_name 同参数不同 namespace 也应当是同 signature
    a = ToolCallEmit(id="x", name="ns1__browser_click", arguments_json='{"ref":"e1"}')
    b = ToolCallEmit(id="y", name="ns2__browser_click", arguments_json='{"ref":"e1"}')
    assert _tool_signature(a) == _tool_signature(b)


def test_snapshot_diff_pct_zero_for_identical() -> None:
    assert _snapshot_diff_pct("a\nb\nc", "a\nb\nc") == 0.0


def test_snapshot_diff_pct_one_for_disjoint() -> None:
    assert _snapshot_diff_pct("a\nb", "x\ny") == pytest.approx(1.0)


def test_snapshot_diff_pct_partial_overlap() -> None:
    # 3 共有 + 1 新增 + 1 删除 = 5 union, 2 diff -> 0.4
    pct = _snapshot_diff_pct("a\nb\nc\nd", "a\nb\nc\ne")
    assert 0.3 < pct < 0.5


def test_estimate_step_token_soft_budget_uses_floor_when_total_unknown() -> None:
    assert (
        _estimate_step_token_soft_budget(total_budget=0, estimated_total_steps=10, floor=20_000)
        == 20_000
    )


def test_estimate_step_token_soft_budget_scales_with_total_and_steps() -> None:
    # total=100k, steps=10 -> 100k * 1.5 / 10 = 15k -> floor 20k
    assert (
        _estimate_step_token_soft_budget(total_budget=100_000, estimated_total_steps=10, floor=20_000)
        == 20_000
    )
    # total=300k, steps=5 -> 300k * 1.5 / 5 = 90k > 20k
    assert (
        _estimate_step_token_soft_budget(total_budget=300_000, estimated_total_steps=5, floor=20_000)
        == 90_000
    )


# ─── 信号 a: repeated_tool_signature ──────────────────────────────────


@pytest.mark.asyncio
async def test_signal_a_repeated_tool_signature_breaks_loop() -> None:
    """两轮工具同名同参数 -> dup_threshold=2 触发, 不再走第三轮."""
    exec_id = uuid.uuid4()
    fn, captured = chat_rounds(
        ChatRound(
            tool_calls=[
                ToolCallEmit(id="c1", name=f"{exec_id}__browser_click", arguments_json='{"ref":"e1"}')
            ],
            finish_reason="tool_calls",
            usage_total=20,
        ),
        ChatRound(
            tool_calls=[
                ToolCallEmit(id="c2", name=f"{exec_id}__browser_click", arguments_json='{"ref":"e1"}')
            ],
            finish_reason="tool_calls",
            usage_total=20,
        ),
        # 第三轮不应该被请求, 否则 chat_rounds() 会抛 AssertionError
    )
    runner = StepRunner(
        llm=make_llm(),
        environment=make_env(),
        budget=TokenBudget(limit=10_000),
        execution_id=exec_id,
        chat_round_fn=fn,
        tool_runner=FakeTool({f"{exec_id}__browser_click": lambda _: {"ok": True}}),
    )
    out = await runner.run_one(step_description="点击同一个按钮")
    assert out.success is True
    assert out.loop_break_reason == "repeated_tool_signature"
    # 只跑了 2 轮 LLM
    assert len(captured) == 2
    # _meta_loop_guard 节点必须在末尾
    assert out.tool_calls[-1].raw_name == "_meta_loop_guard"
    meta = out.tool_calls[-1].result
    assert meta["break_reason"] == "repeated_tool_signature"
    assert len(meta["signature_history"]) >= 2
    # 两个签名相同
    assert meta["signature_history"][-1] == meta["signature_history"][-2]


@pytest.mark.asyncio
async def test_signal_a_disabled_via_settings_lets_loop_continue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "UI_LOOP_GUARD_DUP_TOOL", False)
    # 同时关掉 b/c 防其它信号干扰
    monkeypatch.setattr(settings, "UI_LOOP_GUARD_SNAPSHOT_DIFF", False)
    monkeypatch.setattr(settings, "UI_LOOP_GUARD_STEP_TOKEN_SOFT", False)

    exec_id = uuid.uuid4()
    fn, captured = chat_rounds(
        ChatRound(
            tool_calls=[
                ToolCallEmit(id="c1", name=f"{exec_id}__browser_click", arguments_json='{"ref":"e1"}')
            ],
            finish_reason="tool_calls",
            usage_total=20,
        ),
        ChatRound(
            tool_calls=[
                ToolCallEmit(id="c2", name=f"{exec_id}__browser_click", arguments_json='{"ref":"e1"}')
            ],
            finish_reason="tool_calls",
            usage_total=20,
        ),
        ChatRound(content="收尾。", finish_reason="stop", usage_total=10),
    )
    runner = StepRunner(
        llm=make_llm(),
        environment=make_env(),
        budget=TokenBudget(limit=10_000),
        execution_id=exec_id,
        chat_round_fn=fn,
        tool_runner=FakeTool({f"{exec_id}__browser_click": lambda _: {"ok": True}}),
    )
    out = await runner.run_one(step_description="点击同一个按钮")
    assert out.success is True
    assert out.loop_break_reason is None
    assert len(captured) == 3
    # 没有 _meta_loop_guard 节点
    assert all(rec.raw_name != "_meta_loop_guard" for rec in out.tool_calls)


# ─── 信号 b: snapshot_unchanged ────────────────────────────────────────


@pytest.mark.asyncio
async def test_signal_b_snapshot_unchanged_breaks_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """连续 3 轮工具调用快照都不变 (diff_pct == 0) -> snapshot_unchanged 跳出."""
    from app.config import settings

    # 关掉 a / c 防干扰, 只测 b
    monkeypatch.setattr(settings, "UI_LOOP_GUARD_DUP_TOOL", False)
    monkeypatch.setattr(settings, "UI_LOOP_GUARD_STEP_TOKEN_SOFT", False)
    monkeypatch.setattr(settings, "UI_LOOP_GUARD_SNAPSHOT_DIFF", True)
    monkeypatch.setattr(settings, "UI_LOOP_GUARD_SNAPSHOT_DIFF_ROUNDS", 3)
    monkeypatch.setattr(settings, "UI_LOOP_GUARD_SNAPSHOT_DIFF_PCT", 0.05)

    exec_id = uuid.uuid4()
    rounds_b = [
        ChatRound(
            tool_calls=[ToolCallEmit(id=f"c{i}", name=f"{exec_id}__browser_snapshot", arguments_json="{}")],
            finish_reason="tool_calls",
            usage_total=10,
        )
        for i in range(5)  # 留余地, 实际应在第 3 轮触发
    ]
    fn, captured = chat_rounds(*rounds_b)
    # 把 fixed_snapshot 同时作为 initial_snapshot_text 喂进去, 让第 0 轮快照
    # diff_pct 已经是 0 (与基线一致), 这样第 3 轮工具调用后就能稳定触发.
    fixed_snapshot = "Page Title: Demo\n[ref=e1] button \"提交\""
    handler = lambda _: {"text": fixed_snapshot}  # noqa: E731

    runner = StepRunner(
        llm=make_llm(),
        environment=make_env(),
        budget=TokenBudget(limit=100_000),
        execution_id=exec_id,
        chat_round_fn=fn,
        tool_runner=FakeTool({f"{exec_id}__browser_snapshot": handler}),
    )
    out = await runner.run_one(
        step_description="反复 snapshot 页面不动",
        initial_snapshot_text=fixed_snapshot,
    )
    assert out.success is True
    assert out.loop_break_reason == "snapshot_unchanged"
    # 至多 3 轮就该触发, 不应跑到第 4 / 5 轮
    assert len(captured) <= 3
    assert out.tool_calls[-1].raw_name == "_meta_loop_guard"
    assert out.tool_calls[-1].result["break_reason"] == "snapshot_unchanged"
    assert len(out.tool_calls[-1].result["snapshot_diff_pct"]) >= 3
    assert all(p <= 0.05 for p in out.tool_calls[-1].result["snapshot_diff_pct"])


# ─── 信号 c: step_token_soft_budget_exceeded ──────────────────────────


@pytest.mark.asyncio
async def test_signal_c_step_token_soft_budget_breaks_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """单步消耗 >= 软上限 (20k floor) 触发, 即使全局 budget 还远未耗尽也停."""
    from app.config import settings

    monkeypatch.setattr(settings, "UI_LOOP_GUARD_DUP_TOOL", False)
    monkeypatch.setattr(settings, "UI_LOOP_GUARD_SNAPSHOT_DIFF", False)
    monkeypatch.setattr(settings, "UI_LOOP_GUARD_STEP_TOKEN_SOFT", True)
    monkeypatch.setattr(settings, "UI_STEP_TOKEN_SOFT_FLOOR", 20_000)

    exec_id = uuid.uuid4()
    fn, captured = chat_rounds(
        ChatRound(
            tool_calls=[ToolCallEmit(id="c1", name=f"{exec_id}__browser_click", arguments_json='{"ref":"e1"}')],
            finish_reason="tool_calls",
            usage_total=15_000,
        ),
        ChatRound(
            tool_calls=[ToolCallEmit(id="c2", name=f"{exec_id}__browser_click", arguments_json='{"ref":"e2"}')],
            finish_reason="tool_calls",
            usage_total=10_000,  # 累计 25k, 越过 20k floor
        ),
    )
    runner = StepRunner(
        llm=make_llm(),
        environment=make_env(),
        # 全局 budget 还有大把余量 -- 重点验"step soft != global hard"
        budget=TokenBudget(limit=500_000),
        execution_id=exec_id,
        chat_round_fn=fn,
        tool_runner=FakeTool({f"{exec_id}__browser_click": lambda _: {"ok": True}}),
    )
    out = await runner.run_one(
        step_description="点击按钮",
        # estimated_total_steps=10 -> derived = 500k*1.5/10 = 75k > floor 20k;
        # 为了让信号 c 在 25k 就触发, 我们需要 floor 起作用 -> 把 estimated 故意调到很大
        # 让 derived < floor.
        estimated_total_steps=200,
    )
    assert out.success is True
    assert out.loop_break_reason == "step_token_soft_budget_exceeded"
    assert len(captured) == 2
    assert out.tool_calls[-1].raw_name == "_meta_loop_guard"
    meta = out.tool_calls[-1].result
    assert meta["break_reason"] == "step_token_soft_budget_exceeded"
    assert meta["tokens_used_in_step"] >= 20_000
    assert meta["step_soft_budget"] == 20_000


# ─── 复杂表单不误伤: 5 轮多样工具 + 渐变快照 ──────────────────────────


@pytest.mark.asyncio
async def test_complex_form_with_diverse_tools_not_killed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """5 轮工具调用 (fill 不同字段 + click submit), 快照逐轮新增内容,
    token 远低于软上限 -> 不应被任何信号误伤."""
    from app.config import settings

    monkeypatch.setattr(settings, "UI_MAX_STEP_TOOL_ROUNDS", 8)

    exec_id = uuid.uuid4()
    # 用 browser_type / browser_click (在 SecurityGuard 白名单内), 每轮都返回不同
    # 行的 snapshot, 让 diff_pct 维持在 ~0.5 量级 (远高于 5% 阈值).
    fields = ["name", "email", "phone", "company", "submit"]
    rounds = []
    for i, field_name in enumerate(fields):
        is_submit = field_name == "submit"
        rounds.append(
            ChatRound(
                tool_calls=[
                    ToolCallEmit(
                        id=f"c{i}",
                        name=f"{exec_id}__{'browser_click' if is_submit else 'browser_type'}",
                        arguments_json=json.dumps({"ref": f"e{i}", "text": field_name}),
                    )
                ],
                finish_reason="tool_calls",
                usage_total=2_000,  # 5 轮 * 2k = 10k 远低于 20k floor
            )
        )
    rounds.append(ChatRound(content="表单已提交完成。", finish_reason="stop", usage_total=500))

    fn, captured = chat_rounds(*rounds)
    snapshots = iter([
        f"Page Title: Form\nfield_{i} value={field_name}\n[ref=e{i}] input"
        for i, field_name in enumerate(fields)
    ])

    def fill_handler(_args):
        return {"text": next(snapshots)}

    runner = StepRunner(
        llm=make_llm(),
        environment=make_env(),
        budget=TokenBudget(limit=200_000),
        execution_id=exec_id,
        chat_round_fn=fn,
        tool_runner=FakeTool({
            f"{exec_id}__browser_type": fill_handler,
            f"{exec_id}__browser_click": fill_handler,
            f"{exec_id}__browser_snapshot": lambda _: {"text": "final"},
        }),
    )
    out = await runner.run_one(
        step_description="填表并提交",
        estimated_total_steps=5,
    )
    assert out.success is True
    assert out.loop_break_reason is None  # 不应被早停
    assert len(captured) == 6  # 5 轮工具 + 1 轮收尾
    # 5 轮工具调用都正常落地
    deterministic_calls = [
        rec for rec in out.tool_calls
        if rec.raw_name not in ("_meta_loop_guard",)
    ]
    assert len(deterministic_calls) >= 5


# ─── _meta_loop_guard 节点契约 ────────────────────────────────────────


@pytest.mark.asyncio
async def test_meta_loop_guard_contains_required_fields() -> None:
    exec_id = uuid.uuid4()
    fn, _ = chat_rounds(
        ChatRound(
            tool_calls=[
                ToolCallEmit(id="c1", name=f"{exec_id}__browser_click", arguments_json='{"ref":"e1"}')
            ],
            finish_reason="tool_calls",
            usage_total=20,
        ),
        ChatRound(
            tool_calls=[
                ToolCallEmit(id="c2", name=f"{exec_id}__browser_click", arguments_json='{"ref":"e1"}')
            ],
            finish_reason="tool_calls",
            usage_total=20,
        ),
    )
    runner = StepRunner(
        llm=make_llm(),
        environment=make_env(),
        budget=TokenBudget(limit=10_000),
        execution_id=exec_id,
        chat_round_fn=fn,
        tool_runner=FakeTool({f"{exec_id}__browser_click": lambda _: {"ok": True}}),
    )
    out = await runner.run_one(step_description="点击")
    meta_rec = out.tool_calls[-1]
    assert meta_rec.raw_name == "_meta_loop_guard"
    assert meta_rec.blocked is False
    # 4 个必填字段
    payload = meta_rec.result
    assert "break_reason" in payload
    assert "signature_history" in payload
    assert "snapshot_diff_pct" in payload
    assert "tokens_used_in_step" in payload
    assert "step_soft_budget" in payload
