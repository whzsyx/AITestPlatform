"""``system__failure_diagnosis__get_failed_step_trace`` 工具。"""

from __future__ import annotations

import logging
from typing import Any

from app.modules.skills.builtin.failure_diagnosis.tools.common import (
    _load_execution_detail_payload,
    compact_text,
    failed_steps_from_payload,
    mask_sensitive,
    parse_task_id,
    require_runtime,
)

logger = logging.getLogger(__name__)


GET_FAILED_STEP_TRACE_TOOL_NAME = "system__failure_diagnosis__get_failed_step_trace"

GET_FAILED_STEP_TRACE_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": GET_FAILED_STEP_TRACE_TOOL_NAME,
        "description": (
            "提取失败步骤的 tool_calls、AI reasoning、断言证据和错误链路，"
            "用于定位是物料、选择器、环境还是执行计划问题。返回内容自动脱敏。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "UI 执行任务 UUID",
                },
                "step_number": {
                    "type": "integer",
                    "description": "可选：只查看指定步骤序号",
                },
            },
            "required": ["task_id"],
        },
    },
}


async def exec_get_failed_step_trace(args: dict[str, Any]) -> dict[str, Any]:
    rt = require_runtime()
    if rt is None:
        return {"error": "get_failed_step_trace requires an active chat runtime"}

    task_id, err = parse_task_id(args)
    if err is not None:
        return err
    assert task_id is not None

    step_number = _parse_step_number(args.get("step_number"))
    try:
        payload = await _load_execution_detail_payload(rt.db, rt.user, task_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("failure_diagnosis get_failed_step_trace failed")
        return {"error": f"failed to load execution detail: {exc}"}

    failed_steps = [
        _trace_step_view(step)
        for step in failed_steps_from_payload(payload, step_number=step_number)
    ]
    return {
        "task_id": str(task_id),
        "count": len(failed_steps),
        "failed_steps": mask_sensitive(failed_steps),
        "has_trace": payload.get("has_trace"),
        "trace_url": payload.get("trace_url"),
    }


def _parse_step_number(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _trace_step_view(step: dict[str, Any]) -> dict[str, Any]:
    return {
        "case_title": step.get("case_title"),
        "step_number": step.get("step_number"),
        "description": step.get("description"),
        "expected_result": step.get("expected_result"),
        "status": step.get("status"),
        "error_message": step.get("error_message") or step.get("case_error_message"),
        "assertion_reason": step.get("assertion_reason"),
        "assertion_evidence": compact_text(step.get("assertion_evidence")),
        "ai_reasoning": compact_text(step.get("ai_reasoning"), max_len=3000),
        "tool_calls": step.get("tool_calls") or [],
        "snapshot_before": compact_text(step.get("snapshot_before")),
        "snapshot_after": compact_text(step.get("snapshot_after")),
    }
