"""``system__ui_automation__list_testcase_modules`` 工具。

用于 UI 自动化执行前的第一步选择：当用户只说"跑用例"、"执行用例"等
低信息指令时，先把项目模块列出来，再让用户选择模块，避免直接返回最近用例。
"""

from __future__ import annotations

from typing import Any

from app.modules.skills.builtin.ui_automation.schemas import (
    ListTestcaseModulesResult,
    TestcaseModuleSummary,
)
from app.modules.skills.platform_tools import _get_runtime
from app.modules.testcases.schemas import ModuleTreeNode
from app.modules.testcases.service import get_module_tree


LIST_TESTCASE_MODULES_TOOL_NAME = "system__ui_automation__list_testcase_modules"

LIST_TESTCASE_MODULES_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": LIST_TESTCASE_MODULES_TOOL_NAME,
        "description": (
            "列出当前项目的测试用例模块树，返回 module_id / path / case_count。"
            "当用户只说'跑用例'、'跑 UI 测试'、'执行用例'，没有明确 #编号、"
            "用例标题或模块名时，必须先调用本工具并让用户选择模块；用户选定"
            "模块后，再用 search_test_cases(module_id=...) 列出该模块下用例。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "可选模块名/路径关键字过滤，如 '店铺'、'登录'",
                },
                "include_empty": {
                    "type": "boolean",
                    "description": "是否返回 0 用例模块，默认 false",
                    "default": False,
                },
                "limit": {
                    "type": "integer",
                    "description": "最多返回模块数，默认 50，上限 100",
                    "default": 50,
                },
            },
        },
    },
}


def _flatten_modules(
    nodes: list[ModuleTreeNode],
    *,
    query: str,
    include_empty: bool,
    parent_path: list[str] | None = None,
    depth: int = 0,
) -> list[TestcaseModuleSummary]:
    parent_path = parent_path or []
    out: list[TestcaseModuleSummary] = []
    q = query.lower().strip()

    for node in nodes:
        path_parts = [*parent_path, node.name]
        path = " / ".join(path_parts)
        searchable = f"{node.name} {path}".lower()
        include = (include_empty or node.case_count > 0) and (not q or q in searchable)
        if include:
            out.append(
                TestcaseModuleSummary(
                    id=node.id,
                    name=node.name,
                    path=path,
                    parent_id=node.parent_id,
                    depth=depth,
                    case_count=node.case_count,
                    entry_path=node.entry_path,
                ),
            )
        out.extend(
            _flatten_modules(
                node.children or [],
                query=query,
                include_empty=include_empty,
                parent_path=path_parts,
                depth=depth + 1,
            ),
        )
    return out


async def exec_list_testcase_modules(args: dict[str, Any]) -> dict[str, Any]:
    rt = _get_runtime()
    if rt is None:
        return {
            "error": (
                "list_testcase_modules requires an active chat runtime "
                "(no project_id bound)"
            ),
        }

    query = (args.get("query") or "").strip() if isinstance(args.get("query"), str) else ""
    include_empty = bool(args.get("include_empty") or False)
    limit = int(args.get("limit") or 50)
    limit = max(1, min(limit, 100))

    tree = await get_module_tree(rt.db, rt.project_id)
    modules = _flatten_modules(tree, query=query, include_empty=include_empty)
    payload = ListTestcaseModulesResult(
        count=len(modules[:limit]),
        modules=modules[:limit],
        query=query[:100] if query else None,
    )
    return payload.model_dump(mode="json")

