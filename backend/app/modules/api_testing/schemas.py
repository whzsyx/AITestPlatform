from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

ApiMethod = Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
ApiBodyType = Literal["none", "json", "text"]
ApiAssertionType = Literal["status_code", "body_contains", "json_path_eq"]
ApiAutomationScheduleType = Literal["manual", "interval", "daily"]
ApiAutomationTriggerType = Literal["manual", "schedule"]
ApiAutomationStatus = Literal["running", "passed", "failed", "skipped"]
ApiAutomationExtractorSource = Literal[
    "response_json",
    "response_header",
    "response_text",
    "status_code",
]


class ApiTestModuleCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    parent_id: uuid.UUID | None = None
    order_index: int = 0


class ApiTestModuleUpdateRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    parent_id: uuid.UUID | None = None
    order_index: int | None = None


class ApiTestModuleResponse(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    parent_id: uuid.UUID | None
    name: str
    order_index: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ApiTestModuleTreeNode(BaseModel):
    id: uuid.UUID
    name: str
    parent_id: uuid.UUID | None
    order_index: int
    case_count: int = 0
    children: list["ApiTestModuleTreeNode"] = []

    model_config = {"from_attributes": True}


class ApiTestEnvironmentCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    base_url: str = Field(..., min_length=1, max_length=1000)
    description: str | None = None
    order_index: int = 0

    @field_validator("base_url")
    @classmethod
    def _strip_base_url(cls, value: str) -> str:
        return value.strip()


class ApiTestEnvironmentUpdateRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    base_url: str | None = Field(None, min_length=1, max_length=1000)
    description: str | None = None
    order_index: int | None = None

    @field_validator("base_url")
    @classmethod
    def _strip_base_url(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else value


class ApiTestEnvironmentResponse(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    base_url: str
    description: str | None
    order_index: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ApiTestEnvironmentVariableCreateRequest(BaseModel):
    key: str = Field(..., min_length=1, max_length=100)
    value: str = Field(..., max_length=4000)
    description: str | None = None

    @field_validator("key", "value")
    @classmethod
    def _strip_required_text(cls, value: str) -> str:
        return value.strip()


class ApiTestEnvironmentVariableUpdateRequest(BaseModel):
    key: str | None = Field(None, min_length=1, max_length=100)
    value: str | None = Field(None, max_length=4000)
    description: str | None = None

    @field_validator("key", "value")
    @classmethod
    def _strip_optional_text(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else value


class ApiTestEnvironmentVariableResponse(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    environment_id: uuid.UUID
    key: str
    value: str
    description: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ApiAssertion(BaseModel):
    type: ApiAssertionType
    expected: Any = None
    path: str | None = Field(None, max_length=200)


class ApiAssertionResult(BaseModel):
    type: ApiAssertionType
    passed: bool
    reason: str
    expected: Any = None
    actual: Any = None
    path: str | None = None


class ApiTestCaseCreateRequest(BaseModel):
    module_id: uuid.UUID
    environment_id: uuid.UUID | None = None
    name: str = Field(..., min_length=1, max_length=300)
    method: ApiMethod
    url: str | None = Field(None, min_length=1, max_length=1000)
    base_url: str | None = Field(None, max_length=1000)
    path: str | None = Field(None, min_length=1, max_length=1000)
    headers: dict[str, Any] = Field(default_factory=dict)
    query_params: dict[str, Any] = Field(default_factory=dict)
    body_type: ApiBodyType = "none"
    body_json: Any = None
    body_text: str | None = None
    assertions: list[ApiAssertion] = Field(default_factory=list)

    @field_validator("method", mode="before")
    @classmethod
    def _uppercase_method(cls, value: Any) -> Any:
        return str(value).upper() if value is not None else value

    @field_validator("url")
    @classmethod
    def _strip_url(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else value

    @field_validator("base_url", "path")
    @classmethod
    def _strip_optional_text(cls, value: str | None) -> str | None:
        text = value.strip() if value is not None else None
        return text or None


class ApiTestCaseUpdateRequest(BaseModel):
    module_id: uuid.UUID | None = None
    environment_id: uuid.UUID | None = None
    name: str | None = Field(None, min_length=1, max_length=300)
    method: ApiMethod | None = None
    url: str | None = Field(None, min_length=1, max_length=1000)
    base_url: str | None = Field(None, max_length=1000)
    path: str | None = Field(None, min_length=1, max_length=1000)
    headers: dict[str, Any] | None = None
    query_params: dict[str, Any] | None = None
    body_type: ApiBodyType | None = None
    body_json: Any = None
    body_text: str | None = None
    assertions: list[ApiAssertion] | None = None

    @field_validator("method", mode="before")
    @classmethod
    def _uppercase_method(cls, value: Any) -> Any:
        return str(value).upper() if value is not None else value

    @field_validator("url")
    @classmethod
    def _strip_url(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else value

    @field_validator("base_url", "path")
    @classmethod
    def _strip_optional_text(cls, value: str | None) -> str | None:
        text = value.strip() if value is not None else None
        return text or None


class ApiTestCaseListItem(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    module_id: uuid.UUID
    module_name: str | None = None
    environment_id: uuid.UUID | None = None
    environment_name: str | None = None
    name: str
    method: ApiMethod
    url: str
    base_url: str | None = None
    path: str | None = None
    created_by: uuid.UUID
    creator_name: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ApiRenderedRequestConfig(BaseModel):
    url: str
    base_url: str | None = None
    path: str
    headers: dict[str, str] = Field(default_factory=dict)
    query_params: dict[str, Any] = Field(default_factory=dict)
    body_type: ApiBodyType = "none"
    body_json: Any = None
    body_text: str | None = None
    assertions: list[ApiAssertion] = Field(default_factory=list)


class ApiTestCaseResponse(ApiTestCaseListItem):
    headers: dict[str, Any] = Field(default_factory=dict)
    query_params: dict[str, Any] = Field(default_factory=dict)
    body_type: ApiBodyType = "none"
    body_json: Any = None
    body_text: str | None = None
    assertions: list[ApiAssertion] = Field(default_factory=list)
    rendered_request: ApiRenderedRequestConfig | None = None


class ApiTestRunRequest(BaseModel):
    base_url: str | None = Field(
        None,
        max_length=1000,
        description="当接口 URL 是 /path 相对路径时用于拼接的 base_url。",
    )
    timeout_seconds: float = Field(15.0, ge=1.0, le=60.0)

    @field_validator("base_url")
    @classmethod
    def _strip_base_url(cls, value: str | None) -> str | None:
        text = value.strip() if value else None
        return text or None


class ApiTestBatchRunRequest(BaseModel):
    case_ids: list[uuid.UUID] = Field(default_factory=list, max_length=100)
    module_id: uuid.UUID | None = None
    include_descendants: bool = True
    base_url: str | None = Field(
        None,
        max_length=1000,
        description="临时覆盖 Base URL。仅建议同一环境的一批 API 使用。",
    )
    timeout_seconds: float = Field(15.0, ge=1.0, le=60.0)

    @field_validator("base_url")
    @classmethod
    def _strip_base_url(cls, value: str | None) -> str | None:
        text = value.strip() if value else None
        return text or None

    @model_validator(mode="after")
    def _validate_scope(self) -> "ApiTestBatchRunRequest":
        if not self.case_ids and self.module_id is None:
            raise ValueError("请选择要执行的 API，或选择模块下全部 API")
        return self


class ApiTestRunResponse(BaseModel):
    passed: bool
    status_code: int | None = None
    elapsed_ms: int = 0
    request_url: str
    response_headers: dict[str, str] = Field(default_factory=dict)
    response_body: str = ""
    response_json: Any = None
    assertions: list[ApiAssertionResult] = Field(default_factory=list)
    error: str | None = None


class ApiTestBatchRunItem(BaseModel):
    case_id: uuid.UUID
    name: str
    method: ApiMethod
    module_id: uuid.UUID
    module_name: str | None = None
    environment_id: uuid.UUID | None = None
    environment_name: str | None = None
    request_url: str
    passed: bool
    status_code: int | None = None
    elapsed_ms: int = 0
    assertion_count: int = 0
    failed_assertion_count: int = 0
    error: str | None = None
    rendered_request: ApiRenderedRequestConfig | None = None
    run_result: ApiTestRunResponse | None = None


class ApiTestBatchRunResponse(BaseModel):
    total: int
    passed: int
    failed: int
    elapsed_ms: int
    scope: Literal["selected", "module"]
    items: list[ApiTestBatchRunItem] = Field(default_factory=list)


class ApiAutomationExtractor(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    source: ApiAutomationExtractorSource = "response_json"
    path: str | None = Field(None, max_length=300)
    header: str | None = Field(None, max_length=200)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def _validate_locator(self) -> "ApiAutomationExtractor":
        if self.source == "response_json" and not (self.path or "").strip():
            raise ValueError("response_json 提取器必须填写 JSONPath")
        if self.source == "response_header" and not (self.header or "").strip():
            raise ValueError("response_header 提取器必须填写 Header 名称")
        return self


class ApiAutomationStepPayload(BaseModel):
    id: uuid.UUID | None = None
    api_case_id: uuid.UUID
    name: str | None = Field(None, max_length=300)
    order_index: int = 0
    enabled: bool = True
    request_overrides: dict[str, Any] = Field(default_factory=dict)
    extractors: list[ApiAutomationExtractor] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def _strip_optional_name(cls, value: str | None) -> str | None:
        text = value.strip() if value else None
        return text or None


class ApiAutomationTaskCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=300)
    description: str | None = None
    environment_id: uuid.UUID | None = None
    enabled: bool = True
    schedule_type: ApiAutomationScheduleType = "manual"
    interval_minutes: int | None = Field(None, ge=1, le=60 * 24 * 30)
    daily_time: str | None = Field(None, pattern=r"^\d{2}:\d{2}$")
    timeout_seconds: float = Field(20.0, ge=1.0, le=60.0)
    stop_on_failure: bool = True
    steps: list[ApiAutomationStepPayload] = Field(default_factory=list, max_length=100)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        return value.strip()

    @field_validator("description")
    @classmethod
    def _strip_description(cls, value: str | None) -> str | None:
        text = value.strip() if value else None
        return text or None

    @model_validator(mode="after")
    def _validate_schedule(self) -> "ApiAutomationTaskCreateRequest":
        if self.schedule_type == "interval" and not self.interval_minutes:
            raise ValueError("间隔定时任务必须填写 interval_minutes")
        if self.schedule_type == "daily":
            if not self.daily_time:
                raise ValueError("每日定时任务必须填写 daily_time")
            hour, minute = [int(part) for part in self.daily_time.split(":")]
            if hour > 23 or minute > 59:
                raise ValueError("daily_time 必须是 00:00 到 23:59")
        return self


class ApiAutomationTaskUpdateRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=300)
    description: str | None = None
    environment_id: uuid.UUID | None = None
    enabled: bool | None = None
    schedule_type: ApiAutomationScheduleType | None = None
    interval_minutes: int | None = Field(None, ge=1, le=60 * 24 * 30)
    daily_time: str | None = Field(None, pattern=r"^\d{2}:\d{2}$")
    timeout_seconds: float | None = Field(None, ge=1.0, le=60.0)
    stop_on_failure: bool | None = None
    steps: list[ApiAutomationStepPayload] | None = Field(None, max_length=100)

    @field_validator("name", "description")
    @classmethod
    def _strip_optional_text(cls, value: str | None) -> str | None:
        text = value.strip() if value else None
        return text or None


class ApiAutomationStepResponse(BaseModel):
    id: uuid.UUID
    task_id: uuid.UUID
    api_case_id: uuid.UUID
    api_name: str | None = None
    method: ApiMethod | None = None
    path: str | None = None
    name: str | None = None
    order_index: int
    enabled: bool
    request_overrides: dict[str, Any] = Field(default_factory=dict)
    extractors: list[ApiAutomationExtractor] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ApiAutomationTaskListItem(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    environment_id: uuid.UUID | None = None
    environment_name: str | None = None
    name: str
    description: str | None = None
    enabled: bool
    schedule_type: ApiAutomationScheduleType
    interval_minutes: int | None = None
    daily_time: str | None = None
    next_run_at: datetime | None = None
    last_run_at: datetime | None = None
    timeout_seconds: float
    stop_on_failure: bool
    step_count: int = 0
    last_status: str | None = None
    created_by: uuid.UUID
    creator_name: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ApiAutomationTaskResponse(ApiAutomationTaskListItem):
    steps: list[ApiAutomationStepResponse] = Field(default_factory=list)


class PaginatedApiAutomationTasks(BaseModel):
    items: list[ApiAutomationTaskListItem]
    total: int
    page: int
    page_size: int


class ApiAutomationRunRequest(BaseModel):
    trigger_type: ApiAutomationTriggerType = "manual"


class ApiAutomationRunStepResponse(BaseModel):
    id: uuid.UUID
    run_id: uuid.UUID
    task_step_id: uuid.UUID | None = None
    api_case_id: uuid.UUID | None = None
    name: str
    method: ApiMethod | None = None
    order_index: int
    status: ApiAutomationStatus
    request_url: str | None = None
    status_code: int | None = None
    elapsed_ms: int = 0
    request_snapshot: ApiRenderedRequestConfig | None = None
    response_snapshot: ApiTestRunResponse | None = None
    assertion_results: list[ApiAssertionResult] = Field(default_factory=list)
    extracted_values: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ApiAutomationRunResponse(BaseModel):
    id: uuid.UUID
    task_id: uuid.UUID
    task_name: str | None = None
    project_id: uuid.UUID
    trigger_type: ApiAutomationTriggerType
    status: Literal["running", "passed", "failed"]
    started_at: datetime
    completed_at: datetime | None = None
    total_steps: int = 0
    passed_steps: int = 0
    failed_steps: int = 0
    skipped_steps: int = 0
    elapsed_ms: int = 0
    runtime_data: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    steps: list[ApiAutomationRunStepResponse] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class PaginatedApiAutomationRuns(BaseModel):
    items: list[ApiAutomationRunResponse]
    total: int
    page: int
    page_size: int
