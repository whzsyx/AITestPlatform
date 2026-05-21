"""``system__failure_diagnosis__get_execution_detail`` 工具。"""

from __future__ import annotations

import logging
from typing import Any

from app.modules.skills.builtin.failure_diagnosis.tools.common import (
    _load_execution_detail_payload,
    mask_sensitive,
    parse_task_id,
    require_runtime,
)

logger = logging.getLogger(__name__)


GET_EXECUTION_DETAIL_TOOL_NAME = "system__failure_diagnosis__get_execution_detail"

GET_EXECUTION_DETAIL_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": GET_EXECUTION_DETAIL_TOOL_NAME,
        "description": (
            "读取指定 UI 执行任务的完整诊断上下文（执行状态、用例结果、步骤、"
            "物料快照、错误信息）。返回内容会自动脱敏 secret。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "UI 执行任务 UUID",
                },
            },
            "required": ["task_id"],
        },
    },
}


async def exec_get_execution_detail(args: dict[str, Any]) -> dict[str, Any]:
    rt = require_runtime()
    if rt is None:
        return {"error": "get_execution_detail requires an active chat runtime"}

    task_id, err = parse_task_id(args)
    if err is not None:
        return err
    assert task_id is not None

    try:
        payload = await _load_execution_detail_payload(rt.db, rt.user, task_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("failure_diagnosis get_execution_detail failed")
        return {"error": f"failed to load execution detail: {exc}"}

    clean = mask_sensitive(payload)
    return {
        "task_id": str(task_id),
        "status": clean.get("status"),
        "source": clean.get("source"),
        "mode": clean.get("mode"),
        "environment_id": clean.get("environment_id"),
        "total_cases": clean.get("total_cases"),
        "passed_cases": clean.get("passed_cases"),
        "failed_cases": clean.get("failed_cases"),
        "skipped_cases": clean.get("skipped_cases"),
        "error_message": clean.get("error_message"),
        "test_data_snapshot": clean.get("test_data_snapshot"),
        "runtime_data": clean.get("runtime_data"),
        "case_results": clean.get("case_results") or [],
        "has_video": clean.get("has_video"),
        "has_trace": clean.get("has_trace"),
        "trace_url": clean.get("trace_url"),
        "video_url": clean.get("video_url"),
    }
