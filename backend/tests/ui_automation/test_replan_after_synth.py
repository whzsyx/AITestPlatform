"""Phase 15.11 — 占位符自造后重编 plan 单元测试.

覆盖目标:
1. 同一 testcase 下, resolver 缺 key 时编译为 ``UNSUPPORTED``;
   把 key 注入 resolver 后**再次** ``compile_action_plan``,
   原 UNSUPPORTED 步骤升级为 ``FILL`` 等可识别动作.
2. ``_merge_replanned_compiled_steps`` 合并策略:
   - 原 ``UNSUPPORTED`` 被新 ``FILL`` 覆盖
   - 原已识别 step 不被新结果覆盖 (即便新结果换了 kind)
   - 新结果仍 ``UNSUPPORTED`` 不入合并
   - ``base`` 中没有但 ``fresh`` 中有的新 step 直接添加
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from app.modules.ui_automation.action_plan import (
    ActionTarget,
    UIActionKind,
    UIActionStep,
)
from app.modules.ui_automation.execution_engine import (
    _merge_replanned_compiled_steps,
)
from app.modules.ui_automation.plan_compiler import compile_action_plan


class _ResolverStub:
    """最小 TestDataResolver 桩: 只实现 plan_compiler 用得到的 ``render_template``."""

    def __init__(self, values: dict[str, str]):
        self._values = dict(values)

    def render_template(self, text: str) -> str:
        if not text:
            return text
        out = text
        for k, v in self._values.items():
            out = out.replace(f"{{{{{k}}}}}", v)
        return out

    def inject(self, key: str, value: str) -> None:
        self._values[key] = value


def _step(step_number: int, action: str, expected: str = "") -> SimpleNamespace:
    return SimpleNamespace(
        step_number=step_number,
        action=action,
        expected_result=expected,
    )


def _testcase(steps: list[SimpleNamespace]) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        steps=steps,
        module=None,
    )


def test_replan_after_resolver_inject_upgrades_unsupported_step() -> None:
    """模拟首轮编译占位符未解析, _materialize 注入后二次编译升级为 FILL."""
    tc = _testcase([
        _step(1, "在「创作者ID」输入框输入 {{creator_id_combined}}", "输入框值显示为 {{creator_id_combined}}"),
        _step(2, "点击「查询」按钮", "查询完成"),
    ])
    resolver = _ResolverStub({})

    first = compile_action_plan(tc, data_resolver=resolver)
    by_first = {s.source_step_number: s for s in first.plan.steps if s.source_step_number}
    assert by_first[1].kind == UIActionKind.UNSUPPORTED
    assert by_first[1].unsupported_reason is not None
    assert "creator_id_combined" in by_first[1].unsupported_reason
    # step 2 不依赖占位符, 第一轮就已经 click
    assert by_first[2].kind == UIActionKind.CLICK

    resolver.inject("creator_id_combined", "2013,2012")

    second = compile_action_plan(tc, data_resolver=resolver)
    by_second = {s.source_step_number: s for s in second.plan.steps if s.source_step_number}
    assert by_second[1].kind == UIActionKind.FILL
    assert by_second[1].value == "2013,2012"
    assert by_second[1].target.label == "创作者ID"


def test_merge_replanned_overwrites_unsupported_only() -> None:
    """合并策略: UNSUPPORTED 才被覆盖, 已识别 step 保持原样."""
    base = {
        1: _unsupported_step(1, "占位符未解析"),
        2: _click_step(2, "查询"),
    }
    fresh = {
        1: _fill_step(1, label="创作者ID", value="2013"),
        2: _fill_step(2, label="另一个", value="x"),
    }

    upgraded = _merge_replanned_compiled_steps(base=base, fresh=fresh)

    assert upgraded == [1]
    assert base[1].kind == UIActionKind.FILL
    assert base[1].value == "2013"
    # step 2 之前已是 CLICK, 不该被新的 FILL 覆盖
    assert base[2].kind == UIActionKind.CLICK


def test_merge_replanned_skips_still_unsupported() -> None:
    """新一轮仍 UNSUPPORTED 的 step 不进入合并."""
    base = {1: _unsupported_step(1, "原始未解析")}
    fresh = {1: _unsupported_step(1, "二次仍未解析")}

    upgraded = _merge_replanned_compiled_steps(base=base, fresh=fresh)

    assert upgraded == []
    assert base[1].kind == UIActionKind.UNSUPPORTED
    # 不能用"二次仍未解析"覆盖原 reason, 保留首轮编译结果方便审计
    assert base[1].unsupported_reason == "原始未解析"


def test_merge_replanned_adds_brand_new_step() -> None:
    """fresh 里有 base 没有的 step (比如插入了新动作), 直接补进去."""
    base = {1: _click_step(1, "查询")}
    fresh = {
        1: _click_step(1, "查询"),
        2: _fill_step(2, label="名称", value="alpha"),
    }

    upgraded = _merge_replanned_compiled_steps(base=base, fresh=fresh)

    assert upgraded == [2]
    assert base[2].kind == UIActionKind.FILL
    assert base[2].value == "alpha"


def _fill_step(step_number: int, *, label: str, value: str) -> UIActionStep:
    return UIActionStep(
        source_step_number=step_number,
        source_text=f"在「{label}」输入框输入 {value}",
        kind=UIActionKind.FILL,
        target=ActionTarget(label=label),
        value=value,
        confidence=0.78,
        requires_evidence=["form_fields"],
        risk_level="low",
    )


def _click_step(step_number: int, name: str) -> UIActionStep:
    return UIActionStep(
        source_step_number=step_number,
        source_text=f"点击「{name}」按钮",
        kind=UIActionKind.CLICK,
        target=ActionTarget(role="button", name=name),
        confidence=0.82,
        requires_evidence=["locator_match"],
        risk_level="medium",
    )


def _unsupported_step(step_number: int, reason: str) -> UIActionStep:
    return UIActionStep(
        source_step_number=step_number,
        source_text="占位符 step",
        kind=UIActionKind.UNSUPPORTED,
        target=ActionTarget(),
        confidence=0.0,
        requires_evidence=[],
        risk_level="medium",
        unsupported_reason=reason,
    )
