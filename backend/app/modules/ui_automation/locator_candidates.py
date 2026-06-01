"""Phase 15.6: 独立的 Playwright locator 候选构造模块.

历史上 ``_build_locator_candidates`` 与一堆 css/xpath helper 混在
``deterministic_runner.py`` 里, 单元测试很难只验 "候选生成顺序", 引入新增 anchor
策略 / label 同义词时也无法独立 patch. Phase 15.6 把候选构造完全抽到本模块:

- ``build_locator_candidates(page, target)`` 是唯一对外入口; 与原 ``_build_locator_candidates``
  行为兼容, 仅在 label 分支末尾 (受 ``settings.UI_LOCATOR_ANCHOR_BASED`` 开关控制) 追加:
    1. ``label`` 同义词 (基于内置 ``_DEFAULT_LABEL_ALIASES``, 不做项目级 alias 表
       避免复杂化, 命中后通过 deterministic 已有 ``count==1`` 校验).
    2. anchor-based input -- 找到 label/span/div 后用 sibling/following 取
       附近的 ``input``; 解决 ``<label>创作者ID</label><input ...>`` 这类没绑
       ``for=`` 的常见结构.
- 复用历史 helpers (``_optional_page_method`` / ``_optional_css_locator``
  / ``_css_string`` / ``_xpath_string`` / ``_looks_like_search_target``),
  迁移过来后保持原签名以便 deterministic_runner 直接 re-import.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.modules.ui_automation.action_plan import ActionTarget

# Phase 15.6: label 同义词. 命中候选会作为最低优先级追加, deterministic
# resolver 仍按 count==1 强制单匹配, 不会因为引入 alias 直接命中错元素.
# 表保持小而稳: ID 类 / 名称类 / 搜索类 / 时间类是历史 fill 失败 case 里
# 复发率最高的 4 个分组.
_DEFAULT_LABEL_ALIASES: dict[str, tuple[str, ...]] = {
    "ID": ("编号", "id"),
    "id": ("ID", "编号"),
    "编号": ("ID", "id"),
    "名称": ("名字", "title", "name"),
    "名字": ("名称", "title", "name"),
    "搜索": ("查询", "查找", "Search"),
    "查询": ("搜索", "查找", "Search"),
    "查找": ("搜索", "查询", "Search"),
    "时间": ("日期", "date", "time"),
    "日期": ("时间", "date"),
    "手机": ("手机号", "电话", "phone", "mobile"),
    "手机号": ("手机", "电话", "phone", "mobile"),
    "邮箱": ("Email", "email", "邮件"),
    "用户名": ("账号", "登录名", "username", "account"),
}


def _label_aliases(label: str) -> tuple[str, ...]:
    """返回 label 的同义词列表 (不含原 label 本身, 去重保持顺序)."""
    if not label:
        return ()
    seen: dict[str, None] = {}
    direct = _DEFAULT_LABEL_ALIASES.get(label, ())
    lowered = _DEFAULT_LABEL_ALIASES.get(label.lower(), ())
    for alias in (*direct, *lowered):
        if alias and alias != label and alias not in seen:
            seen[alias] = None
    return tuple(seen)


def _anchor_based_input_xpath(label: str) -> str:
    """构造 anchor-based input xpath: 找到 label/span/div 文本节点后跳到附近 input.

    与现有 input_xpath 的差异: 限定 sibling/descendant 关系, 不跨 form 边界,
    更适合 ``<label>名称</label><input/>`` / ``<div>姓名</div><input/>`` 这类
    没 ``for=`` 绑定的"裸 label + 紧邻 input"结构.
    """
    safe = _xpath_string(label)
    return (
        "xpath="
        # label[for] 已由 page.get_by_label 命中, 这里专攻无 for 关系的:
        "//*[self::label or self::span or self::div]"
        f"[normalize-space(.)={safe}]"
        "/following-sibling::*//input[not(@type='hidden')] | "
        "//*[self::label or self::span or self::div]"
        f"[normalize-space(.)={safe}]"
        "/following-sibling::input[not(@type='hidden')] | "
        "//*[self::label or self::span or self::div]"
        f"[normalize-space(.)={safe}]"
        "/parent::*/input[not(@type='hidden')]"
    )


def build_locator_candidates(
    page: Any,
    target: ActionTarget,
    *,
    enable_anchor_based: bool | None = None,
) -> list[tuple[Callable[[], Any | None], dict[str, Any]]]:
    """生成 Playwright locator 候选列表.

    返回元素是 ``(make_locator, details)``. ``make_locator`` 调用得到原始
    Playwright Locator (可能是 None), ``details`` 字典作为 evidence 落库, 让
    历史详情页能展示 "用了哪一条策略 / 哪个 selector 命中".

    Phase 15.6 新增:
    - ``enable_anchor_based``: 显式覆盖 settings.UI_LOCATOR_ANCHOR_BASED, 单测
      用; 不传时按 settings 走.
    """
    if enable_anchor_based is None:
        try:
            from app.config import settings as _settings  # noqa: PLC0415
            enable_anchor_based = bool(
                getattr(_settings, "UI_LOCATOR_ANCHOR_BASED", True),
            )
        except Exception:  # noqa: BLE001
            # config 不可用时按开 (默认行为更激进): anchor-based 候选只在 label 路径末尾追加,
            # 不会把已有正路径替换掉, 引入误命中风险极小.
            enable_anchor_based = True

    candidates: list[tuple[Callable[[], Any | None], dict[str, Any]]] = []

    def add(make_locator: Callable[[], Any | None], details: dict[str, Any]) -> None:
        candidates.append((make_locator, details))

    if target.role and target.name:
        add(
            lambda: _optional_page_method(
                page,
                "get_by_role",
                target.role,
                name=target.name,
            ),
            {
                "strategy": "role",
                "role": target.role,
                "name": target.name,
            },
        )
        if target.role == "button":
            add(
                lambda: _optional_page_method(
                    page,
                    "get_by_text",
                    target.name,
                    exact=True,
                ),
                {"strategy": "text", "text": target.name, "exact": True},
            )
            add(
                lambda: _optional_page_method(
                    page,
                    "get_by_text",
                    target.name,
                    exact=False,
                ),
                {"strategy": "text", "text": target.name, "exact": False},
            )
            add(
                lambda: _optional_css_locator(
                    page,
                    f"button:has-text({_css_string(target.name)})",
                ),
                {
                    "strategy": "css",
                    "selector": f"button:has-text({_css_string(target.name)})",
                },
            )
            add(
                lambda: _optional_css_locator(
                    page,
                    f"[role='button']:has-text({_css_string(target.name)})",
                ),
                {
                    "strategy": "css",
                    "selector": f"[role='button']:has-text({_css_string(target.name)})",
                },
            )
            add(
                lambda: _optional_css_locator(
                    page,
                    ".ant-btn:has-text({0}), .el-button:has-text({0}), "
                    ".n-button:has-text({0})".format(_css_string(target.name)),
                ),
                {
                    "strategy": "css",
                    "selector": (
                        ".ant-btn/.el-button/.n-button has text "
                        f"{target.name}"
                    ),
                },
            )
            button_xpath = (
                "xpath=//*[self::button or @role='button' or "
                "contains(@class, 'button') or contains(@class, 'btn') or "
                "contains(@class, 'el-button') or contains(@class, 'ant-btn') or "
                "contains(@class, 'n-button')]"
                f"[contains(normalize-space(.), {_xpath_string(target.name)})]"
            )
            add(
                lambda: _optional_css_locator(page, button_xpath),
                {"strategy": "xpath", "selector": button_xpath},
            )
        return candidates
    if target.label:
        _add_label_branch(
            candidates,
            page,
            label=target.label,
            enable_anchor_based=enable_anchor_based,
        )
        # Phase 15.6: 同义词候选放在最末 (最低优先级), 命中受 deterministic
        # resolver 的 count==1 约束保护; 同时把每个 alias 用同样的 label 分支
        # 重做一遍, 让 placeholder/aria-label/anchor 都跟着扩展.
        for alias in _label_aliases(target.label):
            _add_label_branch(
                candidates,
                page,
                label=alias,
                enable_anchor_based=enable_anchor_based,
                alias_of=target.label,
            )
        return candidates
    if target.placeholder:
        add(
            lambda: _optional_page_method(
                page,
                "get_by_placeholder",
                target.placeholder,
            ),
            {
                "strategy": "placeholder",
                "placeholder": target.placeholder,
            },
        )
        placeholder_selector = (
            f"input[placeholder*={_css_string(target.placeholder)}], "
            f"textarea[placeholder*={_css_string(target.placeholder)}]"
        )
        add(
            lambda: _optional_css_locator(page, placeholder_selector),
            {"strategy": "css", "selector": placeholder_selector},
        )
        return candidates
    if target.test_id:
        add(
            lambda: _optional_page_method(page, "get_by_test_id", target.test_id),
            {
                "strategy": "test_id",
                "test_id": target.test_id,
            },
        )
        return candidates
    if target.text:
        add(
            lambda: _optional_page_method(
                page,
                "get_by_text",
                target.text,
                exact=True,
            ),
            {"strategy": "text", "text": target.text, "exact": True},
        )
        return candidates
    if target.name:
        add(
            lambda: _optional_page_method(
                page,
                "get_by_text",
                target.name,
                exact=True,
            ),
            {"strategy": "text", "text": target.name, "exact": True},
        )
        return candidates
    return candidates


def _add_label_branch(
    candidates: list[tuple[Callable[[], Any | None], dict[str, Any]]],
    page: Any,
    *,
    label: str,
    enable_anchor_based: bool,
    alias_of: str | None = None,
) -> None:
    """label 路径下的 7 个候选 (含 anchor-based + searchbox), 抽出复用."""
    extra_meta: dict[str, Any] = {"alias_of": alias_of} if alias_of else {}

    def _add(make_locator: Callable[[], Any | None], details: dict[str, Any]) -> None:
        candidates.append((make_locator, {**details, **extra_meta}))

    _add(
        lambda: _optional_page_method(page, "get_by_label", label),
        {"strategy": "label", "label": label},
    )
    _add(
        lambda: _optional_page_method(page, "get_by_placeholder", label),
        {"strategy": "placeholder", "placeholder": label},
    )
    _add(
        lambda: _optional_page_method(page, "get_by_placeholder", f"请输入{label}"),
        {"strategy": "placeholder", "placeholder": f"请输入{label}"},
    )
    _add(
        lambda: _optional_page_method(page, "get_by_role", "textbox", name=label),
        {"strategy": "role", "role": "textbox", "name": label},
    )
    label_selector = (
        f"input[placeholder*={_css_string(label)}], "
        f"textarea[placeholder*={_css_string(label)}], "
        f"[aria-label*={_css_string(label)}]"
    )
    _add(
        lambda: _optional_css_locator(page, label_selector),
        {"strategy": "css", "selector": label_selector},
    )
    input_xpath = (
        "xpath=//input[not(@type='hidden') and "
        f"(contains(@placeholder, {_xpath_string(label)}) or "
        f"contains(@aria-label, {_xpath_string(label)}) or "
        f"contains(@name, {_xpath_string(label)}) or "
        f"contains(@id, {_xpath_string(label)}))] | "
        "//textarea["
        f"contains(@placeholder, {_xpath_string(label)}) or "
        f"contains(@aria-label, {_xpath_string(label)})] | "
        "//*[self::label or self::span or self::div]"
        f"[contains(normalize-space(.), {_xpath_string(label)})]"
        "/following::input[not(@type='hidden')][1]"
    )
    _add(
        lambda: _optional_css_locator(page, input_xpath),
        {"strategy": "xpath", "selector": input_xpath},
    )

    # Phase 15.6 anchor-based input: 处理 <label>名称</label><input/> 这种没绑
    # for= 的结构. 单独 selector 让前端 / 单测能直接识别"走的是 anchor 路径".
    if enable_anchor_based:
        anchor_xpath = _anchor_based_input_xpath(label)
        _add(
            lambda: _optional_css_locator(page, anchor_xpath),
            {"strategy": "anchor", "selector": anchor_xpath, "label": label},
        )

    if _looks_like_search_target(label):
        _add(
            lambda: _optional_page_method(page, "get_by_role", "searchbox"),
            {"strategy": "role", "role": "searchbox"},
        )
        search_selector = (
            "input[type='search'], [role='searchbox'], "
            "input[name*='search' i], input[id*='search' i], "
            "input[placeholder*='搜索'], input[aria-label*='搜索'], "
            "input[name='wd'], textarea[name='wd'], "
            "input[type='text'], textarea"
        )
        _add(
            lambda: _optional_css_locator(page, search_selector),
            {"strategy": "css", "selector": search_selector},
        )


def _optional_page_method(page: Any, method: str, *args: Any, **kwargs: Any) -> Any | None:
    fn = getattr(page, method, None)
    if not callable(fn):
        return None
    return fn(*args, **kwargs)


def _optional_css_locator(page: Any, selector: str) -> Any | None:
    locator_fn = getattr(page, "locator", None)
    if not callable(locator_fn):
        return None
    return locator_fn(selector)


def _looks_like_search_target(value: str | None) -> bool:
    text = str(value or "").strip().lower()
    if not text:
        return False
    return "搜索" in text or "search" in text


def _css_string(value: str) -> str:
    return repr(str(value))


def _xpath_string(value: str) -> str:
    text = str(value)
    if "'" not in text:
        return f"'{text}'"
    if '"' not in text:
        return f'"{text}"'
    parts = text.split("'")
    return "concat(" + ', "\'", '.join(f"'{part}'" for part in parts) + ")"


__all__ = [
    "build_locator_candidates",
]
