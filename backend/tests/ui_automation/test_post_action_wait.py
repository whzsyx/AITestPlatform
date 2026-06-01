"""Phase 15.3 — 动作后等待与表格 polling 单测.

覆盖:
- ``_resolve_wait_strategy``: 显式 wait_strategy > expects_data_refresh > quick.
- ``_wait_after_action``: quick 档历史行为 / data_refresh 档命中 networkidle +
  loading mask 消失 / UI_POST_ACTION_WAIT_MAX_MS 截断.
- ``_poll_locator_count``: 命中即返回 / 超时返回 0 / locator 抛错保险吞.
- plan_compiler: 按钮名 / 按键 → expects_data_refresh 的自动识别.
- EvidenceCollector.collect_table_rows / collect_table_schema 的 polling_ms.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.modules.ui_automation.action_plan import (
    UIActionKind,
    UIActionStep,
)
from app.modules.ui_automation.deterministic_runner import (
    _LOADING_INDICATOR_SELECTORS,
    _poll_locator_count,
    _resolve_wait_strategy,
    _wait_after_action,
)
from app.modules.ui_automation.evidence_collector import EvidenceCollector
from app.modules.ui_automation.plan_compiler import (
    _compile_click,
    _compile_press_key,
)

# ─── helpers ──────────────────────────────────────────────────────────


class _RecordingLocator:
    """单一 selector 上 wait_for(state="hidden", ...) 的记录桩.

    behavior 控制:
    - existing=False: 元素不存在, wait_for 立即返回 (实际 Playwright 行为).
    - existing=True + persist=False: 第一次 wait_for 抛 timeout, 模拟 mask
      没消失.
    """

    def __init__(self, *, existing: bool = False, persist: bool = False) -> None:
        self.existing = existing
        self.persist = persist
        self.wait_for_calls: list[dict[str, Any]] = []

    @property
    def first(self) -> "_RecordingLocator":
        return self

    async def wait_for(self, *, state: str, timeout: int) -> None:
        self.wait_for_calls.append({"state": state, "timeout": timeout})
        if self.existing and self.persist:
            # 真睡一段让墙钟推进, 以便 _wait_after_action 的 budget 截断逻辑
            # 可以被验证 (实际 Playwright 行为也是阻塞 timeout 后才抛).
            import asyncio as _aio
            await _aio.sleep(timeout / 1000.0)
            raise TimeoutError("loading mask still visible")


class _FakePage:
    """轻量 page 桩, 只覆盖 _wait_after_action 用到的方法."""

    def __init__(
        self,
        *,
        load_states_supported: tuple[str, ...] = ("domcontentloaded", "networkidle"),
        locators: dict[str, _RecordingLocator] | None = None,
    ) -> None:
        self.load_states_supported = load_states_supported
        self.load_state_calls: list[dict[str, Any]] = []
        self.timeout_calls: list[int] = []
        self.locator_calls: list[str] = []
        self._locators: dict[str, _RecordingLocator] = locators or {}

    async def wait_for_load_state(self, state: str, *, timeout: int) -> None:
        self.load_state_calls.append({"state": state, "timeout": timeout})
        if state not in self.load_states_supported:
            raise TimeoutError(f"unsupported load state {state}")

    async def wait_for_timeout(self, ms: int) -> None:
        self.timeout_calls.append(int(ms))

    def locator(self, selector: str) -> _RecordingLocator:
        self.locator_calls.append(selector)
        return self._locators.get(selector, _RecordingLocator(existing=False))


# ─── _resolve_wait_strategy ───────────────────────────────────────────


def test_resolve_wait_strategy_default_quick_when_no_step() -> None:
    assert _resolve_wait_strategy(None) == "quick"


def test_resolve_wait_strategy_explicit_overrides_implicit() -> None:
    """显式 wait_strategy 比 expects_data_refresh 优先级高."""
    step = UIActionStep(
        kind=UIActionKind.CLICK,
        source_text="点击查询",
        expects_data_refresh=True,
        wait_strategy="quick",
    )
    assert _resolve_wait_strategy(step) == "quick"


def test_resolve_wait_strategy_implicit_data_refresh() -> None:
    step = UIActionStep(
        kind=UIActionKind.CLICK,
        source_text="点击查询",
        expects_data_refresh=True,
    )
    assert _resolve_wait_strategy(step) == "data_refresh"


def test_resolve_wait_strategy_default_quick() -> None:
    step = UIActionStep(kind=UIActionKind.CLICK, source_text="点击")
    assert _resolve_wait_strategy(step) == "quick"


# ─── _wait_after_action: quick 档历史行为 ──────────────────────────────


@pytest.mark.asyncio
async def test_wait_after_action_quick_path_no_step() -> None:
    """step=None 时只走 domcontentloaded + 300ms 兜底, 与历史行为一致."""
    page = _FakePage()
    await _wait_after_action(page, None)
    assert page.load_state_calls == [{"state": "domcontentloaded", "timeout": 1_500}]
    # quick 档不会探测 networkidle 也不会查 loading mask
    assert not any(c["state"] == "networkidle" for c in page.load_state_calls)
    assert page.locator_calls == []
    assert page.timeout_calls == [300]


@pytest.mark.asyncio
async def test_wait_after_action_quick_path_with_step_no_refresh() -> None:
    page = _FakePage()
    step = UIActionStep(kind=UIActionKind.CLICK, source_text="点击")
    await _wait_after_action(page, step)
    assert page.timeout_calls == [300]
    assert page.locator_calls == []


# ─── _wait_after_action: data_refresh 档命中 networkidle + loading mask ─


@pytest.mark.asyncio
async def test_wait_after_action_data_refresh_path_calls_networkidle_and_loading_selectors() -> None:
    page = _FakePage()
    step = UIActionStep(
        kind=UIActionKind.CLICK,
        source_text="点击查询",
        expects_data_refresh=True,
    )
    await _wait_after_action(page, step)
    # 必须先 domcontentloaded, 再 networkidle
    states = [c["state"] for c in page.load_state_calls]
    assert states[0] == "domcontentloaded"
    assert "networkidle" in states
    # 9 个 loading 指示器 selector 都要尝试 (元素不存在时 wait_for 立即返回)
    assert page.locator_calls == list(_LOADING_INDICATOR_SELECTORS)


@pytest.mark.asyncio
async def test_wait_after_action_data_refresh_swallows_exceptions(monkeypatch) -> None:
    """page.wait_for_load_state / locator 抛错时, _wait_after_action 不能抛."""

    class _ExplodingPage:
        async def wait_for_load_state(self, state: str, *, timeout: int) -> None:
            raise RuntimeError("boom")

        async def wait_for_timeout(self, ms: int) -> None:
            raise RuntimeError("boom")

        def locator(self, selector: str) -> Any:
            raise RuntimeError("boom")

    page = _ExplodingPage()
    step = UIActionStep(
        kind=UIActionKind.CLICK,
        source_text="点击查询",
        expects_data_refresh=True,
    )
    # 不抛即视为通过
    await _wait_after_action(page, step)


@pytest.mark.asyncio
async def test_wait_after_action_data_refresh_respects_max_ms(monkeypatch) -> None:
    """UI_POST_ACTION_WAIT_MAX_MS 截断: 设 100ms 时, 9 个 selector 不会全部跑完."""
    from app.config import settings

    monkeypatch.setattr(settings, "UI_POST_ACTION_WAIT_MAX_MS", 100)

    # 让每个 selector 都模拟 "mask 一直在", wait_for 抛 timeout 把整体预算耗光
    def _persist_locator() -> _RecordingLocator:
        return _RecordingLocator(existing=True, persist=True)

    page = _FakePage(
        locators={sel: _persist_locator() for sel in _LOADING_INDICATOR_SELECTORS},
    )
    step = UIActionStep(
        kind=UIActionKind.CLICK,
        source_text="点击查询",
        expects_data_refresh=True,
    )
    await _wait_after_action(page, step)
    # budget 应该截断 selector 探测; 不是所有 9 个都被试到
    assert len(page.locator_calls) < len(_LOADING_INDICATOR_SELECTORS)


# ─── _poll_locator_count ──────────────────────────────────────────────


class _CountSequenceLocator:
    """count() 按预设序列返回, 用于模拟 SPA 渲染前后 locator 计数变化."""

    def __init__(self, sequence: list[int]) -> None:
        self._sequence = list(sequence)

    async def count(self) -> int:
        if not self._sequence:
            return 0
        return self._sequence.pop(0)


@pytest.mark.asyncio
async def test_poll_locator_count_returns_immediately_when_hit() -> None:
    page = _FakePage()
    locator = _CountSequenceLocator([0, 3])
    out = await _poll_locator_count(
        page, locator, max_ms=2000, interval_ms=10,
    )
    assert out == 3


@pytest.mark.asyncio
async def test_poll_locator_count_returns_zero_on_timeout() -> None:
    page = _FakePage()
    locator = _CountSequenceLocator([0, 0, 0])
    out = await _poll_locator_count(
        page, locator, max_ms=30, interval_ms=10,
    )
    assert out == 0


@pytest.mark.asyncio
async def test_poll_locator_count_swallows_exceptions() -> None:
    page = _FakePage()

    class _ExplodingLocator:
        async def count(self) -> int:
            raise RuntimeError("boom")

    out = await _poll_locator_count(
        page, _ExplodingLocator(), max_ms=20, interval_ms=10,
    )
    assert out == 0


# ─── plan_compiler 编译期识别 ───────────────────────────────────────


def test_plan_compile_click_data_refresh_button_marks_expects_data_refresh() -> None:
    step = _compile_click(1, "点击查询按钮")
    assert step is not None
    assert step.expects_data_refresh is True


@pytest.mark.parametrize(
    "source_text",
    ["点击搜索按钮", "点击刷新按钮", "点击确定按钮", "点击提交按钮", "点击导出按钮"],
)
def test_plan_compile_click_recognizes_all_data_refresh_words(source_text: str) -> None:
    step = _compile_click(1, source_text)
    assert step is not None
    assert step.expects_data_refresh is True


def test_plan_compile_click_non_refresh_button_does_not_mark() -> None:
    step = _compile_click(1, "点击保存草稿按钮")
    assert step is not None
    assert step.expects_data_refresh is False


def test_plan_compile_press_key_enter_marks_expects_data_refresh() -> None:
    step = _compile_press_key(1, "在搜索框按下 Enter 键")
    assert step is not None
    assert step.value == "Enter"
    assert step.expects_data_refresh is True


def test_plan_compile_press_key_tab_does_not_mark() -> None:
    step = _compile_press_key(1, "按下 Tab 键聚焦下一个输入框")
    assert step is not None
    assert step.value == "Tab"
    assert step.expects_data_refresh is False


# ─── EvidenceCollector polling ────────────────────────────────────────


class _EvalScriptedPage:
    """page.evaluate 按脚本依次返回; 用于模拟点击查询后 antd 渲染慢."""

    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self._responses = list(responses)
        self.evaluate_calls = 0

    async def evaluate(self, _script: str, _arg: dict[str, Any] | None = None):
        self.evaluate_calls += 1
        if not self._responses:
            return self._responses[-1] if self._responses else {}
        return self._responses.pop(0)

    async def wait_for_timeout(self, ms: int) -> None:
        # polling 间隔; 对测试不重要, 但要存在让 helper 优先用它
        pass


@pytest.mark.asyncio
async def test_collect_table_rows_polling_ms_zero_does_not_poll() -> None:
    """polling_ms=0 时只 evaluate 一次, 行为与 15.3 之前完全一致."""
    page = _EvalScriptedPage([{"columns": [], "rows": [], "row_count": 0, "limit": 20}])
    out = await EvidenceCollector().collect_table_rows(page, limit=20, polling_ms=0)
    assert out.row_count == 0
    assert page.evaluate_calls == 1


@pytest.mark.asyncio
async def test_collect_table_rows_polling_returns_when_rows_appear() -> None:
    """前两次空, 第三次返回一行 → polling 应该提前命中."""
    page = _EvalScriptedPage([
        {"columns": ["A"], "rows": [], "row_count": 0, "limit": 20},
        {"columns": ["A"], "rows": [], "row_count": 0, "limit": 20},
        {
            "columns": ["A"],
            "rows": [{"A": "1"}],
            "row_count": 1,
            "limit": 20,
        },
    ])
    out = await EvidenceCollector().collect_table_rows(
        page,
        limit=20,
        polling_ms=2000,
    )
    assert out.row_count == 1
    assert out.rows == [{"A": "1"}]
    # 第 3 次 evaluate 命中即停 (不会跑到第 4 次)
    assert page.evaluate_calls == 3


@pytest.mark.asyncio
async def test_collect_table_rows_polling_returns_last_when_timeout() -> None:
    """polling 上限到了仍无数据, 返回最后一次结果 (空但 ok=True)."""
    page = _EvalScriptedPage([
        {"columns": ["A"], "rows": [], "row_count": 0, "limit": 20},
        {"columns": ["A"], "rows": [], "row_count": 0, "limit": 20},
    ])
    out = await EvidenceCollector().collect_table_rows(
        page,
        limit=20,
        polling_ms=20,
    )
    assert out.row_count == 0
    assert out.ok is True


@pytest.mark.asyncio
async def test_collect_table_schema_polling_returns_when_columns_appear() -> None:
    page = _EvalScriptedPage([
        {"columns": [], "visible_columns": [], "total_columns": 0, "table_hint": None},
        {
            "columns": ["A", "B"],
            "visible_columns": ["A", "B"],
            "total_columns": 2,
            "table_hint": None,
        },
    ])
    out = await EvidenceCollector().collect_table_schema(page, polling_ms=2000)
    assert out.columns == ["A", "B"]
    assert page.evaluate_calls == 2
