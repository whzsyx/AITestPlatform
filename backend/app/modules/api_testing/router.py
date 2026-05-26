from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, require_permission
from app.core.response import success_response
from app.modules.api_testing.schemas import (
    ApiTestCaseCreateRequest,
    ApiTestCaseUpdateRequest,
    ApiTestEnvironmentCreateRequest,
    ApiTestEnvironmentUpdateRequest,
    ApiTestEnvironmentVariableCreateRequest,
    ApiTestEnvironmentVariableUpdateRequest,
    ApiTestModuleCreateRequest,
    ApiTestModuleUpdateRequest,
    ApiTestRunRequest,
)
from app.modules.api_testing.service import (
    create_api_test_case,
    create_api_test_environment,
    create_api_test_environment_variable,
    create_api_test_module,
    delete_api_test_case,
    delete_api_test_environment,
    delete_api_test_environment_variable,
    delete_api_test_module,
    get_api_test_case,
    get_api_test_module_tree,
    list_api_test_cases,
    list_api_test_environment_variables,
    list_api_test_environments,
    run_api_test_case,
    update_api_test_case,
    update_api_test_environment,
    update_api_test_environment_variable,
    update_api_test_module,
)
from app.modules.auth.models import User
from app.modules.auth.permissions import Permissions

router = APIRouter(prefix="/api", tags=["API 管理"])


@router.get("/projects/{project_id}/api-test-environments", response_model=dict)
async def list_api_test_environments_endpoint(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.API_TEST_VIEW)),
):
    items = await list_api_test_environments(db, project_id, current_user)
    return success_response(data=[item.model_dump(mode="json") for item in items])


@router.post("/projects/{project_id}/api-test-environments", response_model=dict)
async def create_api_test_environment_endpoint(
    project_id: uuid.UUID,
    data: ApiTestEnvironmentCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.API_TEST_EDIT)),
):
    item = await create_api_test_environment(db, project_id, data, current_user)
    return success_response(data=item.model_dump(mode="json"), message="API 环境创建成功")


@router.patch("/api-test-environments/{environment_id}", response_model=dict)
async def update_api_test_environment_endpoint(
    environment_id: uuid.UUID,
    data: ApiTestEnvironmentUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.API_TEST_EDIT)),
):
    item = await update_api_test_environment(db, environment_id, data, current_user)
    return success_response(data=item.model_dump(mode="json"), message="API 环境更新成功")


@router.delete("/api-test-environments/{environment_id}", response_model=dict)
async def delete_api_test_environment_endpoint(
    environment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.API_TEST_EDIT)),
):
    await delete_api_test_environment(db, environment_id, current_user)
    return success_response(data=None, message="API 环境已删除")


@router.get("/api-test-environments/{environment_id}/variables", response_model=dict)
async def list_api_test_environment_variables_endpoint(
    environment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.API_TEST_VIEW)),
):
    items = await list_api_test_environment_variables(db, environment_id, current_user)
    return success_response(data=[item.model_dump(mode="json") for item in items])


@router.post("/api-test-environments/{environment_id}/variables", response_model=dict)
async def create_api_test_environment_variable_endpoint(
    environment_id: uuid.UUID,
    data: ApiTestEnvironmentVariableCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.API_TEST_EDIT)),
):
    item = await create_api_test_environment_variable(db, environment_id, data, current_user)
    return success_response(data=item.model_dump(mode="json"), message="环境变量已创建")


@router.patch("/api-test-environment-variables/{variable_id}", response_model=dict)
async def update_api_test_environment_variable_endpoint(
    variable_id: uuid.UUID,
    data: ApiTestEnvironmentVariableUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.API_TEST_EDIT)),
):
    item = await update_api_test_environment_variable(db, variable_id, data, current_user)
    return success_response(data=item.model_dump(mode="json"), message="环境变量已更新")


@router.delete("/api-test-environment-variables/{variable_id}", response_model=dict)
async def delete_api_test_environment_variable_endpoint(
    variable_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.API_TEST_EDIT)),
):
    await delete_api_test_environment_variable(db, variable_id, current_user)
    return success_response(data=None, message="环境变量已删除")


@router.get("/projects/{project_id}/api-test-modules", response_model=dict)
async def get_api_test_modules_tree_endpoint(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.API_TEST_VIEW)),
):
    tree = await get_api_test_module_tree(db, project_id, current_user)
    return success_response(data=[node.model_dump(mode="json") for node in tree])


@router.post("/projects/{project_id}/api-test-modules", response_model=dict)
async def create_api_test_module_endpoint(
    project_id: uuid.UUID,
    data: ApiTestModuleCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.API_TEST_EDIT)),
):
    item = await create_api_test_module(db, project_id, data, current_user)
    return success_response(data=item.model_dump(mode="json"), message="模块创建成功")


@router.patch("/api-test-modules/{module_id}", response_model=dict)
async def update_api_test_module_endpoint(
    module_id: uuid.UUID,
    data: ApiTestModuleUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.API_TEST_EDIT)),
):
    item = await update_api_test_module(db, module_id, data, current_user)
    return success_response(data=item.model_dump(mode="json"), message="模块更新成功")


@router.delete("/api-test-modules/{module_id}", response_model=dict)
async def delete_api_test_module_endpoint(
    module_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.API_TEST_EDIT)),
):
    await delete_api_test_module(db, module_id, current_user)
    return success_response(data=None, message="模块已删除")


@router.get("/projects/{project_id}/api-tests", response_model=dict)
async def list_api_tests_endpoint(
    project_id: uuid.UUID,
    module_id: uuid.UUID | None = Query(None),
    search: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.API_TEST_VIEW)),
):
    items, total = await list_api_test_cases(
        db,
        project_id,
        current_user,
        page=page,
        page_size=page_size,
        module_id=module_id,
        search=search,
    )
    return success_response(
        data={
            "items": [item.model_dump(mode="json") for item in items],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


@router.post("/projects/{project_id}/api-tests", response_model=dict)
async def create_api_test_endpoint(
    project_id: uuid.UUID,
    data: ApiTestCaseCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.API_TEST_EDIT)),
):
    item = await create_api_test_case(db, project_id, data, current_user)
    return success_response(data=item.model_dump(mode="json"), message="API 已创建")


@router.get("/api-tests/{case_id}", response_model=dict)
async def get_api_test_endpoint(
    case_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.API_TEST_VIEW)),
):
    item = await get_api_test_case(db, case_id, current_user)
    return success_response(data=item.model_dump(mode="json"))


@router.patch("/api-tests/{case_id}", response_model=dict)
async def update_api_test_endpoint(
    case_id: uuid.UUID,
    data: ApiTestCaseUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.API_TEST_EDIT)),
):
    item = await update_api_test_case(db, case_id, data, current_user)
    return success_response(data=item.model_dump(mode="json"), message="API 已更新")


@router.delete("/api-tests/{case_id}", response_model=dict)
async def delete_api_test_endpoint(
    case_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.API_TEST_EDIT)),
):
    await delete_api_test_case(db, case_id, current_user)
    return success_response(data=None, message="API 已删除")


@router.post("/api-tests/{case_id}/run", response_model=dict)
async def run_api_test_endpoint(
    case_id: uuid.UUID,
    data: ApiTestRunRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.API_TEST_RUN)),
):
    result = await run_api_test_case(db, case_id, current_user, data)
    return success_response(data=result.model_dump(mode="json"), message="接口调试完成")
