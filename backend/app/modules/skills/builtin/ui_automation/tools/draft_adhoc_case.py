"""``system__ui_automation__draft_adhoc_case`` 工具（Phase 13 / Task 13.6）。"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from app.database import async_session_factory
from app.modules.skills.builtin.ui_automation.plan_builder import (
    build_adhoc_execution_plan,
    update_cached_plan_skill_card,
)
from app.modules.skills.platform_tools import _get_runtime

logger = logging.getLogger(__name__)


DRAFT_ADHOC_CASE_TOOL_NAME = "system__ui_automation__draft_adhoc_case"

DRAFT_ADHOC_CASE_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": DRAFT_ADHOC_CASE_TOOL_NAME,
        "description": (
            "当 search_test_cases 0 命中时，把用户自然语言描述转换成可编辑的即席"
            "UI 自动化步骤草稿，并生成 kind=adhoc_plan 的 ConfirmationCard。"
            "用户必须在前端确认后才会真正执行。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "description": {
                    "type": "string",
                    "description": "用户对想测试功能的自然语言描述",
                },
                "environment_id": {
                    "type": "string",
                    "description": "目标环境 UUID（必填，不允许 AI 默认）",
                },
                "title": {
                    "type": "string",
                    "description": "可选草稿标题；省略时由 description 生成",
                },
                "target_url": {
                    "type": "string",
                    "description": "可选入口 URL；相对路径会拼到环境 base_url",
                },
                "llm_config_id": {
                    "type": "string",
                    "description": "本次执行使用的 LLM 配置 UUID；省略时用项目默认配置",
                },
            },
            "required": ["description", "environment_id"],
        },
    },
}


async def exec_draft_adhoc_case(args: dict[str, Any]) -> dict[str, Any]:
    rt = _get_runtime()
    if rt is None:
        return {
            "error": (
                "draft_adhoc_case requires an active chat runtime "
                "(no project_id bound)"
            ),
        }

    description = str(args.get("description") or "").strip()
    if not description:
        return {"error": "description is required"}

    env_raw = args.get("environment_id")
    if not env_raw:
        return {"error": "environment_id is required (do not let AI default it)"}
    try:
        env_id = uuid.UUID(str(env_raw))
    except (TypeError, ValueError):
        return {"error": f"invalid environment_id: {env_raw!r}"}

    llm_raw = args.get("llm_config_id")
    llm_id: uuid.UUID | None = None
    if llm_raw:
        try:
            llm_id = uuid.UUID(str(llm_raw))
        except (TypeError, ValueError):
            return {"error": f"invalid llm_config_id: {llm_raw!r}"}

    try:
        plan = await build_adhoc_execution_plan(
            rt.db,
            project_id=rt.project_id,
            user=rt.user,
            description=description,
            environment_id=env_id,
            llm_config_id=llm_id or rt.llm_config_id,
            title=args.get("title"),
            target_url=args.get("target_url"),
        )
    except ValueError as exc:
        return {"error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        logger.exception("draft_adhoc_case failed")
        return {"error": f"unexpected error: {exc}"}

    if rt.session_id is not None:
        try:
            from app.modules.llm.system_event_service import publish_skill_card

            payload = plan.model_dump(mode="json")
            async with async_session_factory() as bg_db:
                msg = await publish_skill_card(
                    bg_db,
                    session_id=rt.session_id,
                    plan_id=plan.plan_id,
                    plan_payload=payload,
                )
            if msg is not None:
                await update_cached_plan_skill_card(plan.plan_id, msg.id)
                payload["skill_card_message_id"] = str(msg.id)
                return payload
        except Exception:  # noqa: BLE001
            logger.exception("draft_adhoc_case: persist skill_card failed; continuing")

    return plan.model_dump(mode="json")
