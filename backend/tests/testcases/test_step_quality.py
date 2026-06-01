"""Phase 15.5 - validate_step_quality 单元测试。

覆盖 5 类提示 (empty / placeholder / hedging / too_long / anti_bot) 的命中和
不命中场景, 以及输入容错 (dict / 对象 / 空字段).
"""

from __future__ import annotations

from types import SimpleNamespace

from app.modules.testcases.step_quality import validate_step_quality


def _ns(step_number: int, action: str, expected_result: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        step_number=step_number,
        action=action,
        expected_result=expected_result,
    )


# ─── 单条 step / 单类警告命中 ──────────────────────────────────────────


def test_empty_action_emits_empty_action_warning() -> None:
    warnings = validate_step_quality([_ns(1, "")])
    assert len(warnings) == 1
    assert warnings[0].kind == "empty_action"
    assert warnings[0].step_number == 1


def test_unresolved_placeholder_lists_missing_keys() -> None:
    warnings = validate_step_quality(
        [_ns(2, "在创作者 ID 输入 {{creator_id}}", "列表显示 {{name_keyword}}")],
    )
    kinds = {w.kind for w in warnings}
    assert "unresolved_placeholder" in kinds
    msg = next(w.message for w in warnings if w.kind == "unresolved_placeholder")
    # 列出的占位符按字母序去重
    assert "creator_id" in msg
    assert "name_keyword" in msg


def test_hedging_word_emits_exploratory_phrasing() -> None:
    warnings = validate_step_quality(
        [_ns(3, "若有保存按钮则点击")],
    )
    assert any(w.kind == "exploratory_phrasing" for w in warnings)


def test_step_too_long_with_compound_indicator_emits_too_long() -> None:
    long_action = (
        "在用户名输入框输入用户名张三; 在邮箱输入框输入 zhangsan@example.com; "
        "然后在地址输入框继续输入北京市海淀区某街道; 最后在备注框输入这是一个测试"
    )
    assert len(long_action) > 80
    warnings = validate_step_quality([_ns(4, long_action)])
    kinds = {w.kind for w in warnings}
    assert "step_too_long" in kinds


def test_anti_bot_host_emits_external_warning() -> None:
    warnings = validate_step_quality(
        [_ns(5, "打开 https://www.baidu.com 搜索")],
    )
    assert any(w.kind == "external_anti_bot_host" for w in warnings)


# ─── 不命中场景 ────────────────────────────────────────────────────────


def test_clean_step_yields_no_warnings() -> None:
    warnings = validate_step_quality(
        [_ns(1, "点击保存按钮", "提示『保存成功』")],
    )
    assert warnings == []


def test_long_step_without_indicator_does_not_emit_too_long() -> None:
    # 长但只是单一动作描述 -- 不报 step_too_long
    long_single_action = "前往用户管理页面查看张三这个账号的所有历史登录记录并核对最近的 IP 地址"
    warnings = validate_step_quality([_ns(1, long_single_action)])
    assert all(w.kind != "step_too_long" for w in warnings)


# ─── 输入容错 ──────────────────────────────────────────────────────────


def test_supports_dict_input() -> None:
    warnings = validate_step_quality(
        [
            {"step_number": 7, "action": "若有清空按钮则点击", "expected_result": None},
        ],
    )
    assert any(w.kind == "exploratory_phrasing" and w.step_number == 7 for w in warnings)


def test_warnings_sorted_by_step_then_kind() -> None:
    warnings = validate_step_quality(
        [
            _ns(2, "尝试登录"),
            _ns(1, "在 {{username}} 输入框输入 admin"),
        ],
    )
    # step 1 占位符 + step 2 hedging, 按 step 升序
    assert warnings[0].step_number == 1
    assert warnings[-1].step_number == 2


def test_dataset_combination_emits_multiple_warnings() -> None:
    warnings = validate_step_quality(
        [
            _ns(
                1,
                "若有 {{action}} 按钮; 在 {{username}} 输入用户名; 在 {{password}} 输入密码; 点击登录",
                "登录成功",
            ),
        ],
    )
    kinds = {w.kind for w in warnings}
    # 同一步 step 同时含 hedging + placeholder + 长度复合指标
    assert {"unresolved_placeholder", "exploratory_phrasing"} <= kinds
