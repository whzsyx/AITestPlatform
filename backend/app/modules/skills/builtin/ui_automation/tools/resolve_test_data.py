"""``system__ui_automation__resolve_test_data`` tool（Phase 13 / Task 13.5）."""

from __future__ import annotations

import uuid
from typing import Any

from app.modules.skills.builtin.ui_automation.plan_builder import _load_cases
from app.modules.skills.builtin.ui_automation.resolver import resolve_test_data_preview
from app.modules.skills.platform_tools import _get_runtime

RESOLVE_TEST_DATA_TOOL_NAME = "system__ui_automation__resolve_test_data"

RESOLVE_TEST_DATA_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": RESOLVE_TEST_DATA_TOOL_NAME,
        "description": (
            "按 case_ids + environment_id 解析本次执行会看到的测试物料预览。"
            "优先使用用例 required_test_data.semantic 与物料项 semantic 匹配；"
            "返回值会遮蔽 secret 明文，只用于 ConfirmationCard 预览和缺料提示。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "case_ids": {
                    "type": "array",
                    "items": {"type": "string", "format": "uuid"},
                    "description": "要解析物料的用例 UUID 列表",
                },
                "environment_id": {
                    "type": "string",
                    "format": "uuid",
                    "description": "执行环境 UUID",
                },
                "max_items": {
                    "type": "integer",
                    "description": "最多返回物料预览项，默认 12",
                    "default": 12,
                },
            },
            "required": ["case_ids", "environment_id"],
        },
    },
}


def _parse_uuid(value: Any, *, field: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a valid UUID") from exc


async def exec_resolve_test_data(args: dict[str, Any]) -> dict[str, Any]:
    rt = _get_runtime()
    if rt is None:
        return {
            "error": (
                "resolve_test_data requires an active chat runtime "
                "(no project_id bound)"
            ),
        }

    try:
        raw_case_ids = args.get("case_ids") or []
        if not isinstance(raw_case_ids, list) or not raw_case_ids:
            raise ValueError("case_ids must be a non-empty UUID array")
        case_ids = [
            _parse_uuid(v, field=f"case_id[{idx}]")
            for idx, v in enumerate(raw_case_ids)
        ]
        environment_id = _parse_uuid(args.get("environment_id"), field="environment_id")
        max_items = int(args.get("max_items") or 12)
        max_items = max(1, min(max_items, 50))

        cases = await _load_cases(rt.db, rt.project_id, case_ids)
        if not cases:
            raise ValueError("no testcases found for given ids")
        preview = await resolve_test_data_preview(
            rt.db,
            project_id=rt.project_id,
            user=rt.user,
            cases=cases,
            environment_id=environment_id,
            max_items=max_items,
        )
        return preview.model_dump(mode="json")
    except Exception as exc:  # noqa: BLE001 - tool must return JSON error to LLM
        return {"error": str(exc)}
