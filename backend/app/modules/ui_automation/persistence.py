"""执行结果落盘（Task 9.5 实现）。

把 ``ExecutionEngine`` 的事件流落到 ``ui_executions / ui_case_results /
ui_step_results`` 三张表。设计 §4.1 与 ``models.py`` 对齐。

设计要点：
- **独立 session**：每个函数 ``async with async_session_factory()`` 开自己的
  session，不依赖 HTTP 请求 session（Engine 跑在后台 task，没有 request scope）
- **secret 脱敏**：``sanitize_tool_call_for_storage`` 把任何
  ``_test_data_secret_used=True`` 的 tool 结果里的 plaintext 替换成
  ``"<secret used>"`` 占位
- **idempotent**：``init_execution_record`` 已存在时不重复插入
- **插入顺序约束**：先 ``init_execution_record`` → 每条用例 ``create_case_result``
  → 该用例下每步 ``flush_step`` → ``flush_case`` 收口该用例 → 全部完成
  ``flush_execution`` 收口整次执行

测试策略：用 ``in-memory monkeypatch`` 替换 ``async_session_factory`` 即可
脱离真 PG 跑（详见 ``tests/ui_automation/test_persistence.py``）。
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from app.database import async_session_factory
from app.modules.ui_automation.models import (
    UICaseResult,
    UIExecution,
    UIStepResult,
)

logger = logging.getLogger(__name__)
RUNTIME_DATA_MAX_BYTES = 1024 * 1024


# ─── secret 脱敏 ─────────────────────────────────────────────────────


_SECRET_PLACEHOLDER = "<secret used>"


def sanitize_tool_call_for_storage(record: dict[str, Any]) -> dict[str, Any]:
    """把单条 tool_call 记录脱敏后返回新 dict。

    规则：
    - ``record["result"]["_test_data_secret_used"] is True`` → 把 ``value``
      字段替换为 ``"<secret used>"``，并保留 ``key``、``_test_data_secret_used``
    - 其他字段（args / duration / blocked / error）原样保留
    - 输入是 dict 时返回 dict；非 dict 直接返回（不抛错）
    """
    if not isinstance(record, dict):
        return record
    out = dict(record)
    result = out.get("result")
    if isinstance(result, dict) and result.get("_test_data_secret_used"):
        sanitized: dict[str, Any] = {}
        for k, v in result.items():
            if k == "value":
                sanitized[k] = _SECRET_PLACEHOLDER
            else:
                sanitized[k] = v
        out["result"] = sanitized
    return out


def sanitize_tool_calls(records: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if not records:
        return []
    return [sanitize_tool_call_for_storage(r) for r in records]


# ─── execution ───────────────────────────────────────────────────────


async def init_execution_record(
    *,
    execution_id: uuid.UUID,
    project_id: uuid.UUID,
    environment_id: uuid.UUID | None,
    triggered_by: uuid.UUID | None,
    chat_message_id: uuid.UUID | None = None,
    mode: str = "normal",
    total_cases: int = 0,
    config_snapshot: dict[str, Any] | None = None,
    # Phase 13 / Task 13.3 —— chat 派发新增；老调用方不传时按 ORM column 默认
    # 走（source='catalog'，其余 NULL），与 Phase 12 行为一致。
    source: str | None = None,
    triggered_chat_session_id: uuid.UUID | None = None,
    adhoc_steps: dict[str, Any] | None = None,
) -> UIExecution:
    """如果记录不存在则插入；存在则更新初始字段。返回 ORM 行。"""
    async with async_session_factory() as session:
        existing = (
            await session.execute(select(UIExecution).where(UIExecution.id == execution_id))
        ).scalar_one_or_none()
        now = datetime.now(timezone.utc)
        if existing is None:
            row = UIExecution(
                id=execution_id,
                project_id=project_id,
                environment_id=environment_id,
                status="pending",
                mode=mode,
                total_cases=total_cases,
                triggered_by=triggered_by,
                chat_message_id=chat_message_id,
                config_snapshot=config_snapshot or {},
                started_at=None,
                completed_at=None,
                created_at=now,
                updated_at=now,
            )
            if source is not None:
                row.source = source
            if triggered_chat_session_id is not None:
                row.triggered_chat_session_id = triggered_chat_session_id
            if adhoc_steps is not None:
                row.adhoc_steps = adhoc_steps
            row.runtime_data = getattr(row, "runtime_data", None) or {}
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return row
        existing.mode = mode
        existing.total_cases = total_cases
        existing.config_snapshot = config_snapshot or {}
        existing.chat_message_id = chat_message_id
        if source is not None:
            existing.source = source
        if triggered_chat_session_id is not None:
            existing.triggered_chat_session_id = triggered_chat_session_id
        if adhoc_steps is not None:
            existing.adhoc_steps = adhoc_steps
        if getattr(existing, "runtime_data", None) is None:
            existing.runtime_data = {}
        await session.commit()
        await session.refresh(existing)
        return existing


def _runtime_data_size(payload: dict[str, Any]) -> int:
    return len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


async def store_runtime_data(
    execution_id: uuid.UUID,
    key: str,
    value: str,
    *,
    ttl_seconds: int = 3600,
) -> dict[str, Any]:
    """把单个 runtime key 写入 ``ui_executions.runtime_data``。

    ``ttl_seconds`` 暂作为审计回显参数保留；runtime_data 作用域天然限制在单次
    execution，任务结束后不会被后续任务读取。
    """
    async with async_session_factory() as session:
        row = (
            await session.execute(select(UIExecution).where(UIExecution.id == execution_id))
        ).scalar_one_or_none()
        if row is None:
            return {"error": f"execution {execution_id} not found", "error_code": "EXEC_NOT_FOUND"}

        runtime = dict(getattr(row, "runtime_data", None) or {})
        runtime[key] = value
        size = _runtime_data_size(runtime)
        if size > RUNTIME_DATA_MAX_BYTES:
            logger.warning(
                "runtime_data too large; reject write execution_id=%s key=%s size=%s",
                execution_id,
                key,
                size,
            )
            return {
                "error": f"runtime_data exceeds {RUNTIME_DATA_MAX_BYTES} bytes",
                "error_code": "RUNTIME_DATA_TOO_LARGE",
                "size_bytes": size,
            }

        row.runtime_data = runtime
        await session.commit()
        return {
            "key": key,
            "value": value,
            "stored": True,
            "ttl_seconds": ttl_seconds,
            "size_bytes": size,
        }


async def mark_execution_running(
    *,
    execution_id: uuid.UUID,
    test_data_snapshot: dict[str, Any] | None = None,
) -> None:
    async with async_session_factory() as session:
        row = (
            await session.execute(select(UIExecution).where(UIExecution.id == execution_id))
        ).scalar_one_or_none()
        if row is None:
            logger.warning("mark_execution_running: %s not found", execution_id)
            return
        row.status = "running"
        row.started_at = datetime.now(timezone.utc)
        if test_data_snapshot is not None:
            row.test_data_snapshot = test_data_snapshot
        await session.commit()


async def is_execution_stopped(execution_id: uuid.UUID) -> bool:
    """供 Engine 在循环间检查"用户是否点了停止"。"""
    async with async_session_factory() as session:
        row = (
            await session.execute(select(UIExecution).where(UIExecution.id == execution_id))
        ).scalar_one_or_none()
        if row is None:
            return False
        return row.status == "stopped"


async def flush_execution(
    *,
    execution_id: uuid.UUID,
    status: str,
    passed_cases: int = 0,
    failed_cases: int = 0,
    skipped_cases: int = 0,
    duration_ms: int | None = None,
    tokens_total: int = 0,
    video_path: str | None = None,
    trace_path: str | None = None,
    test_data_snapshot: dict[str, Any] | None = None,
    error_message: str | None = None,
) -> None:
    """收口整次执行：写最终状态 + 计数 + 资源路径。"""
    async with async_session_factory() as session:
        row = (
            await session.execute(select(UIExecution).where(UIExecution.id == execution_id))
        ).scalar_one_or_none()
        if row is None:
            logger.warning("flush_execution: %s not found, skipping", execution_id)
            return
        row.status = status
        row.passed_cases = passed_cases
        row.failed_cases = failed_cases
        row.skipped_cases = skipped_cases
        row.duration_ms = duration_ms
        row.tokens_total = tokens_total
        if video_path is not None:
            row.video_path = video_path
        if trace_path is not None:
            row.trace_path = trace_path
        if test_data_snapshot is not None:
            row.test_data_snapshot = test_data_snapshot
        if error_message is not None:
            row.error_message = error_message
        row.completed_at = datetime.now(timezone.utc)
        await session.commit()


# ─── case ────────────────────────────────────────────────────────────


async def create_case_result(
    *,
    execution_id: uuid.UUID,
    testcase_id: uuid.UUID | None,
    sort_order: int = 0,
) -> UICaseResult:
    """开跑用例前插入一行；后续 step 与 flush_case 引用它的 id。"""
    async with async_session_factory() as session:
        now = datetime.now(timezone.utc)
        row = UICaseResult(
            execution_id=execution_id,
            testcase_id=testcase_id,
            status="running",
            sort_order=sort_order,
            started_at=now,
            data_confidence="reliable",
            synthesized_data=[],
            data_failures=[],
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row


async def flush_case(
    *,
    case_result_id: uuid.UUID,
    status: str,
    ai_summary: str | None = None,
    error_message: str | None = None,
    duration_ms: int | None = None,
    tokens_used: int = 0,
    test_data_used: list[dict[str, Any]] | None = None,
    synthesized_data: list[dict[str, Any]] | None = None,
    data_failures: list[dict[str, Any]] | None = None,
    data_confidence: str = "reliable",
    successful_locators: dict[str, Any] | None = None,
) -> None:
    """用例跑完写终态。"""
    async with async_session_factory() as session:
        row = (
            await session.execute(select(UICaseResult).where(UICaseResult.id == case_result_id))
        ).scalar_one_or_none()
        if row is None:
            logger.warning("flush_case: %s not found", case_result_id)
            return
        row.status = status
        row.ai_summary = ai_summary
        row.error_message = error_message
        row.duration_ms = duration_ms
        row.tokens_used = tokens_used
        if test_data_used is not None:
            row.test_data_used = test_data_used
        row.synthesized_data = list(synthesized_data or [])
        row.data_failures = list(data_failures or [])
        row.data_confidence = data_confidence
        # Phase 15.9: 仅当显式传入 (engine 启用 UI_LOCATOR_MEMORY 才会传) 时
        # 才覆盖, 防止旧调用方误把 dict 写成 None.
        if successful_locators is not None:
            row.successful_locators = dict(successful_locators)
        row.completed_at = datetime.now(timezone.utc)
        await session.commit()


async def read_recent_successful_locators(
    *,
    testcase_id: uuid.UUID,
    limit: int,
) -> list[dict[str, Any]]:
    """读最近 ``limit`` 次"已 passed"case_result 的 ``successful_locators`` dict.

    Phase 15.9 接入 ``execution_engine`` 入口, 由 ``intersect_recent_locators``
    判定信任 locator. 顺序: 最近在前.

    返回值是真实 dict 的浅拷贝列表, 调用方可以放心改它而不影响 SQLAlchemy 状态.
    没有命中任何记录时返回空列表 (调用方等同于"无记忆", 不会注入 preferred).
    """
    if limit <= 0:
        return []
    async with async_session_factory() as session:
        result = await session.execute(
            select(UICaseResult.successful_locators)
            .where(UICaseResult.testcase_id == testcase_id)
            .where(UICaseResult.status == "passed")
            .order_by(UICaseResult.completed_at.desc().nulls_last())
            .limit(limit)
        )
        rows = [r for r, in result.all()]
    out: list[dict[str, Any]] = []
    for row in rows:
        if isinstance(row, dict):
            out.append(dict(row))
        else:
            out.append({})
    return out


async def read_latest_case_locators(
    *,
    testcase_id: uuid.UUID,
) -> dict[str, Any]:
    """读最近一次 case_result (任意 status) 的 ``successful_locators`` dict.

    Phase 15.9: 用作 ``apply_step_outcomes`` 的 previous 入参 -- 必须包含
    上一次的 miss_count 状态, 才能让连续 miss 计数累加到 max_miss 阈值后清记忆.
    与 ``read_recent_successful_locators`` (passed only, 用于 intersect) 互补.

    没有任何历史记录时返回空 dict, 调用方等同于"首次执行, 无记忆".
    """
    async with async_session_factory() as session:
        result = await session.execute(
            select(UICaseResult.successful_locators)
            .where(UICaseResult.testcase_id == testcase_id)
            .order_by(UICaseResult.completed_at.desc().nulls_last())
            .limit(1)
        )
        row = result.scalar_one_or_none()
    return dict(row) if isinstance(row, dict) else {}


# ─── step ────────────────────────────────────────────────────────────


async def flush_step(
    *,
    case_result_id: uuid.UUID,
    step_number: int,
    description: str,
    expected_result: str | None = None,
    tool_calls: list[dict[str, Any]] | None = None,
    ai_reasoning: str | None = None,
    snapshot_before: str | None = None,
    snapshot_after: str | None = None,
    assertion_passed: bool | None = None,
    assertion_reason: str | None = None,
    assertion_evidence: str | None = None,
    status: str = "pending",
    screenshot_path: str | None = None,
    error_message: str | None = None,
    retry_count: int = 0,
    tokens_used: int = 0,
    duration_ms: int | None = None,
    execution_path: str | None = None,
    fallback_reason: str | None = None,
    loop_break_reason: str | None = None,
    assertion_method: str | None = None,
) -> uuid.UUID:
    """把单步骤写入 ``ui_step_results``；返回新增行的 id。

    secret 类工具的 plaintext 会被 ``sanitize_tool_calls`` 替换成占位符；
    ``ai_reasoning`` 由调用方负责清洗（StepRunner 已在写消息时调过
    ``redact_tool_result_for_reasoning``，但 reasoning_content 流是模型自己
    生成的，理论上不含 plaintext，无需再处理）。
    """
    async with async_session_factory() as session:
        row = UIStepResult(
            case_result_id=case_result_id,
            step_number=step_number,
            description=description,
            expected_result=expected_result,
            tool_calls=sanitize_tool_calls(tool_calls),
            ai_reasoning=ai_reasoning,
            snapshot_before=snapshot_before,
            snapshot_after=snapshot_after,
            assertion_passed=assertion_passed,
            assertion_reason=assertion_reason,
            assertion_evidence=assertion_evidence,
            status=status,
            screenshot_path=screenshot_path,
            error_message=error_message,
            retry_count=retry_count,
            tokens_used=tokens_used,
            duration_ms=duration_ms,
            execution_path=execution_path,
            fallback_reason=fallback_reason,
            loop_break_reason=loop_break_reason,
            assertion_method=assertion_method,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row.id


__all__ = [
    "create_case_result",
    "flush_case",
    "flush_execution",
    "flush_step",
    "init_execution_record",
    "is_execution_stopped",
    "mark_execution_running",
    "sanitize_tool_call_for_storage",
    "sanitize_tool_calls",
]
