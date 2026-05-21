"""``system__ui_automation__save_adhoc_as_testcase`` 工具（Task 13.6）。"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from app.modules.skills.platform_tools import _get_runtime
from app.modules.ui_automation.execution_service import save_adhoc_as_testcase

logger = logging.getLogger(__name__)


SAVE_ADHOC_AS_TESTCASE_TOOL_NAME = "system__ui_automation__save_adhoc_as_testcase"

SAVE_ADHOC_AS_TESTCASE_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": SAVE_ADHOC_AS_TESTCASE_TOOL_NAME,
        "description": (
            "把一次已成功完成的 source=adhoc UI 执行保存为正式测试用例。"
            "只读取该 execution 的用户确认后 adhoc_steps；不会修改原 execution。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "UI execution task UUID",
                },
                "title": {
                    "type": "string",
                    "description": "可选正式用例标题；省略时沿用 adhoc 草稿标题",
                },
                "module_id": {
                    "type": "string",
                    "description": "可选归属模块 UUID",
                },
            },
            "required": ["task_id"],
        },
    },
}


async def exec_save_adhoc_as_testcase(args: dict[str, Any]) -> dict[str, Any]:
    rt = _get_runtime()
    if rt is None:
        return {
            "error": (
                "save_adhoc_as_testcase requires an active chat runtime "
                "(no project_id bound)"
            ),
        }

    task_raw = args.get("task_id")
    if not task_raw:
        return {"error": "task_id is required"}
    try:
        task_id = uuid.UUID(str(task_raw))
    except (TypeError, ValueError):
        return {"error": f"invalid task_id: {task_raw!r}"}

    module_id: uuid.UUID | None = None
    module_raw = args.get("module_id")
    if module_raw:
        try:
            module_id = uuid.UUID(str(module_raw))
        except (TypeError, ValueError):
            return {"error": f"invalid module_id: {module_raw!r}"}

    try:
        return await save_adhoc_as_testcase(
            rt.db,
            task_id,
            rt.user,
            title_override=args.get("title"),
            module_id=module_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("save_adhoc_as_testcase failed")
        return {"error": str(exc)}
