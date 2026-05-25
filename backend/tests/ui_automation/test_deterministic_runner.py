from __future__ import annotations

from typing import Any

import pytest

from app.modules.ui_automation.action_plan import ActionTarget, UIActionKind, UIActionStep
from app.modules.ui_automation.deterministic_runner import DeterministicRunner


class _FakeLocator:
    def __init__(self, *, count: int = 1, text: str = "") -> None:
        self._count = count
        self.text = text
        self.clicked = False
        self.filled_with: str | None = None
        self.selected_value: str | None = None

    async def count(self) -> int:
        return self._count

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

    def get_by_role(self, role: str, *, name: str):
        self.calls.append(("get_by_role", {"role": role, "name": name}))
        return self.locators.get(("role", f"{role}:{name}"), _FakeLocator(count=0))

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

    async def evaluate(self, _script: str, _arg: dict[str, Any] | None = None):
        self.calls.append(("evaluate", _arg or {}))
        if self.evaluate_results:
            return self.evaluate_results.pop(0)
        return {}


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
    assert page.calls == [("get_by_role", {"role": "button", "name": "新增"})]
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
