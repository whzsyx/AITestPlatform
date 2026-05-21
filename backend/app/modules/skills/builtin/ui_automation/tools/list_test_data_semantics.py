"""``system__ui_automation__list_test_data_semantics`` 工具。

返回平台推荐的物料语义词表，供 LLM 在匹配物料、提示补料或生成执行计划前
统一使用，避免把同一语义猜成多个 key 名。
"""

from __future__ import annotations

from typing import Any

from app.modules.test_data.semantic_catalog import list_semantic_catalog

LIST_TEST_DATA_SEMANTICS_TOOL_NAME = "system__ui_automation__list_test_data_semantics"

LIST_TEST_DATA_SEMANTICS_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": LIST_TEST_DATA_SEMANTICS_TOOL_NAME,
        "description": (
            "列出测试物料的推荐语义词表，包括 item_semantics（物料项语义，如 "
            "login_username/login_password）和 set_purposes（物料集用途，如 "
            "login/smoke/regression）。返回值不包含任何真实物料值。"
        ),
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
}


async def exec_list_test_data_semantics(args: dict[str, Any]) -> dict[str, Any]:
    _ = args
    return list_semantic_catalog()
