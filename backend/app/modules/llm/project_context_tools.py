"""Read-only project context tools for AI chat."""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.requirements.models import RequirementDocument
from app.modules.test_data.models import TestDataSet
from app.modules.testcases.models import Testcase
from app.modules.ui_automation.models import TestEnvironment, UIExecution
from app.modules.ui_automation.requirement_context import extract_relevant_excerpt

PROJECT_SEARCH_CONTEXT_TOOL_NAME = "project_search_context"
PROJECT_CONTEXT_TOOL_NAMES: frozenset[str] = frozenset({PROJECT_SEARCH_CONTEXT_TOOL_NAME})

_VALID_SCOPES = ("requirements", "testcases", "test_data", "environments", "executions")
_MAX_LIMIT = 8


def project_context_tool_schemas() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": PROJECT_SEARCH_CONTEXT_TOOL_NAME,
                "description": (
                    "检索当前项目内的需求文档、测试用例、测试物料、环境和执行记录摘要。"
                    "只能读取当前会话绑定项目的数据；测试物料 secret 值会脱敏。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "检索关键词；为空时返回各范围的最近/常用摘要。",
                        },
                        "scopes": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "enum": [*_VALID_SCOPES, "all"],
                            },
                            "description": (
                                "检索范围。默认 all。requirements=需求文档，"
                                "testcases=测试用例，test_data=测试物料，"
                                "environments=测试环境，executions=最近执行记录。"
                            ),
                        },
                        "limit": {
                            "type": "integer",
                            "description": "每个范围最多返回条数，默认 5，最大 8。",
                            "default": 5,
                        },
                    },
                    "required": ["query"],
                },
            },
        },
    ]


def is_project_context_tool(name: str) -> bool:
    return name in PROJECT_CONTEXT_TOOL_NAMES


def _parse_args(args_json: str) -> dict[str, Any]:
    try:
        parsed = json.loads(args_json) if args_json else {}
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _normalize_scopes(raw: Any) -> list[str]:
    if raw in (None, "", "all"):
        return list(_VALID_SCOPES)
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return list(_VALID_SCOPES)
    values = [str(x) for x in raw]
    if not values or "all" in values:
        return list(_VALID_SCOPES)
    return [s for s in _VALID_SCOPES if s in values]


def _like(query: str) -> str:
    return f"%{query.strip()}%"


def _clamp(text: Any, max_chars: int = 700) -> str:
    value = str(text or "").strip()
    if len(value) <= max_chars:
        return value
    return value[: max(0, max_chars - 1)].rstrip() + "…"


def _redact_context_value(value_type: str | None, value: Any) -> Any:
    if value_type == "secret":
        return "<masked>"
    if isinstance(value, (dict, list)):
        return value
    return _clamp(value, 180)


async def run_project_context_tool(
    db: AsyncSession,
    name: str,
    args_json: str,
    *,
    project_id: uuid.UUID | None,
) -> str:
    if name != PROJECT_SEARCH_CONTEXT_TOOL_NAME:
        return json.dumps({"ok": False, "error": f"unknown project context tool: {name}"})
    if project_id is None:
        return json.dumps(
            {"ok": False, "error": "project_search_context requires a project-bound chat"},
            ensure_ascii=False,
        )
    args = _parse_args(args_json)
    query = str(args.get("query") or "").strip()
    scopes = _normalize_scopes(args.get("scopes"))
    try:
        limit = min(max(int(args.get("limit") or 5), 1), _MAX_LIMIT)
    except (TypeError, ValueError):
        limit = 5

    sections: dict[str, list[dict[str, Any]]] = {}
    if "requirements" in scopes:
        sections["requirements"] = await _search_requirements(db, project_id, query, limit)
    if "testcases" in scopes:
        sections["testcases"] = await _search_testcases(db, project_id, query, limit)
    if "test_data" in scopes:
        sections["test_data"] = await _search_test_data(db, project_id, query, limit)
    if "environments" in scopes:
        sections["environments"] = await _search_environments(db, project_id, query, limit)
    if "executions" in scopes:
        sections["executions"] = await _search_executions(db, project_id, limit)

    return json.dumps(
        {
            "ok": True,
            "query": query,
            "scopes": scopes,
            "results": sections,
            "note": "secret values are masked; all data is scoped to current project.",
        },
        ensure_ascii=False,
    )


async def _search_requirements(
    db: AsyncSession,
    project_id: uuid.UUID,
    query: str,
    limit: int,
) -> list[dict[str, Any]]:
    stmt = select(RequirementDocument).where(RequirementDocument.project_id == project_id)
    if query:
        pat = _like(query)
        stmt = stmt.where(
            or_(
                RequirementDocument.filename.ilike(pat),
                RequirementDocument.content_text.ilike(pat),
            )
        )
    stmt = stmt.order_by(desc(RequirementDocument.updated_at)).limit(limit)
    rows = list((await db.execute(stmt)).scalars().all())
    return [
        {
            "id": str(row.id),
            "filename": row.filename,
            "status": row.status,
            "snippet": extract_relevant_excerpt(
                row.content_text or "",
                query=query or row.filename,
                max_chars=900,
            ),
        }
        for row in rows
    ]


async def _search_testcases(
    db: AsyncSession,
    project_id: uuid.UUID,
    query: str,
    limit: int,
) -> list[dict[str, Any]]:
    stmt = (
        select(Testcase)
        .options(selectinload(Testcase.steps), selectinload(Testcase.module))
        .where(Testcase.project_id == project_id)
    )
    if query:
        pat = _like(query)
        stmt = stmt.where(or_(Testcase.title.ilike(pat), Testcase.precondition.ilike(pat)))
    stmt = stmt.order_by(desc(Testcase.updated_at)).limit(limit)
    rows = list((await db.execute(stmt)).scalars().all())
    return [
        {
            "id": str(row.id),
            "case_no": row.case_no,
            "title": row.title,
            "module": row.module.name if row.module else None,
            "priority": row.priority,
            "status": row.status,
            "precondition": _clamp(row.precondition, 260),
            "steps": [
                {
                    "step_number": step.step_number,
                    "action": _clamp(step.action, 220),
                    "expected_result": _clamp(step.expected_result, 220),
                }
                for step in list(row.steps or [])[:5]
            ],
        }
        for row in rows
    ]


async def _search_test_data(
    db: AsyncSession,
    project_id: uuid.UUID,
    query: str,
    limit: int,
) -> list[dict[str, Any]]:
    stmt = (
        select(TestDataSet)
        .options(selectinload(TestDataSet.items))
        .where(TestDataSet.project_id == project_id)
    )
    if query:
        pat = _like(query)
        stmt = stmt.where(
            or_(
                TestDataSet.name.ilike(pat),
                TestDataSet.description.ilike(pat),
                TestDataSet.purpose.ilike(pat),
                TestDataSet.category.ilike(pat),
            )
        )
    stmt = stmt.order_by(desc(TestDataSet.is_default), desc(TestDataSet.updated_at)).limit(limit)
    rows = list((await db.execute(stmt)).scalars().all())
    return [
        {
            "id": str(row.id),
            "name": row.name,
            "scope": row.scope,
            "purpose": row.purpose,
            "category": row.category,
            "tags": row.tags or [],
            "is_default": row.is_default,
            "items": [
                {
                    "key": item.key,
                    "semantic": item.semantic,
                    "value_type": item.value_type,
                    "description": _clamp(item.description, 180),
                    "value_preview": _redact_context_value(
                        item.value_type,
                        item.value_json if item.value_type == "dataset" else item.value_text,
                    ),
                }
                for item in list(row.items or [])[:8]
            ],
        }
        for row in rows
    ]


async def _search_environments(
    db: AsyncSession,
    project_id: uuid.UUID,
    query: str,
    limit: int,
) -> list[dict[str, Any]]:
    stmt = select(TestEnvironment).where(TestEnvironment.project_id == project_id)
    if query:
        pat = _like(query)
        stmt = stmt.where(or_(TestEnvironment.name.ilike(pat), TestEnvironment.description.ilike(pat)))
    stmt = stmt.order_by(desc(TestEnvironment.updated_at)).limit(limit)
    rows = list((await db.execute(stmt)).scalars().all())
    return [
        {
            "id": str(row.id),
            "name": row.name,
            "description": _clamp(row.description, 260),
            "base_url": row.base_url,
            "risk_level": row.risk_level,
            "enable_browser_evaluate": row.enable_browser_evaluate,
            "default_data_set_ids": row.default_data_set_ids or [],
        }
        for row in rows
    ]


async def _search_executions(
    db: AsyncSession,
    project_id: uuid.UUID,
    limit: int,
) -> list[dict[str, Any]]:
    stmt = (
        select(UIExecution)
        .where(UIExecution.project_id == project_id)
        .order_by(desc(UIExecution.created_at))
        .limit(limit)
    )
    rows = list((await db.execute(stmt)).scalars().all())
    return [
        {
            "id": str(row.id),
            "status": row.status,
            "source": row.source,
            "mode": row.mode,
            "total_cases": row.total_cases,
            "passed_cases": row.passed_cases,
            "failed_cases": row.failed_cases,
            "skipped_cases": row.skipped_cases,
            "duration_ms": row.duration_ms,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "error_message": _clamp(row.error_message, 260),
        }
        for row in rows
    ]


__all__ = [
    "PROJECT_CONTEXT_TOOL_NAMES",
    "PROJECT_SEARCH_CONTEXT_TOOL_NAME",
    "_redact_context_value",
    "is_project_context_tool",
    "project_context_tool_schemas",
    "run_project_context_tool",
]
