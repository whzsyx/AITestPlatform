from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.modules.ui_automation.execution_engine import (
    EngineDeps,
    ExecutionEngine,
    ExecutionInputs,
)
from app.modules.ui_automation.execution_service import _build_config_snapshot
from app.modules.ui_automation.schemas import ExecutionCreateRequest
from tests.ui_automation.test_engine import (
    _FakePersistence,
    _FakeSessionContext,
    _FakeStepRunner,
    _FakeStreamHub,
    _make_resolver_stub,
    _patch_db_loaders,
    _patch_resolver,
    _Step,
    _step_run_ok,
    _Testcase,
)


class _FakeLocator:
    def __init__(self, count: int) -> None:
        self._count = count

    async def count(self) -> int:
        return self._count


class _FakePage:
    def __init__(self, *, text_count: int = 1) -> None:
        self.text_count = text_count
        self.url = "https://app.example.com/shop"
        self.lookups: list[tuple[str, bool]] = []
        self.evaluate_results: list[dict[str, Any]] = []

    def get_by_text(self, text: str, *, exact: bool = True) -> _FakeLocator:
        self.lookups.append((text, exact))
        return _FakeLocator(self.text_count)

    async def evaluate(self, _script: str, _arg: dict[str, Any] | None = None):
        if self.evaluate_results:
            return self.evaluate_results.pop(0)
        return {}


class _BundleWithPage:
    def __init__(self, page: Any) -> None:
        self.execution_id = uuid.uuid4()
        self.mcp_unavailable = True
        self.closed = False
        self.page = page

    async def register_mcp_tools_for_agent(self) -> list[dict[str, Any]]:
        return []

    def get_primary_page(self) -> Any:
        return self.page

    async def close(self) -> None:
        self.closed = True


def test_execution_strategy_is_validated_and_recorded_in_snapshot() -> None:
    testcase_id = uuid.uuid4()
    default_request = ExecutionCreateRequest(testcase_ids=[testcase_id])
    default_snapshot = _build_config_snapshot(
        default_request,
        testcase_ids=[testcase_id],
    )
    default_inputs = ExecutionInputs(
        execution_id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        environment_id=uuid.uuid4(),
        testcase_ids=[testcase_id],
        llm_config_id=None,
        triggered_by=uuid.uuid4(),
    )

    assert default_request.execution_strategy == "hybrid_lightweight"
    assert default_snapshot["execution_strategy"] == "hybrid_lightweight"
    assert default_inputs.execution_strategy == "hybrid_lightweight"

    request = ExecutionCreateRequest(
        testcase_ids=[testcase_id],
        execution_strategy="ai_step_runner",
    )

    snapshot = _build_config_snapshot(request, testcase_ids=[testcase_id])

    assert request.execution_strategy == "ai_step_runner"
    assert snapshot["execution_strategy"] == "ai_step_runner"

    with pytest.raises(ValidationError):
        ExecutionCreateRequest(
            testcase_ids=[testcase_id],
            execution_strategy="browser_ai_freeform",
        )


@pytest.mark.asyncio
async def test_hybrid_uses_deterministic_runner_for_supported_assertion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolver, _state = _make_resolver_stub()
    _patch_resolver(monkeypatch, lambda: resolver)

    tc = _Testcase(
        id=uuid.uuid4(),
        title="保存成功提示",
        steps=[
            _Step(
                step_number=1,
                action="验证页面显示保存成功提示",
                expected_result="保存成功",
            ),
        ],
    )
    _patch_db_loaders(monkeypatch, testcases=[tc])

    page = _FakePage(text_count=1)
    bundle = _BundleWithPage(page)
    runner = _FakeStepRunner(results=[_step_run_ok(snapshot="不应调用 AI StepRunner")])
    persistence = _FakePersistence()
    hub = _FakeStreamHub()
    deps = EngineDeps(
        db_session_factory=lambda: _FakeSessionContext(),
        open_browser_bundle=AsyncMock(return_value=bundle),
        step_runner_factory=lambda env, llm, budget, eid: runner,
        persistence=persistence,
        stream_hub=hub,
    )
    engine = ExecutionEngine(deps=deps)
    inputs = ExecutionInputs(
        execution_id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        environment_id=uuid.uuid4(),
        testcase_ids=[tc.id],
        llm_config_id=None,
        triggered_by=uuid.uuid4(),
        execution_strategy="hybrid_lightweight",
    )

    outcome = await engine.run(inputs)

    assert outcome.status == "completed"
    assert outcome.passed == 1
    assert runner.calls == []
    assert page.lookups == [("保存成功", True)]
    flushed_step = persistence.steps_flushed[0]
    assert flushed_step["tokens_used"] == 0
    assert flushed_step["tool_calls"][0]["raw_name"] == "deterministic_runner"
    assert flushed_step["tool_calls"][0]["result"]["execution_path"] == "deterministic"
    assert flushed_step["tool_calls"][-1]["raw_name"] == "execution_meta"
    assert flushed_step["tool_calls"][-1]["result"]["execution_path"] == "deterministic"
    assert flushed_step["tool_calls"][-1]["result"]["llm_calls"] == 0
    step_events = [
        payload
        for event, payload in hub.streams[inputs.execution_id].events
        if event == "step_complete"
    ]
    assert step_events[0]["execution_path"] == "deterministic"


@pytest.mark.asyncio
async def test_hybrid_keeps_deterministic_table_row_verdict_authoritative(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolver, _state = _make_resolver_stub()
    _patch_resolver(monkeypatch, lambda: resolver)

    tc = _Testcase(
        id=uuid.uuid4(),
        title="新增列数据展示",
        steps=[
            _Step(
                step_number=1,
                action="查看新增列的数据行展示情况",
                expected_result="新增列数据展示正常，样式与原有列保持一致",
            ),
        ],
    )
    _patch_db_loaders(monkeypatch, testcases=[tc])

    page = _FakePage()
    page.evaluate_results.append(
        {
            "table_hint": None,
            "columns": ["店铺ID", "提现银行账户"],
            "rows": [{"row": 0, "店铺ID": "S001", "提现银行账户": ""}],
            "row_count": 1,
            "limit": 50,
        },
    )
    bundle = _BundleWithPage(page)
    runner = _FakeStepRunner(results=[_step_run_ok(snapshot="不应调用 AI StepRunner")])
    persistence = _FakePersistence()
    hub = _FakeStreamHub()
    deps = EngineDeps(
        db_session_factory=lambda: _FakeSessionContext(),
        open_browser_bundle=AsyncMock(return_value=bundle),
        step_runner_factory=lambda env, llm, budget, eid: runner,
        persistence=persistence,
        stream_hub=hub,
    )
    engine = ExecutionEngine(deps=deps)
    inputs = ExecutionInputs(
        execution_id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        environment_id=uuid.uuid4(),
        testcase_ids=[tc.id],
        llm_config_id=None,
        triggered_by=uuid.uuid4(),
        execution_strategy="hybrid_lightweight",
    )

    outcome = await engine.run(inputs)

    assert outcome.status == "completed"
    assert outcome.passed == 1
    assert runner.calls == []
    flushed_step = persistence.steps_flushed[0]
    assert flushed_step["assertion_passed"] is True
    assert flushed_step["assertion_reason"] == "表格至少一行数据"
    assert flushed_step["assertion_evidence"] == "表格行数：1"


@pytest.mark.asyncio
async def test_hybrid_falls_back_to_step_runner_when_deterministic_locator_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolver, _state = _make_resolver_stub()
    _patch_resolver(monkeypatch, lambda: resolver)

    tc = _Testcase(
        id=uuid.uuid4(),
        title="保存成功提示",
        steps=[
            _Step(
                step_number=1,
                action="验证页面显示保存成功提示",
                expected_result="保存成功",
            ),
        ],
    )
    _patch_db_loaders(monkeypatch, testcases=[tc])

    page = _FakePage(text_count=0)
    bundle = _BundleWithPage(page)
    runner = _FakeStepRunner(results=[_step_run_ok(snapshot="保存成功", tokens=25)])
    persistence = _FakePersistence()
    hub = _FakeStreamHub()
    deps = EngineDeps(
        db_session_factory=lambda: _FakeSessionContext(),
        open_browser_bundle=AsyncMock(return_value=bundle),
        step_runner_factory=lambda env, llm, budget, eid: runner,
        persistence=persistence,
        stream_hub=hub,
    )
    engine = ExecutionEngine(deps=deps)
    inputs = ExecutionInputs(
        execution_id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        environment_id=uuid.uuid4(),
        testcase_ids=[tc.id],
        llm_config_id=None,
        triggered_by=uuid.uuid4(),
        execution_strategy="hybrid_lightweight",
    )

    outcome = await engine.run(inputs)

    assert outcome.status == "completed"
    assert outcome.passed == 1
    assert len(runner.calls) == 1
    flushed_step = persistence.steps_flushed[0]
    assert flushed_step["tool_calls"][0]["raw_name"] == "deterministic_runner"
    assert flushed_step["tool_calls"][0]["result"]["success"] is False
    assert flushed_step["tool_calls"][-1]["raw_name"] == "execution_meta"
    assert flushed_step["tool_calls"][-1]["result"]["execution_path"] == "ai_fallback"
    assert flushed_step["tool_calls"][-1]["result"]["llm_calls"] == 1
    step_events = [
        payload
        for event, payload in hub.streams[inputs.execution_id].events
        if event == "step_complete"
    ]
    assert step_events[0]["execution_path"] == "ai_fallback"


@pytest.mark.asyncio
async def test_hybrid_uses_step_runner_for_unsupported_steps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolver, _state = _make_resolver_stub()
    _patch_resolver(monkeypatch, lambda: resolver)

    tc = _Testcase(
        id=uuid.uuid4(),
        title="复杂业务流程",
        steps=[
            _Step(
                step_number=1,
                action="完成复杂业务流程校验",
                expected_result="业务状态正确",
            ),
        ],
    )
    _patch_db_loaders(monkeypatch, testcases=[tc])

    runner = _FakeStepRunner(results=[_step_run_ok(snapshot="业务状态正确", tokens=18)])
    persistence = _FakePersistence()
    hub = _FakeStreamHub()
    deps = EngineDeps(
        db_session_factory=lambda: _FakeSessionContext(),
        open_browser_bundle=AsyncMock(return_value=_BundleWithPage(_FakePage())),
        step_runner_factory=lambda env, llm, budget, eid: runner,
        persistence=persistence,
        stream_hub=hub,
    )
    engine = ExecutionEngine(deps=deps)
    inputs = ExecutionInputs(
        execution_id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        environment_id=uuid.uuid4(),
        testcase_ids=[tc.id],
        llm_config_id=None,
        triggered_by=uuid.uuid4(),
        execution_strategy="hybrid_lightweight",
    )

    outcome = await engine.run(inputs)

    assert outcome.status == "completed"
    assert outcome.passed == 1
    assert len(runner.calls) == 1
    flushed_step = persistence.steps_flushed[0]
    assert flushed_step["tool_calls"][-1]["raw_name"] == "execution_meta"
    assert flushed_step["tool_calls"][-1]["result"]["execution_path"] == "ai_only"
    assert flushed_step["tool_calls"][-1]["result"]["llm_calls"] == 1
    step_events = [
        payload
        for event, payload in hub.streams[inputs.execution_id].events
        if event == "step_complete"
    ]
    assert step_events[0]["execution_path"] == "ai_step_runner"
