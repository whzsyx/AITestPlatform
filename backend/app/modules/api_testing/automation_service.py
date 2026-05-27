from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from datetime import time as dt_time
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.core.exceptions import AppException, NotFoundException
from app.modules.api_testing.models import (
    ApiAutomationRun,
    ApiAutomationRunStep,
    ApiAutomationTask,
    ApiAutomationTaskStep,
    ApiTestCase,
    ApiTestEnvironment,
)
from app.modules.api_testing.schemas import (
    ApiAutomationExtractor,
    ApiAutomationRunRequest,
    ApiAutomationRunResponse,
    ApiAutomationRunStepResponse,
    ApiAutomationStepPayload,
    ApiAutomationStepResponse,
    ApiAutomationTaskCreateRequest,
    ApiAutomationTaskListItem,
    ApiAutomationTaskResponse,
    ApiAutomationTaskUpdateRequest,
    ApiRenderedRequestConfig,
    ApiTestRunResponse,
    PaginatedApiAutomationRuns,
    PaginatedApiAutomationTasks,
)
from app.modules.api_testing.service import (
    _execute_api_test_row,
    _format_failed_assertions,
    _format_report_value,
    _load_environment_variables_map,
    build_rendered_request_config,
)
from app.modules.auth.models import User
from app.modules.ui_automation.service import _check_project_member

logger = logging.getLogger(__name__)

_AUTOMATION_STEP_LIMIT = 100
_MISSING = object()


async def create_api_automation_task(
    db: AsyncSession,
    project_id: uuid.UUID,
    data: ApiAutomationTaskCreateRequest,
    user: User,
) -> ApiAutomationTaskResponse:
    await _check_project_member(db, project_id, user)
    if data.environment_id:
        await _ensure_environment_belongs_to_project(db, project_id, data.environment_id)
    await _ensure_cases_belong_to_project(db, project_id, [step.api_case_id for step in data.steps])

    row = ApiAutomationTask(
        project_id=project_id,
        environment_id=data.environment_id,
        name=data.name,
        description=data.description,
        enabled=data.enabled,
        schedule_type=data.schedule_type,
        interval_minutes=data.interval_minutes,
        daily_time=data.daily_time,
        timeout_seconds=data.timeout_seconds,
        stop_on_failure=data.stop_on_failure,
        created_by=user.id,
    )
    row.next_run_at = calculate_next_run_at(row) if row.enabled else None
    db.add(row)
    await db.flush()
    await _replace_task_steps(db, row, data.steps)
    await db.flush()
    return await get_api_automation_task(db, row.id, user)


async def update_api_automation_task(
    db: AsyncSession,
    task_id: uuid.UUID,
    data: ApiAutomationTaskUpdateRequest,
    user: User,
) -> ApiAutomationTaskResponse:
    row = await _get_automation_task_for_edit(db, task_id, user)
    if "environment_id" in data.model_fields_set and data.environment_id:
        await _ensure_environment_belongs_to_project(db, row.project_id, data.environment_id)
    if data.steps is not None:
        await _ensure_cases_belong_to_project(db, row.project_id, [step.api_case_id for step in data.steps])

    if data.name is not None:
        row.name = data.name
    if "description" in data.model_fields_set:
        row.description = data.description
    if "environment_id" in data.model_fields_set:
        row.environment_id = data.environment_id
    if data.enabled is not None:
        row.enabled = data.enabled
    if data.schedule_type is not None:
        row.schedule_type = data.schedule_type
    if "interval_minutes" in data.model_fields_set:
        row.interval_minutes = data.interval_minutes
    if "daily_time" in data.model_fields_set:
        row.daily_time = data.daily_time
    if data.timeout_seconds is not None:
        row.timeout_seconds = data.timeout_seconds
    if data.stop_on_failure is not None:
        row.stop_on_failure = data.stop_on_failure
    _validate_task_schedule(row)
    row.next_run_at = calculate_next_run_at(row) if row.enabled else None

    if data.steps is not None:
        await _replace_task_steps(db, row, data.steps)

    await db.flush()
    return await get_api_automation_task(db, row.id, user)


async def delete_api_automation_task(db: AsyncSession, task_id: uuid.UUID, user: User) -> None:
    row = await _get_automation_task_for_edit(db, task_id, user)
    await db.delete(row)


async def get_api_automation_task(
    db: AsyncSession,
    task_id: uuid.UUID,
    user: User,
) -> ApiAutomationTaskResponse:
    row = await _get_automation_task_for_edit(db, task_id, user)
    return _to_task_response(row)


async def list_api_automation_tasks(
    db: AsyncSession,
    project_id: uuid.UUID,
    user: User,
    *,
    page: int = 1,
    page_size: int = 20,
    search: str | None = None,
) -> PaginatedApiAutomationTasks:
    await _check_project_member(db, project_id, user)
    query = (
        select(ApiAutomationTask)
        .options(
            selectinload(ApiAutomationTask.environment),
            selectinload(ApiAutomationTask.creator),
            selectinload(ApiAutomationTask.steps),
        )
        .where(ApiAutomationTask.project_id == project_id)
    )
    count_query = select(func.count()).select_from(ApiAutomationTask).where(
        ApiAutomationTask.project_id == project_id,
    )
    if search:
        keyword = f"%{search.strip()}%"
        query = query.where(ApiAutomationTask.name.ilike(keyword))
        count_query = count_query.where(ApiAutomationTask.name.ilike(keyword))

    total = int((await db.execute(count_query)).scalar() or 0)
    rows = (
        (
            await db.execute(
                query.order_by(ApiAutomationTask.updated_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size),
            )
        )
        .scalars()
        .unique()
        .all()
    )
    return PaginatedApiAutomationTasks(
        items=[_to_task_list_item(row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


async def run_api_automation_task(
    db: AsyncSession,
    task_id: uuid.UUID,
    user: User | None,
    data: ApiAutomationRunRequest,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> ApiAutomationRunResponse:
    task = await _get_automation_task_for_run(db, task_id, user)
    steps = await _load_automation_steps_for_run(db, task)
    return await _execute_automation_task(db, task, steps, data.trigger_type, transport=transport)


async def list_api_automation_runs(
    db: AsyncSession,
    task_id: uuid.UUID,
    user: User,
    *,
    page: int = 1,
    page_size: int = 20,
) -> PaginatedApiAutomationRuns:
    task = await _get_automation_task_for_edit(db, task_id, user)
    count_query = select(func.count()).select_from(ApiAutomationRun).where(ApiAutomationRun.task_id == task.id)
    total = int((await db.execute(count_query)).scalar() or 0)
    rows = (
        (
            await db.execute(
                select(ApiAutomationRun)
                .options(
                    selectinload(ApiAutomationRun.task),
                    selectinload(ApiAutomationRun.steps),
                )
                .where(ApiAutomationRun.task_id == task.id)
                .order_by(ApiAutomationRun.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size),
            )
        )
        .scalars()
        .unique()
        .all()
    )
    return PaginatedApiAutomationRuns(
        items=[_to_run_response(row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


async def get_api_automation_run(
    db: AsyncSession,
    run_id: uuid.UUID,
    user: User,
) -> ApiAutomationRunResponse:
    result = await db.execute(
        select(ApiAutomationRun)
        .options(selectinload(ApiAutomationRun.task), selectinload(ApiAutomationRun.steps))
        .where(ApiAutomationRun.id == run_id)
    )
    row = result.scalars().unique().one_or_none()
    if row is None:
        raise NotFoundException("API 自动化执行记录不存在")
    await _check_project_member(db, row.project_id, user)
    return _to_run_response(row)


async def run_due_api_automation_tasks_once(
    *,
    now: datetime | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    from app.database import async_session_factory

    current = now or datetime.now(timezone.utc)
    stats: dict[str, Any] = {"checked": 0, "started": 0, "failed": 0}
    async with async_session_factory() as db:
        result = await db.execute(
            select(ApiAutomationTask)
            .options(
                selectinload(ApiAutomationTask.environment).selectinload(ApiTestEnvironment.variables),
                selectinload(ApiAutomationTask.steps)
                .selectinload(ApiAutomationTaskStep.api_case)
                .selectinload(ApiTestCase.environment)
                .selectinload(ApiTestEnvironment.variables),
            )
            .where(
                ApiAutomationTask.enabled.is_(True),
                ApiAutomationTask.schedule_type != "manual",
                ApiAutomationTask.next_run_at.is_not(None),
                ApiAutomationTask.next_run_at <= current,
            )
            .order_by(ApiAutomationTask.next_run_at)
            .limit(20)
        )
        tasks = result.scalars().unique().all()
        stats["checked"] = len(tasks)
        for task in tasks:
            try:
                steps = await _load_automation_steps_for_run(db, task)
                await _execute_automation_task(db, task, steps, "schedule", transport=transport)
                stats["started"] += 1
                await db.commit()
            except Exception:  # noqa: BLE001 - scheduler must keep running later tasks.
                logger.exception("API automation scheduled task failed: %s", task.id)
                stats["failed"] += 1
                await db.rollback()
    return stats


async def _execute_automation_task(
    db: AsyncSession,
    task: ApiAutomationTask,
    steps: list[ApiAutomationTaskStep],
    trigger_type: str,
    *,
    transport: httpx.AsyncBaseTransport | None,
) -> ApiAutomationRunResponse:
    started = datetime.now(timezone.utc)
    run = ApiAutomationRun(
        task_id=task.id,
        project_id=task.project_id,
        trigger_type=trigger_type,
        status="running",
        started_at=started,
        total_steps=len(steps),
    )
    db.add(run)
    await db.flush()

    runtime_data: dict[str, Any] = {}
    run_steps: list[ApiAutomationRunStep] = []
    stopped = False
    start_perf = time.perf_counter()

    for step in steps:
        if stopped:
            run_steps.append(await _create_skipped_step(db, run, step, "前置步骤失败，已跳过"))
            continue
        step_result = await _run_automation_step(
            db,
            task,
            run,
            step,
            runtime_data,
            transport=transport,
        )
        run_steps.append(step_result)
        if step_result.status != "passed" and task.stop_on_failure:
            stopped = True

    completed = datetime.now(timezone.utc)
    run.elapsed_ms = int((time.perf_counter() - start_perf) * 1000)
    run.completed_at = completed
    run.passed_steps = sum(1 for item in run_steps if item.status == "passed")
    run.failed_steps = sum(1 for item in run_steps if item.status == "failed")
    run.skipped_steps = sum(1 for item in run_steps if item.status == "skipped")
    run.runtime_data = runtime_data
    run.status = "passed" if run.failed_steps == 0 and run.skipped_steps == 0 else "failed"
    if run.failed_steps:
        first_failed = next((item for item in run_steps if item.status == "failed"), None)
        run.error = first_failed.error if first_failed else None
    task.last_run_at = completed
    task.next_run_at = (
        calculate_next_run_at(task, from_time=completed)
        if getattr(task, "enabled", True)
        else None
    )
    await db.flush()

    return _to_run_response(run, run_steps=run_steps)


async def _run_automation_step(
    db: AsyncSession,
    task: ApiAutomationTask,
    run: ApiAutomationRun,
    step: ApiAutomationTaskStep,
    runtime_data: dict[str, Any],
    *,
    transport: httpx.AsyncBaseTransport | None,
) -> ApiAutomationRunStep:
    api_case = step.api_case
    variables = await _load_step_variables(db, task, api_case, runtime_data)
    rendered = _build_step_rendered_request(task, step, variables)
    result = await _execute_api_test_row(
        api_case,
        variables,
        base_url=None,
        timeout_seconds=task.timeout_seconds,
        transport=transport,
        rendered_request=rendered,
    )
    extracted: dict[str, Any] = {}
    extraction_error: str | None = None
    if result.passed:
        try:
            extracted = extract_runtime_values(step.extractors or [], result)
            runtime_data.update(extracted)
        except AppException as exc:
            extraction_error = exc.message
            result.passed = False

    failed_assertions = [item for item in result.assertions if not item.passed]
    error = result.error or extraction_error or _format_failed_assertions(failed_assertions)
    status = "passed" if result.passed and not extraction_error else "failed"
    row = ApiAutomationRunStep(
        run_id=run.id,
        task_step_id=step.id,
        api_case_id=api_case.id,
        name=step.name or api_case.name,
        method=api_case.method,
        order_index=step.order_index,
        status=status,
        request_url=result.request_url,
        status_code=result.status_code,
        elapsed_ms=result.elapsed_ms,
        request_snapshot=rendered.model_dump(mode="json"),
        response_snapshot=result.model_dump(mode="json"),
        assertion_results=[item.model_dump(mode="json") for item in result.assertions],
        extracted_values=extracted,
        error=error,
    )
    db.add(row)
    await db.flush()
    return row


async def _create_skipped_step(
    db: AsyncSession,
    run: ApiAutomationRun,
    step: ApiAutomationTaskStep,
    reason: str,
) -> ApiAutomationRunStep:
    api_case = step.api_case
    row = ApiAutomationRunStep(
        run_id=run.id,
        task_step_id=step.id,
        api_case_id=api_case.id,
        name=step.name or api_case.name,
        method=api_case.method,
        order_index=step.order_index,
        status="skipped",
        elapsed_ms=0,
        assertion_results=[],
        extracted_values={},
        error=reason,
    )
    db.add(row)
    await db.flush()
    return row


def extract_runtime_values(extractors: list[dict[str, Any]], result: ApiTestRunResponse) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for raw in extractors:
        extractor = ApiAutomationExtractor.model_validate(raw)
        if extractor.source == "status_code":
            value: Any = result.status_code
        elif extractor.source == "response_text":
            value = result.response_body
        elif extractor.source == "response_header":
            value = _get_header(result.response_headers, extractor.header or "")
        else:
            value = _json_path_get(result.response_json, extractor.path or "")
        if value is _MISSING:
            label = extractor.path or extractor.header or extractor.source
            raise AppException(
                f"提取运行时变量 {extractor.name} 失败：{label} 不存在",
                code="API_AUTOMATION_EXTRACT_FAILED",
                status_code=400,
            )
        out[extractor.name] = value
    return out


def calculate_next_run_at(
    task: ApiAutomationTask,
    *,
    from_time: datetime | None = None,
) -> datetime | None:
    if getattr(task, "schedule_type", "manual") == "manual":
        return None
    base = from_time or datetime.now(timezone.utc)
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    if getattr(task, "schedule_type", "manual") == "interval":
        if not task.interval_minutes:
            return None
        return base + timedelta(minutes=int(task.interval_minutes))
    if getattr(task, "schedule_type", "manual") == "daily":
        if not task.daily_time:
            return None
        hour, minute = [int(part) for part in task.daily_time.split(":")]
        tz = _schedule_timezone()
        local_base = base.astimezone(tz)
        candidate = datetime.combine(local_base.date(), dt_time(hour=hour, minute=minute), tzinfo=tz)
        if candidate <= local_base:
            candidate += timedelta(days=1)
        return candidate.astimezone(timezone.utc)
    return None


def _build_step_rendered_request(
    task: ApiAutomationTask,
    step: ApiAutomationTaskStep,
    variables: dict[str, Any],
) -> ApiRenderedRequestConfig:
    api_case = step.api_case
    overrides = step.request_overrides or {}
    task_environment = getattr(task, "environment", None)
    override_base_url = overrides.get("base_url") if "base_url" in overrides else None
    task_base_url = getattr(task_environment, "base_url", None)
    effective_environment = (
        SimpleNamespace(base_url=override_base_url or task_base_url)
        if (override_base_url or task_base_url)
        else api_case.environment
    )
    headers = _merge_mapping(api_case.headers or {}, overrides.get("headers"))
    query_params = _merge_mapping(api_case.query_params or {}, overrides.get("query_params"))
    body_type = overrides.get("body_type", api_case.body_type)
    row = SimpleNamespace(
        method=api_case.method,
        url=overrides.get("path") or api_case.path or api_case.url,
        path=overrides.get("path") if "path" in overrides else api_case.path,
        base_url=api_case.base_url,
        environment=effective_environment,
        headers=headers,
        query_params=query_params,
        body_type=body_type,
        body_json=overrides.get("body_json") if "body_json" in overrides else api_case.body_json,
        body_text=overrides.get("body_text") if "body_text" in overrides else api_case.body_text,
        assertions=overrides.get("assertions") if "assertions" in overrides else api_case.assertions,
    )
    return build_rendered_request_config(row, {key: str(value) for key, value in variables.items()})


async def _load_step_variables(
    db: AsyncSession,
    task: ApiAutomationTask,
    api_case: ApiTestCase,
    runtime_data: dict[str, Any],
) -> dict[str, Any]:
    variables = await _load_environment_variables_map(db, api_case)
    task_environment = getattr(task, "environment", None)
    if task_environment is not None:
        for item in getattr(task_environment, "variables", []) or []:
            variables[item.key] = item.value
    for key, value in runtime_data.items():
        variables[f"runtime.{key}"] = value
    return variables


async def _get_automation_task_for_run(
    db: AsyncSession,
    task_id: uuid.UUID,
    user: User | None,
) -> ApiAutomationTask:
    result = await db.execute(
        select(ApiAutomationTask)
        .options(
            selectinload(ApiAutomationTask.environment).selectinload(ApiTestEnvironment.variables),
        )
        .where(ApiAutomationTask.id == task_id)
    )
    row = result.scalars().unique().one_or_none()
    if row is None:
        row = await db.get(ApiAutomationTask, task_id)
    if row is None:
        raise NotFoundException("API 自动化任务不存在")
    if user is not None:
        await _check_project_member(db, row.project_id, user)
    return row


async def _get_automation_task_for_edit(
    db: AsyncSession,
    task_id: uuid.UUID,
    user: User,
) -> ApiAutomationTask:
    result = await db.execute(
        select(ApiAutomationTask)
        .options(
            selectinload(ApiAutomationTask.environment).selectinload(ApiTestEnvironment.variables),
            selectinload(ApiAutomationTask.creator),
            selectinload(ApiAutomationTask.steps)
            .selectinload(ApiAutomationTaskStep.api_case)
            .selectinload(ApiTestCase.environment),
        )
        .where(ApiAutomationTask.id == task_id)
    )
    row = result.scalars().unique().one_or_none()
    if row is None:
        raise NotFoundException("API 自动化任务不存在")
    await _check_project_member(db, row.project_id, user)
    return row


async def _load_automation_steps_for_run(
    db: AsyncSession,
    task: ApiAutomationTask,
) -> list[ApiAutomationTaskStep]:
    result = await db.execute(
        select(ApiAutomationTaskStep)
        .options(
            selectinload(ApiAutomationTaskStep.api_case)
            .selectinload(ApiTestCase.environment)
            .selectinload(ApiTestEnvironment.variables),
            selectinload(ApiAutomationTaskStep.api_case).selectinload(ApiTestCase.module),
        )
        .where(
            ApiAutomationTaskStep.task_id == task.id,
            ApiAutomationTaskStep.enabled.is_(True),
        )
        .order_by(ApiAutomationTaskStep.order_index)
        .limit(_AUTOMATION_STEP_LIMIT + 1)
    )
    steps = result.scalars().unique().all()
    if len(steps) > _AUTOMATION_STEP_LIMIT:
        raise AppException(
            f"API 自动化任务最多支持 {_AUTOMATION_STEP_LIMIT} 个步骤",
            code="API_AUTOMATION_TOO_MANY_STEPS",
            status_code=400,
        )
    if not steps:
        raise AppException("API 自动化任务没有可执行步骤", code="API_AUTOMATION_NO_STEPS", status_code=400)
    return steps


async def _replace_task_steps(
    db: AsyncSession,
    task: ApiAutomationTask,
    steps: list[ApiAutomationStepPayload],
) -> None:
    await db.execute(delete(ApiAutomationTaskStep).where(ApiAutomationTaskStep.task_id == task.id))
    for index, step in enumerate(steps):
        db.add(
            ApiAutomationTaskStep(
                task_id=task.id,
                api_case_id=step.api_case_id,
                name=step.name,
                order_index=step.order_index if step.order_index is not None else index,
                enabled=step.enabled,
                request_overrides=step.request_overrides or {},
                extractors=[item.model_dump(mode="json") for item in step.extractors],
            )
        )


async def _ensure_environment_belongs_to_project(
    db: AsyncSession,
    project_id: uuid.UUID,
    environment_id: uuid.UUID,
) -> ApiTestEnvironment:
    environment = await db.get(ApiTestEnvironment, environment_id)
    if environment is None:
        raise NotFoundException("API 环境不存在")
    if environment.project_id != project_id:
        raise AppException("API 环境不属于当前项目", code="INVALID_API_ENVIRONMENT", status_code=400)
    return environment


async def _ensure_cases_belong_to_project(
    db: AsyncSession,
    project_id: uuid.UUID,
    case_ids: list[uuid.UUID],
) -> None:
    unique_ids = list(dict.fromkeys(case_ids))
    if not unique_ids:
        return
    rows = (
        (
            await db.execute(
                select(ApiTestCase.id).where(
                    ApiTestCase.id.in_(unique_ids),
                    ApiTestCase.project_id == project_id,
                )
            )
        )
        .scalars()
        .all()
    )
    if set(rows) != set(unique_ids):
        raise AppException("存在不属于当前项目或已删除的 API", code="INVALID_API_AUTOMATION_CASE", status_code=400)


def _validate_task_schedule(task: ApiAutomationTask) -> None:
    if task.schedule_type == "interval" and not task.interval_minutes:
        raise AppException("间隔定时任务必须填写间隔分钟", code="INVALID_API_AUTOMATION_SCHEDULE", status_code=400)
    if task.schedule_type == "daily":
        if not task.daily_time:
            raise AppException("每日定时任务必须填写执行时间", code="INVALID_API_AUTOMATION_SCHEDULE", status_code=400)
        hour, minute = [int(part) for part in task.daily_time.split(":")]
        if hour > 23 or minute > 59:
            raise AppException(
                "每日执行时间必须是 00:00 到 23:59",
                code="INVALID_API_AUTOMATION_SCHEDULE",
                status_code=400,
            )


def _merge_mapping(base: dict[str, Any], override: Any) -> dict[str, Any]:
    merged = dict(base or {})
    if isinstance(override, dict):
        merged.update(override)
    return merged


def _get_header(headers: dict[str, str], name: str) -> Any:
    target = name.lower()
    for key, value in headers.items():
        if key.lower() == target:
            return value
    return _MISSING


def _json_path_get(data: Any, path: str) -> Any:
    if not path or not path.startswith("$"):
        return _MISSING
    current = data
    token = ""
    index_mode = False
    parts: list[Any] = []
    for char in path[1:]:
        if char == "." and not index_mode:
            if token:
                parts.append(token)
                token = ""
            continue
        if char == "[" and not index_mode:
            if token:
                parts.append(token)
                token = ""
            index_mode = True
            continue
        if char == "]" and index_mode:
            try:
                parts.append(int(token))
            except ValueError:
                return _MISSING
            token = ""
            index_mode = False
            continue
        token += char
    if token:
        parts.append(token)

    for part in parts:
        if isinstance(part, int):
            if not isinstance(current, list) or part >= len(current):
                return _MISSING
            current = current[part]
        else:
            if not isinstance(current, dict) or part not in current:
                return _MISSING
            current = current[part]
    return current


def _to_task_list_item(row: ApiAutomationTask) -> ApiAutomationTaskListItem:
    return ApiAutomationTaskListItem(
        id=row.id,
        project_id=row.project_id,
        environment_id=row.environment_id,
        environment_name=getattr(getattr(row, "environment", None), "name", None),
        name=row.name,
        description=row.description,
        enabled=row.enabled,
        schedule_type=row.schedule_type,
        interval_minutes=row.interval_minutes,
        daily_time=row.daily_time,
        next_run_at=row.next_run_at,
        last_run_at=row.last_run_at,
        timeout_seconds=row.timeout_seconds,
        stop_on_failure=row.stop_on_failure,
        step_count=len(getattr(row, "steps", []) or []),
        created_by=row.created_by,
        creator_name=(
            getattr(getattr(row, "creator", None), "display_name", None)
            or getattr(getattr(row, "creator", None), "username", None)
        ),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _to_task_response(row: ApiAutomationTask) -> ApiAutomationTaskResponse:
    item = _to_task_list_item(row).model_dump()
    return ApiAutomationTaskResponse(
        **item,
        steps=[_to_step_response(step) for step in sorted(row.steps, key=lambda item: item.order_index)],
    )


def _to_step_response(row: ApiAutomationTaskStep) -> ApiAutomationStepResponse:
    api_case = getattr(row, "api_case", None)
    return ApiAutomationStepResponse(
        id=row.id,
        task_id=row.task_id,
        api_case_id=row.api_case_id,
        api_name=getattr(api_case, "name", None),
        method=getattr(api_case, "method", None),
        path=getattr(api_case, "path", None) or getattr(api_case, "url", None),
        name=row.name,
        order_index=row.order_index,
        enabled=row.enabled,
        request_overrides=row.request_overrides or {},
        extractors=[ApiAutomationExtractor.model_validate(item) for item in row.extractors or []],
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _to_run_response(
    row: ApiAutomationRun,
    *,
    run_steps: list[ApiAutomationRunStep] | None = None,
) -> ApiAutomationRunResponse:
    steps = run_steps if run_steps is not None else list(getattr(row, "steps", []) or [])
    return ApiAutomationRunResponse(
        id=row.id,
        task_id=row.task_id,
        task_name=getattr(getattr(row, "task", None), "name", None),
        project_id=row.project_id,
        trigger_type=row.trigger_type,
        status=row.status,
        started_at=row.started_at,
        completed_at=row.completed_at,
        total_steps=row.total_steps,
        passed_steps=row.passed_steps,
        failed_steps=row.failed_steps,
        skipped_steps=row.skipped_steps,
        elapsed_ms=row.elapsed_ms,
        runtime_data=row.runtime_data or {},
        error=row.error,
        steps=[_to_run_step_response(step) for step in sorted(steps, key=lambda item: item.order_index)],
    )


def _to_run_step_response(row: ApiAutomationRunStep) -> ApiAutomationRunStepResponse:
    request_snapshot = (
        ApiRenderedRequestConfig.model_validate(row.request_snapshot)
        if row.request_snapshot
        else None
    )
    response_snapshot = (
        ApiTestRunResponse.model_validate(row.response_snapshot)
        if row.response_snapshot
        else None
    )
    return ApiAutomationRunStepResponse(
        id=row.id,
        run_id=row.run_id,
        task_step_id=row.task_step_id,
        api_case_id=row.api_case_id,
        name=row.name,
        method=row.method,
        order_index=row.order_index,
        status=row.status,
        request_url=row.request_url,
        status_code=row.status_code,
        elapsed_ms=row.elapsed_ms,
        request_snapshot=request_snapshot,
        response_snapshot=response_snapshot,
        assertion_results=row.assertion_results or [],
        extracted_values=row.extracted_values or {},
        error=_append_extracted_hint(row.error, row.extracted_values),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _append_extracted_hint(error: str | None, values: dict | None) -> str | None:
    if not error or not values:
        return error
    rendered = "，".join(f"{key}={_format_report_value(value)}" for key, value in values.items())
    return f"{error}；已提取：{rendered}"


def _schedule_timezone() -> ZoneInfo:
    name = getattr(settings, "API_AUTOMATION_TIMEZONE", "Asia/Shanghai")
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        return ZoneInfo("Asia/Shanghai")
