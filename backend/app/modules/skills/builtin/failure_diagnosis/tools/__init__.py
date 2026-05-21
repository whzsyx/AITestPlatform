"""``system__failure_diagnosis__*`` 工具集（Phase 13 / Task 13.8）。"""

from __future__ import annotations

from app.modules.skills.builtin.failure_diagnosis.tools.get_execution_detail import (
    GET_EXECUTION_DETAIL_SCHEMA,
    GET_EXECUTION_DETAIL_TOOL_NAME,
    exec_get_execution_detail,
)
from app.modules.skills.builtin.failure_diagnosis.tools.get_failed_step_trace import (
    GET_FAILED_STEP_TRACE_SCHEMA,
    GET_FAILED_STEP_TRACE_TOOL_NAME,
    exec_get_failed_step_trace,
)
from app.modules.skills.builtin.failure_diagnosis.tools.get_step_screenshots import (
    GET_STEP_SCREENSHOTS_SCHEMA,
    GET_STEP_SCREENSHOTS_TOOL_NAME,
    exec_get_step_screenshots,
)
from app.modules.skills.builtin.failure_diagnosis.tools.propose_fix_action import (
    PROPOSE_FIX_ACTION_SCHEMA,
    PROPOSE_FIX_ACTION_TOOL_NAME,
    exec_propose_fix_action,
)

FAILURE_DIAGNOSIS_TOOL_NAMES: tuple[str, ...] = (
    GET_EXECUTION_DETAIL_TOOL_NAME,
    GET_STEP_SCREENSHOTS_TOOL_NAME,
    GET_FAILED_STEP_TRACE_TOOL_NAME,
    PROPOSE_FIX_ACTION_TOOL_NAME,
)


def failure_diagnosis_chat_openai_schemas() -> dict[str, dict]:
    """4 个 ``system__failure_diagnosis__*`` tool 的 OpenAI Chat tool spec。"""
    return {
        GET_EXECUTION_DETAIL_TOOL_NAME: GET_EXECUTION_DETAIL_SCHEMA,
        GET_STEP_SCREENSHOTS_TOOL_NAME: GET_STEP_SCREENSHOTS_SCHEMA,
        GET_FAILED_STEP_TRACE_TOOL_NAME: GET_FAILED_STEP_TRACE_SCHEMA,
        PROPOSE_FIX_ACTION_TOOL_NAME: PROPOSE_FIX_ACTION_SCHEMA,
    }


_REGISTERED = False


def ensure_failure_diagnosis_tools_registered() -> None:
    """进程级一次性注册到 ``TOOL_REGISTRY``。"""
    global _REGISTERED
    if _REGISTERED:
        return
    from app.modules.llm.agent_tools import register_tool

    register_tool(GET_EXECUTION_DETAIL_TOOL_NAME, exec_get_execution_detail)
    register_tool(GET_STEP_SCREENSHOTS_TOOL_NAME, exec_get_step_screenshots)
    register_tool(GET_FAILED_STEP_TRACE_TOOL_NAME, exec_get_failed_step_trace)
    register_tool(PROPOSE_FIX_ACTION_TOOL_NAME, exec_propose_fix_action)
    _REGISTERED = True


__all__ = [
    "FAILURE_DIAGNOSIS_TOOL_NAMES",
    "GET_EXECUTION_DETAIL_TOOL_NAME",
    "GET_FAILED_STEP_TRACE_TOOL_NAME",
    "GET_STEP_SCREENSHOTS_TOOL_NAME",
    "PROPOSE_FIX_ACTION_TOOL_NAME",
    "ensure_failure_diagnosis_tools_registered",
    "failure_diagnosis_chat_openai_schemas",
]
