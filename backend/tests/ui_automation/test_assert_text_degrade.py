"""Phase 15.6 - assert_text 三级降级单测.

设计要点:
- _FakePage 可控制 exact / contains / loose 三个级别各自的命中数;
- 验证 evidence.details["match_strategy"] 在每级命中时分别 == "exact" / "contains" / "loose";
- 全 0 时返回 assertion_failed, match_strategy=None, match_attempts 长度 = 实际尝试级数;
- UI_ASSERT_TEXT_DEGRADE_LEVEL=1 / 2 时高级降级被截断, 不再尝试更宽松匹配.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.modules.ui_automation.action_plan import (
    ActionTarget,
    UIActionKind,
    UIActionStep,
)
from app.modules.ui_automation.deterministic_runner import DeterministicRunner


class _FakeLocator:
    def __init__(self, count: int) -> None:
        self._count = count

    async def count(self) -> int:
        return self._count


class _OrLocator:
    """模拟 page.locator(":text-is(...)").or_(page.locator(":has-text(...)")) 的 count."""

    def __init__(self, count: int) -> None:
        self._count = count

    async def count(self) -> int:
        return self._count


class _LooseTextLocator:
    """level 3 入口: page.locator(':text-is(...)') 的桩, 提供 .or_."""

    def __init__(self, loose_count: int) -> None:
        self._loose_count = loose_count

    async def count(self) -> int:
        # 不直接被命中, 走 .or_ 统一计数
        return self._loose_count

    def or_(self, _other: Any) -> _OrLocator:
        return _OrLocator(self._loose_count)


class _FakePage:
    """按 (exact / contains / loose) 三档可独立设置 count, 不依赖真实浏览器."""

    def __init__(
        self,
        *,
        exact_count: int = 0,
        contains_count: int = 0,
        loose_count: int = 0,
    ) -> None:
        self.exact_count = exact_count
        self.contains_count = contains_count
        self.loose_count = loose_count
        self.url = "https://example.com"
        self.calls: list[str] = []

    def get_by_text(self, _text: str, *, exact: bool = False) -> _FakeLocator:
        if exact:
            self.calls.append("exact")
            return _FakeLocator(self.exact_count)
        self.calls.append("contains")
        return _FakeLocator(self.contains_count)

    def locator(self, selector: str) -> Any:
        # level-3 用 :text-is(...)/:has-text(...); 其它 selector (loading mask /
        # 兜底 wait_after_action 内调用) 返回 0 count locator 即可.
        if ":text-is" in selector:
            self.calls.append("loose_textis")
            return _LooseTextLocator(self.loose_count)
        if ":has-text" in selector:
            self.calls.append("loose_hastext")
            return _FakeLocator(self.loose_count)
        return _FakeLocator(0)

    async def wait_for_load_state(self, *_a: Any, **_k: Any) -> None:
        return None

    async def wait_for_timeout(self, *_a: Any, **_k: Any) -> None:
        return None

    async def evaluate(self, *_a: Any, **_k: Any) -> Any:
        return {"ok": True, "texts": []}


def _step(text: str = "保存成功") -> UIActionStep:
    return UIActionStep(
        source_step_number=1,
        source_text=f"验证页面显示 {text}",
        kind=UIActionKind.ASSERT_TEXT,
        target=ActionTarget(text=text),
        confidence=0.9,
    )


@pytest.mark.asyncio
async def test_assert_text_level_1_exact_hit() -> None:
    page = _FakePage(exact_count=1)
    runner = DeterministicRunner()
    result = await runner._assert_text(page, _step())
    assert result.success is True
    assert result.evidence.details["match_strategy"] == "exact"


@pytest.mark.asyncio
async def test_assert_text_level_2_contains_hit_when_exact_miss() -> None:
    page = _FakePage(exact_count=0, contains_count=1)
    runner = DeterministicRunner()
    result = await runner._assert_text(page, _step())
    assert result.success is True
    assert result.evidence.details["match_strategy"] == "contains"
    # 第一级 + 第二级均尝试过
    attempts = result.evidence.details["match_attempts"]
    levels = [a["match_strategy"] for a in attempts]
    assert levels[:2] == ["exact", "contains"]


@pytest.mark.asyncio
async def test_assert_text_level_3_loose_hit_when_lower_levels_miss() -> None:
    page = _FakePage(exact_count=0, contains_count=0, loose_count=2)
    runner = DeterministicRunner()
    result = await runner._assert_text(page, _step())
    assert result.success is True
    assert result.evidence.details["match_strategy"] == "loose"


@pytest.mark.asyncio
async def test_assert_text_all_levels_miss_records_full_attempts() -> None:
    page = _FakePage(exact_count=0, contains_count=0, loose_count=0)
    runner = DeterministicRunner()
    result = await runner._assert_text(page, _step())
    assert result.success is False
    assert result.evidence.error_kind == "assertion_failed"
    assert result.evidence.details["match_strategy"] is None
    levels = [a["match_strategy"] for a in result.evidence.details["match_attempts"]]
    assert levels == ["exact", "contains", "loose"]


@pytest.mark.asyncio
async def test_assert_text_strict_mode_skips_higher_degradation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """UI_ASSERT_TEXT_DEGRADE_LEVEL=1 时, contains/loose 不再尝试."""
    from app.config import settings as _settings
    monkeypatch.setattr(_settings, "UI_ASSERT_TEXT_DEGRADE_LEVEL", 1)

    page = _FakePage(exact_count=0, contains_count=999, loose_count=999)
    runner = DeterministicRunner()
    result = await runner._assert_text(page, _step())
    assert result.success is False
    levels = [a["match_strategy"] for a in result.evidence.details["match_attempts"]]
    assert levels == ["exact"], f"strict mode 不应降级, got {levels}"


@pytest.mark.asyncio
async def test_assert_text_level_2_only_skips_loose(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import settings as _settings
    monkeypatch.setattr(_settings, "UI_ASSERT_TEXT_DEGRADE_LEVEL", 2)

    page = _FakePage(exact_count=0, contains_count=0, loose_count=999)
    runner = DeterministicRunner()
    result = await runner._assert_text(page, _step())
    assert result.success is False
    levels = [a["match_strategy"] for a in result.evidence.details["match_attempts"]]
    assert levels == ["exact", "contains"], f"level=2 不应触发 loose, got {levels}"
