"""``system__failure_diagnosis__propose_fix_action`` 工具。"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

from app.modules.skills.builtin.failure_diagnosis.tools.common import (
    mask_sensitive,
    normalize_suggested_actions,
    parse_task_id,
)

PROPOSE_FIX_ACTION_TOOL_NAME = "system__failure_diagnosis__propose_fix_action"

PROPOSE_FIX_ACTION_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": PROPOSE_FIX_ACTION_TOOL_NAME,
        "description": (
            "把失败诊断结论整理成前端可渲染的 FixActionCard 结构化 meta。"
            "用于给出重试、修正物料、打开 trace 或改执行计划等建议；本工具不会"
            "直接重新执行任务。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "UI 执行任务 UUID",
                },
                "failed_step": {
                    "type": "object",
                    "description": "失败步骤摘要，如 index/name/status",
                },
                "diagnosis": {
                    "type": "object",
                    "description": "诊断结论，建议包含 root_cause/evidence/confidence",
                },
                "suggested_actions": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": (
                        "建议动作列表，如 retry_with_correction / update_test_data / "
                        "open_trace_viewer。params 会自动脱敏。"
                    ),
                },
            },
            "required": ["task_id", "diagnosis", "suggested_actions"],
        },
    },
}


async def exec_propose_fix_action(args: dict[str, Any]) -> dict[str, Any]:
    task_id, err = parse_task_id(args)
    if err is not None:
        return err
    assert isinstance(task_id, uuid.UUID)

    diagnosis = args.get("diagnosis")
    if not isinstance(diagnosis, Mapping):
        diagnosis = {}

    failed_step = args.get("failed_step")
    if not isinstance(failed_step, Mapping):
        failed_step = {}

    actions = normalize_suggested_actions(args.get("suggested_actions"))
    if not actions:
        actions = [
            {
                "action": "retry_with_correction",
                "label": "按诊断建议重新生成执行计划",
                "params": {},
            },
        ]

    clean_diagnosis = mask_sensitive(dict(diagnosis))
    evidence = clean_diagnosis.get("evidence")
    if not isinstance(evidence, list):
        evidence = []

    return {
        "action_type": "fix_action",
        "task_id": str(task_id),
        "failed_step": mask_sensitive(dict(failed_step)),
        "diagnosis": {
            "root_cause": clean_diagnosis.get("root_cause") or "未定位到明确根因",
            "evidence": evidence[:8],
            "confidence": _clamp_confidence(clean_diagnosis.get("confidence")),
        },
        "suggested_actions": actions,
    }


def _clamp_confidence(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.5
    return max(0.0, min(parsed, 1.0))
