from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx

from app.modules.api_testing.automation_service import run_api_automation_task
from app.modules.api_testing.models import (
    ApiAutomationRun,
    ApiAutomationRunStep,
)
from app.modules.api_testing.schemas import (
    ApiAssertion,
    ApiAutomationRunRequest,
)


class _DBStub:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.flushed = False

    def add(self, obj) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        self.flushed = True
        now = datetime.now(timezone.utc)
        for item in self.added:
            if getattr(item, "id", None) is None:
                item.id = uuid.uuid4()
            if getattr(item, "created_at", None) is None:
                item.created_at = now
            if getattr(item, "updated_at", None) is None:
                item.updated_at = now

    async def refresh(self, _obj) -> None:
        return None


def _case(
    *,
    project_id: uuid.UUID,
    module_id: uuid.UUID,
    name: str,
    method: str,
    path: str,
    headers: dict | None = None,
    body_json: dict | None = None,
    assertions: list[ApiAssertion] | None = None,
):
    case_id = uuid.uuid4()
    return SimpleNamespace(
        id=case_id,
        project_id=project_id,
        module_id=module_id,
        module=SimpleNamespace(name="接口模块"),
        environment_id=None,
        environment=SimpleNamespace(name="测试环境", base_url="https://api.example.com", variables=[]),
        created_by=uuid.uuid4(),
        creator=SimpleNamespace(username="tester", display_name="测试"),
        name=name,
        method=method,
        url=path,
        base_url=None,
        path=path,
        headers=headers or {},
        query_params={},
        body_type="json" if body_json is not None else "none",
        body_json=body_json,
        body_text=None,
        assertions=[item.model_dump(mode="json") for item in assertions or []],
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


def _step(
    *,
    task_id: uuid.UUID,
    api_case,
    order_index: int,
    name: str,
    extractors: list[dict] | None = None,
):
    return SimpleNamespace(
        id=uuid.uuid4(),
        task_id=task_id,
        api_case_id=api_case.id,
        api_case=api_case,
        order_index=order_index,
        name=name,
        enabled=True,
        request_overrides={},
        extractors=extractors or [],
    )


async def test_run_api_automation_task_extracts_runtime_value_for_later_step(
    monkeypatch,
) -> None:
    from app.modules.api_testing import automation_service

    project_id = uuid.uuid4()
    module_id = uuid.uuid4()
    task_id = uuid.uuid4()
    user = SimpleNamespace(id=uuid.uuid4(), is_superuser=True)
    task = SimpleNamespace(
        id=task_id,
        project_id=project_id,
        name="登录后查用户",
        environment_id=None,
        environment=None,
        timeout_seconds=15.0,
        stop_on_failure=True,
    )
    login_case = _case(
        project_id=project_id,
        module_id=module_id,
        name="登录",
        method="POST",
        path="/login",
        body_json={"account": "demo"},
        assertions=[ApiAssertion(type="status_code", expected=200)],
    )
    profile_case = _case(
        project_id=project_id,
        module_id=module_id,
        name="用户详情",
        method="GET",
        path="/users/{{runtime.user_id}}",
        headers={"Authorization": "Bearer {{runtime.token}}"},
        assertions=[ApiAssertion(type="json_path_eq", path="$.ok", expected=True)],
    )
    steps = [
        _step(
            task_id=task_id,
            api_case=login_case,
            order_index=1,
            name="登录",
            extractors=[
                {"name": "token", "source": "response_json", "path": "$.data.token"},
                {"name": "user_id", "source": "response_json", "path": "$.data.user.id"},
            ],
        ),
        _step(task_id=task_id, api_case=profile_case, order_index=2, name="用户详情"),
    ]

    async def fake_get_task(_db, _task_id, _user):
        return task

    async def fake_load_steps(_db, _task):
        return steps

    monkeypatch.setattr(automation_service, "_get_automation_task_for_run", fake_get_task)
    monkeypatch.setattr(automation_service, "_load_automation_steps_for_run", fake_load_steps)

    seen_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_paths.append(request.url.path)
        if request.url.path == "/login":
            return httpx.Response(
                200,
                json={"data": {"token": "token-abc", "user": {"id": "u-1001"}}},
            )
        assert request.headers["authorization"] == "Bearer token-abc"
        return httpx.Response(200, json={"ok": True})

    result = await run_api_automation_task(
        _DBStub(),
        task_id,
        user,
        ApiAutomationRunRequest(trigger_type="manual"),
        transport=httpx.MockTransport(handler),
    )

    assert seen_paths == ["/login", "/users/u-1001"]
    assert result.status == "passed"
    assert result.total_steps == 2
    assert result.passed_steps == 2
    assert result.runtime_data == {"token": "token-abc", "user_id": "u-1001"}
    assert result.steps[1].request_url == "https://api.example.com/users/u-1001"


async def test_run_api_automation_task_stops_after_failed_dependency(monkeypatch) -> None:
    from app.modules.api_testing import automation_service

    project_id = uuid.uuid4()
    module_id = uuid.uuid4()
    task_id = uuid.uuid4()
    user = SimpleNamespace(id=uuid.uuid4(), is_superuser=True)
    task = SimpleNamespace(
        id=task_id,
        project_id=project_id,
        name="失败停止",
        environment_id=None,
        environment=None,
        timeout_seconds=15.0,
        stop_on_failure=True,
    )
    first_case = _case(
        project_id=project_id,
        module_id=module_id,
        name="前置接口",
        method="GET",
        path="/first",
        assertions=[ApiAssertion(type="status_code", expected=200)],
    )
    second_case = _case(
        project_id=project_id,
        module_id=module_id,
        name="依赖接口",
        method="GET",
        path="/second",
        assertions=[ApiAssertion(type="status_code", expected=200)],
    )
    steps = [
        _step(task_id=task_id, api_case=first_case, order_index=1, name="前置接口"),
        _step(task_id=task_id, api_case=second_case, order_index=2, name="依赖接口"),
    ]

    async def fake_get_task(_db, _task_id, _user):
        return task

    async def fake_load_steps(_db, _task):
        return steps

    monkeypatch.setattr(automation_service, "_get_automation_task_for_run", fake_get_task)
    monkeypatch.setattr(automation_service, "_load_automation_steps_for_run", fake_load_steps)

    seen_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_paths.append(request.url.path)
        return httpx.Response(500, json={"ok": False})

    db = _DBStub()
    result = await run_api_automation_task(
        db,
        task_id,
        user,
        ApiAutomationRunRequest(trigger_type="manual"),
        transport=httpx.MockTransport(handler),
    )

    assert seen_paths == ["/first"]
    assert result.status == "failed"
    assert result.total_steps == 2
    assert result.failed_steps == 1
    assert result.skipped_steps == 1
    assert result.steps[1].status == "skipped"
    assert "前置步骤失败" in str(result.steps[1].error)
    assert any(isinstance(item, ApiAutomationRun) for item in db.added)
    assert sum(isinstance(item, ApiAutomationRunStep) for item in db.added) == 2
