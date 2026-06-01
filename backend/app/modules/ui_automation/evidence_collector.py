"""Structured, read-only DOM evidence collection for UI automation."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel, Field


class EvidenceBase(BaseModel):
    ok: bool = True
    error: str | None = None


class PageIdentityEvidence(EvidenceBase):
    url: str = ""
    title: str = ""
    headings: list[str] = Field(default_factory=list)


class TableSchemaEvidence(EvidenceBase):
    table_hint: str | None = None
    columns: list[str] = Field(default_factory=list)
    visible_columns: list[str] = Field(default_factory=list)
    total_columns: int = 0


class TableRowsEvidence(EvidenceBase):
    table_hint: str | None = None
    columns: list[str] = Field(default_factory=list)
    rows: list[dict[str, str]] = Field(default_factory=list)
    row_count: int = 0
    limit: int = 50


class FormFieldEvidence(BaseModel):
    label: str = ""
    placeholder: str = ""
    name: str = ""
    value: str = ""
    disabled: bool = False
    readonly: bool = False
    tag_name: str = ""
    type: str = ""


class FormFieldsEvidence(EvidenceBase):
    fields: list[FormFieldEvidence] = Field(default_factory=list)


class ConsoleErrorsEvidence(EvidenceBase):
    error_count: int = 0
    warning_count: int = 0
    messages: list[dict[str, str]] = Field(default_factory=list)


class EvidenceCollector:
    """Collect page evidence through fixed internal scripts.

    The public API never accepts JavaScript from callers. Every DOM read goes
    through a hard-coded, read-only script owned by this module.
    """

    def __init__(self, *, max_console_messages: int = 200) -> None:
        self.max_console_messages = max_console_messages
        self._console_messages: list[dict[str, str]] = []

    def attach_to_page(self, page: Any) -> None:
        """Register a console listener when the page object supports it."""
        on = getattr(page, "on", None)
        if callable(on):
            on("console", self.record_console_message)

    def record_console_message(self, message: Any) -> None:
        msg_type = _read_message_attr(message, "type")
        if msg_type not in {"error", "warning"}:
            return
        text = _read_message_attr(message, "text")
        self._console_messages.append({"type": msg_type, "text": text})
        if len(self._console_messages) > self.max_console_messages:
            self._console_messages = self._console_messages[-self.max_console_messages :]

    def collect_console_errors(self) -> ConsoleErrorsEvidence:
        return ConsoleErrorsEvidence(
            error_count=sum(1 for item in self._console_messages if item["type"] == "error"),
            warning_count=sum(
                1 for item in self._console_messages if item["type"] == "warning"
            ),
            messages=list(self._console_messages),
        )

    async def collect_page_identity(self, page: Any) -> PageIdentityEvidence:
        try:
            raw = await page.evaluate(_PAGE_IDENTITY_SCRIPT)
            return PageIdentityEvidence(
                url=str(raw.get("url") or ""),
                title=str(raw.get("title") or ""),
                headings=_string_list(raw.get("headings")),
            )
        except Exception as exc:  # noqa: BLE001
            return PageIdentityEvidence(ok=False, error=str(exc))

    async def collect_table_schema(
        self,
        page: Any,
        *,
        table_hint: str | None = None,
        polling_ms: int = 0,
    ) -> TableSchemaEvidence:
        """Phase 15.3: ``polling_ms > 0`` 时启用短窗口轮询.

        deterministic_runner 在 ``expects_data_refresh=True`` 的步骤里会传
        ``polling_ms=6000``: 后端 ajax 慢 / antd 列表渲染晚, 第一次拿不到列
        头是常见的, 但 500ms 后通常就有了. 命中条件: ok=True 且至少一列.
        失败保险吞掉, 不让 polling 自身成为新失败源.
        """
        async def _once() -> TableSchemaEvidence:
            try:
                raw = await page.evaluate(
                    _TABLE_SCHEMA_SCRIPT,
                    {"table_hint": table_hint},
                )
                columns = _string_list(raw.get("columns"))
                visible_columns = _string_list(raw.get("visible_columns"))
                return TableSchemaEvidence(
                    table_hint=_optional_str(raw.get("table_hint")),
                    columns=columns,
                    visible_columns=visible_columns,
                    total_columns=int(raw.get("total_columns") or len(columns)),
                )
            except Exception as exc:  # noqa: BLE001
                return TableSchemaEvidence(ok=False, error=str(exc))

        evidence = await _once()
        if polling_ms <= 0:
            return evidence
        return await _poll_until(
            page,
            once=_once,
            satisfied=lambda ev: ev.ok and bool(ev.columns),
            initial=evidence,
            polling_ms=polling_ms,
        )

    async def collect_table_rows(
        self,
        page: Any,
        *,
        table_hint: str | None = None,
        limit: int = 50,
        polling_ms: int = 0,
    ) -> TableRowsEvidence:
        """Phase 15.3: ``polling_ms > 0`` 时启用短窗口轮询.

        点击查询/搜索后表格还在 spinner 中是历史失败的高发场景 ("快照仅显示
        点击操作成功, 未提供查询结果数据"). polling_ms=6000 通常足以等到
        antd / element / naive 数据网格刷新出第一行. 命中条件: ok=True 且
        至少 1 行. 失败保险吞掉.
        """
        safe_limit = max(1, min(int(limit or 50), 500))

        async def _once() -> TableRowsEvidence:
            try:
                raw = await page.evaluate(
                    _TABLE_ROWS_SCRIPT,
                    {"table_hint": table_hint, "limit": safe_limit},
                )
                rows = raw.get("rows") or []
                if not isinstance(rows, list):
                    rows = []
                return TableRowsEvidence(
                    table_hint=_optional_str(raw.get("table_hint")),
                    columns=_string_list(raw.get("columns")),
                    rows=[_string_dict(row) for row in rows if isinstance(row, dict)],
                    row_count=int(raw.get("row_count") or len(rows)),
                    limit=int(raw.get("limit") or safe_limit),
                )
            except Exception as exc:  # noqa: BLE001
                return TableRowsEvidence(ok=False, error=str(exc), limit=safe_limit)

        evidence = await _once()
        if polling_ms <= 0:
            return evidence
        return await _poll_until(
            page,
            once=_once,
            satisfied=lambda ev: ev.ok and ev.row_count >= 1,
            initial=evidence,
            polling_ms=polling_ms,
        )

    async def collect_form_fields(self, page: Any) -> FormFieldsEvidence:
        try:
            raw = await page.evaluate(_FORM_FIELDS_SCRIPT)
            fields_raw = raw.get("fields") if isinstance(raw, dict) else []
            if not isinstance(fields_raw, list):
                fields_raw = []
            return FormFieldsEvidence(
                fields=[
                    FormFieldEvidence(
                        label=str(item.get("label") or ""),
                        placeholder=str(item.get("placeholder") or ""),
                        name=str(item.get("name") or ""),
                        value=str(item.get("value") or ""),
                        disabled=bool(item.get("disabled")),
                        readonly=bool(item.get("readonly")),
                        tag_name=str(item.get("tag_name") or ""),
                        type=str(item.get("type") or ""),
                    )
                    for item in fields_raw
                    if isinstance(item, dict)
                ],
            )
        except Exception as exc:  # noqa: BLE001
            return FormFieldsEvidence(ok=False, error=str(exc))


def _read_message_attr(message: Any, name: str) -> str:
    value = getattr(message, name, "")
    if isinstance(value, Callable):
        value = value()
    return str(value or "")


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if isinstance(item, dict):
            text = str(
                item.get("text")
                or item.get("label")
                or item.get("name")
                or item.get("title")
                or "",
            ).strip()
        else:
            text = str(item).strip()
        if text:
            out.append(text)
    return out


def _string_dict(value: dict[Any, Any]) -> dict[str, str]:
    return {str(key): str(val) for key, val in value.items()}


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


_PAGE_IDENTITY_SCRIPT = """
(() => {
  // EVIDENCE_COLLECTOR_PAGE_IDENTITY_V1
  const visibleText = (el) => {
    const style = window.getComputedStyle(el);
    if (style.visibility === 'hidden' || style.display === 'none') return '';
    return (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
  };
  return {
    url: window.location.href,
    title: document.title || '',
    headings: Array.from(document.querySelectorAll('h1,h2,h3,h4,h5,h6,[role="heading"]'))
      .map(visibleText)
      .filter(Boolean)
      .slice(0, 20),
  };
})()
"""


_TABLE_SCHEMA_SCRIPT = """
async ({ table_hint: tableHint }) => {
  // EVIDENCE_COLLECTOR_TABLE_SCHEMA_V1
  const clean = (value) => String(value || '').replace(/\\s+/g, ' ').trim();
  const uniq = (items) => {
    const out = [];
    const seen = new Set();
    for (const item of items.map(clean).filter(Boolean)) {
      if (!seen.has(item)) {
        seen.add(item);
        out.push(item);
      }
    }
    return out;
  };
  const candidateSelectors = [
    'table',
    '[role="table"]',
    '[role="grid"]',
    '.n-data-table',
    '.ant-table',
    '.el-table',
  ];
  const candidates = Array.from(document.querySelectorAll(candidateSelectors.join(',')));
  const score = (el) => {
    if (!tableHint) return 0;
    return clean(el.innerText || el.textContent).includes(tableHint) ? 10 : 0;
  };
  const root = candidates.sort((a, b) => score(b) - score(a))[0] || document.body;
  const readHeaders = () => uniq(Array.from(root.querySelectorAll([
    'thead th',
    '[role="columnheader"]',
    '.n-data-table-th',
    '.ant-table-cell',
    '.el-table__cell',
  ].join(','))).map((el) => clean(el.innerText || el.textContent)));
  const visibleColumns = readHeaders();
  const scrollables = Array.from(root.querySelectorAll('*')).filter((el) => {
    const style = window.getComputedStyle(el);
    return (style.overflowX === 'auto' || style.overflowX === 'scroll') &&
      el.scrollWidth > el.clientWidth;
  });
  const allColumns = [...visibleColumns];
  for (const el of scrollables) {
    const original = el.scrollLeft;
    const points = [0, Math.floor((el.scrollWidth - el.clientWidth) / 2), el.scrollWidth];
    for (const point of points) {
      el.scrollLeft = point;
      await new Promise((resolve) => requestAnimationFrame(resolve));
      allColumns.push(...readHeaders());
    }
    el.scrollLeft = original;
  }
  const columns = uniq(allColumns);
  return {
    table_hint: tableHint || null,
    columns,
    visible_columns: visibleColumns,
    total_columns: columns.length,
  };
}
"""


_TABLE_ROWS_SCRIPT = """
({ table_hint: tableHint, limit }) => {
  // EVIDENCE_COLLECTOR_TABLE_ROWS_V1
  const clean = (value) => String(value || '').replace(/\\s+/g, ' ').trim();
  const candidateSelectors = [
    'table',
    '[role="table"]',
    '[role="grid"]',
    '.n-data-table',
    '.ant-table',
    '.el-table',
  ];
  const candidates = Array.from(document.querySelectorAll(candidateSelectors.join(',')));
  const score = (el) => tableHint && clean(el.innerText || el.textContent).includes(tableHint) ? 10 : 0;
  const root = candidates.sort((a, b) => score(b) - score(a))[0] || document.body;
  const headerSelector = [
    'thead th',
    '[role="columnheader"]',
    '.n-data-table-th',
    '.ant-table-cell',
    '.el-table__cell',
  ].join(',');
  const rowSelector = [
    'tbody tr',
    '[role="row"]',
    '.n-data-table-tr',
    '.ant-table-row',
    '.el-table__row',
  ].join(',');
  const cellSelector = [
    'td',
    '[role="cell"]',
    '.n-data-table-td',
    '.ant-table-cell',
    '.el-table__cell',
  ].join(',');
  const columns = Array.from(root.querySelectorAll(headerSelector))
    .map((el) => clean(el.innerText || el.textContent))
    .filter(Boolean);
  const rowEls = Array.from(root.querySelectorAll(rowSelector))
    .filter((row) => row.querySelectorAll(cellSelector).length > 0)
    .slice(0, limit);
  const rows = rowEls.map((row) => {
    const cells = Array.from(row.querySelectorAll(cellSelector))
      .map((el) => clean(el.innerText || el.textContent));
    const out = {};
    cells.forEach((cell, index) => {
      out[columns[index] || `col_${index + 1}`] = cell;
    });
    return out;
  });
  return {
    table_hint: tableHint || null,
    columns,
    rows,
    row_count: rows.length,
    limit,
  };
}
"""


_FORM_FIELDS_SCRIPT = """
(() => {
  // EVIDENCE_COLLECTOR_FORM_FIELDS_V1
  const clean = (value) => String(value || '').replace(/\\s+/g, ' ').trim();
  const visible = (el) => {
    const style = window.getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style.display !== 'none'
      && style.visibility !== 'hidden'
      && Number(style.opacity || 1) !== 0
      && rect.width > 0
      && rect.height > 0;
  };
  const overlaySelectors = [
    '.ant-drawer',
    '.ant-modal',
    '.el-drawer',
    '.el-dialog',
    '.n-drawer',
    '.n-modal',
    '[role="dialog"]',
    '.drawer',
    '[class*="drawer"]',
  ];
  const overlays = Array.from(document.querySelectorAll(overlaySelectors.join(',')))
    .filter(visible);
  const activeRoot = overlays.length ? overlays[overlays.length - 1] : document;
  const labelFor = (el) => {
    if (el.id) {
      const label = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (label) return clean(label.innerText || label.textContent);
    }
    const wrapped = el.closest('label');
    if (wrapped) return clean(wrapped.innerText || wrapped.textContent);
    return clean(el.getAttribute('aria-label') || el.getAttribute('data-label') || '');
  };
  const fields = Array.from(activeRoot.querySelectorAll('input,textarea,select,[contenteditable="true"]'))
    .filter((el) => {
      const type = clean(el.getAttribute('type')).toLowerCase();
      return visible(el) && type !== 'hidden' && type !== 'submit' && type !== 'button';
    })
    .map((el) => ({
      label: labelFor(el),
      placeholder: clean(el.getAttribute('placeholder')),
      name: clean(el.getAttribute('name') || el.id),
      value: clean('value' in el ? el.value : el.textContent),
      disabled: Boolean(el.disabled || el.getAttribute('aria-disabled') === 'true'),
      readonly: Boolean(
        el.readOnly ||
        el.getAttribute('readonly') !== null ||
        el.getAttribute('aria-readonly') === 'true'
      ),
      tag_name: clean(el.tagName).toLowerCase(),
      type: clean(el.getAttribute('type')).toLowerCase(),
    }));
  return { fields };
})()
"""


async def _poll_until(
    page: Any,
    *,
    once: Callable[[], "Awaitable[Any]"],
    satisfied: Callable[[Any], bool],
    initial: Any,
    polling_ms: int,
    interval_ms: int = 500,
) -> Any:
    """Phase 15.3: 内部短窗口 polling helper.

    每隔 ``interval_ms`` (默认 500ms) 重跑 ``once()``, 直到 ``satisfied``
    命中或耗尽 ``polling_ms``. 优先使用 ``page.wait_for_timeout`` 让等待
    与 Playwright 事件循环对齐, 不可用时 fallback ``asyncio.sleep``.
    """
    if satisfied(initial):
        return initial
    import asyncio as _asyncio
    import time as _time
    wait_fn = getattr(page, "wait_for_timeout", None)
    deadline = _time.monotonic() + max(0, polling_ms) / 1000.0
    last = initial
    while _time.monotonic() < deadline:
        try:
            if callable(wait_fn):
                await wait_fn(interval_ms)
            else:
                await _asyncio.sleep(interval_ms / 1000.0)
        except Exception:  # noqa: BLE001
            await _asyncio.sleep(interval_ms / 1000.0)
        last = await once()
        if satisfied(last):
            return last
    return last
