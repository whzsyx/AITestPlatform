"""Phase 15.6 - locator_candidates.build_locator_candidates 单元测试.

覆盖 4 类 fill 结构 (label for / sibling label / placeholder / aria-label) 都能
出现在候选列表中, 同义词 alias 也按预期追加. 不依赖真实浏览器, 通过 _FakePage
桩记录 (method, args, kwargs).
"""

from __future__ import annotations

from typing import Any

from app.modules.ui_automation.action_plan import ActionTarget
from app.modules.ui_automation.locator_candidates import (
    _DEFAULT_LABEL_ALIASES,
    _label_aliases,
    build_locator_candidates,
)


class _FakePage:
    """记录所有 get_by_* / locator 调用, 不返回真 locator."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def __getattr__(self, name: str):
        # role / label / placeholder / test_id / text / locator 全部走通用 record
        def _record(*args: Any, **kwargs: Any) -> str:
            self.calls.append((name, args, kwargs))
            return f"<{name}:{args}:{kwargs}>"
        return _record


# ─── label 路径覆盖 ────────────────────────────────────────────────────


def test_label_branch_emits_anchor_based_when_setting_enabled() -> None:
    page = _FakePage()
    target = ActionTarget(label="创建者ID")
    cands = build_locator_candidates(page, target, enable_anchor_based=True)
    strategies = [d.get("strategy") for _, d in cands]
    # 确保 anchor 策略出现 (新增的关键)
    assert "anchor" in strategies, f"anchor 候选缺失, got: {strategies}"
    # 同时 label / placeholder / role(textbox) / css 都还在
    assert "label" in strategies
    assert "placeholder" in strategies
    assert "role" in strategies
    assert "css" in strategies
    assert "xpath" in strategies


def test_label_branch_skips_anchor_when_setting_disabled() -> None:
    page = _FakePage()
    target = ActionTarget(label="创建者ID")
    cands = build_locator_candidates(page, target, enable_anchor_based=False)
    strategies = [d.get("strategy") for _, d in cands]
    assert "anchor" not in strategies
    assert "label" in strategies  # 旧路径仍在


def test_label_alias_expansion_runs_full_branch_per_alias() -> None:
    page = _FakePage()
    target = ActionTarget(label="ID")
    cands = build_locator_candidates(page, target, enable_anchor_based=True)
    # alias_of 字段标记的候选必然是 alias 扩展产生的
    alias_details = [d for _, d in cands if d.get("alias_of")]
    assert alias_details, "ID 同义词应至少扩展出一组候选"
    # 包含至少一种从 _DEFAULT_LABEL_ALIASES['ID'] 来的同义词 (编号 / id)
    aliased_labels = {d.get("label") or d.get("placeholder") for d in alias_details}
    assert {"编号", "id"} & set(filter(None, aliased_labels))


def test_label_branch_includes_searchbox_for_search_targets() -> None:
    page = _FakePage()
    target = ActionTarget(label="搜索")
    cands = build_locator_candidates(page, target, enable_anchor_based=True)
    # 命中搜索类时应有 role=searchbox
    assert any(
        d.get("strategy") == "role" and d.get("role") == "searchbox"
        for _, d in cands
    )


# ─── 4 种结构验证 (placeholder / aria-label / label sibling / label for) ──


def test_placeholder_only_branch() -> None:
    page = _FakePage()
    target = ActionTarget(placeholder="输入名称")
    cands = build_locator_candidates(page, target)
    strategies = {d.get("strategy") for _, d in cands}
    assert {"placeholder", "css"} <= strategies


def test_test_id_branch() -> None:
    page = _FakePage()
    target = ActionTarget(test_id="user-name-input")
    cands = build_locator_candidates(page, target)
    strategies = {d.get("strategy") for _, d in cands}
    assert "test_id" in strategies


def test_text_branch_only_for_pure_text_target() -> None:
    page = _FakePage()
    target = ActionTarget(text="提交订单")
    cands = build_locator_candidates(page, target)
    strategies = {d.get("strategy") for _, d in cands}
    assert "text" in strategies


def test_role_button_branch_keeps_legacy_xpath_candidates() -> None:
    page = _FakePage()
    target = ActionTarget(role="button", name="保存")
    cands = build_locator_candidates(page, target)
    strategies = [d.get("strategy") for _, d in cands]
    # role / text / css / xpath 至少各出现一次
    assert "role" in strategies
    assert "text" in strategies
    assert "css" in strategies
    assert "xpath" in strategies


# ─── alias helper 自身的边界 ───────────────────────────────────────────


def test_label_aliases_unique_and_exclude_self() -> None:
    aliases = _label_aliases("ID")
    assert "ID" not in aliases
    assert len(aliases) == len(set(aliases))


def test_label_aliases_empty_for_unknown_label() -> None:
    assert _label_aliases("某个完全不存在的 label") == ()


def test_default_aliases_dict_consistency() -> None:
    # Sanity check: 字典里互为逆向对应的 key 至少出现一对
    assert "ID" in _DEFAULT_LABEL_ALIASES
    assert "编号" in _DEFAULT_LABEL_ALIASES
    assert "id" in _DEFAULT_LABEL_ALIASES["ID"]
