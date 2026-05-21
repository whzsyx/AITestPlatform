"""Semantic test-data preview resolver for Phase 13 / Task 13.5.

This module is intentionally scoped to the Agent/ConfirmationCard preview path.
It reuses ``ui_automation.test_data_resolver.TestDataResolver`` for the existing
five-layer merge, then selects preview rows by testcase ``required_test_data``
semantics. ExecutionEngine still consumes ``{{key}}`` exactly as before.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import User
from app.modules.skills.builtin.ui_automation.schemas import (
    TestDataPreview,
    TestDataPreviewItem,
)
from app.modules.test_data.models import TestDataSet
from app.modules.testcases.models import Testcase
from app.modules.ui_automation.test_data_resolver import (
    TestDataItem,
    TestDataResolver,
)

SECRET_KEY_HINTS = ("password", "pwd", "passwd", "secret", "token", "api_key")


@dataclass(slots=True)
class _PreviewExecution:
    triggered_by: uuid.UUID
    project_id: uuid.UUID
    environment_id: uuid.UUID | None


def _is_secret_item(item: TestDataItem) -> bool:
    key = (item.key or "").lower()
    return item.value_type == "secret" or any(hint in key for hint in SECRET_KEY_HINTS)


def _safe_preview_value(item: TestDataItem) -> str:
    if _is_secret_item(item):
        return "<masked>"
    value = item.display_safe_value(max_len=64)
    return value if len(value) <= 64 else value[:60] + "..."


def _semantic_requirements(cases: Sequence[Any]) -> list[tuple[str, bool]]:
    """Return ``[(semantic, required)]`` in testcase order, with duplicate removal."""
    out: list[tuple[str, bool]] = []
    seen: set[str] = set()
    for case in cases:
        rows = getattr(case, "required_test_data", None) or []
        for raw in rows:
            semantic: str | None = None
            required = True
            if isinstance(raw, str):
                semantic = raw
            elif isinstance(raw, Mapping):
                semantic = str(raw.get("semantic") or "").strip() or None
                required = bool(raw.get("required", True))
            if not semantic or semantic in seen:
                continue
            seen.add(semantic)
            out.append((semantic, required))
    return out


def _source_label(
    item: TestDataItem,
    *,
    set_meta_by_id: dict[uuid.UUID, dict[str, Any]],
) -> str:
    if item.source_set_id is not None:
        meta = set_meta_by_id.get(item.source_set_id, {})
        name = meta.get("name") or item.source_set_name or str(item.source_set_id)
        scope = meta.get("scope")
        return f"{name}（{scope}）" if scope else str(name)
    if item.synthetic_source:
        return f"运行时生成：{item.synthetic_source}"
    return "运行时物料"


def _item_to_preview(
    item: TestDataItem,
    *,
    set_meta_by_id: dict[uuid.UUID, dict[str, Any]],
) -> TestDataPreviewItem:
    return TestDataPreviewItem(
        semantic=item.semantic,
        key=item.key,
        value_preview=_safe_preview_value(item),
        source=_source_label(item, set_meta_by_id=set_meta_by_id),
        source_set_id=item.source_set_id,
        is_secret=_is_secret_item(item),
    )


def build_test_data_preview_from_resolver(
    cases: Sequence[Any],
    resolver: TestDataResolver,
    *,
    set_summaries: list[dict[str, Any]] | None = None,
    max_items: int = 12,
) -> TestDataPreview:
    """Build a secret-safe ConfirmationCard preview from a merged resolver."""
    set_summaries = set_summaries or []
    set_meta_by_id: dict[uuid.UUID, dict[str, Any]] = {}
    for summary in set_summaries:
        raw_id = summary.get("id")
        try:
            sid = uuid.UUID(str(raw_id))
        except (TypeError, ValueError):
            continue
        set_meta_by_id[sid] = summary

    items_by_semantic: dict[str, TestDataItem] = {}
    for key in sorted(resolver.data):
        item = resolver.data[key]
        if item.semantic and item.semantic not in items_by_semantic:
            items_by_semantic[item.semantic] = item

    requirements = _semantic_requirements(cases)
    missing: list[str] = []
    preview_items: list[TestDataPreviewItem] = []
    used_keys: set[str] = set()

    for semantic, required in requirements:
        item = items_by_semantic.get(semantic)
        if item is None:
            if required:
                missing.append(semantic)
            continue
        preview_items.append(_item_to_preview(item, set_meta_by_id=set_meta_by_id))
        used_keys.add(item.key)
        if len(preview_items) >= max_items:
            break

    if not requirements:
        for key in sorted(resolver.data):
            if len(preview_items) >= max_items:
                break
            item = resolver.data[key]
            if item.key in used_keys:
                continue
            preview_items.append(_item_to_preview(item, set_meta_by_id=set_meta_by_id))
            used_keys.add(item.key)

    return TestDataPreview(
        items=preview_items,
        missing_semantics=missing,
        set_summaries=set_summaries,
    )


async def _load_set_summaries(
    db: AsyncSession,
    resolver: TestDataResolver,
) -> list[dict[str, Any]]:
    source_ids: list[uuid.UUID] = []
    seen: set[uuid.UUID] = set()
    counts: dict[uuid.UUID, int] = {}
    for item in resolver.data.values():
        sid = item.source_set_id
        if sid is None:
            continue
        counts[sid] = counts.get(sid, 0) + 1
        if sid in seen:
            continue
        seen.add(sid)
        source_ids.append(sid)
    if not source_ids:
        return []

    rows = (
        await db.execute(select(TestDataSet).where(TestDataSet.id.in_(source_ids)))
    ).scalars().all()
    by_id = {row.id: row for row in rows}
    out: list[dict[str, Any]] = []
    for sid in source_ids:
        row = by_id.get(sid)
        if row is None:
            out.append(
                {
                    "id": str(sid),
                    "name": str(sid),
                    "scope": None,
                    "item_count": counts.get(sid, 0),
                },
            )
            continue
        out.append(
            {
                "id": str(row.id),
                "name": row.name,
                "scope": row.scope,
                "item_count": counts.get(sid, 0),
            },
        )
    return out


async def resolve_test_data_preview(
    db: AsyncSession,
    *,
    project_id: uuid.UUID,
    user: User | None,
    cases: Sequence[Testcase],
    environment_id: uuid.UUID | None,
    loaded_set_ids: Sequence[uuid.UUID] | None = None,
    manual_overrides: Mapping[str, Any] | None = None,
    max_items: int = 12,
) -> TestDataPreview:
    """Resolve merged test data and return a secret-safe semantic preview."""
    triggered_by = getattr(user, "id", None) or uuid.UUID(int=0)
    base_resolver = await TestDataResolver.build(
        db,
        _PreviewExecution(
            triggered_by=triggered_by,
            project_id=project_id,
            environment_id=environment_id,
        ),
        manual_overrides=manual_overrides or {},
        loaded_set_ids=loaded_set_ids or [],
    )

    resolver = base_resolver
    if len(cases) == 1:
        case_id = getattr(cases[0], "id", None)
        if case_id is not None:
            resolver = await base_resolver.with_case_overrides(uuid.UUID(str(case_id)))

    set_summaries = await _load_set_summaries(db, resolver)
    return build_test_data_preview_from_resolver(
        cases,
        resolver,
        set_summaries=set_summaries,
        max_items=max_items,
    )


__all__ = [
    "build_test_data_preview_from_resolver",
    "resolve_test_data_preview",
]
