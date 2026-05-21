"""Phase 13 / Task 13.1 — plan_builder 风险分级 + plan cache 单测。

DoD：propose_execution_plan 在 low / medium / high risk 三种环境下分别返回
NONE / SOFT / STRICT confirmation_strength（设计文档 §10.3.2 决策表）。
"""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.modules.skills.builtin.ui_automation import plan_builder
from app.modules.skills.builtin.ui_automation.plan_builder import (
    _decide_confirmation,
    _estimate_duration_seconds,
    _infer_risk_level,
    build_adhoc_execution_plan,
    build_execution_plan,
    get_cached_plan,
)
from app.modules.skills.builtin.ui_automation.schemas import (
    ConfirmationStrength,
    EnvRiskLevel,
)

# ────────────────── _infer_risk_level ──────────────────


@pytest.mark.parametrize(
    "name,url,expected",
    [
        ("dev", "https://dev.foo.com", EnvRiskLevel.LOW),
        ("test", "https://test.foo.com", EnvRiskLevel.LOW),
        ("staging", "https://staging.foo.com", EnvRiskLevel.MEDIUM),
        ("uat-1", "https://uat.foo.com", EnvRiskLevel.MEDIUM),
        ("preprod", "https://pre.foo.com", EnvRiskLevel.MEDIUM),
        ("prod", "https://prod.foo.com", EnvRiskLevel.HIGH),
        ("Production", "https://www.foo.com", EnvRiskLevel.HIGH),
        ("线上", "https://www.foo.com", EnvRiskLevel.HIGH),
    ],
)
def test_infer_risk_level_from_name_and_url(
    name: str, url: str, expected: EnvRiskLevel,
) -> None:
    level, reason = _infer_risk_level(name, url)
    assert level is expected
    assert isinstance(reason, str) and reason


# ────────────────── _decide_confirmation ──────────────────


def test_decide_confirmation_high_is_strict() -> None:
    strength, payload = _decide_confirmation(EnvRiskLevel.HIGH, 1)
    assert strength is ConfirmationStrength.STRICT
    assert "challenge" in payload
    assert payload["challenge_value"] == "YES PROD"


def test_decide_confirmation_high_uses_environment_name_challenge() -> None:
    strength, payload = _decide_confirmation(
        EnvRiskLevel.HIGH, 1, env_name="prod-readonly",
    )
    assert strength is ConfirmationStrength.STRICT
    assert payload["challenge_value"] == "YES prod-readonly"
    assert "YES prod-readonly" in payload["challenge"]


def test_decide_confirmation_medium_is_soft() -> None:
    strength, payload = _decide_confirmation(EnvRiskLevel.MEDIUM, 1)
    assert strength is ConfirmationStrength.SOFT
    assert "message" in payload


def test_decide_confirmation_low_single_is_none() -> None:
    strength, payload = _decide_confirmation(EnvRiskLevel.LOW, 1)
    assert strength is ConfirmationStrength.NONE
    assert payload == {}


def test_decide_confirmation_low_multi_is_soft() -> None:
    strength, payload = _decide_confirmation(EnvRiskLevel.LOW, 5)
    assert strength is ConfirmationStrength.SOFT
    assert "5" in payload["message"]


# ────────────────── _estimate_duration_seconds ──────────────────


def test_estimate_duration_seconds_scales_with_count() -> None:
    assert _estimate_duration_seconds(1) > 0
    assert _estimate_duration_seconds(3) > _estimate_duration_seconds(1)


# ────────────────── build_execution_plan（mock DB）──────────────────


def _fake_case(cid: uuid.UUID, case_no: int = 1) -> SimpleNamespace:
    return SimpleNamespace(
        id=cid,
        case_no=case_no,
        title=f"用例 {case_no}",
        priority="medium",
        status="active",
        steps=[],
    )


def _fake_env(
    eid: uuid.UUID,
    project_id: uuid.UUID,
    name: str,
    base_url: str,
    *,
    risk_level: str | None = None,
) -> SimpleNamespace:
    payload = dict(
        id=eid, project_id=project_id, name=name, base_url=base_url,
    )
    if risk_level is not None:
        payload["risk_level"] = risk_level
    return SimpleNamespace(**payload)


@pytest.fixture(autouse=True)
def _isolate_plan_cache() -> None:
    asyncio.run(plan_builder._clear_plan_cache_for_test())


@pytest.mark.asyncio
async def test_build_execution_plan_low_risk_single_case_is_none() -> None:
    pid = uuid.uuid4()
    case_id = uuid.uuid4()
    env_id = uuid.uuid4()
    case = _fake_case(case_id)
    env = _fake_env(env_id, pid, "dev", "https://dev.foo.com")

    with (
        patch.object(plan_builder, "_load_cases", AsyncMock(return_value=[case])),
        patch.object(plan_builder, "_load_environment", AsyncMock(return_value=env)),
        patch.object(
            plan_builder,
            "resolve_test_data_preview",
            AsyncMock(return_value=plan_builder.TestDataPreview()),
            create=True,
        ),
        patch.object(
            plan_builder, "_load_llm_provider_summary",
            AsyncMock(return_value=SimpleNamespace()),
        ) as llm_mock,
    ):
        from app.modules.skills.builtin.ui_automation.schemas import LLMProviderSummary
        llm_mock.return_value = LLMProviderSummary(
            id=None, name="X", provider="x", model="m",
        )
        plan = await build_execution_plan(
            db=AsyncMock(),
            project_id=pid,
            user=None,
            case_ids=[case_id],
            environment_id=env_id,
        )

    assert plan.confirmation_strength is ConfirmationStrength.NONE
    assert plan.environment.risk_level is EnvRiskLevel.LOW
    assert plan.confirmation_payload == {}
    assert len(plan.cases) == 1


@pytest.mark.asyncio
async def test_build_execution_plan_medium_risk_is_soft() -> None:
    pid = uuid.uuid4()
    case_id = uuid.uuid4()
    env_id = uuid.uuid4()
    case = _fake_case(case_id)
    env = _fake_env(env_id, pid, "staging-1", "https://staging.foo.com")

    from app.modules.skills.builtin.ui_automation.schemas import LLMProviderSummary

    with (
        patch.object(plan_builder, "_load_cases", AsyncMock(return_value=[case])),
        patch.object(plan_builder, "_load_environment", AsyncMock(return_value=env)),
        patch.object(
            plan_builder,
            "resolve_test_data_preview",
            AsyncMock(return_value=plan_builder.TestDataPreview()),
            create=True,
        ),
        patch.object(
            plan_builder, "_load_llm_provider_summary",
            AsyncMock(return_value=LLMProviderSummary(
                id=None, name="X", provider="x", model="m",
            )),
        ),
    ):
        plan = await build_execution_plan(
            db=AsyncMock(),
            project_id=pid,
            user=None,
            case_ids=[case_id],
            environment_id=env_id,
        )

    assert plan.confirmation_strength is ConfirmationStrength.SOFT
    assert plan.environment.risk_level is EnvRiskLevel.MEDIUM


@pytest.mark.asyncio
async def test_build_execution_plan_high_risk_is_strict() -> None:
    pid = uuid.uuid4()
    case_id = uuid.uuid4()
    env_id = uuid.uuid4()
    case = _fake_case(case_id)
    env = _fake_env(env_id, pid, "PROD", "https://prod.foo.com")

    from app.modules.skills.builtin.ui_automation.schemas import LLMProviderSummary

    with (
        patch.object(plan_builder, "_load_cases", AsyncMock(return_value=[case])),
        patch.object(plan_builder, "_load_environment", AsyncMock(return_value=env)),
        patch.object(
            plan_builder,
            "resolve_test_data_preview",
            AsyncMock(return_value=plan_builder.TestDataPreview()),
            create=True,
        ),
        patch.object(
            plan_builder, "_load_llm_provider_summary",
            AsyncMock(return_value=LLMProviderSummary(
                id=None, name="X", provider="x", model="m",
            )),
        ),
    ):
        plan = await build_execution_plan(
            db=AsyncMock(),
            project_id=pid,
            user=None,
            case_ids=[case_id],
            environment_id=env_id,
        )

    assert plan.confirmation_strength is ConfirmationStrength.STRICT
    assert plan.environment.risk_level is EnvRiskLevel.HIGH
    assert plan.confirmation_payload["challenge_value"] == "YES PROD"


@pytest.mark.asyncio
async def test_build_execution_plan_uses_configured_environment_risk_level() -> None:
    """M2 后风险等级来自环境配置；旧的 name/url 启发式只作为兼容兜底。"""
    pid = uuid.uuid4()
    case_id = uuid.uuid4()
    env_id = uuid.uuid4()
    case = _fake_case(case_id)
    env = _fake_env(
        env_id, pid, "dev", "https://dev.foo.com", risk_level="high",
    )

    from app.modules.skills.builtin.ui_automation.schemas import LLMProviderSummary

    with (
        patch.object(plan_builder, "_load_cases", AsyncMock(return_value=[case])),
        patch.object(plan_builder, "_load_environment", AsyncMock(return_value=env)),
        patch.object(
            plan_builder,
            "resolve_test_data_preview",
            AsyncMock(return_value=plan_builder.TestDataPreview()),
            create=True,
        ),
        patch.object(
            plan_builder, "_load_llm_provider_summary",
            AsyncMock(return_value=LLMProviderSummary(
                id=None, name="X", provider="x", model="m",
            )),
        ),
    ):
        plan = await build_execution_plan(
            db=AsyncMock(),
            project_id=pid,
            user=None,
            case_ids=[case_id],
            environment_id=env_id,
        )

    assert plan.environment.risk_level is EnvRiskLevel.HIGH
    assert plan.environment.risk_reason == "configured risk_level=high"
    assert plan.confirmation_strength is ConfirmationStrength.STRICT


@pytest.mark.asyncio
async def test_build_execution_plan_uses_semantic_test_data_preview() -> None:
    pid = uuid.uuid4()
    case_id = uuid.uuid4()
    env_id = uuid.uuid4()
    case = _fake_case(case_id)
    env = _fake_env(env_id, pid, "dev", "https://dev.foo.com")

    from app.modules.skills.builtin.ui_automation.schemas import (
        LLMProviderSummary,
        TestDataPreview,
        TestDataPreviewItem,
    )

    preview = TestDataPreview(
        items=[
            TestDataPreviewItem(
                semantic="login_username",
                key="username",
                value_preview="alice",
                source="账号集（project）",
            ),
        ],
    )
    preview_mock = AsyncMock(return_value=preview)

    with (
        patch.object(plan_builder, "_load_cases", AsyncMock(return_value=[case])),
        patch.object(plan_builder, "_load_environment", AsyncMock(return_value=env)),
        patch.object(
            plan_builder,
            "resolve_test_data_preview",
            preview_mock,
            create=True,
        ),
        patch.object(
            plan_builder, "_load_llm_provider_summary",
            AsyncMock(return_value=LLMProviderSummary(
                id=None, name="X", provider="x", model="m",
            )),
        ),
    ):
        plan = await build_execution_plan(
            db=AsyncMock(),
            project_id=pid,
            user=SimpleNamespace(id=uuid.uuid4()),
            case_ids=[case_id],
            environment_id=env_id,
        )

    preview_mock.assert_awaited_once()
    assert plan.test_data_preview.items[0].semantic == "login_username"


@pytest.mark.asyncio
async def test_build_execution_plan_infers_runtime_data_flow() -> None:
    """Task 13.7：多用例计划中出现 ``{{runtime.xxx}}`` 时展示跨用例数据流。"""
    pid = uuid.uuid4()
    env_id = uuid.uuid4()
    create_id = uuid.uuid4()
    login_id = uuid.uuid4()
    create_case = _fake_case(create_id, case_no=1)
    create_case.title = "创建账号"
    create_case.steps = [SimpleNamespace(action="创建一个新用户", expected_result="成功")]
    login_case = _fake_case(login_id, case_no=2)
    login_case.title = "新账号登录"
    login_case.steps = [
        SimpleNamespace(action="使用 {{runtime.new_user_id}} 登录", expected_result="进入首页"),
    ]
    env = _fake_env(env_id, pid, "dev", "https://dev.foo.com")

    from app.modules.skills.builtin.ui_automation.schemas import LLMProviderSummary

    with (
        patch.object(
            plan_builder, "_load_cases",
            AsyncMock(return_value=[create_case, login_case]),
        ),
        patch.object(plan_builder, "_load_environment", AsyncMock(return_value=env)),
        patch.object(
            plan_builder,
            "resolve_test_data_preview",
            AsyncMock(return_value=plan_builder.TestDataPreview()),
            create=True,
        ),
        patch.object(
            plan_builder, "_load_llm_provider_summary",
            AsyncMock(return_value=LLMProviderSummary(
                id=None, name="X", provider="x", model="m",
            )),
        ),
    ):
        plan = await build_execution_plan(
            db=AsyncMock(),
            project_id=pid,
            user=None,
            case_ids=[create_id, login_id],
            environment_id=env_id,
        )

    assert plan.runtime_data_flow is not None
    assert len(plan.runtime_data_flow) == 1
    edge = plan.runtime_data_flow[0]
    assert edge.from_case_id == create_id
    assert edge.to_case_id == login_id
    assert edge.runtime_keys == ["new_user_id"]


@pytest.mark.asyncio
async def test_build_execution_plan_caches_by_plan_id() -> None:
    """plan_id 缓存：build 后立刻 get_cached_plan 应命中。"""
    pid = uuid.uuid4()
    case_id = uuid.uuid4()
    env_id = uuid.uuid4()

    from app.modules.skills.builtin.ui_automation.schemas import LLMProviderSummary

    with (
        patch.object(
            plan_builder, "_load_cases",
            AsyncMock(return_value=[_fake_case(case_id)]),
        ),
        patch.object(
            plan_builder, "_load_environment",
            AsyncMock(return_value=_fake_env(env_id, pid, "dev", "https://x.com")),
        ),
        patch.object(
            plan_builder,
            "resolve_test_data_preview",
            AsyncMock(return_value=plan_builder.TestDataPreview()),
            create=True,
        ),
        patch.object(
            plan_builder, "_load_llm_provider_summary",
            AsyncMock(return_value=LLMProviderSummary(
                id=None, name="X", provider="x", model="m",
            )),
        ),
    ):
        plan = await build_execution_plan(
            db=AsyncMock(),
            project_id=pid,
            user=None,
            case_ids=[case_id],
            environment_id=env_id,
        )

    cached = await get_cached_plan(plan.plan_id)
    assert cached is not None
    assert cached.plan.plan_id == plan.plan_id
    assert cached.case_ids == [case_id]
    assert cached.environment_id == env_id
    assert cached.project_id == pid

    miss = await get_cached_plan(uuid.uuid4())
    assert miss is None


@pytest.mark.asyncio
async def test_build_adhoc_execution_plan_returns_editable_adhoc_card() -> None:
    """Task 13.6：search 0 命中后，用户自然语言应转为 adhoc_plan 确认卡。

    这里不测 LLM 文案质量，只锁定后端协议：
    - ``kind='adhoc_plan'`` + ``adhoc_case.steps`` 可给前端编辑
    - 不绑定正式 testcase（``case_ids=[]``），cache 里记录 source=adhoc
    - 草稿置信度低时强制 STRICT，防止一键跑未检查步骤
    """
    pid = uuid.uuid4()
    env_id = uuid.uuid4()
    env = _fake_env(env_id, pid, "dev", "https://dev.foo.com", risk_level="low")

    from app.modules.skills.builtin.ui_automation.schemas import LLMProviderSummary

    preview_mock = AsyncMock(return_value=plan_builder.TestDataPreview())
    with (
        patch.object(plan_builder, "_load_environment", AsyncMock(return_value=env)),
        patch.object(plan_builder, "resolve_test_data_preview", preview_mock, create=True),
        patch.object(
            plan_builder, "_load_llm_provider_summary",
            AsyncMock(return_value=LLMProviderSummary(
                id=None, name="X", provider="x", model="m",
            )),
        ),
    ):
        plan = await build_adhoc_execution_plan(
            db=AsyncMock(),
            project_id=pid,
            user=SimpleNamespace(id=uuid.uuid4()),
            description="测一下购物车清空功能",
            environment_id=env_id,
        )

    assert plan.kind == "adhoc_plan"
    assert plan.cases == []
    assert plan.adhoc_case is not None
    assert plan.adhoc_case.steps
    assert plan.adhoc_case.draft_confidence < 0.6
    assert plan.confirmation_strength is ConfirmationStrength.STRICT
    assert plan.confirmation_payload["challenge_value"] == "YES DRAFT"
    cached = await get_cached_plan(plan.plan_id)
    assert cached is not None
    assert cached.case_ids == []
    assert cached.source == "adhoc"
    assert cached.adhoc_steps is not None
    assert cached.adhoc_steps["steps"][0]["action"]
    preview_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_build_execution_plan_rejects_empty_case_ids() -> None:
    with pytest.raises(ValueError, match="case_ids must not be empty"):
        await build_execution_plan(
            db=AsyncMock(),
            project_id=uuid.uuid4(),
            user=None,
            case_ids=[],
            environment_id=uuid.uuid4(),
        )


@pytest.mark.asyncio
async def test_build_execution_plan_rejects_missing_environment() -> None:
    pid = uuid.uuid4()
    case_id = uuid.uuid4()
    env_id = uuid.uuid4()

    with (
        patch.object(
            plan_builder, "_load_cases",
            AsyncMock(return_value=[_fake_case(case_id)]),
        ),
        patch.object(plan_builder, "_load_environment", AsyncMock(return_value=None)),
    ):
        with pytest.raises(ValueError, match="environment .* not found"):
            await build_execution_plan(
                db=AsyncMock(),
                project_id=pid,
                user=None,
                case_ids=[case_id],
                environment_id=env_id,
            )


@pytest.mark.asyncio
async def test_build_execution_plan_rejects_cross_project_environment() -> None:
    pid = uuid.uuid4()
    other = uuid.uuid4()
    case_id = uuid.uuid4()
    env_id = uuid.uuid4()
    env = _fake_env(env_id, other, "dev", "https://x.com")

    with (
        patch.object(
            plan_builder, "_load_cases",
            AsyncMock(return_value=[_fake_case(case_id)]),
        ),
        patch.object(plan_builder, "_load_environment", AsyncMock(return_value=env)),
    ):
        with pytest.raises(ValueError, match="does not belong to project"):
            await build_execution_plan(
                db=AsyncMock(),
                project_id=pid,
                user=None,
                case_ids=[case_id],
                environment_id=env_id,
            )
