"""``system__ui_automation__search_test_cases`` 工具（Phase 13 / Task 13.2）。

实现：调 ``matchers.case_matcher.match_test_cases`` 跑三策略级联——

- 策略 1：``#NNN`` / ``TC-NNN`` / UUID 精确（score=1.0）
- 策略 2：title 模糊 + tags GIN 召回（score 0.4 ~ 0.95）
- 策略 3：步骤内容 ilike 兜底（score 0.3 ~ 0.6）

返回 ``CaseSummary`` 列表，含 ``relevance_score`` 与 ``matched_via``——前端
ConfirmationCard 后续会基于这两个字段渲染"为什么命中"徽章 + 排序。
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any

from app.modules.skills.builtin.ui_automation.matchers.case_matcher import (
    candidate_to_dict,
    match_test_cases,
)
from app.modules.skills.builtin.ui_automation.schemas import (
    CaseSummary,
    SearchTestCasesResult,
)
from app.modules.skills.platform_tools import _get_runtime

logger = logging.getLogger(__name__)


SEARCH_TEST_CASES_TOOL_NAME = "system__ui_automation__search_test_cases"

SEARCH_TEST_CASES_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": SEARCH_TEST_CASES_TOOL_NAME,
        "description": (
            "在当前项目下搜索 UI 自动化测试用例（三策略级联：① #NNN/TC-NNN/UUID "
            "精确；② title + tags 模糊；③ 步骤内容召回）。每条返回含 "
            "relevance_score (0..1) 与 matched_via 命中策略，AI 据此判断："
            "命中 1 条 → 继续让用户确认环境；命中 N 条 → 让用户选；"
            "命中 0 条 → 走 adhoc 流程。若用户只说'跑用例/执行用例'且没有"
            "明确模块、标题或编号，必须先调用 list_testcase_modules 让用户选模块，"
            "不要直接用空 query 搜最近用例。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "搜索关键字。支持自然语言（'登录用例'/'回归用例'/"
                        "'点击登录按钮'）、编号引用（'#123' / 'TC-0042'）、"
                        "用例 UUID 直填。已传 module_id 时可省略（列出该模块最近"
                        "更新的若干条）。未传 module_id 时不要用空 query。"
                    ),
                },
                "module_id": {
                    "type": "string",
                    "description": (
                        "可选模块 UUID。用户已选择模块时必须传；搜索范围包含该模块"
                        "及其所有子模块。"
                    ),
                },
                "limit": {
                    "type": "integer",
                    "description": "最多返回条数，默认 10，上限 30",
                    "default": 10,
                },
            },
        },
    },
}


_LOW_INFORMATION_QUERY_RE = re.compile(
    r"^(?:跑|执行|运行|启动|帮我跑|帮跑|请跑|麻烦跑)?"
    r"(?:一下|下|一遍|一轮|个)?"
    r"(?:ui)?(?:自动化)?(?:测试)?用例(?:测试)?$",
    re.IGNORECASE,
)


def _is_low_information_query(query: str) -> bool:
    q = re.sub(r"[\s,，。.!！?？]+", "", (query or "").strip().lower())
    if not q:
        return True
    return bool(_LOW_INFORMATION_QUERY_RE.match(q)) or q in {
        "用例",
        "测试用例",
        "ui用例",
        "自动化用例",
        "ui自动化用例",
        "测试",
        "uitest",
        "testcase",
        "cases",
    }


async def exec_search_test_cases(args: dict[str, Any]) -> dict[str, Any]:
    rt = _get_runtime()
    if rt is None:
        return {
            "error": (
                "search_test_cases requires an active chat runtime "
                "(no project_id bound)"
            ),
        }

    raw_q = args.get("query")
    q = (raw_q or "").strip() if isinstance(raw_q, str) else ""
    limit = int(args.get("limit") or 10)
    limit = max(1, min(limit, 30))

    raw_module_id = args.get("module_id")
    module_id: uuid.UUID | None = None
    if raw_module_id:
        try:
            module_id = uuid.UUID(str(raw_module_id))
        except (TypeError, ValueError):
            return {"error": f"invalid module_id: {raw_module_id!r}"}

    if module_id is None and _is_low_information_query(q):
        payload = SearchTestCasesResult(
            count=0,
            cases=[],
            query=q[:100] if q else None,
            requires_module_selection=True,
            message=(
                "当前执行指令没有明确模块或用例。请先调用 "
                "system__ui_automation__list_testcase_modules 列出模块，并让用户选择模块。"
            ),
        )
        return payload.model_dump(mode="json")

    effective_query = "" if module_id is not None and _is_low_information_query(q) else q
    candidates = await match_test_cases(
        rt.db, effective_query, rt.project_id, limit=limit, module_id=module_id,
    )

    cases = [
        CaseSummary(
            id=c.case.id,
            case_no=c.case.case_no,
            title=c.case.title,
            priority=c.case.priority,
            status=c.case.status,
            relevance_score=round(float(c.relevance_score), 3),
            matched_via=[m.value for m in c.matched_via],
        )
        for c in candidates
    ]
    payload = SearchTestCasesResult(
        count=len(cases),
        cases=cases,
        query=effective_query[:100] if effective_query else None,
        module_id=module_id,
    )
    out = payload.model_dump(mode="json")
    # 调试日志：让排错时一眼看到三策略的命中分布
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(
            "search_test_cases: q=%r → %d candidates: %s",
            q, len(candidates),
            [candidate_to_dict(c) for c in candidates],
        )
    return out
