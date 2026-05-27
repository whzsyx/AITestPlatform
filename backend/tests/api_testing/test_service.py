from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest

from app.core.exceptions import AppException
from app.modules.api_testing import service as api_testing_service
from app.modules.api_testing.models import ApiTestEnvironment as _ApiTestEnvironment
from app.modules.api_testing.models import ApiTestEnvironmentVariable as _ApiTestEnvironmentVariable
from app.modules.api_testing.models import ApiTestModule as _ApiTestModule
from app.modules.api_testing.schemas import (
    ApiAssertion,
    ApiTestBatchRunRequest,
    ApiTestCaseCreateRequest,
    ApiTestEnvironmentCreateRequest,
    ApiTestEnvironmentVariableCreateRequest,
    ApiTestRunRequest,
)
from app.modules.api_testing.service import (
    build_rendered_request_config,
    build_request_url,
    create_api_test_case,
    create_api_test_environment,
    create_api_test_environment_variable,
    evaluate_assertions,
    resolve_environment_templates,
    run_api_test_batch,
    run_api_test_case,
)


class _DBStub:
    def __init__(self) -> None:
        self.objects: dict[tuple[type, uuid.UUID], object] = {}
        self.added: list[object] = []
        self.deleted: list[object] = []
        self.flushed = False

    async def get(self, model, id_):
        return self.objects.get((model, id_))

    async def execute(self, _stmt):
        return _ResultStub([])

    def add(self, obj) -> None:
        self.added.append(obj)

    async def delete(self, obj) -> None:
        self.deleted.append(obj)

    async def flush(self) -> None:
        self.flushed = True
        for item in self.added:
            if getattr(item, "id", None) is None:
                item.id = uuid.uuid4()
            if getattr(item, "created_at", None) is None:
                item.created_at = datetime.now(timezone.utc)
            if getattr(item, "updated_at", None) is None:
                item.updated_at = datetime.now(timezone.utc)

    async def refresh(self, _obj) -> None:
        return None


class _ResultStub:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows

    def scalar_one_or_none(self):
        return self.rows[0] if self.rows else None

    def scalar(self):
        return self.rows[0] if self.rows else None

    def scalars(self):
        return _ScalarsStub(self.rows)


class _ScalarsStub:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows

    def unique(self):
        return self


def _module(module_id: uuid.UUID, project_id: uuid.UUID) -> _ApiTestModule:
    module = _ApiTestModule(project_id=project_id, name="订单接口")
    module.id = module_id
    return module


def _environment(env_id: uuid.UUID, project_id: uuid.UUID) -> _ApiTestEnvironment:
    env = _ApiTestEnvironment(project_id=project_id, name="测试环境", base_url="https://api.example.com")
    env.id = env_id
    env.variables = []
    return env


def _variable(
    variable_id: uuid.UUID,
    env_id: uuid.UUID,
    project_id: uuid.UUID,
    key: str,
    value: str,
) -> _ApiTestEnvironmentVariable:
    variable = _ApiTestEnvironmentVariable(
        project_id=project_id,
        environment_id=env_id,
        key=key,
        value=value,
    )
    variable.id = variable_id
    return variable


def test_build_request_url_requires_base_url_for_relative_path() -> None:
    with pytest.raises(AppException) as exc_info:
        build_request_url("/api/orders", base_url=None)

    assert exc_info.value.status_code == 400
    assert "base_url" in exc_info.value.message


def test_build_request_url_accepts_absolute_http_url() -> None:
    assert (
        build_request_url("https://api.example.com/orders", base_url=None)
        == "https://api.example.com/orders"
    )


def test_evaluate_assertions_supports_status_body_and_json_path() -> None:
    results = evaluate_assertions(
        assertions=[
            ApiAssertion(type="status_code", expected=200),
            ApiAssertion(type="body_contains", expected="ok"),
            ApiAssertion(type="json_path_eq", path="$.data.id", expected=123),
        ],
        status_code=200,
        response_text='{"message":"ok","data":{"id":123}}',
        response_json={"message": "ok", "data": {"id": 123}},
    )

    assert [item.passed for item in results] == [True, True, True]


async def test_create_api_test_environment_normalizes_base_url() -> None:
    project_id = uuid.uuid4()
    user = SimpleNamespace(id=uuid.uuid4(), is_superuser=True)
    db = _DBStub()

    result = await create_api_test_environment(
        db,
        project_id,
        ApiTestEnvironmentCreateRequest(name="  测试环境  ", base_url=" https://api.example.com/ "),
        user,
    )

    assert result.name == "测试环境"
    assert result.base_url == "https://api.example.com"
    assert db.added[0].project_id == project_id


async def test_create_api_test_environment_variable_requires_same_project_environment() -> None:
    project_id = uuid.uuid4()
    env_id = uuid.uuid4()
    user = SimpleNamespace(id=uuid.uuid4(), is_superuser=True)
    db = _DBStub()
    db.objects[(_ApiTestEnvironment, env_id)] = _environment(env_id, project_id)

    result = await create_api_test_environment_variable(
        db,
        env_id,
        ApiTestEnvironmentVariableCreateRequest(key=" token ", value=" abc123 "),
        user,
    )

    assert result.key == "token"
    assert result.value == "abc123"
    assert db.added[0].project_id == project_id
    assert db.added[0].environment_id == env_id


def test_resolve_environment_templates_replaces_nested_request_data() -> None:
    rendered = resolve_environment_templates(
        {
            "path": "/users/{{mid}}",
            "headers": {"X-{{tenant}}": "Bearer {{token}}"},
            "body": {"id": "{{mid}}", "tags": ["{{tag}}"]},
        },
        {"mid": "10001", "token": "abc123", "tag": "vip", "tenant": "Tenant"},
    )

    assert rendered == {
        "path": "/users/10001",
        "headers": {"X-Tenant": "Bearer abc123"},
        "body": {"id": "10001", "tags": ["vip"]},
    }


def test_resolve_environment_templates_coerces_full_json_placeholders() -> None:
    rendered = resolve_environment_templates(
        {
            "body": {
                "mid": "{{h-appid}}",
                "enabled": "{{enabled}}",
                "profile": "{{profile}}",
                "label": "user-{{h-appid}}",
            }
        },
        {"h-appid": "99", "enabled": "true", "profile": '{"level":2}'},
        coerce_json_scalars=True,
    )

    assert rendered == {
        "body": {
            "mid": 99,
            "enabled": True,
            "profile": {"level": 2},
            "label": "user-99",
        }
    }


def test_resolve_environment_templates_rejects_missing_variable() -> None:
    with pytest.raises(AppException) as exc_info:
        resolve_environment_templates("/users/{{mid}}", {})

    assert exc_info.value.status_code == 400
    assert "mid" in exc_info.value.message


def test_build_rendered_request_config_resolves_preview_values() -> None:
    row = SimpleNamespace(
        method="POST",
        url="/api/users/{{mid}}",
        path="/api/users/{{mid}}",
        base_url=None,
        environment=SimpleNamespace(base_url="https://api.example.com"),
        headers={"h-appid": "{{h-appid}}", "X-Trace": "trace-{{mid}}"},
        query_params={"page": "{{page}}"},
        body_type="json",
        body_json={"mid": "{{mid}}", "label": "user-{{mid}}"},
        body_text=None,
        assertions=[{"type": "json_path_eq", "path": "$.mid", "expected": "{{mid}}"}],
    )

    rendered = build_rendered_request_config(
        row,
        {"h-appid": "99", "mid": "123", "page": "1"},
    )

    assert rendered.url == "https://api.example.com/api/users/123"
    assert rendered.path == "/api/users/123"
    assert rendered.base_url == "https://api.example.com"
    assert rendered.headers == {"h-appid": "99", "X-Trace": "trace-123"}
    assert rendered.query_params == {"page": "1"}
    assert rendered.body_json == {"mid": 123, "label": "user-123"}
    assert rendered.assertions[0].expected == 123


async def test_create_api_test_case_requires_existing_project_module() -> None:
    project_id = uuid.uuid4()
    module_id = uuid.uuid4()
    user = SimpleNamespace(id=uuid.uuid4(), is_superuser=True)
    db = _DBStub()
    db.objects[(_ApiTestModule, module_id)] = _module(module_id, project_id)

    result = await create_api_test_case(
        db,
        project_id,
        ApiTestCaseCreateRequest(
            module_id=module_id,
            name="创建订单接口",
            method="post",
            url="/api/orders",
            assertions=[ApiAssertion(type="status_code", expected=201)],
        ),
        user,
    )

    assert result.module_id == module_id
    assert result.method == "POST"
    assert db.added[0].module_id == module_id
    assert db.added[0].project_id == project_id


async def test_create_api_test_case_rejects_cross_project_module() -> None:
    project_id = uuid.uuid4()
    module_id = uuid.uuid4()
    user = SimpleNamespace(id=uuid.uuid4(), is_superuser=True)
    db = _DBStub()
    db.objects[(_ApiTestModule, module_id)] = _module(module_id, uuid.uuid4())

    with pytest.raises(AppException) as exc_info:
        await create_api_test_case(
            db,
            project_id,
            ApiTestCaseCreateRequest(
                module_id=module_id,
                name="跨项目模块不允许",
                method="GET",
                url="/api/orders",
            ),
            user,
        )

    assert exc_info.value.status_code == 400
    assert "模块不属于当前项目" in exc_info.value.message


async def test_run_api_test_case_uses_saved_environment_base_url() -> None:
    project_id = uuid.uuid4()
    module_id = uuid.uuid4()
    env_id = uuid.uuid4()
    user = SimpleNamespace(id=uuid.uuid4(), is_superuser=True)
    db = _DBStub()
    db.objects[(_ApiTestModule, module_id)] = _module(module_id, project_id)
    db.objects[(_ApiTestEnvironment, env_id)] = _environment(env_id, project_id)
    created = await create_api_test_case(
        db,
        project_id,
        ApiTestCaseCreateRequest(
            module_id=module_id,
            environment_id=env_id,
            name="环境订单详情接口",
            method="GET",
            path="/orders/123",
            assertions=[ApiAssertion(type="status_code", expected=200)],
        ),
        user,
    )
    case = db.added[0]
    case.module = _module(module_id, project_id)
    environment = _environment(env_id, project_id)
    environment.variables = [
        _variable(uuid.uuid4(), env_id, project_id, "order_id", "123"),
        _variable(uuid.uuid4(), env_id, project_id, "token", "abc123"),
    ]
    case.environment = environment
    case.path = "/orders/{{order_id}}"
    case.headers = {"Authorization": "Bearer {{token}}"}
    db.objects[(type(case), case.id)] = case

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://api.example.com/orders/123"
        assert request.headers["authorization"] == "Bearer abc123"
        return httpx.Response(200, json={"ok": True})

    result = await run_api_test_case(
        db,
        created.id,
        user,
        ApiTestRunRequest(),
        transport=httpx.MockTransport(handler),
    )

    assert result.passed is True
    assert result.request_url == "https://api.example.com/orders/123"


async def test_run_api_test_case_returns_assertion_results() -> None:
    project_id = uuid.uuid4()
    module_id = uuid.uuid4()
    user = SimpleNamespace(id=uuid.uuid4(), is_superuser=True)
    db = _DBStub()
    db.objects[(_ApiTestModule, module_id)] = _module(module_id, project_id)
    created = await create_api_test_case(
        db,
        project_id,
        ApiTestCaseCreateRequest(
            module_id=module_id,
            name="订单详情接口",
            method="GET",
            url="/orders/123",
            assertions=[
                ApiAssertion(type="status_code", expected=200),
                ApiAssertion(type="json_path_eq", path="$.data.id", expected="123"),
            ],
        ),
        user,
    )
    case = db.added[0]
    case.module = _module(module_id, project_id)
    db.objects[(type(case), case.id)] = case

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://api.example.com/orders/123"
        return httpx.Response(200, json={"data": {"id": "123"}})

    result = await run_api_test_case(
        db,
        created.id,
        user,
        ApiTestRunRequest(base_url="https://api.example.com"),
        transport=httpx.MockTransport(handler),
    )

    assert result.passed is True
    assert result.status_code == 200
    assert [item.passed for item in result.assertions] == [True, True]


async def test_run_api_test_batch_returns_per_api_report(monkeypatch: pytest.MonkeyPatch) -> None:
    project_id = uuid.uuid4()
    module_id = uuid.uuid4()
    user = SimpleNamespace(id=uuid.uuid4(), is_superuser=True)
    db = _DBStub()
    db.objects[(_ApiTestModule, module_id)] = _module(module_id, project_id)
    first = await create_api_test_case(
        db,
        project_id,
        ApiTestCaseCreateRequest(
            module_id=module_id,
            name="健康检查",
            method="GET",
            url="/ok",
            assertions=[ApiAssertion(type="status_code", expected=200)],
        ),
        user,
    )
    second = await create_api_test_case(
        db,
        project_id,
        ApiTestCaseCreateRequest(
            module_id=module_id,
            name="异常接口",
            method="GET",
            url="/bad",
            assertions=[ApiAssertion(type="status_code", expected=200)],
        ),
        user,
    )
    rows = [db.added[0], db.added[1]]
    for row in rows:
        row.module = _module(module_id, project_id)

    async def fake_load_rows(_db, _project_id, _data):  # noqa: ANN001
        return rows

    monkeypatch.setattr(api_testing_service, "_load_batch_api_test_rows", fake_load_rows)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/ok":
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(500, json={"ok": False})

    result = await run_api_test_batch(
        db,
        project_id,
        user,
        ApiTestBatchRunRequest(case_ids=[first.id, second.id], base_url="https://api.example.com"),
        transport=httpx.MockTransport(handler),
    )

    assert result.total == 2
    assert result.passed == 1
    assert result.failed == 1
    assert [item.name for item in result.items] == ["健康检查", "异常接口"]
    assert result.items[0].passed is True
    assert result.items[1].passed is False
    assert result.items[1].status_code == 500
    assert "状态码" in str(result.items[1].error)
    assert "期望=200" in str(result.items[1].error)
    assert "实际=500" in str(result.items[1].error)
    assert result.items[0].rendered_request is not None
    assert result.items[0].rendered_request.url == "https://api.example.com/ok"
    assert result.items[0].run_result is not None
    assert result.items[0].run_result.response_json == {"ok": True}
