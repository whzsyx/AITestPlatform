"""``system__ui_automation__*`` 工具集（Phase 13 / Task 13.1）。

- ``search_test_cases``：按标题模糊搜（M1）；M2 task 13.2 升级为三策略级联
- ``list_environments``：列项目环境 + 真实 risk_level
- ``list_test_data_sets``：列项目物料集 + scope / item_count
- ``list_test_data_semantics``：列物料语义词表，不含真实物料值
- ``resolve_test_data``：按语义解析本次执行物料预览，不暴露 secret 明文
- ``propose_execution_plan``：装配 ConfirmationCard payload，返回 plan_id
- ``draft_adhoc_case``：search 0 命中后生成可编辑即席步骤确认卡
- ``save_adhoc_as_testcase``：把成功的 adhoc 执行转为正式用例

八个 tool 的 OpenAI schema 与执行函数同时通过 ``ensure_ui_automation_tools_
registered()`` 注册到 ``TOOL_REGISTRY``；由 ``platform_tools`` 暴露的 chat
runtime（``ChatPlatformRuntime``）提供 db / user / project_id。
"""

from app.modules.skills.builtin.ui_automation.tools.draft_adhoc_case import (
    DRAFT_ADHOC_CASE_SCHEMA,
    DRAFT_ADHOC_CASE_TOOL_NAME,
    exec_draft_adhoc_case,
)
from app.modules.skills.builtin.ui_automation.tools.list_environments import (
    LIST_ENVIRONMENTS_SCHEMA,
    LIST_ENVIRONMENTS_TOOL_NAME,
    exec_list_environments,
)
from app.modules.skills.builtin.ui_automation.tools.list_test_data_semantics import (
    LIST_TEST_DATA_SEMANTICS_SCHEMA,
    LIST_TEST_DATA_SEMANTICS_TOOL_NAME,
    exec_list_test_data_semantics,
)
from app.modules.skills.builtin.ui_automation.tools.list_test_data_sets import (
    LIST_TEST_DATA_SETS_SCHEMA,
    LIST_TEST_DATA_SETS_TOOL_NAME,
    exec_list_test_data_sets,
)
from app.modules.skills.builtin.ui_automation.tools.propose_execution_plan import (
    PROPOSE_EXECUTION_PLAN_SCHEMA,
    PROPOSE_EXECUTION_PLAN_TOOL_NAME,
    exec_propose_execution_plan,
)
from app.modules.skills.builtin.ui_automation.tools.resolve_test_data import (
    RESOLVE_TEST_DATA_SCHEMA,
    RESOLVE_TEST_DATA_TOOL_NAME,
    exec_resolve_test_data,
)
from app.modules.skills.builtin.ui_automation.tools.save_adhoc_as_testcase import (
    SAVE_ADHOC_AS_TESTCASE_SCHEMA,
    SAVE_ADHOC_AS_TESTCASE_TOOL_NAME,
    exec_save_adhoc_as_testcase,
)
from app.modules.skills.builtin.ui_automation.tools.search_test_cases import (
    SEARCH_TEST_CASES_SCHEMA,
    SEARCH_TEST_CASES_TOOL_NAME,
    exec_search_test_cases,
)

#: 设计文档 §10.7：``run_ui_test`` 永远不在此 list 中——LLM 不能直接派发
#: 执行；只能调 ``propose_execution_plan`` 走前端用户 confirm 路径。
UI_AUTOMATION_TOOL_NAMES: tuple[str, ...] = (
    SEARCH_TEST_CASES_TOOL_NAME,
    LIST_ENVIRONMENTS_TOOL_NAME,
    LIST_TEST_DATA_SETS_TOOL_NAME,
    LIST_TEST_DATA_SEMANTICS_TOOL_NAME,
    RESOLVE_TEST_DATA_TOOL_NAME,
    PROPOSE_EXECUTION_PLAN_TOOL_NAME,
    DRAFT_ADHOC_CASE_TOOL_NAME,
    SAVE_ADHOC_AS_TESTCASE_TOOL_NAME,
)


def ui_automation_chat_openai_schemas() -> dict[str, dict]:
    """8 个 ``system__ui_automation__*`` tool 的 OpenAI Chat tool spec。"""
    return {
        SEARCH_TEST_CASES_TOOL_NAME: SEARCH_TEST_CASES_SCHEMA,
        LIST_ENVIRONMENTS_TOOL_NAME: LIST_ENVIRONMENTS_SCHEMA,
        LIST_TEST_DATA_SETS_TOOL_NAME: LIST_TEST_DATA_SETS_SCHEMA,
        LIST_TEST_DATA_SEMANTICS_TOOL_NAME: LIST_TEST_DATA_SEMANTICS_SCHEMA,
        RESOLVE_TEST_DATA_TOOL_NAME: RESOLVE_TEST_DATA_SCHEMA,
        PROPOSE_EXECUTION_PLAN_TOOL_NAME: PROPOSE_EXECUTION_PLAN_SCHEMA,
        DRAFT_ADHOC_CASE_TOOL_NAME: DRAFT_ADHOC_CASE_SCHEMA,
        SAVE_ADHOC_AS_TESTCASE_TOOL_NAME: SAVE_ADHOC_AS_TESTCASE_SCHEMA,
    }


_REGISTERED = False


def ensure_ui_automation_tools_registered() -> None:
    """进程级一次性注册到 ``TOOL_REGISTRY``；同 ``ensure_platform_tools_registered``
    幂等可重复调用（已注册的会触发 ``register_tool`` warning，但不会重复执行）。
    """
    global _REGISTERED
    if _REGISTERED:
        return
    from app.modules.llm.agent_tools import register_tool

    register_tool(SEARCH_TEST_CASES_TOOL_NAME, exec_search_test_cases)
    register_tool(LIST_ENVIRONMENTS_TOOL_NAME, exec_list_environments)
    register_tool(LIST_TEST_DATA_SETS_TOOL_NAME, exec_list_test_data_sets)
    register_tool(LIST_TEST_DATA_SEMANTICS_TOOL_NAME, exec_list_test_data_semantics)
    register_tool(RESOLVE_TEST_DATA_TOOL_NAME, exec_resolve_test_data)
    register_tool(PROPOSE_EXECUTION_PLAN_TOOL_NAME, exec_propose_execution_plan)
    register_tool(DRAFT_ADHOC_CASE_TOOL_NAME, exec_draft_adhoc_case)
    register_tool(SAVE_ADHOC_AS_TESTCASE_TOOL_NAME, exec_save_adhoc_as_testcase)
    _REGISTERED = True


__all__ = [
    "DRAFT_ADHOC_CASE_TOOL_NAME",
    "LIST_ENVIRONMENTS_TOOL_NAME",
    "LIST_TEST_DATA_SETS_TOOL_NAME",
    "LIST_TEST_DATA_SEMANTICS_TOOL_NAME",
    "PROPOSE_EXECUTION_PLAN_TOOL_NAME",
    "RESOLVE_TEST_DATA_TOOL_NAME",
    "SAVE_ADHOC_AS_TESTCASE_TOOL_NAME",
    "SEARCH_TEST_CASES_TOOL_NAME",
    "UI_AUTOMATION_TOOL_NAMES",
    "ensure_ui_automation_tools_registered",
    "ui_automation_chat_openai_schemas",
]
