"""failure_diagnosis 内置工具的共享实现。"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterable, Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import User
from app.modules.skills.platform_tools import ChatPlatformRuntime, _get_runtime

SECRET_KEY_HINTS: tuple[str, ...] = (
    "password",
    "passwd",
    "pwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "authorization",
    "cookie",
)
MASK = "<masked>"

_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(password|passwd|pwd|secret|token|api_key|apikey|authorization|cookie)\s*=\s*([^\s,'\"<>]+)",
)
_PASSWORD_INPUT_VALUE_RE = re.compile(
    r"(?is)(<input\b[^>]*type\s*=\s*['\"]?password['\"]?[^>]*\bvalue\s*=\s*['\"])([^'\"]+)(['\"])",
)


async def _load_execution_detail_payload(
    db: AsyncSession,
    user: User,
    task_id: uuid.UUID,
) -> dict[str, Any]:
    """从 UI 自动化执行服务读取详情，并转换为可脱敏的 plain dict。"""
    from app.modules.ui_automation.execution_service import get_execution_detail

    detail = await get_execution_detail(db, task_id, user)
    if hasattr(detail, "model_dump"):
        return detail.model_dump(mode="json")
    if isinstance(detail, dict):
        return detail
    return dict(detail)


def require_runtime() -> ChatPlatformRuntime | None:
    """诊断读取类工具必须运行在 chat platform runtime 内。"""
    return _get_runtime()


def parse_task_id(args: Mapping[str, Any]) -> tuple[uuid.UUID | None, dict[str, str] | None]:
    raw = args.get("task_id") or args.get("execution_id")
    if not raw:
        return None, {"error": "task_id is required"}
    try:
        return uuid.UUID(str(raw)), None
    except (TypeError, ValueError):
        return None, {"error": f"invalid task_id: {raw!r}"}


def mask_sensitive(value: Any) -> Any:
    """递归脱敏诊断 payload。

    规则故意保守：只要 key 命中 secret hint，或对象标记了
    ``_test_data_secret_used``，就屏蔽对应 value。字符串里常见
    ``password=xxx`` / ``token=xxx`` 也会被替换。
    """
    if isinstance(value, Mapping):
        secret_marked = bool(value.get("_test_data_secret_used"))
        secret_context = secret_marked or any(
            _is_secret_key(str(k).lower())
            or (isinstance(v, str) and _contains_secret_hint(v))
            for k, v in value.items()
        )
        out: dict[str, Any] = {}
        for raw_key, raw_val in value.items():
            key = str(raw_key)
            key_lower = key.lower()
            if secret_context and key in {"value", "value_text", "text", "result"}:
                out[key] = MASK
            elif _is_secret_key(key_lower):
                out[key] = MASK
            else:
                out[key] = mask_sensitive(raw_val)
        return out
    if isinstance(value, list):
        return [mask_sensitive(item) for item in value]
    if isinstance(value, tuple):
        return [mask_sensitive(item) for item in value]
    if isinstance(value, str):
        return _mask_string(value)
    return value


def compact_text(value: Any, *, max_len: int = 2000) -> Any:
    """限制大字段长度，避免把完整 DOM / trace 塞进 tool result。"""
    if not isinstance(value, str):
        return value
    if len(value) <= max_len:
        return value
    return f"{value[:max_len]}...<truncated>"


def failed_steps_from_payload(
    payload: Mapping[str, Any],
    *,
    step_number: int | None = None,
) -> list[dict[str, Any]]:
    failed: list[dict[str, Any]] = []
    for case in _iter_case_results(payload):
        case_title = case.get("testcase_title") or case.get("testcase_name") or case.get("title")
        case_status = case.get("status")
        for step in _iter_steps(case):
            if step_number is not None and int(step.get("step_number") or -1) != step_number:
                continue
            status = str(step.get("status") or "").lower()
            assertion_passed = step.get("assertion_passed")
            if status not in {"failed", "error", "timeout"} and assertion_passed is not False:
                continue
            merged = dict(step)
            merged["case_title"] = case_title
            merged["case_status"] = case_status
            merged["case_error_message"] = case.get("error_message")
            failed.append(merged)
    return failed


def normalize_suggested_actions(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    actions: list[dict[str, Any]] = []
    for item in value[:5]:
        if not isinstance(item, Mapping):
            continue
        action = str(item.get("action") or "").strip() or "retry_with_correction"
        label = str(item.get("label") or "").strip() or "按建议重试"
        params = item.get("params")
        actions.append({
            "action": action,
            "label": label,
            "params": mask_sensitive(params if isinstance(params, Mapping) else {}),
        })
    return actions


def _iter_case_results(payload: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
    raw = payload.get("case_results") or payload.get("cases") or []
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, Mapping)]


def _iter_steps(case: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
    raw = case.get("steps") or case.get("step_results") or []
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, Mapping)]


def _is_secret_key(key_lower: str) -> bool:
    return any(hint in key_lower for hint in SECRET_KEY_HINTS)


def _contains_secret_hint(value: str) -> bool:
    lower = value.lower()
    return any(hint in lower for hint in SECRET_KEY_HINTS)


def _mask_string(value: str) -> str:
    out = _ASSIGNMENT_RE.sub(lambda m: f"{m.group(1)}={MASK}", value)
    return _PASSWORD_INPUT_VALUE_RE.sub(lambda m: f"{m.group(1)}{MASK}{m.group(3)}", out)
