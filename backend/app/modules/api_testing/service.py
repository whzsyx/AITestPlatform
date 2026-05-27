from __future__ import annotations

import json
import re
import time
import uuid
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import AppException, NotFoundException
from app.modules.api_testing.models import (
    ApiTestCase,
    ApiTestEnvironment,
    ApiTestEnvironmentVariable,
    ApiTestModule,
)
from app.modules.api_testing.schemas import (
    ApiAssertion,
    ApiAssertionResult,
    ApiRenderedRequestConfig,
    ApiTestBatchRunItem,
    ApiTestBatchRunRequest,
    ApiTestBatchRunResponse,
    ApiTestCaseCreateRequest,
    ApiTestCaseListItem,
    ApiTestCaseResponse,
    ApiTestCaseUpdateRequest,
    ApiTestEnvironmentCreateRequest,
    ApiTestEnvironmentResponse,
    ApiTestEnvironmentUpdateRequest,
    ApiTestEnvironmentVariableCreateRequest,
    ApiTestEnvironmentVariableResponse,
    ApiTestEnvironmentVariableUpdateRequest,
    ApiTestModuleCreateRequest,
    ApiTestModuleResponse,
    ApiTestModuleTreeNode,
    ApiTestModuleUpdateRequest,
    ApiTestRunRequest,
    ApiTestRunResponse,
)
from app.modules.auth.models import User
from app.modules.ui_automation.service import _check_project_member

_MISSING = object()
_RESPONSE_BODY_LIMIT = 200_000
_BATCH_RUN_LIMIT = 100
_VARIABLE_PATTERN = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_.-]*)\s*\}\}")
_VARIABLE_KEY_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*$")


async def create_api_test_environment(
    db: AsyncSession,
    project_id: uuid.UUID,
    data: ApiTestEnvironmentCreateRequest,
    user: User,
) -> ApiTestEnvironmentResponse:
    await _check_project_member(db, project_id, user)
    row = ApiTestEnvironment(
        project_id=project_id,
        name=data.name.strip(),
        base_url=_normalize_base_url(data.base_url),
        description=(data.description or "").strip() or None,
        order_index=data.order_index,
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return _to_environment_response(row)


async def update_api_test_environment(
    db: AsyncSession,
    environment_id: uuid.UUID,
    data: ApiTestEnvironmentUpdateRequest,
    user: User,
) -> ApiTestEnvironmentResponse:
    row = await _get_environment_or_404(db, environment_id)
    await _check_project_member(db, row.project_id, user)
    if data.name is not None:
        row.name = data.name.strip()
    if data.base_url is not None:
        row.base_url = _normalize_base_url(data.base_url)
    if "description" in data.model_fields_set:
        row.description = (data.description or "").strip() or None
    if data.order_index is not None:
        row.order_index = data.order_index
    await db.flush()
    await db.refresh(row)
    return _to_environment_response(row)


async def delete_api_test_environment(
    db: AsyncSession,
    environment_id: uuid.UUID,
    user: User,
) -> None:
    row = await _get_environment_or_404(db, environment_id)
    await _check_project_member(db, row.project_id, user)
    await db.delete(row)


async def list_api_test_environments(
    db: AsyncSession,
    project_id: uuid.UUID,
    user: User,
) -> list[ApiTestEnvironmentResponse]:
    await _check_project_member(db, project_id, user)
    result = await db.execute(
        select(ApiTestEnvironment)
        .where(ApiTestEnvironment.project_id == project_id)
        .order_by(ApiTestEnvironment.order_index, ApiTestEnvironment.updated_at.desc())
    )
    return [_to_environment_response(row) for row in result.scalars().unique().all()]


async def create_api_test_environment_variable(
    db: AsyncSession,
    environment_id: uuid.UUID,
    data: ApiTestEnvironmentVariableCreateRequest,
    user: User,
) -> ApiTestEnvironmentVariableResponse:
    environment = await _get_environment_or_404(db, environment_id)
    await _check_project_member(db, environment.project_id, user)
    key = _normalize_variable_key(data.key)
    await _ensure_variable_key_available(db, environment_id, key)
    row = ApiTestEnvironmentVariable(
        project_id=environment.project_id,
        environment_id=environment.id,
        key=key,
        value=data.value.strip(),
        description=(data.description or "").strip() or None,
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return _to_environment_variable_response(row)


async def update_api_test_environment_variable(
    db: AsyncSession,
    variable_id: uuid.UUID,
    data: ApiTestEnvironmentVariableUpdateRequest,
    user: User,
) -> ApiTestEnvironmentVariableResponse:
    row = await _get_environment_variable_or_404(db, variable_id)
    await _check_project_member(db, row.project_id, user)
    if data.key is not None:
        key = _normalize_variable_key(data.key)
        if key != row.key:
            await _ensure_variable_key_available(db, row.environment_id, key, exclude_id=row.id)
        row.key = key
    if data.value is not None:
        row.value = data.value.strip()
    if "description" in data.model_fields_set:
        row.description = (data.description or "").strip() or None
    await db.flush()
    await db.refresh(row)
    return _to_environment_variable_response(row)


async def delete_api_test_environment_variable(
    db: AsyncSession,
    variable_id: uuid.UUID,
    user: User,
) -> None:
    row = await _get_environment_variable_or_404(db, variable_id)
    await _check_project_member(db, row.project_id, user)
    await db.delete(row)


async def list_api_test_environment_variables(
    db: AsyncSession,
    environment_id: uuid.UUID,
    user: User,
) -> list[ApiTestEnvironmentVariableResponse]:
    environment = await _get_environment_or_404(db, environment_id)
    await _check_project_member(db, environment.project_id, user)
    result = await db.execute(
        select(ApiTestEnvironmentVariable)
        .where(ApiTestEnvironmentVariable.environment_id == environment.id)
        .order_by(ApiTestEnvironmentVariable.key)
    )
    return [_to_environment_variable_response(row) for row in result.scalars().unique().all()]


async def create_api_test_module(
    db: AsyncSession,
    project_id: uuid.UUID,
    data: ApiTestModuleCreateRequest,
    user: User,
) -> ApiTestModuleResponse:
    await _check_project_member(db, project_id, user)
    if data.parent_id:
        parent = await _get_module_or_404(db, data.parent_id)
        if parent.project_id != project_id:
            raise AppException("父模块不属于当前项目", code="INVALID_PARENT", status_code=400)
    row = ApiTestModule(
        project_id=project_id,
        parent_id=data.parent_id,
        name=data.name.strip(),
        order_index=data.order_index,
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return _to_module_response(row)


async def update_api_test_module(
    db: AsyncSession,
    module_id: uuid.UUID,
    data: ApiTestModuleUpdateRequest,
    user: User,
) -> ApiTestModuleResponse:
    row = await _get_module_or_404(db, module_id)
    await _check_project_member(db, row.project_id, user)
    if data.name is not None:
        row.name = data.name.strip()
    if data.order_index is not None:
        row.order_index = data.order_index
    if data.parent_id is not None:
        if data.parent_id == row.id:
            raise AppException("不能将模块设为自身的子模块", code="INVALID_PARENT", status_code=400)
        parent = await _get_module_or_404(db, data.parent_id)
        if parent.project_id != row.project_id:
            raise AppException("父模块不属于当前项目", code="INVALID_PARENT", status_code=400)
        row.parent_id = data.parent_id
    await db.flush()
    await db.refresh(row)
    return _to_module_response(row)


async def delete_api_test_module(db: AsyncSession, module_id: uuid.UUID, user: User) -> None:
    row = await _get_module_or_404(db, module_id)
    await _check_project_member(db, row.project_id, user)
    await db.delete(row)


async def get_api_test_module_tree(
    db: AsyncSession,
    project_id: uuid.UUID,
    user: User,
) -> list[ApiTestModuleTreeNode]:
    await _check_project_member(db, project_id, user)
    result = await db.execute(
        select(ApiTestModule)
        .where(ApiTestModule.project_id == project_id)
        .order_by(ApiTestModule.order_index)
    )
    all_modules = list(result.scalars().unique().all())
    count_rows = await db.execute(
        select(ApiTestCase.module_id, func.count(ApiTestCase.id))
        .where(ApiTestCase.project_id == project_id)
        .group_by(ApiTestCase.module_id)
    )
    direct_counts: dict[uuid.UUID | None, int] = {row[0]: row[1] for row in count_rows}

    modules_by_parent: dict[uuid.UUID | None, list[ApiTestModule]] = {}
    for module in all_modules:
        modules_by_parent.setdefault(module.parent_id, []).append(module)

    def build_tree(parent_id: uuid.UUID | None) -> list[ApiTestModuleTreeNode]:
        nodes: list[ApiTestModuleTreeNode] = []
        for module in modules_by_parent.get(parent_id, []):
            children = build_tree(module.id)
            count = direct_counts.get(module.id, 0) + sum(child.case_count for child in children)
            nodes.append(
                ApiTestModuleTreeNode(
                    id=module.id,
                    name=module.name,
                    parent_id=module.parent_id,
                    order_index=module.order_index,
                    case_count=count,
                    children=children,
                )
            )
        return nodes

    return build_tree(None)


async def create_api_test_case(
    db: AsyncSession,
    project_id: uuid.UUID,
    data: ApiTestCaseCreateRequest,
    user: User,
) -> ApiTestCaseResponse:
    await _ensure_module_belongs_to_project(db, project_id, data.module_id)
    environment, base_url, path, display_url = await _prepare_case_url_parts(
        db,
        project_id,
        environment_id=data.environment_id,
        base_url=data.base_url,
        path=data.path,
        legacy_url=data.url,
    )
    row = ApiTestCase(
        project_id=project_id,
        module_id=data.module_id,
        environment_id=environment.id if environment else None,
        name=data.name.strip(),
        method=data.method,
        url=display_url,
        base_url=base_url,
        path=path,
        headers=_normalize_mapping(data.headers),
        query_params=_normalize_mapping(data.query_params),
        body_type=data.body_type,
        body_json=data.body_json if data.body_type == "json" else None,
        body_text=data.body_text if data.body_type == "text" else None,
        assertions=[item.model_dump(mode="json") for item in data.assertions],
        created_by=user.id,
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return _to_response(row)


async def update_api_test_case(
    db: AsyncSession,
    case_id: uuid.UUID,
    data: ApiTestCaseUpdateRequest,
    user: User,
) -> ApiTestCaseResponse:
    row = await _get_case_or_404(db, case_id, user)
    if data.module_id is not None:
        await _ensure_module_belongs_to_project(db, row.project_id, data.module_id)
        row.module_id = data.module_id
    if data.name is not None:
        row.name = data.name.strip()
    if data.method is not None:
        row.method = data.method
    if (
        "environment_id" in data.model_fields_set
        or "base_url" in data.model_fields_set
        or "path" in data.model_fields_set
        or data.url is not None
    ):
        environment_id = data.environment_id if "environment_id" in data.model_fields_set else row.environment_id
        base_url_value = data.base_url if "base_url" in data.model_fields_set else row.base_url
        path_value = data.path if data.path is not None else row.path
        legacy_url = data.url if data.url is not None else row.url
        environment, base_url, path, display_url = await _prepare_case_url_parts(
            db,
            row.project_id,
            environment_id=environment_id,
            base_url=base_url_value,
            path=path_value,
            legacy_url=legacy_url,
        )
        row.environment_id = environment.id if environment else None
        row.environment = environment
        row.base_url = base_url
        row.path = path
        row.url = display_url
    if data.headers is not None:
        row.headers = _normalize_mapping(data.headers)
    if data.query_params is not None:
        row.query_params = _normalize_mapping(data.query_params)
    if data.body_type is not None:
        row.body_type = data.body_type
        if data.body_type == "none":
            row.body_json = None
            row.body_text = None
    if "body_json" in data.model_fields_set:
        row.body_json = data.body_json if row.body_type == "json" else None
    if "body_text" in data.model_fields_set:
        row.body_text = data.body_text if row.body_type == "text" else None
    if data.assertions is not None:
        row.assertions = [item.model_dump(mode="json") for item in data.assertions]
    await db.flush()
    await db.refresh(row)
    return _to_response(row)


async def delete_api_test_case(db: AsyncSession, case_id: uuid.UUID, user: User) -> None:
    row = await _get_case_or_404(db, case_id, user)
    await db.delete(row)


async def get_api_test_case(
    db: AsyncSession,
    case_id: uuid.UUID,
    user: User,
) -> ApiTestCaseResponse:
    row = await _get_case_or_404(db, case_id, user)
    rendered_request: ApiRenderedRequestConfig | None = None
    try:
        rendered_request = build_rendered_request_config(
            row,
            await _load_environment_variables_map(db, row),
        )
    except AppException:
        # Detail pages must remain editable even when a referenced variable is missing;
        # execution still surfaces the strict missing-variable error.
        rendered_request = None
    return _to_response(row, rendered_request=rendered_request)


async def list_api_test_cases(
    db: AsyncSession,
    project_id: uuid.UUID,
    user: User,
    *,
    page: int = 1,
    page_size: int = 20,
    module_id: uuid.UUID | None = None,
    search: str | None = None,
) -> tuple[list[ApiTestCaseListItem], int]:
    await _check_project_member(db, project_id, user)
    base_query = (
        select(ApiTestCase)
        .options(
            selectinload(ApiTestCase.module),
            selectinload(ApiTestCase.environment),
            selectinload(ApiTestCase.creator),
        )
        .where(ApiTestCase.project_id == project_id)
    )
    count_query = select(func.count()).select_from(ApiTestCase).where(
        ApiTestCase.project_id == project_id,
    )
    if module_id:
        module_ids = await _collect_api_module_ids_with_descendants(db, project_id, module_id)
        base_query = base_query.where(ApiTestCase.module_id.in_(module_ids))
        count_query = count_query.where(ApiTestCase.module_id.in_(module_ids))
    if search:
        kw = f"%{search.strip()}%"
        search_clause = or_(
            ApiTestCase.name.ilike(kw),
            ApiTestCase.url.ilike(kw),
            ApiTestCase.base_url.ilike(kw),
            ApiTestCase.path.ilike(kw),
        )
        base_query = base_query.where(search_clause)
        count_query = count_query.where(search_clause)
    total = (await db.execute(count_query)).scalar() or 0
    rows = (
        (
            await db.execute(
                base_query.order_by(ApiTestCase.updated_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size),
            )
        )
        .scalars()
        .unique()
        .all()
    )
    return [_to_list_item(row) for row in rows], int(total)


async def run_api_test_case(
    db: AsyncSession,
    case_id: uuid.UUID,
    user: User,
    data: ApiTestRunRequest,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> ApiTestRunResponse:
    row = await _get_case_or_404(db, case_id, user)
    variables = await _load_environment_variables_map(db, row)
    return await _execute_api_test_row(
        row,
        variables,
        base_url=data.base_url,
        timeout_seconds=data.timeout_seconds,
        transport=transport,
    )


async def run_api_test_batch(
    db: AsyncSession,
    project_id: uuid.UUID,
    user: User,
    data: ApiTestBatchRunRequest,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> ApiTestBatchRunResponse:
    await _check_project_member(db, project_id, user)
    rows = await _load_batch_api_test_rows(db, project_id, data)
    started = time.perf_counter()
    items: list[ApiTestBatchRunItem] = []
    for row in rows:
        try:
            variables = await _load_environment_variables_map(db, row)
            result = await _execute_api_test_row(
                row,
                variables,
                base_url=data.base_url,
                timeout_seconds=data.timeout_seconds,
                transport=transport,
            )
            items.append(_to_batch_run_item(row, result))
        except Exception as exc:  # noqa: BLE001 - batch execution must keep later APIs running.
            items.append(_to_batch_error_item(row, exc))
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    passed = sum(1 for item in items if item.passed)
    return ApiTestBatchRunResponse(
        total=len(items),
        passed=passed,
        failed=len(items) - passed,
        elapsed_ms=elapsed_ms,
        scope="selected" if data.case_ids else "module",
        items=items,
    )


async def _execute_api_test_row(
    row: ApiTestCase,
    variables: dict[str, str],
    *,
    base_url: str | None,
    timeout_seconds: float,
    transport: httpx.AsyncBaseTransport | None = None,
) -> ApiTestRunResponse:
    rendered = build_rendered_request_config(row, variables, override_base_url=base_url)
    request_kwargs: dict[str, Any] = {
        "headers": rendered.headers,
        "params": rendered.query_params,
    }
    if rendered.body_type == "json":
        request_kwargs["json"] = rendered.body_json
    elif rendered.body_type == "text":
        request_kwargs["content"] = rendered.body_text or ""

    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(
            timeout=timeout_seconds,
            follow_redirects=True,
            transport=transport,
        ) as client:
            response = await client.request(row.method, rendered.url, **request_kwargs)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        response_text = response.text[:_RESPONSE_BODY_LIMIT]
        response_json = _try_json(response_text)
        assertion_results = evaluate_assertions(
            assertions=rendered.assertions,
            status_code=response.status_code,
            response_text=response_text,
            response_json=response_json,
        )
        return ApiTestRunResponse(
            passed=all(item.passed for item in assertion_results),
            status_code=response.status_code,
            elapsed_ms=elapsed_ms,
            request_url=rendered.url,
            response_headers={str(k): str(v) for k, v in response.headers.items()},
            response_body=response_text,
            response_json=response_json,
            assertions=assertion_results,
        )
    except httpx.HTTPError as exc:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return ApiTestRunResponse(
            passed=False,
            elapsed_ms=elapsed_ms,
            request_url=rendered.url,
            error=str(exc),
        )


def build_request_url(url: str, *, base_url: str | None) -> str:
    raw = str(url or "").strip()
    parsed = urlparse(raw)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return raw
    if parsed.scheme:
        raise AppException("接口 URL 仅支持 http/https", code="INVALID_API_URL", status_code=400)
    if not raw.startswith("/"):
        raise AppException("相对接口 URL 必须以 / 开头", code="INVALID_API_URL", status_code=400)
    if not base_url:
        raise AppException("相对接口 URL 需要提供 base_url", code="MISSING_BASE_URL", status_code=400)
    base = str(base_url).strip()
    base_parsed = urlparse(base)
    if base_parsed.scheme not in {"http", "https"} or not base_parsed.netloc:
        raise AppException("base_url 必须是 http/https 完整地址", code="INVALID_BASE_URL", status_code=400)
    return urljoin(base.rstrip("/") + "/", raw.lstrip("/"))


def build_case_request_url(
    row: ApiTestCase,
    *,
    override_base_url: str | None = None,
    variables: dict[str, str] | None = None,
) -> str:
    values = variables or {}
    path = resolve_environment_templates((row.path or row.url or "").strip(), values)
    base_url = (
        override_base_url
        or getattr(getattr(row, "environment", None), "base_url", None)
        or row.base_url
    )
    rendered_base_url = resolve_environment_templates(base_url, values) if base_url else None
    return build_request_url(path, base_url=rendered_base_url)


def build_rendered_request_config(
    row: ApiTestCase,
    variables: dict[str, str],
    *,
    override_base_url: str | None = None,
) -> ApiRenderedRequestConfig:
    path = resolve_environment_templates((row.path or row.url or "").strip(), variables)
    base_url = (
        override_base_url
        or getattr(getattr(row, "environment", None), "base_url", None)
        or row.base_url
    )
    rendered_base_url = resolve_environment_templates(base_url, variables) if base_url else None
    body_json: Any = None
    body_text: str | None = None
    if row.body_type == "json":
        body_json = resolve_environment_templates(
            row.body_json,
            variables,
            coerce_json_scalars=True,
        )
    elif row.body_type == "text":
        body_text = resolve_environment_templates(row.body_text or "", variables)

    return ApiRenderedRequestConfig(
        url=build_request_url(path, base_url=rendered_base_url),
        base_url=rendered_base_url,
        path=path,
        headers=_string_mapping(resolve_environment_templates(row.headers or {}, variables)),
        query_params=_query_params(resolve_environment_templates(row.query_params or {}, variables)),
        body_type=row.body_type,
        body_json=body_json,
        body_text=body_text,
        assertions=[
            ApiAssertion.model_validate(item)
            for item in resolve_environment_templates(
                row.assertions or [],
                variables,
                coerce_json_scalars=True,
            )
        ],
    )


def resolve_environment_templates(
    value: Any,
    variables: dict[str, str],
    *,
    coerce_json_scalars: bool = False,
) -> Any:
    if isinstance(value, str):
        return _render_template(value, variables, coerce_json_scalars=coerce_json_scalars)
    if isinstance(value, list):
        return [
            resolve_environment_templates(
                item,
                variables,
                coerce_json_scalars=coerce_json_scalars,
            )
            for item in value
        ]
    if isinstance(value, dict):
        return {
            resolve_environment_templates(key, variables) if isinstance(key, str) else key: (
                resolve_environment_templates(
                    item,
                    variables,
                    coerce_json_scalars=coerce_json_scalars,
                )
            )
            for key, item in value.items()
        }
    return value


def evaluate_assertions(
    *,
    assertions: list[ApiAssertion],
    status_code: int,
    response_text: str,
    response_json: Any,
) -> list[ApiAssertionResult]:
    results: list[ApiAssertionResult] = []
    for assertion in assertions:
        if assertion.type == "status_code":
            expected = int(assertion.expected)
            passed = status_code == expected
            results.append(
                ApiAssertionResult(
                    type=assertion.type,
                    passed=passed,
                    expected=expected,
                    actual=status_code,
                    reason=f"状态码 {'匹配' if passed else '不匹配'}：期望 {expected}，实际 {status_code}",
                )
            )
            continue
        if assertion.type == "body_contains":
            expected_text = str(assertion.expected or "")
            passed = expected_text in response_text
            results.append(
                ApiAssertionResult(
                    type=assertion.type,
                    passed=passed,
                    expected=expected_text,
                    actual="命中" if passed else "未命中",
                    reason=f"响应文本{'包含' if passed else '未包含'}：{expected_text}",
                )
            )
            continue
        actual = _json_path_get(response_json, assertion.path or "")
        passed = actual == assertion.expected
        results.append(
            ApiAssertionResult(
                type=assertion.type,
                passed=passed,
                expected=assertion.expected,
                actual=None if actual is _MISSING else actual,
                path=assertion.path,
                reason=(
                    f"JSON 路径 {assertion.path} {'匹配' if passed else '不匹配'}"
                    if actual is not _MISSING
                    else f"JSON 路径 {assertion.path} 不存在"
                ),
            )
        )
    return results


async def _ensure_module_belongs_to_project(
    db: AsyncSession,
    project_id: uuid.UUID,
    module_id: uuid.UUID,
) -> ApiTestModule:
    module = await db.get(ApiTestModule, module_id)
    if module is None:
        raise NotFoundException("模块不存在")
    if module.project_id != project_id:
        raise AppException("模块不属于当前项目", code="INVALID_MODULE", status_code=400)
    return module


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


async def _collect_api_module_ids_with_descendants(
    db: AsyncSession,
    project_id: uuid.UUID,
    module_id: uuid.UUID,
) -> list[uuid.UUID]:
    module = await _ensure_module_belongs_to_project(db, project_id, module_id)
    result = await db.execute(
        select(ApiTestModule.id, ApiTestModule.parent_id).where(
            ApiTestModule.project_id == project_id,
        )
    )
    children_by_parent: dict[uuid.UUID | None, list[uuid.UUID]] = {}
    for child_id, parent_id in result.all():
        children_by_parent.setdefault(parent_id, []).append(child_id)

    out: list[uuid.UUID] = []

    def visit(current_id: uuid.UUID) -> None:
        out.append(current_id)
        for child_id in children_by_parent.get(current_id, []):
            visit(child_id)

    visit(module.id)
    return out


async def _load_batch_api_test_rows(
    db: AsyncSession,
    project_id: uuid.UUID,
    data: ApiTestBatchRunRequest,
) -> list[ApiTestCase]:
    base_query = (
        select(ApiTestCase)
        .options(
            selectinload(ApiTestCase.module),
            selectinload(ApiTestCase.environment).selectinload(ApiTestEnvironment.variables),
        )
        .where(ApiTestCase.project_id == project_id)
    )
    if data.case_ids:
        case_ids = list(dict.fromkeys(data.case_ids))
        rows = (
            (
                await db.execute(
                    base_query.where(ApiTestCase.id.in_(case_ids)).limit(_BATCH_RUN_LIMIT + 1),
                )
            )
            .scalars()
            .unique()
            .all()
        )
        rows_by_id = {row.id: row for row in rows}
        missing_ids = [case_id for case_id in case_ids if case_id not in rows_by_id]
        if missing_ids:
            raise AppException("存在不属于当前项目或已删除的 API", code="INVALID_API_BATCH", status_code=400)
        return [rows_by_id[case_id] for case_id in case_ids]

    if data.module_id is None:
        return []
    if data.include_descendants:
        module_ids = await _collect_api_module_ids_with_descendants(db, project_id, data.module_id)
    else:
        module = await _ensure_module_belongs_to_project(db, project_id, data.module_id)
        module_ids = [module.id]
    rows = (
        (
            await db.execute(
                base_query.where(ApiTestCase.module_id.in_(module_ids))
                .order_by(ApiTestCase.updated_at.desc())
                .limit(_BATCH_RUN_LIMIT + 1),
            )
        )
        .scalars()
        .unique()
        .all()
    )
    if len(rows) > _BATCH_RUN_LIMIT:
        raise AppException(
            f"批量执行最多支持 {_BATCH_RUN_LIMIT} 个 API，请缩小模块范围或勾选部分 API",
            code="API_BATCH_TOO_LARGE",
            status_code=400,
        )
    return rows


async def _get_module_or_404(db: AsyncSession, module_id: uuid.UUID) -> ApiTestModule:
    module = await db.get(ApiTestModule, module_id)
    if module is None:
        raise NotFoundException("模块不存在")
    return module


async def _get_environment_or_404(
    db: AsyncSession,
    environment_id: uuid.UUID,
) -> ApiTestEnvironment:
    environment = await db.get(ApiTestEnvironment, environment_id)
    if environment is None:
        raise NotFoundException("API 环境不存在")
    return environment


async def _get_environment_variable_or_404(
    db: AsyncSession,
    variable_id: uuid.UUID,
) -> ApiTestEnvironmentVariable:
    variable = await db.get(ApiTestEnvironmentVariable, variable_id)
    if variable is None:
        raise NotFoundException("API 环境变量不存在")
    return variable


async def _get_case_or_404(
    db: AsyncSession,
    case_id: uuid.UUID,
    user: User,
) -> ApiTestCase:
    result = await db.execute(
        select(ApiTestCase)
        .options(
            selectinload(ApiTestCase.module),
            selectinload(ApiTestCase.environment).selectinload(ApiTestEnvironment.variables),
            selectinload(ApiTestCase.creator),
        )
        .where(ApiTestCase.id == case_id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        # Unit-test stubs in this project commonly implement ``get`` but not full
        # SQLAlchemy query semantics; keep this fallback harmless for production.
        row = await db.get(ApiTestCase, case_id)
    if row is None:
        raise NotFoundException("接口测试不存在")
    await _check_project_member(db, row.project_id, user)
    return row


def _to_list_item(row: ApiTestCase) -> ApiTestCaseListItem:
    environment = getattr(row, "environment", None)
    return ApiTestCaseListItem(
        id=row.id,
        project_id=row.project_id,
        module_id=row.module_id,
        module_name=getattr(getattr(row, "module", None), "name", None),
        environment_id=row.environment_id,
        environment_name=getattr(environment, "name", None),
        name=row.name,
        method=row.method,
        url=_display_case_url(row),
        base_url=getattr(environment, "base_url", None) or row.base_url,
        path=row.path or row.url,
        created_by=row.created_by,
        creator_name=(
            getattr(getattr(row, "creator", None), "display_name", None)
            or getattr(getattr(row, "creator", None), "username", None)
        ),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _to_response(
    row: ApiTestCase,
    *,
    rendered_request: ApiRenderedRequestConfig | None = None,
) -> ApiTestCaseResponse:
    item = _to_list_item(row).model_dump()
    return ApiTestCaseResponse(
        **item,
        headers=dict(row.headers or {}),
        query_params=dict(row.query_params or {}),
        body_type=row.body_type,
        body_json=row.body_json,
        body_text=row.body_text,
        assertions=[ApiAssertion.model_validate(item) for item in row.assertions or []],
        rendered_request=rendered_request,
    )


def _to_batch_run_item(row: ApiTestCase, result: ApiTestRunResponse) -> ApiTestBatchRunItem:
    failed_assertions = [item for item in result.assertions if not item.passed]
    return ApiTestBatchRunItem(
        case_id=row.id,
        name=row.name,
        method=row.method,
        module_id=row.module_id,
        module_name=getattr(getattr(row, "module", None), "name", None),
        environment_id=row.environment_id,
        environment_name=getattr(getattr(row, "environment", None), "name", None),
        request_url=result.request_url,
        passed=result.passed,
        status_code=result.status_code,
        elapsed_ms=result.elapsed_ms,
        assertion_count=len(result.assertions),
        failed_assertion_count=len(failed_assertions),
        error=result.error or _format_failed_assertions(failed_assertions),
    )


def _to_batch_error_item(row: ApiTestCase, exc: Exception) -> ApiTestBatchRunItem:
    message = getattr(exc, "message", None) or str(exc) or exc.__class__.__name__
    return ApiTestBatchRunItem(
        case_id=row.id,
        name=row.name,
        method=row.method,
        module_id=row.module_id,
        module_name=getattr(getattr(row, "module", None), "name", None),
        environment_id=row.environment_id,
        environment_name=getattr(getattr(row, "environment", None), "name", None),
        request_url=_display_case_url(row),
        passed=False,
        assertion_count=0,
        failed_assertion_count=0,
        error=message,
    )


def _format_failed_assertions(assertions: list[ApiAssertionResult]) -> str | None:
    if not assertions:
        return None
    details = [_format_assertion_failure(item) for item in assertions[:3]]
    if len(assertions) > 3:
        details.append(f"另有 {len(assertions) - 3} 条失败断言")
    return "；".join(details)


def _format_assertion_failure(item: ApiAssertionResult) -> str:
    label = {
        "status_code": "状态码断言",
        "body_contains": "响应包含断言",
        "json_path_eq": f"JSON Path 断言 {item.path or ''}".strip(),
    }.get(item.type, item.type)
    return (
        f"{label}失败：{item.reason}，"
        f"期望={_format_report_value(item.expected)}，"
        f"实际={_format_report_value(item.actual)}"
    )


def _format_report_value(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, str):
        return value or '""'
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except TypeError:
        return str(value)


def _to_module_response(row: ApiTestModule) -> ApiTestModuleResponse:
    return ApiTestModuleResponse(
        id=row.id,
        project_id=row.project_id,
        parent_id=row.parent_id,
        name=row.name,
        order_index=row.order_index,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _to_environment_response(row: ApiTestEnvironment) -> ApiTestEnvironmentResponse:
    return ApiTestEnvironmentResponse(
        id=row.id,
        project_id=row.project_id,
        name=row.name,
        base_url=row.base_url,
        description=row.description,
        order_index=row.order_index,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _to_environment_variable_response(
    row: ApiTestEnvironmentVariable,
) -> ApiTestEnvironmentVariableResponse:
    return ApiTestEnvironmentVariableResponse(
        id=row.id,
        project_id=row.project_id,
        environment_id=row.environment_id,
        key=row.key,
        value=row.value,
        description=row.description,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def _prepare_case_url_parts(
    db: AsyncSession,
    project_id: uuid.UUID,
    *,
    environment_id: uuid.UUID | None,
    base_url: str | None,
    path: str | None,
    legacy_url: str | None,
) -> tuple[ApiTestEnvironment | None, str | None, str, str]:
    environment: ApiTestEnvironment | None = None
    if environment_id is not None:
        environment = await _ensure_environment_belongs_to_project(db, project_id, environment_id)

    normalized_base_url = _normalize_base_url(base_url) if base_url else None
    normalized_path = _normalize_path(path) if path else None
    if normalized_path is None and legacy_url:
        normalized_base_url, normalized_path = _split_legacy_url(legacy_url)

    if not normalized_path:
        raise AppException("请输入接口 Path", code="MISSING_API_PATH", status_code=400)
    if environment is not None:
        normalized_base_url = None

    display_base_url = environment.base_url if environment else normalized_base_url
    if display_base_url or urlparse(normalized_path).scheme in {"http", "https"}:
        display_url = build_request_url(normalized_path, base_url=display_base_url)
    else:
        display_url = normalized_path
    return environment, normalized_base_url, normalized_path, display_url


def _normalize_base_url(value: str) -> str:
    text = str(value or "").strip().rstrip("/")
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise AppException("环境 URL 必须是 http/https 完整地址", code="INVALID_API_BASE_URL", status_code=400)
    return text


def _normalize_path(value: str) -> str:
    text = str(value or "").strip()
    parsed = urlparse(text)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return text
    if parsed.scheme:
        raise AppException("接口 Path 仅支持相对路径或 http/https 完整地址", code="INVALID_API_PATH", status_code=400)
    if not text.startswith("/"):
        raise AppException("接口 Path 必须以 / 开头", code="INVALID_API_PATH", status_code=400)
    return text


def _split_legacy_url(value: str) -> tuple[str | None, str]:
    text = str(value or "").strip()
    parsed = urlparse(text)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        base_url = f"{parsed.scheme}://{parsed.netloc}"
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"
        return base_url, path
    return None, _normalize_path(text)


def _display_case_url(row: ApiTestCase) -> str:
    try:
        return build_case_request_url(row)
    except AppException:
        return row.url


async def _ensure_variable_key_available(
    db: AsyncSession,
    environment_id: uuid.UUID,
    key: str,
    *,
    exclude_id: uuid.UUID | None = None,
) -> None:
    query = select(ApiTestEnvironmentVariable).where(
        ApiTestEnvironmentVariable.environment_id == environment_id,
        ApiTestEnvironmentVariable.key == key,
    )
    if exclude_id is not None:
        query = query.where(ApiTestEnvironmentVariable.id != exclude_id)
    result = await db.execute(query)
    if result.scalar_one_or_none() is not None:
        raise AppException("环境变量 Key 已存在", code="DUPLICATE_API_ENV_VARIABLE", status_code=400)


def _normalize_variable_key(value: str) -> str:
    key = str(value or "").strip()
    if not _VARIABLE_KEY_PATTERN.match(key):
        raise AppException(
            "环境变量 Key 只能包含字母、数字、下划线、点和短横线，且必须以字母或下划线开头",
            code="INVALID_API_ENV_VARIABLE_KEY",
            status_code=400,
        )
    return key


def _environment_variables_map(environment: ApiTestEnvironment | None) -> dict[str, str]:
    if environment is None:
        return {}
    return {
        variable.key: variable.value
        for variable in getattr(environment, "variables", []) or []
        if variable.key
    }


async def _load_environment_variables_map(
    db: AsyncSession,
    row: ApiTestCase,
) -> dict[str, str]:
    if not row.environment_id:
        return {}
    result = await db.execute(
        select(ApiTestEnvironmentVariable).where(
            ApiTestEnvironmentVariable.environment_id == row.environment_id,
        )
    )
    variables = {
        variable.key: variable.value
        for variable in result.scalars().unique().all()
        if variable.key
    }
    if variables:
        return variables
    return _environment_variables_map(getattr(row, "environment", None))


def _render_template(
    text: str,
    variables: dict[str, str],
    *,
    coerce_json_scalars: bool = False,
) -> Any:
    full_match = _VARIABLE_PATTERN.fullmatch(text.strip())
    if full_match:
        key = full_match.group(1)
        if key not in variables:
            raise AppException(f"未找到环境变量：{key}", code="MISSING_API_ENV_VARIABLE", status_code=400)
        return _coerce_json_scalar(variables[key]) if coerce_json_scalars else variables[key]

    missing: list[str] = []

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in variables:
            missing.append(key)
            return match.group(0)
        return variables[key]

    rendered = _VARIABLE_PATTERN.sub(replace, text)
    if missing:
        unique = "、".join(dict.fromkeys(missing))
        raise AppException(f"未找到环境变量：{unique}", code="MISSING_API_ENV_VARIABLE", status_code=400)
    return rendered


def _coerce_json_scalar(value: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _normalize_mapping(value: dict[str, Any]) -> dict[str, Any]:
    return {str(k).strip(): v for k, v in (value or {}).items() if str(k).strip()}


def _string_mapping(value: dict[str, Any]) -> dict[str, str]:
    return {str(k): str(v) for k, v in value.items() if v is not None}


def _query_params(value: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, val in value.items():
        if val is None:
            continue
        if isinstance(val, list):
            out[str(key)] = [str(item) for item in val]
        else:
            out[str(key)] = str(val)
    return out


def _try_json(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _json_path_get(value: Any, path: str) -> Any:
    if not path.startswith("$."):
        return _MISSING
    current = value
    for token in _tokenize_json_path(path[2:]):
        if isinstance(token, int):
            if not isinstance(current, list) or token >= len(current):
                return _MISSING
            current = current[token]
            continue
        if not isinstance(current, dict) or token not in current:
            return _MISSING
        current = current[token]
    return current


def _tokenize_json_path(path: str) -> list[str | int]:
    tokens: list[str | int] = []
    for part in path.split("."):
        rest = part
        while rest:
            if "[" not in rest:
                tokens.append(rest)
                break
            head, tail = rest.split("[", 1)
            if head:
                tokens.append(head)
            idx, _, rest = tail.partition("]")
            if not idx.isdigit():
                return []
            tokens.append(int(idx))
    return tokens
