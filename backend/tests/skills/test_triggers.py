"""Task 12.2 — match_triggers 排序与 max 截断。"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

from app.modules.skills.models import Skill
from app.modules.skills.triggers import match_triggers


class _Scalars:
    def __init__(self, items: list[Skill]) -> None:
        self._items = items

    def all(self) -> list[Skill]:
        return list(self._items)


class _ExecResult:
    def __init__(self, items: list[Skill]) -> None:
        self._items = items

    def scalars(self) -> _Scalars:
        return _Scalars(self._items)


def _mk_skill(
    slug: str,
    triggers: list[str],
    *,
    activation_mode: str = "trigger",
) -> Skill:
    return Skill(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        name=slug,
        slug=slug,
        description="d",
        body="b",
        created_by=uuid.uuid4(),
        triggers=triggers,
        tools_required=[],
        activation_mode=activation_mode,
    )


@pytest.mark.asyncio
async def test_orders_by_trigger_length() -> None:
    proj = uuid.uuid4()
    short = _mk_skill("a", ["登录"])
    long = _mk_skill("b", ["自动化登录流程"])
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_ExecResult([short, long]))

    out = await match_triggers(
        db,
        proj,
        "我要跑自动化登录流程测试",
        max_matches=3,
    )
    assert [s.slug for s in out] == ["b", "a"]


@pytest.mark.asyncio
async def test_max_matches_enforced() -> None:
    proj = uuid.uuid4()
    s1 = _mk_skill("s1", ["alpha"])
    s2 = _mk_skill("s2", ["beta"])
    s3 = _mk_skill("s3", ["gamma"])
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_ExecResult([s1, s2, s3]))

    out = await match_triggers(db, proj, "alpha beta gamma", max_matches=2)
    assert len(out) == 2


@pytest.mark.asyncio
async def test_agent_callable_trigger_matches_but_manual_does_not() -> None:
    proj = uuid.uuid4()
    agent = _mk_skill(
        "agent_ui",
        ["跑用例"],
        activation_mode="agent_callable",
    )
    manual = _mk_skill(
        "manual_only",
        ["跑用例"],
        activation_mode="manual",
    )
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_ExecResult([agent, manual]))

    out = await match_triggers(db, proj, "跑用例", max_matches=3)

    assert [s.slug for s in out] == ["agent_ui"]
