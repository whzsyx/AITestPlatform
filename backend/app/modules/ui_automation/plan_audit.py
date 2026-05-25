"""Helpers for storing compiled UIActionPlan snapshots for audit/preview."""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.modules.testcases.models import Testcase
from app.modules.ui_automation.plan_compiler import compile_action_plan

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


def build_compiled_action_plan_snapshots(
    testcases: Sequence[Any],
    *,
    module_entry_overrides: Mapping[uuid.UUID, str] | None = None,
) -> list[dict[str, Any]]:
    """Return JSON-serializable compiled plan snapshots.

    Compile errors are recorded as per-case audit entries so plan preview never
    blocks the legacy StepRunner execution path.
    """
    overrides = dict(module_entry_overrides or {})
    snapshots: list[dict[str, Any]] = []
    for testcase in testcases:
        testcase_id = getattr(testcase, "id", None)
        title = str(getattr(testcase, "title", "") or "")
        try:
            result = compile_action_plan(
                testcase,
                module_entry_path=_resolve_module_entry_path(testcase, overrides),
            )
            snapshots.append(
                {
                    "testcase_id": str(testcase_id) if testcase_id is not None else None,
                    "title": title,
                    "supported_step_count": result.supported_step_count,
                    "unsupported_step_count": result.unsupported_step_count,
                    "warnings": list(result.warnings),
                    "plan": result.plan.model_dump(mode="json", exclude_none=True),
                },
            )
        except Exception as exc:  # noqa: BLE001
            snapshots.append(
                {
                    "testcase_id": str(testcase_id) if testcase_id is not None else None,
                    "title": title,
                    "supported_step_count": 0,
                    "unsupported_step_count": len(getattr(testcase, "steps", []) or []),
                    "warnings": [f"compiled_action_plan failed: {exc}"],
                    "compile_error": str(exc),
                    "plan": None,
                },
            )
    return snapshots


async def load_compiled_action_plan_snapshots(
    db: "AsyncSession",
    *,
    project_id: uuid.UUID,
    testcase_ids: Sequence[uuid.UUID],
    module_entry_overrides: Mapping[uuid.UUID, str] | None = None,
) -> list[dict[str, Any]]:
    if not testcase_ids:
        return []
    rows = (
        await db.execute(
            select(Testcase)
            .options(selectinload(Testcase.steps), selectinload(Testcase.module))
            .where(Testcase.project_id == project_id, Testcase.id.in_(list(testcase_ids)))
        )
    ).scalars().unique().all()
    by_id = {row.id: row for row in rows}
    ordered = [by_id[tid] for tid in testcase_ids if tid in by_id]
    return build_compiled_action_plan_snapshots(
        ordered,
        module_entry_overrides=module_entry_overrides,
    )


def _resolve_module_entry_path(
    testcase: Any,
    overrides: Mapping[uuid.UUID, str],
) -> str | None:
    module_id = getattr(testcase, "module_id", None)
    if module_id in overrides:
        raw_override = (overrides[module_id] or "").strip()
        return raw_override or None

    module = getattr(testcase, "module", None)
    raw_entry = getattr(module, "entry_path", None) if module is not None else None
    if raw_entry is None:
        return None
    raw_entry = str(raw_entry).strip()
    return raw_entry or None
