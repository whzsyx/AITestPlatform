from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.ui_automation.evidence_collector import EvidenceCollector


class _FakePage:
    def __init__(self, responses: list[Any] | None = None, *, error: Exception | None = None):
        self.responses = list(responses or [])
        self.error = error
        self.evaluate_calls: list[tuple[str, Any]] = []
        self.handlers: dict[str, Any] = {}

    async def evaluate(self, script: str, arg: Any = None):
        self.evaluate_calls.append((script, arg))
        if self.error is not None:
            raise self.error
        if not self.responses:
            raise AssertionError("unexpected evaluate call")
        return self.responses.pop(0)

    def on(self, event_name: str, handler: Any) -> None:
        self.handlers[event_name] = handler


@pytest.mark.asyncio
async def test_collect_page_identity_returns_url_title_and_headings() -> None:
    page = _FakePage([
        {
            "url": "https://example.com/admin/stores",
            "title": "店铺管理",
            "headings": ["店铺列表", "筛选条件"],
        },
    ])

    evidence = await EvidenceCollector().collect_page_identity(page)

    assert evidence.ok is True
    assert evidence.url == "https://example.com/admin/stores"
    assert evidence.title == "店铺管理"
    assert evidence.headings == ["店铺列表", "筛选条件"]
    script, arg = page.evaluate_calls[0]
    assert "EVIDENCE_COLLECTOR_PAGE_IDENTITY_V1" in script
    assert arg is None


@pytest.mark.asyncio
async def test_collect_table_schema_keeps_complete_columns_and_hint() -> None:
    page = _FakePage([
        {
            "table_hint": "店铺列表",
            "columns": ["店铺ID", "店铺名称", "平台", "负责人"],
            "visible_columns": ["店铺ID", "店铺名称"],
            "total_columns": 4,
        },
    ])

    evidence = await EvidenceCollector().collect_table_schema(
        page,
        table_hint="店铺列表",
    )

    assert evidence.ok is True
    assert evidence.table_hint == "店铺列表"
    assert evidence.columns == ["店铺ID", "店铺名称", "平台", "负责人"]
    assert evidence.visible_columns == ["店铺ID", "店铺名称"]
    assert evidence.total_columns == 4
    script, arg = page.evaluate_calls[0]
    assert "EVIDENCE_COLLECTOR_TABLE_SCHEMA_V1" in script
    assert arg == {"table_hint": "店铺列表"}


@pytest.mark.asyncio
async def test_collect_table_rows_returns_structured_rows_with_limit() -> None:
    page = _FakePage([
        {
            "table_hint": "店铺列表",
            "columns": ["店铺ID", "店铺名称"],
            "rows": [
                {"店铺ID": "S001", "店铺名称": "旗舰店"},
                {"店铺ID": "S002", "店铺名称": "二店"},
            ],
            "row_count": 2,
            "limit": 50,
        },
    ])

    evidence = await EvidenceCollector().collect_table_rows(
        page,
        table_hint="店铺列表",
        limit=50,
    )

    assert evidence.ok is True
    assert evidence.columns == ["店铺ID", "店铺名称"]
    assert evidence.rows[0]["店铺ID"] == "S001"
    assert evidence.row_count == 2
    assert evidence.limit == 50
    assert page.evaluate_calls[0][1] == {"table_hint": "店铺列表", "limit": 50}


@pytest.mark.asyncio
async def test_collect_form_fields_returns_disabled_and_readonly() -> None:
    page = _FakePage([
        {
            "fields": [
                {
                    "label": "店铺名称",
                    "placeholder": "请输入店铺名称",
                    "name": "storeName",
                    "value": "旗舰店",
                    "disabled": False,
                    "readonly": False,
                    "tag_name": "input",
                    "type": "text",
                },
                {
                    "label": "店铺ID",
                    "placeholder": "",
                    "name": "storeId",
                    "value": "S001",
                    "disabled": True,
                    "readonly": True,
                    "tag_name": "input",
                    "type": "text",
                },
            ],
        },
    ])

    evidence = await EvidenceCollector().collect_form_fields(page)

    assert evidence.ok is True
    assert len(evidence.fields) == 2
    assert evidence.fields[0].label == "店铺名称"
    assert evidence.fields[0].disabled is False
    assert evidence.fields[1].label == "店铺ID"
    assert evidence.fields[1].disabled is True
    assert evidence.fields[1].readonly is True


@pytest.mark.asyncio
async def test_collect_form_fields_script_prefers_visible_overlay_root() -> None:
    page = _FakePage([{"fields": []}])

    await EvidenceCollector().collect_form_fields(page)

    script, _arg = page.evaluate_calls[0]
    assert "activeRoot" in script
    assert ".ant-drawer" in script
    assert "[role=\"dialog\"]" in script


def test_console_errors_can_be_recorded_and_collected() -> None:
    collector = EvidenceCollector()
    collector.record_console_message(SimpleNamespace(type="log", text="ok"))
    collector.record_console_message(SimpleNamespace(type="error", text="boom"))
    collector.record_console_message(SimpleNamespace(type=lambda: "warning", text=lambda: "warn"))

    evidence = collector.collect_console_errors()

    assert evidence.ok is True
    assert evidence.error_count == 1
    assert evidence.warning_count == 1
    assert evidence.messages == [
        {"type": "error", "text": "boom"},
        {"type": "warning", "text": "warn"},
    ]


def test_attach_to_page_registers_console_handler() -> None:
    collector = EvidenceCollector()
    page = _FakePage()

    collector.attach_to_page(page)
    page.handlers["console"](SimpleNamespace(type="error", text="from browser"))

    evidence = collector.collect_console_errors()
    assert evidence.error_count == 1
    assert evidence.messages[0]["text"] == "from browser"


@pytest.mark.asyncio
async def test_collect_failures_return_structured_error() -> None:
    page = _FakePage(error=RuntimeError("dom unavailable"))

    evidence = await EvidenceCollector().collect_table_schema(page)

    assert evidence.ok is False
    assert evidence.error == "dom unavailable"
    assert evidence.columns == []
    assert evidence.total_columns == 0
