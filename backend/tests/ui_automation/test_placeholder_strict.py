"""Phase 15.5 - 占位符严格模式 + plan_compiler 接 data_resolver 单元测试.

覆盖:
- compile_action_plan 不传 resolver -> 旧行为 (含 {{xxx}} 但不报错, 由后续
  preflight / step_runner 处理).
- compile_action_plan 传 resolver -> 替换值 + 残留占位符 -> UNSUPPORTED 步骤
  ``unresolved_placeholder: ...``.
- _build_config_snapshot 把 preflight_alerts 落到 ``preflight_warnings``.
- preflight_data_check 找到的 missing key 与 plan_compiler 残留 key 交集.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.ui_automation.action_plan import UIActionKind
from app.modules.ui_automation.execution_engine import (
    ExecutionInputs,
    _build_config_snapshot,
)
from app.modules.ui_automation.plan_compiler import compile_action_plan
from app.modules.ui_automation.preflight import (
    MissingDataAlert,
    MissingStepRef,
    preflight_data_check,
)


class _FakeResolver:
    """最小 TestDataResolver 桩: 提供 render_template (按 mapping 替换), 缺 key 保留原文."""

    def __init__(self, values: dict[str, str]):
        self._values = values

    def render_template(self, text: str) -> str:
        if not text:
            return text
        out = text
        for k, v in self._values.items():
            out = out.replace(f"{{{{{k}}}}}", v)
        return out


def _step(step_number: int, action: str, expected: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        step_number=step_number,
        action=action,
        expected_result=expected,
    )


def _testcase(steps: list[SimpleNamespace], *, module_entry_path: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        steps=steps,
        module=SimpleNamespace(entry_path=module_entry_path) if module_entry_path else None,
    )


# ─── plan_compiler 接 data_resolver ───────────────────────────────────


def test_compile_without_resolver_keeps_legacy_behavior() -> None:
    tc = _testcase([_step(1, "在创作者 ID 输入框输入 {{creator_id}}")])
    result = compile_action_plan(tc)
    # 不传 resolver: 编译器拿到原文, fill 仍能识别"输入框输入"; 不被标 UNSUPPORTED
    assert all(s.kind != UIActionKind.UNSUPPORTED for s in result.plan.steps)


def test_compile_with_resolver_renders_known_placeholders() -> None:
    tc = _testcase(
        [_step(1, "在创作者 ID 输入框输入 {{creator_id}}")],
    )
    resolver = _FakeResolver({"creator_id": "C-9527"})
    result = compile_action_plan(tc, data_resolver=resolver)
    rendered = result.plan.steps[0]
    assert rendered.kind != UIActionKind.UNSUPPORTED
    assert "C-9527" in rendered.source_text


def test_compile_with_resolver_marks_unresolved_as_unsupported() -> None:
    tc = _testcase(
        [_step(1, "在创作者 ID 输入框输入 {{missing_key}}")],
    )
    resolver = _FakeResolver({})
    result = compile_action_plan(tc, data_resolver=resolver)
    compiled = result.plan.steps[0]
    assert compiled.kind == UIActionKind.UNSUPPORTED
    assert compiled.unsupported_reason
    assert "unresolved_placeholder" in compiled.unsupported_reason
    assert "missing_key" in compiled.unsupported_reason
    assert any("missing_key" in w for w in result.warnings)


def test_compile_partial_render_keeps_known_replaced_and_lists_missing() -> None:
    tc = _testcase(
        [_step(1, "搜索 {{name_keyword}} 创建者 {{missing_key}}", "看到 {{existing_creator_id}}")],
    )
    resolver = _FakeResolver({"name_keyword": "测试人", "existing_creator_id": "C-1"})
    result = compile_action_plan(tc, data_resolver=resolver)
    compiled = result.plan.steps[0]
    assert compiled.kind == UIActionKind.UNSUPPORTED
    assert "missing_key" in (compiled.unsupported_reason or "")
    # 已知 key 不应出现在 unsupported_reason 里
    assert "name_keyword" not in (compiled.unsupported_reason or "")
    assert "existing_creator_id" not in (compiled.unsupported_reason or "")


# ─── _build_config_snapshot 注入 preflight_warnings ───────────────────


def _make_inputs(**overrides: Any) -> ExecutionInputs:
    base: dict[str, Any] = dict(
        execution_id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        environment_id=None,
        triggered_by=uuid.uuid4(),
        testcase_ids=[uuid.uuid4()],
        llm_config_id=None,
    )
    base.update(overrides)
    return ExecutionInputs(**base)


def test_config_snapshot_serializes_preflight_alerts() -> None:
    alerts = [
        MissingDataAlert(
            key="creator_id",
            detected_in_steps=[
                MissingStepRef(testcase_id="00000000-0000-0000-0000-000000000001",
                               step_number=1, where="action"),
            ],
        ),
    ]
    snapshot = _build_config_snapshot(_make_inputs(), preflight_alerts=alerts)
    assert "preflight_warnings" in snapshot
    assert snapshot["preflight_warnings"][0]["key"] == "creator_id"


def test_config_snapshot_preflight_warnings_empty_when_no_alerts() -> None:
    snapshot = _build_config_snapshot(_make_inputs())
    assert snapshot["preflight_warnings"] == []


# ─── preflight_data_check 与 plan_compiler 协同 ───────────────────────


@pytest.mark.asyncio
async def test_preflight_and_compile_agree_on_missing_keys() -> None:
    tc = _testcase(
        [_step(1, "在 {{missing_key}} 输入框输入 {{another_miss}}")],
    )
    # resolver 没任何 key
    class _Empty:
        data: dict[str, Any] = {}

    alerts = await preflight_data_check([tc], _Empty())  # type: ignore[arg-type]
    missing = {a.key for a in alerts}
    assert {"missing_key", "another_miss"} <= missing

    # plan_compiler 也应给出相同的缺失 key 标记
    resolver = _FakeResolver({})
    result = compile_action_plan(tc, data_resolver=resolver)
    reason = result.plan.steps[0].unsupported_reason or ""
    assert "missing_key" in reason
    assert "another_miss" in reason
