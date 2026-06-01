from __future__ import annotations

from typing import Any

import pytest

from app.modules.ui_automation.action_plan import ActionTarget, UIActionKind, UIActionStep
from app.modules.ui_automation.deterministic_runner import DeterministicRunner


class _FakeLocator:
    def __init__(
        self,
        *,
        count: int = 1,
        text: str = "",
        count_sequence: list[int] | None = None,
        visible_locator: "_FakeLocator | None" = None,
        best_index: int | None = None,
        nth_locators: dict[int, "_FakeLocator"] | None = None,
    ) -> None:
        self._count = count
        self._count_sequence = list(count_sequence or [])
        self._visible_locator = visible_locator
        self._best_index = best_index
        self._nth_locators = dict(nth_locators or {})
        self.text = text
        self.clicked = False
        self.filled_with: str | None = None
        self.selected_value: str | None = None

    async def count(self) -> int:
        if self._count_sequence:
            return self._count_sequence.pop(0)
        return self._count

    def filter(self, **kwargs: Any) -> "_FakeLocator":
        if kwargs.get("visible") is True and self._visible_locator is not None:
            return self._visible_locator
        return self

    async def evaluate_all(self, _script: str, _arg: dict[str, Any] | None = None):
        return {"best_index": self._best_index}

    def nth(self, index: int) -> "_FakeLocator":
        return self._nth_locators.get(index, self)

    async def click(self, **_kwargs: Any) -> None:
        self.clicked = True

    async def fill(self, value: str, **_kwargs: Any) -> None:
        self.filled_with = value

    async def select_option(self, value: str, **_kwargs: Any) -> None:
        self.selected_value = value

    async def inner_text(self, **_kwargs: Any) -> str:
        return self.text


class _FakePage:
    def __init__(self) -> None:
        self.url = "https://example.com/admin"
        self.calls: list[tuple[str, Any]] = []
        self.locators: dict[tuple[str, str], _FakeLocator] = {}
        self.evaluate_results: list[dict[str, Any]] = []
        self.goto_url: str | None = None
        self.waited_url: str | None = None
        self.keyboard = _FakeKeyboard(self.calls)

    def set_locator(self, kind: str, key: str, locator: _FakeLocator) -> _FakeLocator:
        self.locators[(kind, key)] = locator
        return locator

    async def goto(self, url: str, **_kwargs: Any) -> None:
        self.calls.append(("goto", url))
        self.goto_url = url
        self.url = url

    async def wait_for_url(self, url: str, **_kwargs: Any) -> None:
        self.calls.append(("wait_for_url", url))
        self.waited_url = url
        self.url = url

    async def wait_for_timeout(self, ms: int) -> None:
        self.calls.append(("wait_for_timeout", ms))

    def get_by_role(self, role: str, *, name: str | None = None):
        self.calls.append(("get_by_role", {"role": role, "name": name}))
        key = f"{role}:{name}" if name is not None else role
        return self.locators.get(("role", key), _FakeLocator(count=0))

    def get_by_label(self, label: str):
        self.calls.append(("get_by_label", label))
        return self.locators.get(("label", label), _FakeLocator(count=0))

    def get_by_placeholder(self, placeholder: str):
        self.calls.append(("get_by_placeholder", placeholder))
        return self.locators.get(("placeholder", placeholder), _FakeLocator(count=0))

    def get_by_test_id(self, test_id: str):
        self.calls.append(("get_by_test_id", test_id))
        return self.locators.get(("test_id", test_id), _FakeLocator(count=0))

    def get_by_text(self, text: str, *, exact: bool = True):
        self.calls.append(("get_by_text", {"text": text, "exact": exact}))
        return self.locators.get(("text", text), _FakeLocator(count=0))

    def locator(self, selector: str):
        self.calls.append(("locator", selector))
        return self.locators.get(("css", selector), _FakeLocator(count=0))

    async def evaluate(self, _script: str, _arg: dict[str, Any] | None = None):
        self.calls.append(("evaluate", _arg or {}))
        if self.evaluate_results:
            return self.evaluate_results.pop(0)
        return {}


class _FakeKeyboard:
    def __init__(self, calls: list[tuple[str, Any]]) -> None:
        self.calls = calls

    async def press(self, key: str) -> None:
        self.calls.append(("keyboard_press", key))


@pytest.mark.asyncio
async def test_navigate_uses_page_goto_and_returns_evidence() -> None:
    page = _FakePage()
    step = UIActionStep(
        source_text="进入店铺列表",
        kind=UIActionKind.NAVIGATE,
        target=ActionTarget(url="https://example.com/admin/stores"),
    )

    result = await DeterministicRunner().run_step(page, step)

    assert result.success is True
    assert result.evidence.action_kind == UIActionKind.NAVIGATE
    assert result.evidence.details["url"] == "https://example.com/admin/stores"
    assert page.goto_url == "https://example.com/admin/stores"


@pytest.mark.asyncio
async def test_navigate_resolves_runtime_template_variables() -> None:
    page = _FakePage()
    step = UIActionStep(
        source_text="打开模块入口",
        kind=UIActionKind.NAVIGATE,
        target=ActionTarget(url="{{module.entry_url}}"),
    )

    result = await DeterministicRunner(
        variables={"module.entry_url": "https://example.com/admin/stores"},
    ).run_step(page, step)

    assert result.success is True
    assert page.goto_url == "https://example.com/admin/stores"


@pytest.mark.asyncio
async def test_click_uses_strict_role_locator_and_does_not_call_llm() -> None:
    page = _FakePage()
    locator = page.set_locator("role", "button:新增", _FakeLocator(count=1))
    step = UIActionStep(
        source_text="点击新增按钮",
        kind=UIActionKind.CLICK,
        target=ActionTarget(role="button", name="新增"),
    )

    result = await DeterministicRunner().run_step(page, step)

    assert result.success is True
    assert locator.clicked is True
    assert page.calls[0] == ("get_by_role", {"role": "button", "name": "新增"})
    assert result.evidence.execution_path == "deterministic"


@pytest.mark.asyncio
async def test_locator_not_found_returns_structured_fallback_result() -> None:
    page = _FakePage()
    step = UIActionStep(
        source_text="点击查询按钮",
        kind=UIActionKind.CLICK,
        target=ActionTarget(role="button", name="查询"),
    )

    result = await DeterministicRunner().run_step(page, step)

    assert result.success is False
    assert result.evidence.action_kind == UIActionKind.CLICK
    assert result.evidence.error_kind == "locator_not_found"
    assert result.fallback_recommended is True
    assert "查询" in result.evidence.message


@pytest.mark.asyncio
async def test_fill_falls_back_from_label_to_placeholder_locator() -> None:
    page = _FakePage()
    placeholder_locator = page.set_locator(
        "placeholder",
        "创作者名称",
        _FakeLocator(count=1),
    )
    step = UIActionStep(
        source_text="在创作者名称输入框输入 测试创作者",
        kind=UIActionKind.FILL,
        target=ActionTarget(label="创作者名称"),
        value="测试创作者",
    )

    result = await DeterministicRunner().run_step(page, step)

    assert result.success is True
    assert placeholder_locator.filled_with == "测试创作者"
    assert result.evidence.details["strategy"] == "placeholder"
    assert ("get_by_label", "创作者名称") in page.calls
    assert ("get_by_placeholder", "创作者名称") in page.calls


@pytest.mark.asyncio
async def test_fill_generic_search_box_uses_searchbox_role_fallback() -> None:
    page = _FakePage()
    searchbox_locator = page.set_locator("role", "searchbox", _FakeLocator(count=1))
    step = UIActionStep(
        source_text="在「搜索框」中输入“北京天气”",
        kind=UIActionKind.FILL,
        target=ActionTarget(label="搜索框"),
        value="北京天气",
    )

    result = await DeterministicRunner().run_step(page, step)

    assert result.success is True
    assert searchbox_locator.filled_with == "北京天气"
    assert result.evidence.details["strategy"] == "role"
    assert ("get_by_role", {"role": "searchbox", "name": None}) in page.calls


@pytest.mark.asyncio
async def test_click_falls_back_from_role_button_to_visible_text() -> None:
    page = _FakePage()
    text_locator = page.set_locator("text", "添加创作者", _FakeLocator(count=1))
    step = UIActionStep(
        source_text="点击添加创作者按钮",
        kind=UIActionKind.CLICK,
        target=ActionTarget(role="button", name="添加创作者"),
    )

    result = await DeterministicRunner().run_step(page, step)

    assert result.success is True
    assert text_locator.clicked is True
    assert result.evidence.details["strategy"] == "text"
    assert ("get_by_role", {"role": "button", "name": "添加创作者"}) in page.calls
    assert ("get_by_text", {"text": "添加创作者", "exact": True}) in page.calls


@pytest.mark.asyncio
async def test_click_waits_for_spa_locator_to_appear() -> None:
    page = _FakePage()
    locator = page.set_locator(
        "role",
        "button:添加创作者",
        _FakeLocator(count_sequence=[0, 0, 1]),
    )
    step = UIActionStep(
        source_text="点击添加创作者按钮",
        kind=UIActionKind.CLICK,
        target=ActionTarget(role="button", name="添加创作者"),
    )

    result = await DeterministicRunner(timeout_ms=500).run_step(page, step)

    assert result.success is True
    assert locator.clicked is True


@pytest.mark.asyncio
async def test_fill_uses_unique_visible_locator_when_placeholder_has_hidden_duplicates() -> None:
    page = _FakePage()
    visible = _FakeLocator(count=1)
    page.set_locator(
        "placeholder",
        "创作者名称",
        _FakeLocator(count=3, visible_locator=visible),
    )
    step = UIActionStep(
        source_text="在创作者名称输入框输入 测试",
        kind=UIActionKind.FILL,
        target=ActionTarget(label="创作者名称"),
        value="测试",
    )

    result = await DeterministicRunner().run_step(page, step)

    assert result.success is True
    assert visible.filled_with == "测试"
    assert result.evidence.details["visible_count"] == 1


@pytest.mark.asyncio
async def test_fill_disambiguates_duplicate_visible_textboxes_by_editable_score() -> None:
    page = _FakePage()
    chosen = _FakeLocator(count=1)
    page.set_locator(
        "placeholder",
        "创作者ID",
        _FakeLocator(
            count=3,
            visible_locator=_FakeLocator(count=3),
            best_index=1,
            nth_locators={1: chosen},
        ),
    )
    step = UIActionStep(
        source_text="在创作者ID输入框输入 123456",
        kind=UIActionKind.FILL,
        target=ActionTarget(label="创作者ID"),
        value="123456",
    )

    result = await DeterministicRunner().run_step(page, step)

    assert result.success is True
    assert chosen.filled_with == "123456"
    assert result.evidence.details["best_index"] == 1


@pytest.mark.asyncio
async def test_click_collects_post_action_structured_evidence_for_assertion() -> None:
    page = _FakePage()
    locator = page.set_locator("role", "button:添加创作者", _FakeLocator(count=1))
    page.evaluate_results.extend(
        [
            {"url": "https://example.com/admin/creators", "title": "创作者管理", "headings": []},
            {"texts": ["添加创作者", "创作者名称", "创作者简介", "创作者头像"]},
            {
                "fields": [
                    {"label": "创作者名称", "placeholder": "创作者名称"},
                    {"label": "创作者简介", "placeholder": "创作者简介"},
                    {"label": "创作者头像", "placeholder": "创作者头像"},
                ],
            },
            {"columns": [], "visible_columns": [], "total_columns": 0},
            {"columns": [], "rows": [], "row_count": 0},
        ],
    )
    step = UIActionStep(
        source_text="点击添加创作者按钮",
        kind=UIActionKind.CLICK,
        target=ActionTarget(role="button", name="添加创作者"),
    )

    result = await DeterministicRunner().run_step(page, step)

    assert result.success is True
    assert locator.clicked is True
    structured = result.evidence.details["structured_evidence"]
    assert "添加创作者" in structured["page_text"]["texts"]
    assert structured["form_fields"]["fields"][0]["label"] == "创作者名称"


@pytest.mark.asyncio
async def test_ambiguous_locator_does_not_click_first_match() -> None:
    page = _FakePage()
    locator = page.set_locator("role", "button:查询", _FakeLocator(count=2))
    step = UIActionStep(
        source_text="点击查询按钮",
        kind=UIActionKind.CLICK,
        target=ActionTarget(role="button", name="查询"),
    )

    result = await DeterministicRunner().run_step(page, step)

    assert result.success is False
    assert result.evidence.error_kind == "locator_ambiguous"
    assert locator.clicked is False
    assert result.fallback_recommended is True


@pytest.mark.asyncio
async def test_dangerous_click_requires_explicit_source_step() -> None:
    page = _FakePage()
    locator = page.set_locator("role", "button:删除", _FakeLocator(count=1))
    step = UIActionStep(
        source_text="点击更多操作按钮",
        kind=UIActionKind.CLICK,
        target=ActionTarget(role="button", name="删除"),
    )

    result = await DeterministicRunner().run_step(page, step)

    assert result.success is False
    assert result.evidence.error_kind == "dangerous_action_blocked"
    assert locator.clicked is False
    assert result.fallback_recommended is False


@pytest.mark.asyncio
async def test_fill_select_wait_and_assertions() -> None:
    page = _FakePage()
    name_field = page.set_locator("label", "店铺名称", _FakeLocator(count=1))
    platform_select = page.set_locator("label", "平台", _FakeLocator(count=1))
    page.set_locator("text", "保存成功", _FakeLocator(count=1, text="保存成功"))

    runner = DeterministicRunner()
    fill_result = await runner.run_step(
        page,
        UIActionStep(
            source_text="填写店铺名称",
            kind=UIActionKind.FILL,
            target=ActionTarget(label="店铺名称"),
            value="旗舰店",
        ),
    )
    select_result = await runner.run_step(
        page,
        UIActionStep(
            source_text="选择平台",
            kind=UIActionKind.SELECT,
            target=ActionTarget(label="平台"),
            value="天猫",
        ),
    )
    wait_result = await runner.run_step(
        page,
        UIActionStep(
            source_text="等待进入详情页",
            kind=UIActionKind.WAIT_FOR_URL,
            target=ActionTarget(url="**/admin/stores/detail"),
        ),
    )
    url_result = await runner.run_step(
        page,
        UIActionStep(
            source_text="验证URL包含详情页",
            kind=UIActionKind.ASSERT_URL,
            target=ActionTarget(url="/admin/stores/detail"),
        ),
    )
    text_result = await runner.run_step(
        page,
        UIActionStep(
            source_text="验证页面显示保存成功",
            kind=UIActionKind.ASSERT_TEXT,
            target=ActionTarget(text="保存成功"),
        ),
    )

    assert fill_result.success is True
    assert name_field.filled_with == "旗舰店"
    assert select_result.success is True
    assert platform_select.selected_value == "天猫"
    assert wait_result.success is True
    assert page.waited_url == "**/admin/stores/detail"
    assert url_result.success is True
    assert text_result.success is True


@pytest.mark.asyncio
async def test_press_key_uses_page_keyboard_and_collects_evidence() -> None:
    page = _FakePage()
    page.evaluate_results.extend(
        [
            {"url": "https://example.com/search?q=test", "title": "搜索结果", "headings": []},
            {"texts": ["搜索结果", "test"]},
            {"fields": []},
            {"columns": [], "visible_columns": [], "total_columns": 0},
            {"columns": [], "rows": [], "row_count": 0},
        ],
    )
    step = UIActionStep(
        source_text="按下键盘「Enter」键",
        kind=UIActionKind.PRESS_KEY,
        value="Enter",
    )

    result = await DeterministicRunner().run_step(page, step)

    assert result.success is True
    assert ("keyboard_press", "Enter") in page.calls
    structured = result.evidence.details["structured_evidence"]
    assert structured["page_identity"]["title"] == "搜索结果"


@pytest.mark.asyncio
async def test_assert_table_columns_uses_structured_evidence() -> None:
    page = _FakePage()
    page.evaluate_results.append(
        {
            "table_hint": "店铺列表",
            "columns": ["店铺ID", "店铺名称", "平台"],
            "visible_columns": ["店铺ID", "店铺名称", "平台"],
            "total_columns": 3,
        },
    )
    step = UIActionStep(
        source_text="验证店铺列表列名包含店铺ID、店铺名称、平台",
        kind=UIActionKind.ASSERT_TABLE_COLUMNS,
        target=ActionTarget(table_hint="店铺列表", columns=["店铺ID", "店铺名称", "平台"]),
    )

    result = await DeterministicRunner().run_step(page, step)

    assert result.success is True
    assert result.evidence.details["structured_evidence"]["table_schema"]["columns"] == [
        "店铺ID",
        "店铺名称",
        "平台",
    ]


@pytest.mark.asyncio
async def test_assert_page_loaded_requires_url_and_page_evidence() -> None:
    page = _FakePage()
    page.url = "https://example.com/admin/stores"
    page.evaluate_results.extend(
        [
            {
                "url": "https://example.com/admin/stores",
                "title": "店铺管理",
                "headings": ["店铺管理"],
            },
            {
                "table_hint": None,
                "columns": ["店铺ID", "店铺名称", "平台"],
                "visible_columns": ["店铺ID", "店铺名称", "平台"],
                "total_columns": 3,
            },
        ],
    )
    step = UIActionStep(
        source_text="进入店铺列表页面",
        kind=UIActionKind.ASSERT_PAGE_LOADED,
        target=ActionTarget(url="{{module.entry_url}}"),
    )

    result = await DeterministicRunner(
        variables={"module.entry_url": "https://example.com/admin/stores"},
    ).run_step(page, step)

    assert result.success is True
    assert "采集到 3 个表格列" in result.evidence.message
    assert result.evidence.details["structured_evidence"]["page_identity"]["title"] == "店铺管理"


@pytest.mark.asyncio
async def test_assert_form_values_uses_dom_field_state() -> None:
    page = _FakePage()
    page.evaluate_results.append(
        {
            "fields": [
                {
                    "label": "店铺ID",
                    "value": "S001",
                    "readonly": True,
                    "disabled": False,
                    "tag_name": "input",
                    "type": "text",
                },
            ],
        },
    )
    step = UIActionStep(
        source_text="验证店铺ID字段只读",
        kind=UIActionKind.ASSERT_FORM_VALUES,
        value="店铺ID字段只读",
    )

    result = await DeterministicRunner().run_step(page, step)

    assert result.success is True
    assert result.evidence.details["structured_evidence"]["form_fields"]["fields"][0][
        "readonly"
    ] is True


# ─── Phase 15.4b: extra_locator_candidates 自愈接入 ─────────────────────


@pytest.mark.asyncio
async def test_extra_locator_candidate_picks_up_when_default_misses() -> None:
    """LLM 自愈给 css=".save-btn" -> 默认 6 个候选 count=0, 自愈候选 count=1
    通过 strict 校验后被选中执行点击."""
    page = _FakePage()
    # 默认 role/text 候选全部 count=0 -> 进自愈候选
    self_heal_locator = page.set_locator("css", ".save-btn", _FakeLocator(count=1))
    step = UIActionStep(
        source_text="点击保存按钮",
        kind=UIActionKind.CLICK,
        target=ActionTarget(role="button", name="保存"),
    )

    result = await DeterministicRunner().run_step(
        page,
        step,
        extra_locator_candidates=[
            {"strategy": "css", "value": ".save-btn", "rationale": "css class hint"},
        ],
    )

    assert result.success is True
    assert self_heal_locator.clicked is True


@pytest.mark.asyncio
async def test_extra_locator_candidate_with_invalid_strategy_is_dropped() -> None:
    """evaluate 不在 _AI_LOCATOR_ALLOWED_STRATEGIES 白名单, 自愈候选必须被静默丢弃,
    不能改变行为. 默认候选全 0 -> 仍然 locator_not_found."""
    page = _FakePage()
    step = UIActionStep(
        source_text="点击保存按钮",
        kind=UIActionKind.CLICK,
        target=ActionTarget(role="button", name="保存"),
    )

    result = await DeterministicRunner().run_step(
        page,
        step,
        extra_locator_candidates=[
            {"strategy": "evaluate", "value": "page.evaluate('...')"},
            {"strategy": "css", "value": ""},  # 空 value 也丢
        ],
    )

    assert result.success is False
    assert result.evidence.error_kind == "locator_not_found"


@pytest.mark.asyncio
async def test_extra_locator_candidate_cleared_between_runs() -> None:
    """run_step 出口必须把 _extra_locator_candidates 清空, 避免上一步的自愈候选
    污染下一步."""
    page = _FakePage()
    page.set_locator("css", ".save-btn", _FakeLocator(count=1))
    step1 = UIActionStep(
        source_text="点击保存按钮",
        kind=UIActionKind.CLICK,
        target=ActionTarget(role="button", name="保存"),
    )
    runner = DeterministicRunner()
    r1 = await runner.run_step(
        page,
        step1,
        extra_locator_candidates=[{"strategy": "css", "value": ".save-btn"}],
    )
    assert r1.success is True
    # 第二次不传 extra, 自愈候选必须被清空 -> default 全 0 直接失败
    step2 = UIActionStep(
        source_text="点击保存按钮",
        kind=UIActionKind.CLICK,
        target=ActionTarget(role="button", name="保存"),
    )
    r2 = await runner.run_step(page, step2)
    assert r2.success is False
    assert r2.evidence.error_kind == "locator_not_found"
