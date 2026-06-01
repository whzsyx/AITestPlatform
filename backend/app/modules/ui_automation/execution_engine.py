"""ExecutionEngine — UI 自动化执行流程编排（Task 9.5）。

把前面 Task 7 / 8 / 9.1–9.4 的所有部件串成一次完整的 ``execution.run``：

1. 加载环境 / LLM 配置 / 用例（含 steps）
2. 构建 ``TestDataResolver``、注册 ``platform_*`` 物料工具、跑 preflight 缺料告警
3. 落 ``ui_executions`` 行 → 切到 ``running`` 状态
4. 起 ``BrowserBundle``（Task 7.3）+ 注册 MCP browser_* 工具（Task 7.2）
5. 跑前置步骤（Task 8.2）
6. 循环用例：
    - ``case_resolver = resolver.with_case_overrides(testcase_id)``
    - 重新注册 platform 工具到 case_resolver（保证 ``finalize_case`` 拿到本用
      例的 synth / failure）
    - 循环 step：``StepRunner.run_one`` → ``AssertionJudge.judge`` → ``flush_step``
    - 用户主动停止 / token 超预算 → 提早结束（``stopped`` / ``aborted_budget``）
    - ``data_failure`` 仅终止当前用例，**继续后续用例**（核心需求）
    - ``case_resolver.finalize_case()`` → ``flush_case``
7. ``flush_execution`` 收口；finally 关 bundle、卸 platform tools、mark stream done

设计关键：
- 所有外部依赖（DB query / Bundle.open / StepRunner / Judge / persistence /
  stream hub publish）都通过 ``EngineDeps`` 注入，方便单测全 mock，不用启
  Playwright / Postgres
- 失败语义清晰：
    - ``aborted_budget``：``BudgetExceededError`` → 整个 execution 终止
    - ``data_failure``：仅本 case 终止，``data_confidence=data_failure``
    - ``failed``：execution 入口异常或 strict_data_mode 拒绝执行
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Protocol

from app.core.crypto import decrypt
from app.modules.ui_automation import persistence as default_persistence
from app.modules.ui_automation.action_plan import UIActionKind, UIActionStep
from app.modules.ui_automation.assertion_judge import (
    AssertionJudge,
    AssertionLLMConfig,
    AssertionVerdict,
)
from app.modules.ui_automation.data_platform_tools import (
    register_data_tools,
    unregister_data_tools,
)
from app.modules.ui_automation.data_synthesizer import DataSynthesizer
from app.modules.ui_automation.debug_control import (
    DEBUG_CONTROL_HUB,
    DEFAULT_DEBUG_TIMEOUT_SECONDS,
)
from app.modules.ui_automation.deterministic_runner import (
    DeterministicRunner,
    DeterministicRunResult,
)
from app.modules.ui_automation.execution_metrics import make_execution_meta_tool_call
from app.modules.ui_automation.failure_triage import triage_step_failure
from app.modules.ui_automation.locator_memory import (
    StepLocatorOutcome,
    apply_step_outcomes,
    intersect_recent_locators,
    serialize_locator_signature,
)
from app.modules.ui_automation.plan_audit import build_compiled_action_plan_snapshots
from app.modules.ui_automation.plan_compiler import (
    compile_action_plan,
    detect_public_anti_bot_target,
)
from app.modules.ui_automation.preflight import (
    MissingDataAlert,
    extract_template_keys,
    preflight_data_check,
)
from app.modules.ui_automation.requirement_context import load_requirement_contexts
from app.modules.ui_automation.schemas import HYBRID_EXECUTION_STRATEGIES
from app.modules.ui_automation.security import (
    BudgetExceededError,
    SecurityError,
    TokenBudget,
)
from app.modules.ui_automation.snapshot_clipper import clip_to_char_limit
from app.modules.ui_automation.step_runner import (
    StepRunner,
    StepRunResult,
    ToolCallRecord,
    decide_self_heal_action,
)
from app.modules.ui_automation.stream_hub import (
    EXECUTION_STREAM_HUB,
    _ExecutionStream,
)
from app.modules.ui_automation.test_data_resolver import TestDataResolver

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.modules.llm.models import LLMConfig
    from app.modules.testcases.models import Testcase
    from app.modules.ui_automation.models import TestEnvironment


logger = logging.getLogger(__name__)

_ASSERTION_EVIDENCE_TOOLS = frozenset({
    "browser_evaluate",
    "browser_console_messages",
    "browser_network_requests",
    "deterministic_runner",
})
_ASSERTION_TOOL_RESULT_MAX_CHARS = 6_000
_ASSERTION_CONTEXT_MAX_CHARS = 24_000
DEFAULT_EXECUTION_STRATEGY = "hybrid_lightweight"
DIRECT_DEFAULT_TOKEN_BUDGET = 5_000_000
DIRECT_DEFAULT_ALLOWED_HOSTS: tuple[str, ...] = ("*",)
_DETERMINISTIC_ASSERTION_KIND_VALUES = frozenset(
    {
        UIActionKind.ASSERT_TEXT.value,
        UIActionKind.ASSERT_URL.value,
        UIActionKind.ASSERT_PAGE_LOADED.value,
        UIActionKind.ASSERT_TABLE_COLUMNS.value,
        UIActionKind.ASSERT_TABLE_ROWS.value,
        UIActionKind.ASSERT_FORM_VALUES.value,
    }
)
_EXTERNAL_VERIFICATION_TERMS = (
    "安全验证",
    "验证码",
    "滑块验证",
    "请完成下方验证",
    "人机验证",
    "verify you are human",
    "captcha",
    "wappass.baidu.com/static/captcha",
)


async def _release_engine_db_transaction(db: Any) -> None:
    """结束当前 ORM 事务，避免长耗时步骤把连接卡在 *idle in transaction*。

    Engine 在 ``async with db_session_factory() as db`` 内包揽整批 UI 执行。
    SQLAlchemy 2 ``autobegin`` 会在首次 ``execute`` 后自动打开事务；随后若只有
    浏览器 / LLM（中间不再打 SQL），连接会一直停在「事务内空闲」——云数据库常
    配 ``idle_in_transaction_session_timeout``，到点直接掐连接；下一次再查
    ``testcases``（``TestDataResolver.with_case_overrides``）就会在已关闭连接
    上做 ``fetch()``，抛出 asyncpg::

        InterfaceError: cannot call PreparedStatement.fetch(): the underlying
        connection is closed

    执行落盘走的 ``persistence.*`` 都是独立 ``async_session_factory``，不依赖本条
    session；本条 session 主要为 resolver / ``platform_*`` 读物料与合成推断服务，
    ``commit()`` 可把读事务收口，不改变业务语义（无跨连接必须原子化的写）。
    """
    try:
        await db.commit()
    except Exception:  # noqa: BLE001
        logger.exception("engine session commit failed; rolling back")
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            logger.exception("engine session rollback after failed commit")


# ─── 输入参数 ────────────────────────────────────────────────────────


@dataclass
class ExecutionInputs:
    """``ExecutionEngine.run`` 的全部入参（来自 API / chat / SDK）。

    在 Engine 内不会再读 DB 拿这些字段，全部由调用方填好。
    """

    execution_id: uuid.UUID
    project_id: uuid.UUID
    environment_id: uuid.UUID | None
    testcase_ids: list[uuid.UUID]
    llm_config_id: uuid.UUID | None
    triggered_by: uuid.UUID | None
    manual_overrides: dict[str, Any] = field(default_factory=dict)
    loaded_set_ids: list[uuid.UUID] = field(default_factory=list)
    mode: str = "normal"
    execution_strategy: str = DEFAULT_EXECUTION_STRATEGY
    chat_message_id: uuid.UUID | None = None
    token_budget_override: int | None = None
    """覆盖 environment.token_budget；为 None 时用环境默认。"""
    strict_data_mode: bool = False
    """缺料严格模式：preflight 发现缺 key 直接拒绝执行。"""
    module_entry_overrides: dict[uuid.UUID, str] = field(default_factory=dict)
    """按 module_id 临时覆盖 module.entry_path（仅本次执行有效）。

    取值规则（在引擎里查找 effective entry_path 时按下述优先级）：
        ``module_entry_overrides[module_id]`` → ``module.entry_path`` (DB) → None

    None 表示"该模块没配入口"——AI 仍能跑，但 prompt 里不会出现 target_url
    那一段，行为退回到现状（依赖用例 step 自然语言）。
    """
    source: str = "catalog"
    """catalog/chat/adhoc。adhoc 时跳过 testcase 加载，直接执行 adhoc_steps。"""
    adhoc_steps: dict[str, Any] | None = None
    """用户确认后的即席步骤草稿；仅 source=adhoc 时使用。"""


@dataclass
class ExecutionOutcome:
    """run() 收尾后的简短摘要。SSE / API 响应可用。"""

    execution_id: uuid.UUID
    status: str
    total: int
    passed: int
    failed: int
    skipped: int
    duration_ms: int
    tokens_total: int
    error_message: str | None = None
    # 产物路径（Engine 在 bundle 关闭后填入；outer finally 会带入 flush_execution）
    video_path: str | None = None
    trace_path: str | None = None


@dataclass
class _AdhocStep:
    step_number: int
    action: str
    expected_result: str | None = None


@dataclass
class _AdhocCase:
    id: None
    title: str
    steps: list[_AdhocStep]
    target_url: str | None = None
    required_test_data: list[dict[str, Any]] = field(default_factory=list)
    default_data_set_ids: list[str] = field(default_factory=list)
    case_no: int | None = None
    module_id: uuid.UUID | None = None


# ─── Dependency injection ────────────────────────────────────────────


class _BundleLike(Protocol):
    """Engine 用到的 BrowserBundle 最小契约（简化测试 mock）。"""

    execution_id: uuid.UUID
    mcp_unavailable: bool

    async def register_mcp_tools_for_agent(self) -> list[dict[str, Any]]: ...
    async def close(self) -> None: ...


@dataclass
class EngineDeps:
    """所有"会读外部世界"的依赖都在这里，方便单测整体替换。

    生产默认实现都在 module 级别，测试可以替换其中任何一个。
    """

    db_session_factory: Callable[[], "AsyncSession"] = field(
        default=lambda: _default_db_session_factory()
    )
    """每次调一次得到一个 ``AsyncSession``（已 begin / not yet committed）。
    Engine 用它 ``await session.execute(...)`` 拿环境 / 用例 / llm 配置。
    """

    open_browser_bundle: Callable[..., Awaitable[_BundleLike]] | None = None
    """``async def(env, execution_id) -> BrowserBundle``。None = lazy import。"""

    step_runner_factory: Callable[..., StepRunner] | None = None
    """``(env, llm, budget, execution_id) -> StepRunner``。None = 直接 ``StepRunner(...)``。"""

    assertion_judge_factory: Callable[[], AssertionJudge] | None = None

    persistence: Any = default_persistence
    """暴露 ``init_execution_record / mark_execution_running / create_case_result /
    flush_step / flush_case / flush_execution / is_execution_stopped``。"""

    stream_hub: Any = EXECUTION_STREAM_HUB

    run_preconditions: (
        Callable[..., Awaitable[list[dict[str, Any]]]] | None
    ) = None
    """``async def(bundle, env, llm_config_or_none) -> list[result_dict]``。
    None 时跳过前置步骤（典型：本环境没配前置模板）。"""

    debug_controller: Any = DEBUG_CONTROL_HUB
    """Task 9.7 — debug 模式 pause/continue 信号 hub。注入便于单测。"""

    debug_timeout_seconds: float = DEFAULT_DEBUG_TIMEOUT_SECONDS
    """每个 step 之间最多 pause 多久；超过自动 stop。测试时可以 patch 成 0.05 秒。"""


def _default_db_session_factory() -> "AsyncSession":
    """运行时再 import 避免 alembic 拓扑被无谓加载。"""
    from app.database import async_session_factory

    return async_session_factory()


async def _default_open_bundle(env: Any, execution_id: uuid.UUID) -> _BundleLike:
    from app.config import settings
    from app.modules.ui_automation.browser_bundle import BrowserBundle, BundleOptions

    artifacts_root = os.path.abspath(settings.UI_ARTIFACTS_DIR)
    video_dir = os.path.join(artifacts_root, str(execution_id), "video")
    os.makedirs(video_dir, exist_ok=True)

    # 出口代理（VPN 场景）：优先取 environment 自身配置，回落到全局
    # ``settings.UI_BROWSER_PROXY``。这样常态部署可以全局走一个统一代理，单环境
    # 也能定制（比如跨多 VPN 多代理的高级场景）。
    env_proxy = getattr(env, "browser_proxy", None) or None
    proxy_server = env_proxy or settings.UI_BROWSER_PROXY or None
    proxy_bypass = (
        getattr(env, "browser_proxy_bypass", None)
        or settings.UI_BROWSER_PROXY_BYPASS
        or None
    )

    return await BrowserBundle.open(  # type: ignore[return-value]
        env,
        execution_id,
        options=BundleOptions(
            headless=getattr(env, "headless", True),
            record_video_dir=video_dir,
            browser_proxy=proxy_server,
            browser_proxy_bypass=proxy_bypass,
        ),
    )


# playwright-mcp 0.x 的 snapshot result 通常包含一段::
#     ### Page
#     - Page URL: https://x.com/foo
#     - Page Title: Foo Dashboard
#     ### Snapshot
#     ...
# 直接 regex 抽出 URL / title 比再发一次 MCP 调用更省 token、更稳（同步内存
# 操作，不会因 MCP 抖动失败）。
_PAGE_URL_RE = re.compile(r"Page URL:\s*(\S+)", re.IGNORECASE)
_PAGE_TITLE_RE = re.compile(r"Page Title:\s*([^\r\n]+)", re.IGNORECASE)


def _safe_extract_page_url(snapshot_text: str | None) -> str | None:
    """从 a11y snapshot 文本里抽 ``Page URL: ...``；找不到返回 None。"""
    if not snapshot_text:
        return None
    m = _PAGE_URL_RE.search(snapshot_text)
    return m.group(1).strip() if m else None


def _safe_extract_page_title(snapshot_text: str | None) -> str | None:
    """从 a11y snapshot 文本里抽 ``Page Title: ...``；找不到返回 None。"""
    if not snapshot_text:
        return None
    m = _PAGE_TITLE_RE.search(snapshot_text)
    if m:
        return m.group(1).strip() or None
    return None


async def _safe_get_current_url(
    bundle: Any, *, fallback_snapshot: str | None = None,
) -> str | None:
    """尽力取浏览器当前页面 URL；任何失败返回 None。

    解析顺序（优先级降序）：
    1. 从 ``fallback_snapshot`` regex 抽 ``Page URL:`` —— 便宜 + 稳
    2. 调 ``bundle.get_current_url_via_mcp()`` —— 当 snapshot 里没带时兜底

    用途：ExecutionEngine 在两步骤之间刷新"当前 URL"，让下一步的 prompt
    准确反映浏览器状态。失败不阻塞用例推进。
    """
    from_snap = _safe_extract_page_url(fallback_snapshot)
    if from_snap:
        return from_snap
    if bundle is None:
        return None
    try:
        get_url = getattr(bundle, "get_current_url_via_mcp", None)
        if get_url is None:
            return None
        result = await get_url()
        if isinstance(result, str) and result.strip():
            return result.strip()
    except Exception as exc:  # noqa: BLE001
        logger.info("ExecutionEngine refresh current_url failed: %s", exc)
    return None


async def _capture_step_screenshot_safe(
    *,
    bundle: Any,
    execution_id: uuid.UUID,
    case_result_id: uuid.UUID,
    step_number: int,
) -> str | None:
    """尽力抓一张当前 step 完成时的浏览器截图；任何失败都返回 None，不阻塞
    step flush。

    优先级：
    1. **MCP** ``browser_take_screenshot`` —— 最可靠，因为 MCP 一定知道哪个
       tab 是 active，且截图作用于 MCP 操作的 page（与 Python SDK 的 context
       不一定共享）。
    2. **Playwright SDK** ``page.screenshot()`` —— fallback。仅当 MCP 不可用
       或返回 None 时尝试。
    """
    try:
        from app.config import settings

        ext = (settings.UI_STEP_SCREENSHOT_TYPE or "png").lower()
        if ext not in ("png", "jpeg", "jpg"):
            ext = "png"
        image_type = "jpeg" if ext in ("jpeg", "jpg") else "png"
        steps_dir = os.path.join(
            os.path.abspath(settings.UI_ARTIFACTS_DIR),
            str(execution_id),
            "steps",
        )
        os.makedirs(steps_dir, exist_ok=True)
        dest = os.path.join(
            steps_dir,
            f"case_{case_result_id}_step_{step_number:03d}.{ext}",
        )
    except Exception:  # noqa: BLE001
        logger.exception("capture_step_screenshot_safe path setup failed")
        return None

    via_mcp = getattr(bundle, "capture_step_screenshot_via_mcp", None)
    if callable(via_mcp):
        try:
            path = await via_mcp(dest, image_type=image_type)
            if path:
                return path
        except Exception:  # noqa: BLE001
            logger.exception("capture_step_screenshot_via_mcp raised")

    via_sdk = getattr(bundle, "capture_step_screenshot", None)
    if callable(via_sdk):
        try:
            return await via_sdk(dest, image_type=image_type, full_page=False)
        except Exception:  # noqa: BLE001
            logger.exception("capture_step_screenshot (SDK) raised")
    return None


# ─── ExecutionEngine ─────────────────────────────────────────────────


class ExecutionEngine:
    """单次执行批次的编排器。一次 ``run()`` 调用 = 一次执行。"""

    __test__ = False

    def __init__(self, *, deps: EngineDeps | None = None) -> None:
        self.deps = deps or EngineDeps()

    async def run(self, inputs: ExecutionInputs) -> ExecutionOutcome:
        started_at = time.monotonic()
        stream = await self.deps.stream_hub.register(inputs.execution_id)

        # Task 9.7：debug 模式下提前 register 信号槽，让 router 在 step_paused
        # 第一次出现之前就能接收 ``POST /continue``——否则极快的第一步会出现
        # "用户点 continue 时 signal 还没建" 的竞态。
        debug_registered = False
        if inputs.mode == "debug":
            try:
                await self.deps.debug_controller.register(inputs.execution_id)
                debug_registered = True
            except Exception:  # noqa: BLE001
                logger.exception("debug_controller.register failed")

        total_cases = (
            1 if inputs.source == "adhoc" and inputs.adhoc_steps else len(inputs.testcase_ids)
        )
        outcome = ExecutionOutcome(
            execution_id=inputs.execution_id,
            status="failed",
            total=total_cases,
            passed=0,
            failed=0,
            skipped=0,
            duration_ms=0,
            tokens_total=0,
        )

        try:
            await self._run_inner(inputs, stream, outcome)
        except BudgetExceededError as exc:
            outcome.status = "aborted_budget"
            outcome.error_message = str(exc)
            await stream.append("budget_exceeded", {"message": str(exc)})
        except Exception as exc:  # noqa: BLE001
            logger.exception("ExecutionEngine.run crashed: %s", inputs.execution_id)
            outcome.status = "failed"
            outcome.error_message = f"{type(exc).__name__}: {exc}"
            await stream.append(
                "execution_error",
                {"error": outcome.error_message},
            )
        finally:
            outcome.duration_ms = int((time.monotonic() - started_at) * 1000)
            try:
                await self.deps.persistence.flush_execution(
                    execution_id=inputs.execution_id,
                    status=outcome.status,
                    passed_cases=outcome.passed,
                    failed_cases=outcome.failed,
                    skipped_cases=outcome.skipped,
                    duration_ms=outcome.duration_ms,
                    tokens_total=outcome.tokens_total,
                    error_message=outcome.error_message,
                    video_path=outcome.video_path,
                    trace_path=outcome.trace_path,
                )
            except Exception as flush_exc:  # noqa: BLE001
                logger.exception("flush_execution failed: %s", flush_exc)

            await stream.append(
                "execution_complete",
                {
                    "execution_id": str(inputs.execution_id),
                    "status": outcome.status,
                    "passed": outcome.passed,
                    "failed": outcome.failed,
                    "skipped": outcome.skipped,
                    "duration_ms": outcome.duration_ms,
                    "tokens_total": outcome.tokens_total,
                    "error_message": outcome.error_message,
                },
            )
            await stream.mark_done()

            # Task 9.7：必清——否则 hub 会越积越多 _DebugSignal 实例
            if debug_registered:
                try:
                    await self.deps.debug_controller.unregister(inputs.execution_id)
                except Exception:  # noqa: BLE001
                    logger.exception("debug_controller.unregister failed")

        return outcome

    # ── 主流程 ───────────────────────────────────────────────────

    async def _run_inner(
        self,
        inputs: ExecutionInputs,
        stream: _ExecutionStream,
        outcome: ExecutionOutcome,
    ) -> None:
        # 1. 加载环境 / LLM 配置 / 用例
        async with self.deps.db_session_factory() as db:
            environment = await _load_environment(db, inputs.environment_id)
            llm_config_orm = await _load_llm_config(db, inputs.llm_config_id)
            if inputs.source == "adhoc":
                testcases = _build_adhoc_cases(inputs.adhoc_steps)
            else:
                testcases = await _load_testcases(db, inputs.testcase_ids)
            requirement_contexts = (
                {}
                if inputs.source == "adhoc"
                else await load_requirement_contexts(
                    db,
                    project_id=inputs.project_id,
                    testcases=testcases,
                )
            )
            # 预加载本批次所有用例的 module.entry_path —— 后续 _run_one_case
            # 再去拼 target_url 时 O(1) 查表，不用每条用例都打一次 DB
            #
            # 用 ``getattr`` 兜底是因为单元测试里的轻量 ``_Testcase`` stub 不带
            # 这个字段；生产 ORM 一定有（``Testcase.module_id`` 是 mapped_column）。
            module_entry_map = await _load_module_entry_paths(
                db,
                [
                    getattr(tc, "module_id", None)
                    for tc in testcases
                    if getattr(tc, "module_id", None) is not None
                ],
            )
            if inputs.environment_id is None:
                _configure_direct_environment_hosts(
                    environment,
                    testcases=testcases,
                    module_entry_map=module_entry_map,
                    module_entry_overrides=inputs.module_entry_overrides,
                )
            compiled_action_plans = (
                []
                if inputs.source == "adhoc"
                else build_compiled_action_plan_snapshots(
                    testcases,
                    module_entry_overrides=inputs.module_entry_overrides,
                )
            )

            # 2. 构建 TestDataResolver
            resolver = await TestDataResolver.build(
                db=db,
                execution=_ResolverExecutionStub(
                    id=inputs.execution_id,
                    project_id=inputs.project_id,
                    environment_id=inputs.environment_id,
                    triggered_by=inputs.triggered_by,
                ),
                manual_overrides=inputs.manual_overrides,
                loaded_set_ids=inputs.loaded_set_ids,
            )
            # build with_case_overrides 需要的是同一个 db session；后续在该
            # session 上做的查询都已在 selectin 加载，调用方关闭 session 后
            # 不能再用 resolver.with_case_overrides —— 因此本函数把整段
            # "用例循环"也圈在 db scope 内

            # 收集本次「显式配置」的物料集 id（验收反馈：物料快照仅展示这些
            # 集合的明细，过滤掉个人/项目 scope 自动合并的杂项）：
            #   loaded_set_ids（弹窗勾选）
            # + env.default_data_set_ids（环境默认）
            # + testcase.default_data_set_ids（用例默认）
            configured_set_ids = await _collect_configured_set_ids(
                db=db,
                project_id=inputs.project_id,
                environment_id=inputs.environment_id,
                loaded_set_ids=inputs.loaded_set_ids,
                testcase_ids=inputs.testcase_ids,
            )
            data_snapshot = resolver.serialize_for_audit(
                configured_set_ids=configured_set_ids,
            )

            # Phase 15.5: 把缺料 preflight 提前到 init 之前算, 这样 alerts
            # 可以直接落到 config_snapshot.preflight_warnings, 历史详情页能
            # 用红色徽章把"哪些 key 没物料供给"显示出来, 而不只是 SSE 转瞬即逝.
            preflight_alerts = await preflight_data_check(testcases, resolver)

            await self.deps.persistence.init_execution_record(
                execution_id=inputs.execution_id,
                project_id=inputs.project_id,
                environment_id=inputs.environment_id,
                triggered_by=inputs.triggered_by,
                chat_message_id=inputs.chat_message_id,
                mode=inputs.mode,
                total_cases=len(testcases),
                config_snapshot=_build_config_snapshot(
                    inputs,
                    configured_set_ids=configured_set_ids,
                    compiled_action_plans=compiled_action_plans,
                    preflight_alerts=preflight_alerts,
                ),
                source=inputs.source,
                adhoc_steps=inputs.adhoc_steps if inputs.source == "adhoc" else None,
            )
            await self.deps.persistence.mark_execution_running(
                execution_id=inputs.execution_id,
                test_data_snapshot=data_snapshot,
            )
            await stream.append(
                "execution_started",
                {
                    "execution_id": str(inputs.execution_id),
                    "total_cases": len(testcases),
                    "mode": inputs.mode,
                },
            )

            if preflight_alerts:
                await stream.append(
                    "missing_data_warning",
                    {
                        "alerts": [a.model_dump() for a in preflight_alerts],
                        "strict": inputs.strict_data_mode,
                    },
                )
                if inputs.strict_data_mode:
                    outcome.status = "failed"
                    outcome.error_message = (
                        f"严格物料模式：发现 {len(preflight_alerts)} 个缺料 key，拒绝执行 "
                        f"(missing keys: {', '.join(a.key for a in preflight_alerts[:5])}"
                        f"{'...' if len(preflight_alerts) > 5 else ''})"
                    )
                    await _release_engine_db_transaction(db)
                    return

            # Phase 15.8: public anti-bot host preflight 拒绝.
            # 已知 demo 用例打 baidu / google 反爬页面 16 次执行 100% 失败,
            # 不该把这些用例放进默认回归集. 这里在执行前直接拒绝, 错误信息提示
            # 用户改去内网受控环境 (UI_EARLY_TERMINATE_ON_CAPTCHA 关掉时仍会
            # 走到这里 -- 关 captcha early terminate 是面向"已经在跑了出现验证码"
            # 场景, 跟 "压根就不该跑这个公网 host" 是两码事).
            anti_bot_hits: list[tuple[str, str]] = []  # (testcase_id, keyword)
            for tc in testcases:
                module_id = getattr(tc, "module_id", None)
                module_entry_url = (
                    module_entry_map.get(module_id) if module_id else None
                )
                hit = detect_public_anti_bot_target(
                    tc, module_entry_url=module_entry_url,
                )
                if hit:
                    anti_bot_hits.append((str(getattr(tc, "id", "?")), hit))

            if anti_bot_hits:
                await stream.append(
                    "public_anti_bot_blocked",
                    {
                        "hits": [
                            {"testcase_id": tc_id, "keyword": kw}
                            for tc_id, kw in anti_bot_hits
                        ],
                    },
                )
                outcome.status = "failed"
                outcome.error_message = (
                    "用例命中公网反爬 host (例如 "
                    f"{anti_bot_hits[0][1]}), unsupported_reason=public_anti_bot_target. "
                    "请改用内网受控环境或登录态测试站点, 不要在默认回归集里跑公开搜索引擎."
                )
                await _release_engine_db_transaction(db)
                return

            if not testcases:
                outcome.status = "completed"
                await _release_engine_db_transaction(db)
                return

            # 浏览器 / 前置 / MCP / 逐步 LLM 可能极长：先收口本条 session 的事务，
            # 否则会长时间 idle-in-transaction（见 ``_release_engine_db_transaction``）。
            await _release_engine_db_transaction(db)

            # 4. 起浏览器 + 注册 MCP 工具
            bundle = await _open_bundle(self.deps, environment, inputs.execution_id)
            try:
                if getattr(bundle, "headless_downgraded", False):
                    await stream.append(
                        "headless_downgraded",
                        {
                            "execution_id": str(inputs.execution_id),
                            "message": (
                                "当前部署运行在容器中且未挂载显示器（DISPLAY），"
                                "已自动忽略环境的『有头模式』设置改用无头模式。"
                                "如需有头浏览器，请在带 X 服务器（或 Xvfb）的宿主机直接部署后端。"
                            ),
                        },
                    )
                await stream.append(
                    "bundle_ready",
                    {
                        "execution_id": str(inputs.execution_id),
                        "mcp_unavailable": bundle.mcp_unavailable,
                    },
                )
                mcp_specs: list[dict[str, Any]] = []
                if not bundle.mcp_unavailable:
                    try:
                        mcp_specs = await bundle.register_mcp_tools_for_agent()
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("register_mcp_tools_for_agent failed: %s", exc)
                        mcp_specs = []

                # 5. 跑前置步骤（默认走 ``_default_run_preconditions``，环境
                #    没配前置步骤时返回 [] 自然 no-op；测试可通过
                #    ``EngineDeps.run_preconditions=...`` 覆盖）。
                run_preconds = (
                    self.deps.run_preconditions or _default_run_preconditions
                )
                try:
                    pre_results = await run_preconds(
                        bundle, environment, llm_config_orm,
                    )
                    if pre_results:
                        await stream.append(
                            "preconditions_complete",
                            {"results": pre_results},
                        )
                        # 若任一前置步骤明确失败 → 后续用例不再继续，避免在
                        # 没有登录态 / 关键 cookie 的状态下大批量失败。
                        first_failed = next(
                            (r for r in pre_results if not r.get("success", True)),
                            None,
                        )
                        if first_failed is not None:
                            outcome.status = "failed"
                            outcome.error_message = (
                                f"前置步骤未通过：{first_failed.get('name')!r} → "
                                f"{first_failed.get('error') or first_failed.get('error_kind')}"
                            )
                            await stream.append(
                                "precondition_error",
                                {
                                    "error": outcome.error_message,
                                    "error_kind": first_failed.get("error_kind"),
                                },
                            )
                            return
                except Exception as exc:  # noqa: BLE001
                    logger.exception("run_preconditions failed")
                    await stream.append(
                        "precondition_error",
                        {"error": f"{type(exc).__name__}: {exc}"},
                    )

                # 6. 准备运行时
                budget = TokenBudget(
                    limit=inputs.token_budget_override
                    or getattr(environment, "token_budget", 50_000)
                )
                llm_config_proto = _build_llm_proto(llm_config_orm)
                judge_llm_config = (
                    AssertionLLMConfig(
                        provider=llm_config_proto.provider,
                        model=llm_config_proto.model,
                        api_key=llm_config_proto.api_key,
                        base_url=llm_config_proto.base_url,
                        temperature=0.0,
                        max_tokens=512,
                    )
                    if llm_config_proto.api_key or llm_config_proto.base_url
                    else None
                )
                runner_factory = self.deps.step_runner_factory or (
                    lambda env, llm, budget_, execution_id: StepRunner(
                        llm=llm,
                        environment=env,
                        budget=budget_,
                        execution_id=execution_id,
                    )
                )
                step_runner = runner_factory(
                    environment, llm_config_proto, budget, inputs.execution_id,
                )
                judge_factory = self.deps.assertion_judge_factory or AssertionJudge
                judge = judge_factory()

                # 7. 用例循环
                for sort_idx, tc in enumerate(testcases):
                    # 检查停止信号
                    if await _check_stopped(self.deps, inputs.execution_id):
                        outcome.status = "stopped"
                        outcome.error_message = "用户主动停止"
                        await stream.append(
                            "execution_stopped",
                            {"reason": "user_stop"},
                        )
                        # 剩余用例不执行 → 计入 skipped
                        outcome.skipped += len(testcases) - sort_idx
                        return

                    if budget.over_limit:
                        outcome.status = "aborted_budget"
                        outcome.error_message = (
                            f"已超过 token 预算 {budget.limit}（消耗 {budget.consumed}）"
                        )
                        await stream.append(
                            "budget_exceeded",
                            {"message": outcome.error_message},
                        )
                        outcome.skipped += len(testcases) - sort_idx
                        return

                    case_aborted = await self._run_one_case(
                        db=db,
                        bundle=bundle,
                        tc=tc,
                        sort_idx=sort_idx,
                        inputs=inputs,
                        environment=environment,
                        module_entry_map=module_entry_map,
                        requirement_contexts=requirement_contexts,
                        resolver=resolver,
                        mcp_specs=mcp_specs,
                        step_runner=step_runner,
                        judge=judge,
                        judge_llm_config=judge_llm_config,
                        budget=budget,
                        stream=stream,
                        outcome=outcome,
                    )
                    if case_aborted == "budget":
                        outcome.status = "aborted_budget"
                        outcome.error_message = (
                            f"已超过 token 预算 {budget.limit}（消耗 {budget.consumed}）"
                        )
                        await stream.append(
                            "budget_exceeded",
                            {"message": outcome.error_message},
                        )
                        outcome.skipped += len(testcases) - sort_idx - 1
                        return
                    if case_aborted in ("stopped", "debug_timeout"):
                        outcome.status = "stopped"
                        outcome.error_message = (
                            "用户在调试模式中主动停止"
                            if case_aborted == "stopped"
                            else f"调试模式 {self.deps.debug_timeout_seconds:.0f}s 内未"
                                 "收到 continue，自动停止"
                        )
                        reason = (
                            "user_stop_during_debug"
                            if case_aborted == "stopped"
                            else "debug_timeout"
                        )
                        await stream.append(
                            "execution_stopped" if case_aborted == "stopped"
                            else "debug_timeout",
                            {
                                "reason": reason,
                                "timeout_seconds": self.deps.debug_timeout_seconds,
                            },
                        )
                        outcome.skipped += len(testcases) - sort_idx - 1
                        return

                outcome.status = "completed"
            finally:
                outcome.tokens_total = budget.consumed if "budget" in locals() else 0
                # 关 bundle 前先固定 video 引用；关了之后 context 就没了
                try:
                    finalize = getattr(bundle, "finalize_videos", None)
                    if callable(finalize):
                        await finalize()
                except Exception:  # noqa: BLE001
                    logger.exception("BrowserBundle.finalize_videos failed")
                try:
                    await bundle.close()
                except Exception:  # noqa: BLE001
                    logger.exception("BrowserBundle.close failed")
                # 关闭后再读 video 实际路径，写回 outcome 让外层 flush_execution 落盘
                try:
                    collect = getattr(bundle, "collect_video_paths", None)
                    if callable(collect):
                        paths = await collect()
                        if paths:
                            outcome.video_path = paths[0]
                except Exception:  # noqa: BLE001
                    logger.exception("BrowserBundle.collect_video_paths failed")

    # ── 单条用例执行 ──────────────────────────────────────────────

    async def _run_one_case(
        self,
        *,
        db: "AsyncSession",
        bundle: _BundleLike,
        tc: "Testcase",
        sort_idx: int,
        inputs: ExecutionInputs,
        environment: Any,
        module_entry_map: dict[uuid.UUID, str | None],
        requirement_contexts: dict[uuid.UUID, str],
        resolver: TestDataResolver,
        mcp_specs: list[dict[str, Any]],
        step_runner: StepRunner,
        judge: AssertionJudge,
        judge_llm_config: AssertionLLMConfig | None,
        budget: TokenBudget,
        stream: _ExecutionStream,
        outcome: ExecutionOutcome,
    ) -> str | None:
        """跑一条用例。返回 None / ``"budget"``（外层据此决定是否中止整批）。"""
        case_started = time.monotonic()

        # ── 用例间页面状态清理（sort_idx > 0 时启用）───────────────────
        # 第一条用例不需要重置——bundle.open() 后浏览器本来就是干净状态、且
        # storage_state 注入刚做完。从第二条开始，上一条用例可能在浏览器里
        # 留下未关弹窗 / 未提交表单 / SPA 路由 history / 残留 sessionStorage，
        # 这些会污染下一条用例的判断（典型：上条停在 ``/edit?id=999``、下条
        # 进来 AI 看到 ``current_url`` 不匹配 target_url 就会去 navigate，但
        # navigate 期间未保存的对话框可能挡住操作）。``reset_for_next_case``
        # 关掉多余 page + 主 page 跳 about:blank，**保留 cookies/localStorage**
        # 让登录态延续，单条用例之间从干净起跑。
        if sort_idx > 0:
            reset_fn = getattr(bundle, "reset_for_next_case", None)
            if callable(reset_fn):
                try:
                    reset_report = await reset_fn()
                    await stream.append(
                        "case_reset",
                        {
                            "next_case_index": sort_idx,
                            "closed_extra_pages": reset_report.get("closed_extra_pages", 0),
                            "navigated_to_blank": reset_report.get(
                                "navigated_to_blank", False,
                            ),
                            "errors": reset_report.get("errors") or [],
                        },
                    )
                except Exception as exc:  # noqa: BLE001
                    # reset 失败不致命：本条用例 step 1 的 prompt 仍会引导
                    # AI 自己 navigate 到 target_url 兜底。只 log + 流事件。
                    logger.warning(
                        "reset_for_next_case failed before case sort=%d: %s",
                        sort_idx, exc,
                    )
                    await stream.append(
                        "case_reset",
                        {
                            "next_case_index": sort_idx,
                            "errors": [f"{type(exc).__name__}: {exc}"],
                        },
                    )

        tc_id = getattr(tc, "id", None)
        case_resolver = (
            await resolver.with_case_overrides(tc_id)
            if tc_id is not None
            else resolver
        )
        case_resolver.reset_case_state()
        # 计算本条用例的 target_url（base_url + module.entry_path / override）。
        # None 表示该模块未配且未临时覆盖 → step_runner 收到 None 时 prompt 里
        # 不会出现 "目标 URL：…" 块，行为退回到现状（依赖 step.action 自然语言）。
        target_url = _resolve_target_url(
            tc=tc,
            environment=environment,
            module_entry_map=module_entry_map,
            module_entry_overrides=inputs.module_entry_overrides,
        )
        requirement_context = (
            requirement_contexts.get(tc_id, "")
            if isinstance(tc_id, uuid.UUID)
            else ""
        )

        # 重新注册 platform 工具到 case_resolver
        unregister_data_tools(inputs.execution_id)
        register_data_tools(inputs.execution_id, case_resolver, db=db)
        await _release_engine_db_transaction(db)

        case_row = await self.deps.persistence.create_case_result(
            execution_id=inputs.execution_id,
            testcase_id=tc_id,
            sort_order=sort_idx,
        )
        # 与 replayer 保持事件结构同构：除 title 外还要带 ``testcase_no`` /
        # ``testcase_module_name``，前端用以渲染 ``TC-0061 标题`` 形式。
        # tc 是 ORM 加载的 ``Testcase``——它没有 module_name 直接字段（要 join
        # TestcaseModule），engine 里目前 testcase loader 不一定 eager-load 模
        # 块，所以兜底走 ``getattr(tc, "module", None)`` 走 relationship；如果
        # 没有 relationship 也只是 ``None``，前端展示 ``TC-0061 标题`` 仍然
        # 工作。
        _module = getattr(tc, "module", None)
        await stream.append(
            "case_started",
            {
                "case_result_id": str(case_row.id),
                "testcase_id": str(tc_id) if tc_id is not None else None,
                "title": getattr(tc, "title", "") or "",
                "testcase_no": getattr(tc, "case_no", None),
                "testcase_module_name": getattr(_module, "name", None) if _module else None,
                "sort_order": sort_idx,
            },
        )

        case_status = "passed"
        case_error: str | None = None
        case_tokens_before = budget.consumed
        last_snapshot_text: str | None = None
        # Task 9.4 修复 #3c95cf69：跨 step 维护"当前 URL / 页面标题"，
        # 让下一个 step 的 prompt 看到准确的浏览器状态——否则 step 2+ 收到
        # ``current_url="(未知)"`` + ``snapshot_block=空``，AI 出于保险倾向
        # 在每个 step 开头都重新 navigate，**冲掉前一步在表单里输入的内容**
        # （典型表现：step 1 输入"9999"通过，step 2 点查询却看到全部数据，
        # 因为 step 2 又 navigate 一次重置了表单）。
        # 步骤之间不连贯 = 整条用例失效，这条修复必须保留。
        #
        # 用例切换后（sort_idx>0）``reset_for_next_case`` 已经把主 page 跳到
        # about:blank。这里给 step 1 的 prompt 同步一个准确的初值——让 AI 看
        # 到 ``current_url=about:blank`` 后明确知道"需要 navigate 到 target_url"，
        # 避免和未知态搅在一起。第一条用例（sort_idx=0）保持 ``(未知)``，因为
        # 浏览器刚启动时主 page 可能还没创建。
        last_url: str
        last_page_title: str
        if sort_idx > 0:
            last_url = "about:blank"
            last_page_title = "(已重置 / 新用例起点)"
        else:
            last_url = "(未知)"
            last_page_title = "(未知)"
        steps = list(getattr(tc, "steps", []) or [])
        step_iter = iter(steps)
        case_aborted_budget = False
        # Task 9.7：debug 模式专属退出原因。与 budget 互斥；最先触发的赢
        case_user_stopped = False
        case_debug_timeout = False
        # Phase 15.8: 外部反爬 / 验证码命中 -> 整条用例早停, 剩余 step 全标 skipped.
        case_external_blocked = False
        is_debug = inputs.mode == "debug"
        deterministic_runner: DeterministicRunner | None = None
        hybrid_steps_by_number: dict[int, UIActionStep] = {}
        hybrid_pre_steps: list[UIActionStep] = []
        # Phase 15.9: 信任 locator 池 (case 级共享, step 循环按 step_number 取).
        # 仅当 ``UI_LOCATOR_MEMORY=True`` 且最近 N 次 (UI_LOCATOR_MEMORY_LOOKBACK)
        # passed case_result 都给出同一签名的 step 才进入. 空 dict 等价于"无记忆".
        trusted_preferred: dict[int, dict[str, Any]] = {}
        # 上次 (最近一次成功) 的 case_result.successful_locators dict, 作为
        # apply_step_outcomes 的 previous 入参 -- 必须保留 miss_count 状态,
        # 否则连续 miss 计数会被重置, 失效 locator 永远不会被清.
        previous_locator_record: dict[str, Any] = {}
        # 记录本 case 内每个 step 的执行结果 (passed / used_preferred /
        # matched_locator), 跑完汇总丢给 apply_step_outcomes.
        step_locator_outcomes: dict[int, StepLocatorOutcome] = {}
        from app.config import settings as _engine_settings  # noqa: PLC0415

        locator_memory_enabled = (
            inputs.execution_strategy in HYBRID_EXECUTION_STRATEGIES
            and bool(getattr(_engine_settings, "UI_LOCATOR_MEMORY", True))
        )
        if inputs.execution_strategy in HYBRID_EXECUTION_STRATEGIES:
            deterministic_runner = DeterministicRunner(
                variables=_deterministic_variables_from_resolver(
                    case_resolver,
                    target_url=target_url,
                ),
            )
            hybrid_pre_steps, hybrid_steps_by_number = _compile_hybrid_plan_steps(
                tc=tc,
                module_entry_url=target_url,
                data_resolver=case_resolver,
            )
            if locator_memory_enabled and tc_id is not None:
                lookback = max(
                    1,
                    int(
                        getattr(_engine_settings, "UI_LOCATOR_MEMORY_LOOKBACK", 3)
                        or 3,
                    ),
                )
                # 失败可观测但不可见; 拉记忆 IO 失败时静默退化为"无记忆", 不该
                # 让记忆机制本身把执行链路打挂.
                try:
                    history = await self.deps.persistence.read_recent_successful_locators(
                        testcase_id=tc_id,
                        limit=lookback,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "locator memory: read recent record failed tc=%s err=%s",
                        tc_id,
                        exc,
                    )
                    history = []
                if history:
                    trusted_preferred = intersect_recent_locators(
                        history, lookback=lookback,
                    )
                # previous 必须取最近一次 case_result (含 failed) 的 record,
                # 才能让连续 miss 计数跨 case 累加到 max_miss 阈值清记忆;
                # 单看 passed 会让失败 case 的 miss_count 永远丢, 失效自愈无效.
                try:
                    previous_locator_record = (
                        await self.deps.persistence.read_latest_case_locators(
                            testcase_id=tc_id,
                        )
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "locator memory: read latest record failed tc=%s err=%s",
                        tc_id,
                        exc,
                    )
                    previous_locator_record = {}

        pre_step_structured_evidence: dict[str, Any] | None = None
        if deterministic_runner is not None and hybrid_pre_steps:
            for pre_step in hybrid_pre_steps:
                pre_result = await _run_deterministic_step(
                    bundle=bundle,
                    runner=deterministic_runner,
                    step=pre_step,
                )
                await stream.append(
                    "hybrid_step_complete",
                    {
                        "case_result_id": str(case_row.id),
                        "source_step_number": pre_step.source_step_number,
                        "action_kind": pre_step.kind.value,
                        "execution_path": "deterministic",
                        "success": pre_result.success,
                        "fallback_recommended": pre_result.fallback_recommended,
                        "error_kind": pre_result.evidence.error_kind,
                        "message": pre_result.evidence.message,
                    },
                )
                if pre_result.success and pre_step.kind == UIActionKind.NAVIGATE:
                    last_url = target_url or last_url
                    last_page_title = "(已通过轻量混合模式打开模块入口)"
                    pre_step_structured_evidence = _structured_evidence_from_action(
                        pre_result,
                    )

        await _materialize_missing_case_placeholders(
            db=db,
            resolver=case_resolver,
            tc=tc,
            structured_evidence=pre_step_structured_evidence,
        )
        if deterministic_runner is not None:
            deterministic_runner.variables = _deterministic_variables_from_resolver(
                case_resolver,
                target_url=target_url,
            )
            # Phase 15.11: 占位符自造完成后重编一次 plan.
            # 首轮 _compile_hybrid_plan_steps 在 case 启动时执行, 那时
            # `{{creator_id_combined}}` 之类动态合成 key 还没被
            # _materialize_missing_case_placeholders 写回 resolver.data,
            # 整步会被编为 UNSUPPORTED("unresolved_placeholder: ...") 进而
            # 走 ai_only -- 单步轻松烧 6w token + 不可避免的 LLM 误判.
            # 自造完成后这些 key 已经在 resolver.data 中, 再编一次就能让
            # FILL/CLICK 类轻量动作回到 deterministic 路径; 只覆盖原本
            # UNSUPPORTED 的 step, 不动已经识别成功的 step, 风险面最小.
            try:
                _, hybrid_steps_by_number_v2 = _compile_hybrid_plan_steps(
                    tc=tc,
                    module_entry_url=target_url,
                    data_resolver=case_resolver,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "phase 15.11 replan after synth failed tc=%s err=%s",
                    tc_id,
                    exc,
                )
                hybrid_steps_by_number_v2 = {}
            replanned_step_numbers = _merge_replanned_compiled_steps(
                base=hybrid_steps_by_number,
                fresh=hybrid_steps_by_number_v2,
            )
            if replanned_step_numbers:
                logger.info(
                    "phase 15.11 replan after synth tc=%s upgraded steps=%s",
                    tc_id,
                    replanned_step_numbers,
                )

        for step in step_iter:
            try:
                rendered_action = case_resolver.render_template(step.action or "")
                rendered_expected = case_resolver.render_template(
                    step.expected_result or "",
                )
                manifest = case_resolver.render_manifest_markdown()

                await stream.append(
                    "step_started",
                    {
                        "case_result_id": str(case_row.id),
                        "step_number": step.step_number,
                        "action_preview": rendered_action[:200],
                    },
                )

                step_started_at = time.monotonic()
                step_tokens_before = budget.consumed
                compiled_step_for_current = hybrid_steps_by_number.get(step.step_number)
                # Phase 15.9: 仅 hybrid 路径 + 该 step 命中 trusted_preferred
                # 时构造 preferred 候选 list, 否则保持 None (deterministic_runner
                # 不会启用 preferred 通道, 走原候选生成流程, 行为等价于关闭).
                preferred_for_step: list[dict[str, Any]] | None = None
                if locator_memory_enabled:
                    sig = trusted_preferred.get(step.step_number)
                    if sig:
                        preferred_for_step = [_signature_to_locator_spec(sig)]
                run_result, execution_path = await _run_step_with_strategy(
                    inputs=inputs,
                    bundle=bundle,
                    step_runner=step_runner,
                    deterministic_runner=deterministic_runner,
                    compiled_step=compiled_step_for_current,
                    step_description=rendered_action,
                    expected=rendered_expected,
                    data_manifest=manifest,
                    data_resolver=case_resolver,
                    prev_snapshot=last_snapshot_text,
                    # 把上一步的"当前 URL / 页面标题 / a11y 快照"注入到本步骤
                    # 的 system prompt，让 AI 看到真实的浏览器状态（关键：
                    # 已经在目标 URL 时不要重新 navigate，详见上文 ``last_url``
                    # 字段注释 + #3c95cf69 修复案例）。step 1 时这三者都是
                    # 默认值，AI 会按 prompt 里的指引 navigate 到 target_url；
                    # step 2+ 接续上一步的状态，AI 不会再保险性 navigate。
                    initial_snapshot_text=last_snapshot_text,
                    current_url=last_url,
                    page_title=last_page_title,
                    mcp_tool_specs=mcp_specs,
                    target_url=target_url,
                    requirement_context=requirement_context,
                    budget=budget,
                    # Phase 15.7: 让 step_runner 拿到当前用例总步数, 用于推算
                    # 单步 token 软上限. 不影响 deterministic 路径.
                    estimated_total_steps=len(steps) if steps else None,
                    preferred_locator_candidates=preferred_for_step,
                )
                last_snapshot_text = run_result.last_snapshot_text or last_snapshot_text
                # 步骤收尾：刷新"当前 URL / 标题"给下一步用。优先从刚拿到的
                # snapshot 文本里抽（playwright-mcp 在 snapshot result 里就带了
                # Page URL/Title），没抽到再调 MCP。best-effort：失败保留旧值。
                fresh_url = await _safe_get_current_url(
                    bundle, fallback_snapshot=run_result.last_snapshot_text,
                )
                if fresh_url:
                    last_url = fresh_url
                fresh_title = _safe_extract_page_title(run_result.last_snapshot_text)
                if fresh_title:
                    last_page_title = fresh_title

                if run_result.error_kind == "budget_exceeded":
                    case_status = "error"
                    case_error = run_result.error or "token 预算耗尽"
                    case_aborted_budget = True

                # AssertionJudge
                verdict: AssertionVerdict
                if run_result.error_kind in ("budget_exceeded", "security_blocked", "llm_error"):
                    verdict = AssertionVerdict(
                        passed=False,
                        reason=run_result.error or run_result.error_kind or "step 异常未通过",
                        method="skipped",
                    )
                elif deterministic_verdict := _deterministic_assertion_verdict(run_result):
                    verdict = deterministic_verdict
                else:
                    verdict = await judge.judge(
                        expected=rendered_expected,
                        snapshot=_build_assertion_context(run_result),
                        step_description=rendered_action,
                        llm_config=judge_llm_config,
                        structured_evidence=_extract_structured_assertion_evidence(run_result),
                    )

                verdict = triage_step_failure(
                    verdict=verdict,
                    run_result=run_result,
                    step_description=rendered_action,
                    expected=rendered_expected,
                    target_url=target_url,
                )

                step_status = (
                    "blocked_by_security"
                    if run_result.error_kind == "security_blocked"
                    else "passed" if verdict.passed
                    else "failed"
                )
                # Phase 15.9: 仅 deterministic 路径成功 / 失败的 step 进入
                # 记忆 outcome -- AI fallback / ai_step_runner 路径不写
                # locator memory (它们没用 page locator, 写了也无意义).
                if (
                    locator_memory_enabled
                    and deterministic_runner is not None
                    and compiled_step_for_current is not None
                    and execution_path == "deterministic"
                ):
                    is_passed = step_status == "passed"
                    matched_sig = (
                        _extract_matched_locator_signature(run_result)
                        if is_passed
                        else None
                    )
                    step_locator_outcomes[step.step_number] = StepLocatorOutcome(
                        passed=is_passed,
                        used_preferred=bool(
                            deterministic_runner.last_run_used_preferred_locator,
                        ),
                        matched_locator=matched_sig,
                        timestamp_iso=datetime.now(timezone.utc).isoformat(),
                    )
                fallback_reason = _extract_fallback_reason(run_result)
                step_duration = int((time.monotonic() - step_started_at) * 1000)
                step_tokens_used = (
                    run_result.tokens_used - step_tokens_before
                    if run_result.tokens_used >= step_tokens_before
                    else 0
                )
                serialized_tool_calls = [
                    _serialize_tool_call(tc_) for tc_ in run_result.tool_calls
                ]
                serialized_tool_calls.append(
                    make_execution_meta_tool_call(
                        execution_path=_metric_execution_path(execution_path),
                        fallback_reason=fallback_reason,
                        llm_calls=_step_llm_call_count(
                            execution_path=execution_path,
                            iterations=run_result.iterations,
                        ),
                    ),
                )

                # 每步截图（best-effort：失败不阻塞用例推进）
                screenshot_path = await _capture_step_screenshot_safe(
                    bundle=bundle,
                    execution_id=inputs.execution_id,
                    case_result_id=case_row.id,
                    step_number=step.step_number,
                )

                await self.deps.persistence.flush_step(
                    case_result_id=case_row.id,
                    step_number=step.step_number,
                    description=rendered_action,
                    expected_result=rendered_expected or None,
                    tool_calls=serialized_tool_calls,
                    ai_reasoning=run_result.reasoning or None,
                    snapshot_before=None,  # Engine 当前未单独捕获 step-before snapshot
                    snapshot_after=run_result.last_snapshot_text,
                    assertion_passed=verdict.passed,
                    assertion_reason=verdict.reason,
                    assertion_evidence=verdict.evidence,
                    status=step_status,
                    screenshot_path=screenshot_path,
                    error_message=run_result.error,
                    tokens_used=step_tokens_used,
                    duration_ms=step_duration,
                    # Phase 15.1: 把"哪条路径走通 / 为什么没进 fallback / 为什么
                    # StepRunner 跳出循环 / 用了哪种断言策略" 4 个诊断字段提为
                    # 列, 让数据分析不必再 LIKE %execution_path% 扒 details JSON.
                    execution_path=_metric_execution_path(execution_path),
                    fallback_reason=fallback_reason,
                    loop_break_reason=getattr(run_result, "loop_break_reason", None),
                    assertion_method=getattr(verdict, "method", None),
                )
                # screenshot_url 在事件里走 nginx 静态路径（无需 Bearer
                # token），让前端 LiveScreenshot 直接 ``<img src>`` 加载
                screenshot_url: str | None = None
                if screenshot_path:
                    from app.config import settings

                    art_root = os.path.abspath(settings.UI_ARTIFACTS_DIR)
                    abs_p = os.path.abspath(screenshot_path)
                    if abs_p.startswith(art_root + os.sep):
                        rel = os.path.relpath(abs_p, art_root).replace(os.sep, "/")
                        screenshot_url = f"/uploads/ui_artifacts/{rel}"
                await stream.append(
                    "step_complete",
                    {
                        "case_result_id": str(case_row.id),
                        "step_number": step.step_number,
                        "status": step_status,
                        "assertion": verdict.to_dict(),
                        "tool_calls": len(run_result.tool_calls),
                        "tokens_used": run_result.tokens_used,
                        "iterations": run_result.iterations,
                        "duration_ms": step_duration,
                        "error": run_result.error,
                        "screenshot_url": screenshot_url,
                        "execution_path": execution_path,
                        "fallback_reason": fallback_reason,
                    },
                )
                await _release_engine_db_transaction(db)

                if budget_warning := budget.maybe_warning():
                    await stream.append("budget_warning", {"message": budget_warning})

                if not verdict.passed and case_status == "passed":
                    case_status = "failed"

                # Phase 15.8: 命中外部反爬 / 验证码 -> 整条用例早停, 剩余 step 全
                # 批量落 skipped, case 标 data_failure (从业务通过率分母里剔除).
                # 5 条百度搜索 demo 用例近 4 周累计 16 次 100% 失败, 22 个 captcha
                # 阻断步骤都来自这 5 条; 继续跑只会再吞 4 倍 token 拿同样结论.
                if getattr(verdict, "early_terminate", False):
                    case_external_blocked = True
                    case_status = "failed"
                    if not case_error:
                        case_error = (
                            "外部安全验证 / 验证码阻断, 已提前结束本用例; "
                            "建议改用稳定测试环境, 或避开公开搜索引擎反爬页面."
                        )
                    # 把当前 step 之后的所有 step 落 skipped, 让前端时间线 / 历史
                    # 详情页都能看到 "case 5 步, 1 失败 4 跳过" 而不是 "1 失败".
                    remaining = [
                        s for s in steps if s.step_number > step.step_number
                    ]
                    for skipped_step in remaining:
                        skip_action = case_resolver.render_template(
                            skipped_step.action or ""
                        )
                        skip_expected = case_resolver.render_template(
                            skipped_step.expected_result or ""
                        )
                        await self.deps.persistence.flush_step(
                            case_result_id=case_row.id,
                            step_number=skipped_step.step_number,
                            description=skip_action,
                            expected_result=skip_expected or None,
                            tool_calls=[],
                            ai_reasoning=None,
                            snapshot_before=None,
                            snapshot_after=None,
                            assertion_passed=None,
                            assertion_reason=(
                                "case_terminated_by_external_verification"
                            ),
                            assertion_evidence="",
                            status="skipped",
                            screenshot_path=None,
                            error_message=(
                                "用例因外部反爬 / 验证码阻断提前结束"
                            ),
                            tokens_used=0,
                            duration_ms=0,
                            execution_path=None,
                            fallback_reason="external_blocked",
                            loop_break_reason=None,
                            assertion_method=None,
                        )
                        await stream.append(
                            "step_complete",
                            {
                                "case_result_id": str(case_row.id),
                                "step_number": skipped_step.step_number,
                                "status": "skipped",
                                "assertion": {
                                    "passed": False,
                                    "reason": "case_terminated_by_external_verification",
                                    "evidence": "",
                                    "method": "skipped",
                                },
                                "tool_calls": 0,
                                "tokens_used": 0,
                                "iterations": 0,
                                "duration_ms": 0,
                                "error": "external_verification_blocked",
                                "screenshot_url": None,
                                "execution_path": None,
                                "fallback_reason": "external_blocked",
                            },
                        )
                    break

                if case_aborted_budget:
                    break

                # Task 9.7 — debug 模式：每步完成后暂停，等用户调
                # ``POST /continue`` 推进。只在还没 abort 的情况下暂停（已经
                # 出 budget / failure 时再暂停就纯属浪费时间）。
                if is_debug:
                    pause_action = await self._maybe_debug_pause(
                        inputs=inputs,
                        stream=stream,
                        case_row_id=case_row.id,
                        step_number=step.step_number,
                    )
                    if pause_action == "stopped":
                        case_user_stopped = True
                        break
                    if pause_action == "timeout":
                        case_debug_timeout = True
                        break

                # data_failure 早停：发现 mark_data_failure 已经触发 → 后续步骤不再跑
                # （case_resolver 会在 finalize_case 里给出 data_failure）
                if case_resolver._case_failures:  # noqa: SLF001
                    case_status = "error"
                    case_error = (
                        f"用例数据问题：{case_resolver._case_failures[-1].get('reason', '')}"  # noqa: SLF001
                    )
                    break
            except BudgetExceededError as exc:
                case_aborted_budget = True
                case_status = "error"
                case_error = str(exc)
                break
            except SecurityError as exc:
                logger.exception("SecurityError during step")
                case_status = "error"
                case_error = str(exc)
                break
            except Exception as exc:  # noqa: BLE001
                logger.exception("Step crashed unexpectedly")
                case_status = "error"
                case_error = f"{type(exc).__name__}: {exc}"
                break

        await _release_engine_db_transaction(db)

        # 收尾本用例
        # Task 9.7：debug 暂停被打断的用例，剩余步骤当作 skipped；状态从 passed
        # 改成 skipped/error 让前端不会误以为"通过"。判断要在 finalize 之前。
        if case_user_stopped and case_status == "passed":
            case_status = "skipped"
            case_error = case_error or "用户在调试中主动停止"
        elif case_debug_timeout and case_status == "passed":
            case_status = "skipped"
            case_error = case_error or (
                f"调试模式 {self.deps.debug_timeout_seconds:.0f}s 内未收到 continue，自动停止"
            )

        case_finalized = case_resolver.finalize_case()
        if case_finalized["data_confidence"] == "data_failure" and case_status == "passed":
            # 即便 step 都"通过"，AI 标了 data_failure，结果应记为 error
            case_status = "error"
            if not case_error:
                fails = case_finalized.get("data_failures") or []
                case_error = "数据失败：" + str(fails[0]) if fails else "数据失败"

        # Phase 15.8: 外部反爬命中后, 把 case 标成 data_failure, 让 dashboard 业务
        # 通过率分母里自动剔除这条 -- 避免被一条已知必败的反爬用例拖低数字.
        if case_external_blocked:
            case_finalized["data_confidence"] = "data_failure"
            existing_fails = case_finalized.get("data_failures") or []
            case_finalized["data_failures"] = list(existing_fails) + [
                {
                    "kind": "external_verification_blocked",
                    "reason": "外部反爬 / 验证码阻断, 用例提前结束",
                }
            ]

        case_tokens_used = max(0, budget.consumed - case_tokens_before)
        case_duration = int((time.monotonic() - case_started) * 1000)

        # Phase 15.9: 算新 locator 记忆 (开关关掉 / 没用 hybrid / 没拿到 tc_id
        # 时为 None, 让 flush_case 跳过对该列的覆盖, 不破坏旧 case_result).
        new_successful_locators: dict[str, Any] | None = None
        if locator_memory_enabled:
            max_miss = max(
                1,
                int(
                    getattr(_engine_settings, "UI_LOCATOR_MEMORY_MAX_MISS", 2) or 2,
                ),
            )
            new_successful_locators = apply_step_outcomes(
                previous=previous_locator_record,
                outcomes=step_locator_outcomes,
                max_miss=max_miss,
            )

        await self.deps.persistence.flush_case(
            case_result_id=case_row.id,
            status=case_status,
            ai_summary=None,
            error_message=case_error,
            duration_ms=case_duration,
            tokens_used=case_tokens_used,
            test_data_used=_extract_test_data_used(case_resolver),
            synthesized_data=case_finalized["synthesized_data"],
            data_failures=case_finalized["data_failures"],
            data_confidence=case_finalized["data_confidence"],
            successful_locators=new_successful_locators,
        )
        await stream.append(
            "case_complete",
            {
                "case_result_id": str(case_row.id),
                "testcase_id": str(tc_id) if tc_id is not None else None,
                "status": case_status,
                "data_confidence": case_finalized["data_confidence"],
                "duration_ms": case_duration,
                "tokens_used": case_tokens_used,
                "error_message": case_error,
            },
        )
        await _release_engine_db_transaction(db)

        if case_status == "passed":
            outcome.passed += 1
        elif case_status == "failed":
            outcome.failed += 1
        elif case_status == "skipped":
            # Task 9.7：debug stop / timeout 被打断的当前用例算 skipped 而非
            # failed —— 它**没有**被测系统的 bug 凭据，纯属人工中断
            outcome.skipped += 1
        else:
            # error 都计入 failed 桶（与设计一致；data_confidence 用来排除
            # "数据问题导致的失败"）
            outcome.failed += 1

        if case_aborted_budget:
            return "budget"
        if case_user_stopped:
            return "stopped"
        if case_debug_timeout:
            return "debug_timeout"
        return None


    # ── Task 9.7：debug 模式 pause hook ─────────────────────────────

    async def _maybe_debug_pause(
        self,
        *,
        inputs: ExecutionInputs,
        stream: _ExecutionStream,
        case_row_id: uuid.UUID,
        step_number: int,
    ) -> str:
        """``mode="debug"`` 时在每步完成后阻塞等用户 ``POST /continue``。

        返回值：
        - ``"continue"``：用户推进，主循环继续
        - ``"stopped"``：用户调了 ``POST /stop``，主循环把当前用例标 skipped
          后退出
        - ``"timeout"``：``debug_timeout_seconds`` 内无信号，自动 stop
        """
        await stream.append(
            "step_paused",
            {
                "case_result_id": str(case_row_id),
                "step_number": step_number,
                "execution_id": str(inputs.execution_id),
                "timeout_seconds": self.deps.debug_timeout_seconds,
                "hint": "请调 POST /api/ui-executions/{id}/continue 推进下一步",
            },
        )

        async def _stop_check() -> bool:
            return await _check_stopped(self.deps, inputs.execution_id)

        try:
            outcome = await self.deps.debug_controller.wait_for_continue(
                inputs.execution_id,
                timeout=self.deps.debug_timeout_seconds,
                stop_check=_stop_check,
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "debug_controller.wait_for_continue raised; treating as continue",
            )
            return "continue"

        # 不是 continue 的话发对应事件，让前端 UI 把 step_paused 关掉
        if outcome == "stopped":
            await stream.append(
                "debug_stopped",
                {
                    "execution_id": str(inputs.execution_id),
                    "case_result_id": str(case_row_id),
                    "step_number": step_number,
                },
            )
        elif outcome == "timeout":
            await stream.append(
                "debug_timeout_pending",
                {
                    "execution_id": str(inputs.execution_id),
                    "case_result_id": str(case_row_id),
                    "step_number": step_number,
                    "timeout_seconds": self.deps.debug_timeout_seconds,
                },
            )
        else:
            await stream.append(
                "step_resumed",
                {
                    "case_result_id": str(case_row_id),
                    "step_number": step_number,
                },
            )
        return outcome


# ─── helpers ─────────────────────────────────────────────────────────


async def _materialize_missing_case_placeholders(
    *,
    db: Any,
    resolver: TestDataResolver,
    tc: "Testcase",
    structured_evidence: dict[str, Any] | None = None,
) -> list[str]:
    """Turn unresolved ``{{key}}`` placeholders into auditable synthetic data.

    Preflight warnings are useful for the UI, but hybrid deterministic steps run
    before the LLM has a chance to call platform tools. If a fill step keeps an
    unresolved placeholder, the runner may type ``{{key}}`` literally. We
    synthesize missing keys once per case so both rendered prompts and the
    deterministic runner see concrete values and the audit trail records that
    data confidence is synthetic.
    """
    del db  # keep the signature explicit for tests/future DB-backed synthesis.
    missing = _collect_missing_case_template_keys(resolver, tc)
    if not missing:
        return []
    cache_fn = getattr(resolver, "cache_synthesized", None)
    if not callable(cache_fn):
        return []

    synthesizer = DataSynthesizer()
    materialized: list[str] = []
    for key in missing:
        hint = _placeholder_hint(tc, key)
        table_value = _table_value_for_placeholder(
            key,
            hint=hint,
            structured_evidence=structured_evidence,
        )
        if table_value:
            if cache_fn(key, table_value, "page_table", hint=hint):
                materialized.append(key)
            continue
        synth = await synthesizer.synthesize(key, hint, "string")
        if cache_fn(key, synth.value, synth.source, hint=hint):
            materialized.append(key)
    return materialized


def _collect_missing_case_template_keys(
    resolver: TestDataResolver,
    tc: "Testcase",
) -> list[str]:
    available = set(getattr(resolver, "data", {}).keys())
    runtime_data = getattr(resolver, "runtime_data", {}) or {}
    seen: dict[str, None] = {}
    for step in list(getattr(tc, "steps", []) or []):
        for payload in (
            getattr(step, "action", None),
            getattr(step, "expected_result", None),
        ):
            for key in extract_template_keys(payload):
                if key.startswith("runtime."):
                    runtime_key = key[len("runtime.") :]
                    if runtime_key in runtime_data:
                        continue
                    continue
                if key in available:
                    continue
                seen.setdefault(key, None)
    return list(seen)


def _placeholder_hint(tc: "Testcase", key: str) -> str:
    title = str(getattr(tc, "title", "") or "")
    fragments: list[str] = []
    for step in list(getattr(tc, "steps", []) or []):
        action = str(getattr(step, "action", "") or "")
        expected = str(getattr(step, "expected_result", "") or "")
        if f"{{{{{key}}}}}" in action or f"{{{{ {key} }}}}" in action:
            fragments.append(action)
        if f"{{{{{key}}}}}" in expected or f"{{{{ {key} }}}}" in expected:
            fragments.append(expected)
    body = "；".join(fragments[:3])
    if title and body:
        return f"{title}：{body}"
    return body or title or key


def _table_value_for_placeholder(
    key: str,
    *,
    hint: str,
    structured_evidence: dict[str, Any] | None,
) -> str | None:
    if not structured_evidence:
        return None
    table_rows = structured_evidence.get("table_rows")
    if not isinstance(table_rows, dict):
        return None
    rows = table_rows.get("rows")
    if not isinstance(rows, list) or not rows:
        return None

    labels = _placeholder_semantic_labels(key, hint)
    if not labels:
        return None
    row_index = _placeholder_row_index(key)
    if row_index >= len(rows):
        row_index = 0
    row = rows[row_index]
    if not isinstance(row, dict):
        return None
    normalized_labels = [_normalize_semantic_label(label) for label in labels]
    for column, value in row.items():
        text = "" if value is None else str(value).strip()
        if not text:
            continue
        norm_col = _normalize_semantic_label(str(column))
        if any(label and (label in norm_col or norm_col in label) for label in normalized_labels):
            return text
    return None


def _placeholder_semantic_labels(key: str, hint: str) -> list[str]:
    labels: list[str] = []
    pattern = re.compile(rf"「([^」]+)」[^\n；。]*\{{\{{\s*{re.escape(key)}\s*\}}\}}")
    labels.extend(match.group(1).strip() for match in pattern.finditer(hint or ""))
    normalized_key = key.lower()
    if "creator_id" in normalized_key or "author_id" in normalized_key:
        labels.extend(["创作者ID", "作者ID", "ID"])
    if (
        "creator_name" in normalized_key
        or "author_name" in normalized_key
        or "name_keyword" in normalized_key
    ):
        labels.extend(["创作者名称", "作者名称", "名称"])
    out: list[str] = []
    seen: set[str] = set()
    for label in labels:
        cleaned = str(label or "").strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            out.append(cleaned)
    return out


def _placeholder_row_index(key: str) -> int:
    match = re.search(r"(?:^|_)(\d+)$", key)
    if not match:
        return 0
    return max(0, int(match.group(1)) - 1)


def _normalize_semantic_label(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "").replace("：", ":")).lower()


def _structured_evidence_from_action(
    result: DeterministicRunResult,
) -> dict[str, Any] | None:
    details = result.evidence.details if result and result.evidence else {}
    structured = details.get("structured_evidence") if isinstance(details, dict) else None
    return structured if isinstance(structured, dict) else None


def _deterministic_variables_from_resolver(
    resolver: TestDataResolver,
    *,
    target_url: str | None,
) -> dict[str, str]:
    variables: dict[str, str] = {"module.entry_url": target_url or ""}
    for key, item in sorted(getattr(resolver, "data", {}).items()):
        value_type = getattr(item, "value_type", "")
        if value_type in {"secret", "file"}:
            continue
        value_fn = getattr(item, "template_substitution_value", None)
        if callable(value_fn):
            variables[str(key)] = str(value_fn())
    runtime_data = getattr(resolver, "runtime_data", {}) or {}
    for key, value in sorted(runtime_data.items()):
        if isinstance(value, (dict, list)):
            variables[f"runtime.{key}"] = json.dumps(value, ensure_ascii=False)
        else:
            variables[f"runtime.{key}"] = "" if value is None else str(value)
    return variables


def _compile_hybrid_plan_steps(
    *,
    tc: "Testcase",
    module_entry_url: str | None,
    data_resolver: TestDataResolver | None = None,
) -> tuple[list[UIActionStep], dict[int, UIActionStep]]:
    """Compile testcase steps for lightweight hybrid execution.

    Compile failures must not block execution; they simply make the engine fall
    back to the legacy StepRunner path for this case.

    Phase 15.5: 接受 ``data_resolver`` 后, 编译时会先把 ``{{key}}`` 渲染掉.
    渲染后仍残留占位符的 step 会被编译为 ``UNSUPPORTED``,
    ``unsupported_reason="unresolved_placeholder: ..."``, deterministic 链路
    遇到这种步骤直接走 step_runner 回退或 data_failure, 避免拿着 ``{{xxx}}``
    去填表/匹配文字制造垃圾失败.
    """
    try:
        result = compile_action_plan(
            tc,
            module_entry_path=module_entry_url,
            data_resolver=data_resolver,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("compile_action_plan failed for hybrid execution: %s", exc)
        return [], {}

    pre_steps: list[UIActionStep] = []
    by_number: dict[int, UIActionStep] = {}
    for compiled in result.plan.steps:
        if compiled.source_step_number == 0:
            pre_steps.append(compiled)
        elif compiled.source_step_number is not None:
            by_number[int(compiled.source_step_number)] = compiled
    return pre_steps, by_number


def _merge_replanned_compiled_steps(
    *,
    base: dict[int, UIActionStep],
    fresh: dict[int, UIActionStep],
) -> list[int]:
    """Phase 15.11 — 占位符自造后的二次 plan 合并策略.

    只把"原本 UNSUPPORTED 现在能识别"的 step 替换进 ``base``;
    已经识别成功的 step 不动 (避免误覆盖 + 保持 confidence/risk_level
    判定稳定); ``fresh`` 里依然 UNSUPPORTED 的 step 也不动 (说明这一步
    与缺数据无关, 留给原降级链路兜).

    返回值: 升级成功的 source_step_number 列表, 用于 logger 可观测.
    """
    upgraded: list[int] = []
    for step_num, fresh_step in fresh.items():
        if fresh_step.kind == UIActionKind.UNSUPPORTED:
            continue
        old = base.get(step_num)
        if old is None or old.kind == UIActionKind.UNSUPPORTED:
            base[step_num] = fresh_step
            upgraded.append(step_num)
    return upgraded


# Phase 15.4a: AI fallback 白名单. 历史 ai_fallback 通过率 < 10%, token 单步动辄
# 几十万; 把放行条件做成"白名单 4 条全部满足"而不是"黑名单兜底", 避免回到原来
# "默认放, 个别拦"的散弹枪策略.
_FALLBACK_ALLOWED_KINDS: frozenset[UIActionKind] = frozenset({
    UIActionKind.CLICK,
    UIActionKind.FILL,
})

# 探索性词汇 -- 用例作者本意是"看一下 / 能就走", 让 AI 兜反而越走越远.
# 与 testcases.step_quality._HEDGING_RE 同步; 命中即拒绝 fallback.
_FALLBACK_HEDGING_PATTERN = re.compile(
    r"(若有|如有|如果(?:存在|有)?|尝试|试试|可能|或许|也许|视情况|看情况|建议|或者|可以)"
)


def _ai_fallback_allowed(
    step: UIActionStep,
    deterministic_result: DeterministicRunResult,
) -> bool:
    """Phase 15.4a: 仅在 "显式 click/fill 目标 + 标准 locator_not_found" 时放行.

    必须**全部满足**才返回 True (白名单语义). 单测会覆盖每条单独不满足时的拒绝.
    """
    if step.kind not in _FALLBACK_ALLOWED_KINDS:
        return False
    if step.risk_level == "high":
        return False
    if deterministic_result.evidence.error_kind != "locator_not_found":
        return False
    if step.source_text and _FALLBACK_HEDGING_PATTERN.search(step.source_text):
        return False
    # belt-and-suspenders: 再兜一遍历史防线 -- dangerous / 外部人机验证场景
    # 一律不让 LLM 兜.
    if deterministic_result.evidence.error_kind == "dangerous_action_blocked":
        return False
    if _deterministic_evidence_has_external_verification(deterministic_result):
        return False
    return True


def _ai_fallback_blocked_reason(
    step: UIActionStep,
    deterministic_result: DeterministicRunResult,
) -> str:
    """Phase 15.4a: 把"为什么没进 fallback"分类成可观测的细粒度原因.

    与 _ai_fallback_allowed 的拒绝顺序保持一致, 让前端徽章 / 历史详情页能直接
    展示哪一条规则 hit. step_complete SSE 事件里走 fallback_reason 字段.
    """
    if step.kind not in _FALLBACK_ALLOWED_KINDS:
        return "action_kind_not_eligible"
    if step.risk_level == "high":
        return "high_risk_action_no_ai_fallback"
    if step.source_text and _FALLBACK_HEDGING_PATTERN.search(step.source_text):
        return "exploratory_step"
    if deterministic_result.evidence.error_kind == "dangerous_action_blocked":
        return "dangerous_action_blocked"
    if _deterministic_evidence_has_external_verification(deterministic_result):
        return "external_verification_blocked"
    if deterministic_result.evidence.error_kind != "locator_not_found":
        return "deterministic_error_not_recoverable"
    return "ai_fallback_not_allowed"


def _deterministic_evidence_has_external_verification(
    deterministic_result: DeterministicRunResult,
) -> bool:
    details = deterministic_result.evidence.details if deterministic_result.evidence else {}
    if not isinstance(details, dict):
        return False
    structured = details.get("structured_evidence")
    if not isinstance(structured, dict):
        return False
    chunks: list[str] = []
    page_identity = structured.get("page_identity")
    if isinstance(page_identity, dict):
        chunks.extend(
            str(page_identity.get(key) or "")
            for key in ("url", "title")
        )
    page_text = structured.get("page_text")
    if isinstance(page_text, dict):
        texts = page_text.get("texts")
        if isinstance(texts, list):
            chunks.extend(str(item) for item in texts[:40])
    haystack = "\n".join(chunks).lower()
    return any(term.lower() in haystack for term in _EXTERNAL_VERIFICATION_TERMS)


def _fallback_reason(result: DeterministicRunResult) -> str:
    return (
        result.evidence.error_kind
        or result.evidence.message
        or "deterministic_failed"
    )


def _build_ai_fallback_context(
    *,
    step: UIActionStep,
    deterministic_result: DeterministicRunResult,
    rendered_action: str,
    rendered_expected: str,
) -> dict[str, Any]:
    return {
        "source_step_number": step.source_step_number,
        "source_text": step.source_text,
        "rendered_action": rendered_action,
        "rendered_expected": rendered_expected,
        "fallback_reason": _fallback_reason(deterministic_result),
        "action_plan_step": step.model_dump(mode="json", exclude_none=True),
        "deterministic_evidence": deterministic_result.evidence.model_dump(
            mode="json",
            exclude_none=True,
        ),
        "policy": {
            "scope": "current_step_only",
            "allowed_tools": [
                "browser_snapshot",
                "browser_screenshot",
                "browser_take_screenshot",
                "browser_console_messages",
                "browser_network_requests",
            ],
            "forbidden": [
                "browser_click",
                "browser_type",
                "browser_fill_form",
                "browser_select",
                "browser_select_option",
                "browser_navigate",
                "browser_evaluate",
                "browser_run_code_unsafe",
            ],
            "candidate_locator_must_be_runner_verified": True,
        },
    }


def _extract_fallback_reason(run_result: StepRunResult) -> str | None:
    for rec in run_result.tool_calls:
        if rec.raw_name != "deterministic_runner":
            continue
        result = rec.result if isinstance(rec.result, dict) else {}
        details = result.get("details")
        if isinstance(details, dict) and details.get("fallback_reason"):
            return str(details["fallback_reason"])
        if result.get("error_kind"):
            return str(result["error_kind"])
    return None


def _metric_execution_path(execution_path: str) -> str:
    if execution_path == "ai_step_runner":
        return "ai_only"
    if execution_path in ("deterministic", "ai_fallback"):
        return execution_path
    return "ai_only"


def _deterministic_assertion_verdict(
    run_result: StepRunResult,
) -> AssertionVerdict | None:
    for rec in run_result.tool_calls:
        if rec.raw_name != "deterministic_runner":
            continue
        result = rec.result if isinstance(rec.result, dict) else {}
        if result.get("execution_path") != "deterministic":
            continue
        action_kind = str(result.get("action_kind") or "")
        if action_kind not in _DETERMINISTIC_ASSERTION_KIND_VALUES:
            continue
        success = result.get("success")
        if not isinstance(success, bool):
            continue
        reason = str(
            result.get("message")
            or ("确定性断言通过" if success else "确定性断言未通过")
        )
        return AssertionVerdict(
            passed=success,
            reason=reason,
            evidence=_deterministic_evidence_summary(result),
            method="deterministic",
        )
    return None


def _deterministic_evidence_summary(result: dict[str, Any]) -> str:
    details = result.get("details") if isinstance(result.get("details"), dict) else {}
    structured = result.get("structured_evidence")
    if not isinstance(structured, dict):
        structured = details.get("structured_evidence") if isinstance(details, dict) else None
    if not isinstance(structured, dict):
        return str(result.get("action_kind") or "deterministic_runner")

    page_identity = structured.get("page_identity")
    if isinstance(page_identity, dict):
        title = page_identity.get("title")
        url = page_identity.get("url")
        if title or url:
            return "页面身份：" + " ".join(str(item) for item in (title, url) if item)

    table_schema = structured.get("table_schema")
    if isinstance(table_schema, dict):
        columns = table_schema.get("columns") or table_schema.get("visible_columns") or []
        if isinstance(columns, list) and columns:
            preview = "、".join(str(item) for item in columns[:8])
            return f"表格列 {len(columns)} 个：{preview}"

    table_rows = structured.get("table_rows")
    if isinstance(table_rows, dict):
        row_count = table_rows.get("row_count")
        return f"表格行数：{row_count if row_count is not None else 0}"

    form_fields = structured.get("form_fields")
    if isinstance(form_fields, dict):
        fields = form_fields.get("fields") or []
        if isinstance(fields, list):
            labels = [
                str(item.get("label") or item.get("placeholder") or item.get("name") or "")
                for item in fields
                if isinstance(item, dict)
            ]
            labels = [item for item in labels if item]
            preview = "、".join(labels[:8])
            return f"表单字段数：{len(fields)}" + (f"：{preview}" if preview else "")

    page_text = structured.get("page_text")
    if isinstance(page_text, dict):
        texts = page_text.get("texts") or []
        if isinstance(texts, list) and texts:
            preview = "、".join(str(item) for item in texts[:8])
            return f"页面文本：{preview}"

    page_identity = structured.get("page_identity")
    if isinstance(page_identity, dict):
        title = page_identity.get("title")
        headings = page_identity.get("headings") or []
        if isinstance(headings, list) and headings:
            return f"页面标题：{headings[0]}"
        if title:
            return f"页面标题：{title}"

    return str(result.get("action_kind") or "deterministic_runner")


def _step_llm_call_count(*, execution_path: str, iterations: int) -> int:
    if _metric_execution_path(execution_path) == "deterministic":
        return 0
    return max(0, int(iterations or 0))


async def _run_step_with_strategy(
    *,
    inputs: ExecutionInputs,
    bundle: _BundleLike,
    step_runner: StepRunner,
    deterministic_runner: DeterministicRunner | None,
    compiled_step: UIActionStep | None,
    step_description: str,
    expected: str,
    data_manifest: str,
    data_resolver: TestDataResolver,
    prev_snapshot: str | None,
    initial_snapshot_text: str | None,
    current_url: str,
    page_title: str,
    mcp_tool_specs: list[dict[str, Any]],
    target_url: str | None,
    requirement_context: str,
    budget: TokenBudget,
    estimated_total_steps: int | None = None,
    preferred_locator_candidates: list[dict[str, Any]] | None = None,
) -> tuple[StepRunResult, str]:
    if inputs.execution_strategy not in HYBRID_EXECUTION_STRATEGIES:
        return (
            await _run_ai_step_runner(
                step_runner=step_runner,
                step_description=step_description,
                expected=expected,
                bundle=bundle,
                data_manifest=data_manifest,
                data_resolver=data_resolver,
                prev_snapshot=prev_snapshot,
                initial_snapshot_text=initial_snapshot_text,
                current_url=current_url,
                page_title=page_title,
                mcp_tool_specs=mcp_tool_specs,
                target_url=target_url,
                requirement_context=requirement_context,
                fallback_context=None,
                estimated_total_steps=estimated_total_steps,
            ),
            "ai_step_runner",
        )

    if (
        deterministic_runner is None
        or compiled_step is None
        or compiled_step.kind == UIActionKind.UNSUPPORTED
    ):
        return (
            await _run_ai_step_runner(
                step_runner=step_runner,
                step_description=step_description,
                expected=expected,
                bundle=bundle,
                data_manifest=data_manifest,
                data_resolver=data_resolver,
                prev_snapshot=prev_snapshot,
                initial_snapshot_text=initial_snapshot_text,
                current_url=current_url,
                page_title=page_title,
                mcp_tool_specs=mcp_tool_specs,
                target_url=target_url,
                requirement_context=requirement_context,
                fallback_context=None,
                estimated_total_steps=estimated_total_steps,
            ),
            "ai_step_runner",
        )

    deterministic_result = await _run_deterministic_step(
        bundle=bundle,
        runner=deterministic_runner,
        step=compiled_step,
        preferred_locator_candidates=preferred_locator_candidates,
    )
    if deterministic_result.success:
        return (
            _step_result_from_deterministic(
                step=compiled_step,
                result=deterministic_result,
                tokens_used=budget.consumed,
                execution_path="deterministic",
            ),
            "deterministic",
        )

    fallback_reason = _fallback_reason(deterministic_result)
    fallback_strategy_enabled = (
        inputs.execution_strategy == "hybrid_lightweight_with_fallback"
    )
    if (
        fallback_strategy_enabled
        and deterministic_result.fallback_recommended
        and _ai_fallback_allowed(compiled_step, deterministic_result)
    ):
        # Phase 15.4b: 把 fallback 从"昂贵失败生成器"升级为"strict-JSON 自愈决策".
        # 开关 UI_AI_FALLBACK_SELF_HEAL=True 时优先走 decide_self_heal_action;
        # 关闭则保持 15.4a 行为 (走 step_runner fallback_context 流程).
        from app.config import settings as _settings  # noqa: PLC0415

        if getattr(_settings, "UI_AI_FALLBACK_SELF_HEAL", True):
            self_heal_outcome = await _try_self_heal(
                inputs=inputs,
                bundle=bundle,
                step_runner=step_runner,
                deterministic_runner=deterministic_runner,
                compiled_step=compiled_step,
                step_description=step_description,
                expected=expected,
                deterministic_result=deterministic_result,
                budget=budget,
            )
            if self_heal_outcome is not None:
                return self_heal_outcome

        fallback_context = _build_ai_fallback_context(
            step=compiled_step,
            deterministic_result=deterministic_result,
            rendered_action=step_description,
            rendered_expected=expected,
        )
        logger.info(
            "AI fallback triggered: step=%s action=%s reason=%s",
            compiled_step.source_step_number,
            compiled_step.kind.value,
            fallback_reason,
        )

        # Phase 15.4a: 给 fallback 加 step 级 token 上界, 防"单步烧 80 万 token"
        # 的极端样本. 实现路径: 临时把全局 budget.limit 截到"已消耗 + step_cap",
        # step_runner 内部 over_limit 检查会把 error_kind 设成 budget_exceeded;
        # fallback 返回后再依据增量是否 >= step_cap 把 error_kind 改成
        # fallback_budget_exceeded, 与"全局预算耗尽"区分开.
        from app.config import settings as _settings  # noqa: PLC0415

        original_limit = budget.limit
        consumed_before = budget.consumed
        step_fallback_cap = max(
            1,
            int(getattr(_settings, "STEP_FALLBACK_TOKEN_BUDGET", 50_000) or 50_000),
        )
        budget.limit = min(original_limit, consumed_before + step_fallback_cap)
        try:
            fallback_result = await _run_ai_step_runner(
                step_runner=step_runner,
                step_description=step_description,
                expected=expected,
                bundle=bundle,
                data_manifest=data_manifest,
                data_resolver=data_resolver,
                prev_snapshot=prev_snapshot,
                initial_snapshot_text=initial_snapshot_text,
                current_url=current_url,
                page_title=page_title,
                mcp_tool_specs=mcp_tool_specs,
                target_url=target_url,
                requirement_context=requirement_context,
                fallback_context=fallback_context,
                estimated_total_steps=estimated_total_steps,
            )
        finally:
            budget.limit = original_limit

        consumed_in_fallback = budget.consumed - consumed_before
        if consumed_in_fallback >= step_fallback_cap:
            fallback_result.error_kind = "fallback_budget_exceeded"
            cap_msg = (
                f"AI fallback 触发后超过 step 级 token 上限 "
                f"({consumed_in_fallback}/{step_fallback_cap}) 强制止血"
            )
            fallback_result.error = (
                f"{fallback_result.error}; {cap_msg}"
                if fallback_result.error
                else cap_msg
            )

        fallback_result.tool_calls = [
            _tool_call_from_deterministic(
                step=compiled_step,
                result=deterministic_result,
                execution_path="deterministic_failed",
            ),
            *fallback_result.tool_calls,
        ]
        return fallback_result, "ai_fallback"

    if deterministic_result.fallback_recommended:
        # Phase 15.4a: 把"为什么没进 fallback"分成可观测的细粒度原因落 evidence.
        # 默认 hybrid_lightweight 下整体禁用 -> fallback_strategy_disabled;
        # with_fallback 下走 _ai_fallback_blocked_reason 分类.
        if not fallback_strategy_enabled:
            blocked_reason = "fallback_strategy_disabled"
        else:
            blocked_reason = _ai_fallback_blocked_reason(
                compiled_step,
                deterministic_result,
            )
        logger.info(
            "AI fallback skipped: step=%s action=%s reason=%s original_reason=%s",
            compiled_step.source_step_number,
            compiled_step.kind.value,
            blocked_reason,
            fallback_reason,
        )
        deterministic_result.evidence.details["fallback_reason"] = blocked_reason

    return (
        _step_result_from_deterministic(
            step=compiled_step,
            result=deterministic_result,
            tokens_used=budget.consumed,
            execution_path="deterministic",
        ),
        "deterministic",
    )


async def _try_self_heal(
    *,
    inputs: ExecutionInputs,
    bundle: _BundleLike,
    step_runner: StepRunner,
    deterministic_runner: DeterministicRunner,
    compiled_step: UIActionStep,
    step_description: str,
    expected: str,
    deterministic_result: DeterministicRunResult,
    budget: TokenBudget,
) -> tuple[StepRunResult, str] | None:
    """Phase 15.4b — strict-JSON 自愈决策 + Runner 二次执行.

    返回 None 表示 "self-heal 没接管, 让上游走 15.4a 旧 fallback 兜底"
    (用于 mark_unsupported / 决策失败等需要保留旧路径的场景).

    返回 (result, execution_path) 表示已经接管, 直接落库:
      - retry_with_locator 二次执行成功: execution_path="ai_fallback_self_heal"
      - retry_with_locator 失败: 保留 deterministic verdict, execution_path="deterministic"
      - wait_and_retry 重试成功: execution_path="ai_fallback_self_heal_wait"
      - wait_and_retry 重试仍失败: 保留 deterministic verdict
      - confirm_external_blocked: execution_path="triage_external"
    """
    from app.config import settings as _settings  # noqa: PLC0415

    # tests / 简化 mock 的 step_runner 可能没绑定 llm; 没 llm 就不能调 decide_self_heal,
    # 直接返 None 让 caller 走 15.4a 旧 fallback. 这条 guard 同时也是生产环境下
    # "step_runner 构造异常" 的最后兜底.
    if not getattr(step_runner, "llm", None):
        return None

    snapshot_text: str | None = None
    try:
        page = await _get_or_create_primary_page(bundle)
        if page is not None:
            try:
                snap = await page.content()
                if isinstance(snap, str):
                    snapshot_text = snap[:6000]
            except Exception:  # noqa: BLE001
                snapshot_text = None
    except Exception:  # noqa: BLE001
        snapshot_text = None

    deterministic_evidence_dict: dict[str, Any] = {}
    evidence = getattr(deterministic_result, "evidence", None)
    if evidence is not None:
        for attr in ("error_kind", "details", "message", "selector", "match_strategy"):
            val = getattr(evidence, attr, None)
            if val is not None:
                deterministic_evidence_dict[attr] = val

    deterministic_message = deterministic_evidence_dict.get("message") or _fallback_reason(
        deterministic_result
    )

    # 单轮 LLM 决策, tools=None, tool_choice="none"
    decision = await decide_self_heal_action(
        llm=step_runner.llm,
        step_description=step_description,
        expected=expected or None,
        deterministic_message=str(deterministic_message),
        deterministic_evidence=deterministic_evidence_dict,
        snapshot_text=snapshot_text,
    )

    logger.info(
        "self-heal decision: step=%s action=%s decision=%s candidates=%d",
        compiled_step.source_step_number,
        compiled_step.kind.value,
        decision.decision,
        len(decision.candidate_locators),
    )

    if decision.decision == "retry_with_locator" and decision.candidate_locators:
        retry_result = await _run_deterministic_step(
            bundle=bundle,
            runner=deterministic_runner,
            step=compiled_step,
            extra_locator_candidates=decision.candidate_locators,
        )
        retry_result.evidence.details["self_heal_decision"] = decision.decision
        retry_result.evidence.details["self_heal_rationale"] = decision.rationale
        retry_result.evidence.details["self_heal_candidates"] = decision.candidate_locators
        if retry_result.success:
            step_result = _step_result_from_deterministic(
                step=compiled_step,
                result=retry_result,
                tokens_used=budget.consumed,
                execution_path="ai_fallback_self_heal",
            )
            return step_result, "ai_fallback_self_heal"
        # 二次执行失败 -> 保留**原** deterministic verdict, 把自愈尝试作为审计字段挂上.
        deterministic_result.evidence.details["self_heal_attempted"] = True
        deterministic_result.evidence.details["self_heal_decision"] = decision.decision
        deterministic_result.evidence.details["self_heal_failure"] = (
            retry_result.evidence.error_kind or "self_heal_retry_failed"
        )
        deterministic_result.evidence.details["self_heal_candidates"] = decision.candidate_locators
        return (
            _step_result_from_deterministic(
                step=compiled_step,
                result=deterministic_result,
                tokens_used=budget.consumed,
                execution_path="deterministic",
            ),
            "deterministic",
        )

    if decision.decision == "wait_and_retry":
        wait_ms = max(0, int(getattr(_settings, "UI_AI_FALLBACK_WAIT_MS", 1500) or 0))
        if wait_ms > 0:
            try:
                page = await _get_or_create_primary_page(bundle)
                if page is not None and hasattr(page, "wait_for_timeout"):
                    await page.wait_for_timeout(wait_ms)
                else:
                    await asyncio.sleep(wait_ms / 1000)
            except Exception:  # noqa: BLE001
                # wait 失败不阻塞重试
                pass
        retry_result = await _run_deterministic_step(
            bundle=bundle,
            runner=deterministic_runner,
            step=compiled_step,
        )
        retry_result.evidence.details["self_heal_decision"] = decision.decision
        retry_result.evidence.details["self_heal_rationale"] = decision.rationale
        retry_result.evidence.details["self_heal_wait_ms"] = wait_ms
        if retry_result.success:
            step_result = _step_result_from_deterministic(
                step=compiled_step,
                result=retry_result,
                tokens_used=budget.consumed,
                execution_path="ai_fallback_self_heal_wait",
            )
            return step_result, "ai_fallback_self_heal_wait"
        deterministic_result.evidence.details["self_heal_attempted"] = True
        deterministic_result.evidence.details["self_heal_decision"] = decision.decision
        deterministic_result.evidence.details["self_heal_failure"] = (
            retry_result.evidence.error_kind or "self_heal_wait_failed"
        )
        return (
            _step_result_from_deterministic(
                step=compiled_step,
                result=deterministic_result,
                tokens_used=budget.consumed,
                execution_path="deterministic",
            ),
            "deterministic",
        )

    if decision.decision == "confirm_external_blocked":
        deterministic_result.evidence.details["self_heal_decision"] = decision.decision
        deterministic_result.evidence.details["self_heal_rationale"] = decision.rationale
        deterministic_result.evidence.details["fallback_reason"] = "external_blocked"
        return (
            _step_result_from_deterministic(
                step=compiled_step,
                result=deterministic_result,
                tokens_used=budget.consumed,
                execution_path="triage_external",
            ),
            "triage_external",
        )

    # mark_unsupported / 解析失败:
    #   - 把决策诊断挂到 evidence 上, 但**不**接管, 让 caller 走 15.4a 旧 fallback
    #     (有些 mark_unsupported 实际是 LLM 想给 step_runner 全权处理, 不能直接判失败).
    deterministic_result.evidence.details["self_heal_decision"] = decision.decision
    if decision.parse_error:
        deterministic_result.evidence.details["self_heal_parse_error"] = decision.parse_error
    if decision.rationale:
        deterministic_result.evidence.details["self_heal_rationale"] = decision.rationale
    return None


async def _run_ai_step_runner(
    *,
    step_runner: StepRunner,
    step_description: str,
    expected: str,
    bundle: _BundleLike,
    data_manifest: str,
    data_resolver: TestDataResolver,
    prev_snapshot: str | None,
    initial_snapshot_text: str | None,
    current_url: str,
    page_title: str,
    mcp_tool_specs: list[dict[str, Any]],
    target_url: str | None,
    requirement_context: str,
    fallback_context: dict[str, Any] | None = None,
    estimated_total_steps: int | None = None,
) -> StepRunResult:
    # Phase 15.7: estimated_total_steps 仅用于推算单步 token 软上限,
    # 不影响 step_runner 现有行为; 调用方拿不到 (例如 self_heal 路径) 时传 None
    # 退化为 floor 兜底.
    return await step_runner.run_one(
        step_description=step_description,
        expected=expected,
        bundle=bundle,
        data_manifest=data_manifest,
        data_resolver=data_resolver,
        prev_snapshot=prev_snapshot,
        initial_snapshot_text=initial_snapshot_text,
        current_url=current_url,
        page_title=page_title,
        mcp_tool_specs=mcp_tool_specs,
        target_url=target_url,
        requirement_context=requirement_context,
        fallback_context=fallback_context,
        estimated_total_steps=estimated_total_steps,
    )


async def _run_deterministic_step(
    *,
    bundle: _BundleLike,
    runner: DeterministicRunner,
    step: UIActionStep,
    extra_locator_candidates: list[dict[str, Any]] | None = None,
    preferred_locator_candidates: list[dict[str, Any]] | None = None,
) -> DeterministicRunResult:
    page = await _get_or_create_primary_page(bundle)
    if page is None:
        return DeterministicRunResult(
            success=False,
            fallback_recommended=True,
            evidence={
                "action_kind": step.kind,
                "execution_path": "deterministic",
                "success": False,
                "error_kind": "page_unavailable",
                "message": "no Playwright page available for deterministic execution",
            },
        )
    # Phase 15.4b: self-heal 二次执行时把 LLM 推荐的候选叠在 _build_locator_candidates
    # 末尾, 仍由同一套 strict count==1 / 评分降级二次校验; runner 自己 finally
    # 里清掉, 不会污染下一步.
    # Phase 15.9: 信任 locator (来自最近 N 次 case_result 的交集) 由本函数透
    # 传到 runner.run_step 前置追加 -- 与 extra (AI 自愈) 候选的优先级正好相反.
    return await runner.run_step(
        page,
        step,
        extra_locator_candidates=extra_locator_candidates,
        preferred_locator_candidates=preferred_locator_candidates,
    )


def _signature_to_locator_spec(sig: dict[str, Any]) -> dict[str, Any]:
    """把 ``locator_memory`` 持久化的签名 dict 还原成 deterministic_runner 内部
    ``_extra_candidate_to_make_locator`` 期望的 ``{strategy, value, rationale}``
    spec.

    Phase 15.9: deterministic_runner 复用 self-heal 的 spec 转换器, 因此前置
    候选必须先转成同样形式. 还原约定 (与 ``_extra_candidate_to_make_locator``
    倒推):

    - ``role`` -> value="role:name" (没有 name 时只给 role).
    - ``text`` -> value=text.
    - ``css``  -> value=selector.
    - ``xpath``-> value=selector (前缀 ``xpath=`` 由 runner 内部补).

    其它 strategy 在 ``serialize_locator_signature`` 阶段已经被白名单过滤,
    这里不会拿到.
    """
    strategy = str(sig.get("strategy") or "").strip().lower()
    if strategy == "role":
        role = str(sig.get("role") or "").strip()
        name = str(sig.get("name") or "").strip()
        value = f"{role}:{name}" if name else role
    elif strategy == "text":
        value = str(sig.get("text") or sig.get("name") or "").strip()
    elif strategy == "css":
        value = str(sig.get("selector") or "").strip()
    elif strategy == "xpath":
        value = str(sig.get("selector") or "").strip()
    else:
        value = ""
    return {
        "strategy": strategy,
        "value": value,
        "rationale": "phase15_9_locator_memory",
    }


def _extract_matched_locator_signature(
    run_result: StepRunResult,
) -> dict[str, Any] | None:
    """从 deterministic step 成功执行的 ``tool_calls`` 里抽出命中 locator 的签名.

    Phase 15.9: deterministic_runner 把命中 details 写到了 evidence.details 里,
    ``_step_result_from_deterministic`` 会把 evidence 落到 tool_calls
    (``raw_name='deterministic_runner'``) 的 result.details. 这里反向扒出来
    (兼容 AI fallback / ai_step_runner 路径 -- 它们没 details, 返回 None).
    """
    for tc_ in run_result.tool_calls or []:
        if tc_.raw_name != "deterministic_runner":
            continue
        result = tc_.result if isinstance(tc_.result, dict) else {}
        details = result.get("details") if isinstance(result, dict) else None
        if not isinstance(details, dict):
            continue
        sig = serialize_locator_signature(details)
        if sig:
            return sig
    return None


async def _get_or_create_primary_page(bundle: _BundleLike) -> Any | None:
    get_primary_page = getattr(bundle, "get_primary_page", None)
    if callable(get_primary_page):
        page = get_primary_page()
        if page is not None:
            return page
    context = getattr(bundle, "context", None)
    new_page = getattr(context, "new_page", None)
    if callable(new_page):
        try:
            return await new_page()
        except Exception as exc:  # noqa: BLE001
            logger.warning("create primary page for deterministic runner failed: %s", exc)
    return None


def _step_result_from_deterministic(
    *,
    step: UIActionStep,
    result: DeterministicRunResult,
    tokens_used: int,
    execution_path: str,
) -> StepRunResult:
    error_kind = None
    if not result.success:
        error_kind = (
            "security_blocked"
            if result.evidence.error_kind == "dangerous_action_blocked"
            else "deterministic_failed"
        )
    return StepRunResult(
        success=result.success,
        iterations=1,
        tokens_used=tokens_used,
        reasoning=f"[{execution_path}] {result.evidence.message}",
        final_message=result.evidence.message,
        tool_calls=[
            _tool_call_from_deterministic(
                step=step,
                result=result,
                execution_path=execution_path,
            ),
        ],
        last_snapshot_text=_snapshot_text_from_deterministic(result),
        last_clipped=None,
        error=None if result.success else result.evidence.message,
        error_kind=error_kind,
    )


def _tool_call_from_deterministic(
    *,
    step: UIActionStep,
    result: DeterministicRunResult,
    execution_path: str,
) -> ToolCallRecord:
    details = dict(result.evidence.details or {})
    payload: dict[str, Any] = {
        "execution_path": execution_path,
        "success": result.success,
        "fallback_recommended": result.fallback_recommended,
        "action_kind": result.evidence.action_kind.value,
        "message": result.evidence.message,
        "error_kind": result.evidence.error_kind,
        "details": details,
    }
    structured = details.get("structured_evidence")
    if isinstance(structured, dict):
        payload["structured_evidence"] = structured
    payload["content"] = json.dumps(payload, ensure_ascii=False, default=str)
    return ToolCallRecord(
        name="deterministic_runner",
        raw_name="deterministic_runner",
        arguments={
            "action_kind": step.kind.value,
            "source_step_number": step.source_step_number,
            "source_text": step.source_text,
            "target": step.target.model_dump(mode="json", exclude_none=True),
        },
        result=payload,
        duration_ms=0,
        blocked=not result.success and not result.fallback_recommended,
        error=None if result.success else result.evidence.message,
        snapshot_after_text=_snapshot_text_from_deterministic(result),
        snapshot_after_chars=len(_snapshot_text_from_deterministic(result) or ""),
    )


def _snapshot_text_from_deterministic(result: DeterministicRunResult) -> str:
    evidence = result.evidence
    lines = [
        f"Deterministic action: {evidence.action_kind.value}",
        f"Success: {result.success}",
        f"Message: {evidence.message}",
    ]
    if evidence.error_kind:
        lines.append(f"Error kind: {evidence.error_kind}")
    structured = (evidence.details or {}).get("structured_evidence")
    if isinstance(structured, dict):
        if page_identity := structured.get("page_identity"):
            if isinstance(page_identity, dict):
                if url := page_identity.get("url"):
                    lines.append(f"Page URL: {url}")
                if title := page_identity.get("title"):
                    lines.append(f"Page Title: {title}")
        if page_text := structured.get("page_text"):
            texts = page_text.get("texts") if isinstance(page_text, dict) else []
            if isinstance(texts, list) and texts:
                lines.append("Visible text: " + " | ".join(str(item) for item in texts[:40]))
        if form_fields := structured.get("form_fields"):
            fields = form_fields.get("fields") if isinstance(form_fields, dict) else []
            if isinstance(fields, list) and fields:
                labels = [
                    str(item.get("label") or item.get("placeholder") or item.get("name") or "")
                    for item in fields
                    if isinstance(item, dict)
                ]
                labels = [item for item in labels if item]
                if labels:
                    lines.append("Form fields: " + " | ".join(labels[:30]))
        if table_schema := structured.get("table_schema"):
            columns = (
                table_schema.get("columns") or table_schema.get("visible_columns")
                if isinstance(table_schema, dict)
                else []
            )
            if isinstance(columns, list) and columns:
                lines.append("Table columns: " + " | ".join(str(item) for item in columns[:30]))
        if table_rows := structured.get("table_rows"):
            if isinstance(table_rows, dict):
                rows = table_rows.get("rows")
                row_count = table_rows.get("row_count")
                lines.append(f"Table row_count: {row_count if row_count is not None else 0}")
                if isinstance(rows, list) and rows:
                    lines.append("Table first rows: " + json.dumps(rows[:3], ensure_ascii=False))
    return "\n".join(lines)


def _serialize_tool_call(rec: ToolCallRecord) -> dict[str, Any]:
    return {
        "name": rec.name,
        "raw_name": rec.raw_name,
        "arguments": rec.arguments,
        "duration_ms": rec.duration_ms,
        "blocked": rec.blocked,
        "error": rec.error,
        "snapshot_chars": rec.snapshot_after_chars,
        "result": rec.result,
    }


def _extract_tool_text(result: dict[str, Any]) -> str:
    if not isinstance(result, dict):
        return ""
    content = result.get("content")
    if isinstance(content, str) and content.strip():
        return content.strip()
    raw = result.get("raw")
    if isinstance(raw, list):
        parts = [
            item.get("text", "")
            for item in raw
            if isinstance(item, dict)
            and item.get("type") == "text"
            and isinstance(item.get("text"), str)
        ]
        return "\n".join(p.strip() for p in parts if p.strip())
    return ""


def _build_assertion_context(run_result: StepRunResult) -> str | None:
    """给 AssertionJudge 的证据上下文。

    ``snapshot_after`` 仍按原样落库；断言阶段额外纳入只读工具证据，尤其是
    ``browser_evaluate`` 抽取的表格列名 / DOM 状态。长列表和横向滚动表格
    经常不会完整出现在 accessibility 快照里，只看 snapshot 会误判。
    """
    parts: list[str] = []
    if run_result.last_snapshot_text and run_result.last_snapshot_text.strip():
        parts.append(
            "## Accessibility 快照\n"
            "```text\n"
            f"{run_result.last_snapshot_text.strip()}\n"
            "```"
        )

    for idx, rec in enumerate(run_result.tool_calls, start=1):
        if rec.raw_name not in _ASSERTION_EVIDENCE_TOOLS:
            continue
        text = _extract_tool_text(rec.result)
        if not text:
            continue
        clipped = clip_to_char_limit(
            text,
            max_chars=_ASSERTION_TOOL_RESULT_MAX_CHARS,
        )
        parts.append(
            f"## 工具证据 {idx}: {rec.raw_name}\n"
            "```text\n"
            f"{clipped}\n"
            "```"
        )

    if not parts:
        return run_result.last_snapshot_text
    return clip_to_char_limit(
        "\n\n".join(parts),
        max_chars=_ASSERTION_CONTEXT_MAX_CHARS,
    )


def _extract_structured_assertion_evidence(
    run_result: StepRunResult,
) -> dict[str, Any] | None:
    """Best-effort extraction of structured evidence from whitelisted tool results."""
    out: dict[str, Any] = {}
    for rec in run_result.tool_calls:
        if rec.raw_name not in _ASSERTION_EVIDENCE_TOOLS:
            continue
        text = _extract_tool_text(rec.result)
        if not text:
            continue
        parsed = _extract_first_json_value(text)
        if parsed is None:
            continue
        _merge_structured_evidence(out, parsed)
    return out or None


def _extract_first_json_value(text: str) -> Any:
    decoder = json.JSONDecoder()
    for idx, ch in enumerate(text):
        if ch not in "[{":
            continue
        try:
            value, _end = decoder.raw_decode(text[idx:])
            return value
        except json.JSONDecodeError:
            continue
    return None


def _merge_structured_evidence(out: dict[str, Any], value: Any) -> None:
    if isinstance(value, list):
        columns = _columns_from_list(value)
        if columns:
            out.setdefault("table_schema", {})["columns"] = columns
            out["table_schema"]["visible_columns"] = columns
            out["table_schema"]["total_columns"] = len(columns)
        return

    if not isinstance(value, dict):
        return

    nested = value.get("structured_evidence")
    if isinstance(nested, dict):
        for key in ("table_schema", "table_rows", "form_fields", "console_errors", "page_text"):
            nested_value = nested.get(key)
            if isinstance(nested_value, dict):
                out[key] = nested_value

    for key in ("table_schema", "table_rows", "form_fields", "console_errors", "page_text"):
        direct_value = value.get(key)
        if isinstance(direct_value, dict):
            out[key] = direct_value

    if "columns" in value:
        out["table_schema"] = {
            "table_hint": value.get("table_hint"),
            "columns": value.get("columns") or [],
            "visible_columns": value.get("visible_columns") or value.get("columns") or [],
            "total_columns": value.get("total_columns") or len(value.get("columns") or []),
        }
    if "rows" in value:
        out["table_rows"] = {
            "table_hint": value.get("table_hint"),
            "columns": value.get("columns") or [],
            "rows": value.get("rows") or [],
            "row_count": value.get("row_count") or len(value.get("rows") or []),
            "limit": value.get("limit") or 50,
        }
    if "fields" in value:
        out["form_fields"] = {"fields": value.get("fields") or []}
    if "error_count" in value or "messages" in value:
        out["console_errors"] = {
            "error_count": value.get("error_count") or 0,
            "warning_count": value.get("warning_count") or 0,
            "messages": value.get("messages") or [],
        }


def _columns_from_list(value: list[Any]) -> list[str]:
    if all(isinstance(item, str) for item in value):
        return [item.strip() for item in value if item.strip()]
    columns: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        text = item.get("text") or item.get("label") or item.get("name")
        if isinstance(text, str) and text.strip():
            columns.append(text.strip())
    return columns


def _build_config_snapshot(
    inputs: ExecutionInputs,
    *,
    configured_set_ids: Sequence[uuid.UUID] | None = None,
    compiled_action_plans: list[dict[str, Any]] | None = None,
    preflight_alerts: list[MissingDataAlert] | None = None,
) -> dict[str, Any]:
    snapshot = {
        "testcase_ids": [str(x) for x in inputs.testcase_ids],
        "loaded_set_ids": [str(x) for x in inputs.loaded_set_ids],
        # 「本次显式配置」的物料集 id 列表（验收反馈：用于前端 snapshot
        # 面板做过滤、后端兼容老快照——值为 None / 缺省时按"全部展示"）
        "configured_set_ids": (
            [str(x) for x in configured_set_ids]
            if configured_set_ids is not None
            else None
        ),
        "manual_overrides": dict(inputs.manual_overrides or {}),
        "llm_config_id": str(inputs.llm_config_id) if inputs.llm_config_id else None,
        "token_budget_override": inputs.token_budget_override,
        "strict_data_mode": inputs.strict_data_mode,
        "environment_mode": "direct" if inputs.environment_id is None else "environment",
        "mode": inputs.mode,
        "execution_strategy": inputs.execution_strategy,
        "source": inputs.source,
        "runtime_data_enabled": True,
        "module_entry_overrides": {
            str(k): v for k, v in (inputs.module_entry_overrides or {}).items()
        },
        "compiled_action_plans": list(compiled_action_plans or []),
        "adhoc_title": (
            inputs.adhoc_steps.get("title")
            if inputs.source == "adhoc" and isinstance(inputs.adhoc_steps, dict)
            else None
        ),
        "adhoc_step_count": (
            len(inputs.adhoc_steps.get("steps") or [])
            if inputs.source == "adhoc" and isinstance(inputs.adhoc_steps, dict)
            else None
        ),
    }
    # Phase 15.5: 把缺料 preflight 告警直接持久化到 config_snapshot, 让历史
    # 详情页 / 重试链路在 SSE 之外也能拿到 missing key 列表 (前端用红色徽章展示).
    snapshot["preflight_warnings"] = [
        a.model_dump() for a in (preflight_alerts or [])
    ]
    return snapshot


async def _collect_configured_set_ids(
    *,
    db: "AsyncSession",
    project_id: uuid.UUID,
    environment_id: uuid.UUID | None,
    loaded_set_ids: Sequence[uuid.UUID],
    testcase_ids: Sequence[uuid.UUID],
) -> list[uuid.UUID]:
    """汇总本次执行「显式配置」的物料集 id（保持插入顺序、去重）。

    包含来源：
    1. ``loaded_set_ids``——执行弹窗里勾选的物料集（最直接的"用户配置"）
    2. 当前环境的 ``default_data_set_ids``——环境层「默认加载」的物料集
    3. 用例的 ``default_data_set_ids``——用例层默认绑定的物料集

    **不**包含：personal scope / 普通 project scope 等"被动合并"的物料集。
    snapshot 用这个集合做过滤（serialize_for_audit），让用户只看到他主动
    配置/选中的明细，避免被项目里全部物料淹没（验收反馈）。

    DB 操作失败 / session stub 不支持 query 时，退化为只返回 ``loaded_set_ids``
    （单测会用 ``_FakeSessionContext`` 这种空 stub，不应阻塞 engine 主流程）。
    """
    seen: set[uuid.UUID] = set()
    out: list[uuid.UUID] = []

    def _push(sid: Any) -> None:
        try:
            parsed = uuid.UUID(str(sid))
        except (ValueError, TypeError):
            return
        if parsed in seen:
            return
        seen.add(parsed)
        out.append(parsed)

    # 1. 弹窗勾选——纯内存去重，永远成功
    for sid in loaded_set_ids or []:
        _push(sid)

    # 2/3. DB 查询包在 try/except 里：单测的轻量 session stub 不支持 .execute()
    try:
        from sqlalchemy import select

        from app.modules.testcases.models import Testcase
        from app.modules.ui_automation.models import TestEnvironment

        if environment_id is not None:
            env_row = (
                await db.execute(
                    select(TestEnvironment).where(TestEnvironment.id == environment_id),
                )
            ).scalar_one_or_none()
            if env_row is not None:
                for sid in env_row.default_data_set_ids or []:
                    _push(sid)

        if testcase_ids:
            rows = (
                await db.execute(
                    select(Testcase.default_data_set_ids).where(
                        Testcase.id.in_(list(testcase_ids)),
                        Testcase.project_id == project_id,
                    ),
                )
            ).all()
            for (id_list,) in rows:
                for sid in id_list or []:
                    _push(sid)
    except (AttributeError, TypeError):  # pragma: no cover - 单测兜底
        # session stub / 单元测试场景：保留 loaded_set_ids 即可
        return out
    except Exception:  # pragma: no cover - 真实 DB 异常时不让 snapshot 把整个执行带挂
        logger.exception("_collect_configured_set_ids 查询失败，仅按 loaded_set_ids 返回")
        return out

    return out


def _extract_test_data_used(resolver: TestDataResolver) -> list[dict[str, Any]]:
    """合并后的 keys 列表 + synthetic 标记，作为本用例 test_data_used 落库。"""
    out: list[dict[str, Any]] = []
    for key, item in sorted(resolver.data.items()):
        out.append({
            "key": key,
            "value_type": item.value_type,
            "synthetic": item.synthetic_source is not None,
            "synthetic_source": item.synthetic_source,
        })
    return out


@dataclass
class _ResolverExecutionStub:
    """``TestDataResolver.build`` 期望的 ``ExecutionLike`` 字段子集。"""

    id: uuid.UUID
    project_id: uuid.UUID
    environment_id: uuid.UUID | None
    triggered_by: uuid.UUID | None


@dataclass
class _LLMConfigProto:
    """``StepRunner`` 用的 LLMConfigLike 实体（已解密）。"""

    provider: str
    model: str
    api_key: str | None
    base_url: str | None
    temperature: float
    max_tokens: int


def _build_llm_proto(orm: "LLMConfig | None") -> _LLMConfigProto:
    if orm is None:
        # 走到这里说明 ``_load_llm_config`` 已 fallback 失败 —— 库里一条
        # LLMConfig 都没有。直接抛错让 ExecutionEngine 的 try/except 把整
        # 个 execution 标记为 failed 并写入 error_message，避免用 hardcoded
        # 假配置去打 OpenAI 收 401。
        raise ValueError(
            "未配置任何 LLM；请先到「系统设置 → LLM 配置」创建并设为默认，"
            "或在执行时显式指定 LLM 配置"
        )
    api_key = (
        decrypt(orm.api_key_encrypted) if getattr(orm, "api_key_encrypted", None) else None
    )
    return _LLMConfigProto(
        provider=orm.provider,
        model=orm.model,
        api_key=api_key,
        base_url=getattr(orm, "base_url", None),
        temperature=getattr(orm, "temperature", 0.0) or 0.0,
        max_tokens=getattr(orm, "max_tokens", 2048) or 2048,
    )


async def _open_bundle(
    deps: EngineDeps,
    env: Any,
    execution_id: uuid.UUID,
) -> _BundleLike:
    if deps.open_browser_bundle is not None:
        return await deps.open_browser_bundle(env, execution_id)
    return await _default_open_bundle(env, execution_id)


async def _default_run_preconditions(
    bundle: Any,
    environment: Any,
    llm_config_orm: Any,
) -> list[dict[str, Any]]:
    """生产默认实现：把环境的 ``preconditions`` 列表按 order_index 跑一遍。

    设计要点：
    - 仅 ``ai_login`` / ``state_inject`` 需要 LLM；缺 LLM 时这两类会自动走
      stub 报错，其他类型（``scripted_steps`` / ``cookie_inject``）无影响。
    - 任一模板失败立刻 break；调用方再决定是否中断后续用例（在
      ``_run_inner`` 里我们选择中断）。
    - 截图只在试跑端点返回 base64；这里 ``capture_screenshot=False`` 节省
      payload，本来 ``preconditions_complete`` 事件也不渲染图。
    - state_target 和 credential 解密参考 ``service.test_precondition`` 的
      做法，但不依赖 service 层（避免循环依赖）。
    """
    from app.core.crypto import decrypt
    from app.modules.ui_automation import state_manager
    from app.modules.ui_automation.ai_login_runner import build_ai_login_runner
    from app.modules.ui_automation.precondition_executor import run_precondition

    raw_templates = getattr(environment, "preconditions", None) or []
    templates = sorted(
        [pt for pt in raw_templates if getattr(pt, "enabled", True)],
        key=lambda t: getattr(t, "order_index", 0),
    )
    if not templates:
        return []

    ai_login_runner = build_ai_login_runner(
        llm_config_orm=llm_config_orm,
        environment=environment,
        budget_limit=getattr(environment, "token_budget", 50_000),
    )

    results: list[dict[str, Any]] = []
    for pt in templates:
        creds: dict[str, Any] | None = None
        if pt.credentials_encrypted:
            try:
                creds = json.loads(decrypt(pt.credentials_encrypted))
            except Exception:  # noqa: BLE001
                logger.exception("decrypt precondition credentials failed: %s", pt.id)
                creds = None

        state_target = state_manager.state_path_for(
            environment.id, session_name=environment.session_name,
        )

        async def _on_state_saved(_p: Any) -> None:
            return None  # 持久化由 service.precondition 端点专管，这里只读

        async def _on_state_invalidated() -> None:
            return None

        try:
            result = await run_precondition(
                bundle, pt,
                base_url=environment.base_url,
                state_target=state_target,
                credentials=creds,
                on_state_saved=_on_state_saved,
                on_state_invalidated=_on_state_invalidated,
                ai_login_runner=ai_login_runner,
                capture_screenshot=False,
                save_state_on_success=True,
                # 与试跑端点保持一致：AI 登录的瓶颈在 LLM inference（每轮
                # 30-60s），10 步 ≈ 300-600s。300s 是中等慢度模型下的合理
                # 默认值；scripted/cookie 类型会自然提前完成，超时无副作用。
                per_template_timeout_seconds=300.0,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("run_precondition crashed: %s", pt.id)
            results.append({
                "template_id": str(pt.id),
                "name": pt.name,
                "type": pt.type,
                "success": False,
                "error": f"{type(exc).__name__}: {exc}",
                "error_kind": "browser_error",
                "elapsed_ms": 0,
                "logs": [],
            })
            break

        results.append({
            "template_id": str(result.template_id),
            "name": result.template_name,
            "type": result.type,
            "success": result.success,
            "error": result.error,
            "error_kind": result.error_kind,
            "fell_back_to": result.fell_back_to,
            "elapsed_ms": result.elapsed_ms,
            "state_was_loaded": result.state_was_loaded,
            "state_was_stale": result.state_was_stale,
            "state_was_saved": result.state_was_saved,
            "logs": list(result.logs),
        })
        if not result.success:
            break

    return results


async def _check_stopped(deps: EngineDeps, execution_id: uuid.UUID) -> bool:
    fn = getattr(deps.persistence, "is_execution_stopped", None)
    if fn is None:
        return False
    try:
        return bool(await fn(execution_id))
    except Exception:  # noqa: BLE001
        return False


def _build_adhoc_cases(payload: dict[str, Any] | None) -> list[_AdhocCase]:
    if not isinstance(payload, dict):
        raise ValueError("source=adhoc requires adhoc_steps payload")
    raw_steps = payload.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise ValueError("adhoc_steps.steps must be a non-empty array")
    steps: list[_AdhocStep] = []
    for idx, raw in enumerate(raw_steps, start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"adhoc step {idx} must be an object")
        action = str(raw.get("action") or "").strip()
        if not action:
            raise ValueError(f"adhoc step {idx}.action must not be empty")
        expected = raw.get("expected_result")
        steps.append(
            _AdhocStep(
                step_number=int(raw.get("step_number") or idx),
                action=action,
                expected_result=(
                    str(expected).strip()
                    if expected is not None and str(expected).strip()
                    else None
                ),
            ),
        )
    return [
        _AdhocCase(
            id=None,
            title=str(payload.get("title") or "即席用例"),
            target_url=(
                str(payload.get("target_url")).strip()
                if payload.get("target_url") is not None and str(payload.get("target_url")).strip()
                else None
            ),
            steps=steps,
            required_test_data=list(payload.get("required_test_data") or []),
        ),
    ]


# ─── DB load helpers ─────────────────────────────────────────────────


async def _load_environment(
    db: "AsyncSession", environment_id: uuid.UUID | None,
) -> "TestEnvironment":
    """加载 environment；允许 environment_id=None 时构造一个最小 stub。"""
    if environment_id is None:
        return _MinimalEnvStub()  # type: ignore[return-value]
    from sqlalchemy import select

    from app.modules.ui_automation.models import TestEnvironment

    row = (
        await db.execute(select(TestEnvironment).where(TestEnvironment.id == environment_id))
    ).scalar_one_or_none()
    if row is None:
        raise ValueError(f"environment {environment_id} not found")
    return row


@dataclass
class _MinimalEnvStub:
    """没有指定 environment 时给 SecurityGuard / Bundle 一个最低门槛配置。

    设计取舍：UI 测试理论上必须依附 environment 才有意义；这里只是为了兼
    容"环境未配置但用户通过 chat 触发"的边角场景，让流程不至于卡在 None。
    """

    base_url: str = ""
    allowed_hosts: list[str] = field(
        default_factory=lambda: list(DIRECT_DEFAULT_ALLOWED_HOSTS)
    )
    token_budget: int = DIRECT_DEFAULT_TOKEN_BUDGET
    enable_browser_evaluate: bool = False
    headless: bool = False
    session_name: str | None = None


async def _load_llm_config(
    db: "AsyncSession", llm_config_id: uuid.UUID | None,
) -> "LLMConfig | None":
    """加载 LLM 配置；``llm_config_id=None`` 时回落到默认配置。

    回落优先级：
    1. ``llm_config_id`` 指定的具体配置（找不到 → ``ValueError``）
    2. ``is_default=True`` 的 LLMConfig（最多一条）
    3. 库里第一条 LLMConfig（兜底，按 created_at 排序保证确定性）

    全部为空 → 返回 None；上层 ``_build_llm_proto`` 会抛错并把执行标记为
    failed，让用户在 ExecutionDetail 上看到明确原因（比"用 OpenAI 假 key
    打 401"友好得多）。
    """
    from sqlalchemy import asc, select

    from app.modules.llm.models import LLMConfig

    if llm_config_id is not None:
        row = (
            await db.execute(select(LLMConfig).where(LLMConfig.id == llm_config_id))
        ).scalar_one_or_none()
        if row is None:
            raise ValueError(f"LLM 配置 {llm_config_id} 不存在")
        return row

    default_row = (
        await db.execute(
            select(LLMConfig).where(LLMConfig.is_default.is_(True)).limit(1)
        )
    ).scalar_one_or_none()
    if default_row is not None:
        return default_row

    return (
        await db.execute(select(LLMConfig).order_by(asc(LLMConfig.created_at)).limit(1))
    ).scalar_one_or_none()


async def _load_testcases(
    db: "AsyncSession", testcase_ids: Sequence[uuid.UUID],
) -> list["Testcase"]:
    if not testcase_ids:
        return []
    from sqlalchemy import select

    from app.modules.testcases.models import Testcase

    rows = (
        await db.execute(select(Testcase).where(Testcase.id.in_(list(testcase_ids))))
    ).scalars().all()
    # 保持 inputs 顺序
    by_id = {r.id: r for r in rows}
    ordered: list[Testcase] = []
    for tid in testcase_ids:
        row = by_id.get(tid)
        if row is not None:
            ordered.append(row)
    return ordered


async def _load_module_entry_paths(
    db: "AsyncSession",
    module_ids: Sequence[uuid.UUID],
) -> dict[uuid.UUID, str | None]:
    """一次性把本批用例涉及的所有 module 的 entry_path 拉出来。

    返回 ``{module_id: entry_path | None}``。无 module_id 的用例自然不查；
    查不到（用例所属 module 已被删）也不报错——结果里就是缺这个 key。
    """
    cleaned = list({mid for mid in module_ids if mid is not None})
    if not cleaned:
        return {}
    from sqlalchemy import select

    from app.modules.testcases.models import TestcaseModule

    rows = (
        await db.execute(
            select(TestcaseModule.id, TestcaseModule.entry_path)
            .where(TestcaseModule.id.in_(cleaned))
        )
    ).all()
    return {row[0]: row[1] for row in rows}


def _resolve_target_url(
    *,
    tc: "Testcase",
    environment: Any,
    module_entry_map: dict[uuid.UUID, str | None],
    module_entry_overrides: dict[uuid.UUID, str],
) -> str | None:
    """计算单条用例的 target_url（用于注入 step_runner prompt）。

    优先级：``module_entry_overrides[module_id]`` → ``module.entry_path`` → None

    拼接规则：
    - 入口是绝对 URL（``http://`` / ``https://``）→ 原样使用
    - 入口是相对路径（``/admin/users``）→ 拼到 ``environment.base_url`` 上
    - 入口为空串 / None → 返回 None（prompt 不展示 target_url 块）

    None 含义：让 AI prompt 里没有 target_url 字段，行为退回现状（依赖
    用例 step 的自然语言指令决定目标地址）。这是向后兼容的 fallback。
    """
    adhoc_target = getattr(tc, "target_url", None)
    if adhoc_target:
        return _compose_target_url(str(adhoc_target), environment)

    module_id = getattr(tc, "module_id", None)
    if module_id is None:
        return None

    raw_entry: str | None = None
    if module_id in module_entry_overrides:
        # 显式空串：表示"本次跑该模块时不附带 entry_path"
        ov = (module_entry_overrides[module_id] or "").strip()
        raw_entry = ov or None
    else:
        raw_entry = module_entry_map.get(module_id)
        if raw_entry is not None:
            raw_entry = raw_entry.strip() or None

    if not raw_entry:
        return None

    return _compose_target_url(raw_entry, environment)


def _configure_direct_environment_hosts(
    environment: Any,
    *,
    testcases: Sequence[Any],
    module_entry_map: dict[uuid.UUID, str | None],
    module_entry_overrides: dict[uuid.UUID, str],
) -> None:
    """Direct 模式按产品约定放开浏览器导航域名。

    该模式用于临时开放页面或跨域验证，不复用环境 allowlist；安全边界主要由
    用户在执行弹窗中选择的用例与目标 URL 控制。
    """
    _ = (testcases, module_entry_map, module_entry_overrides)
    setattr(environment, "allowed_hosts", list(DIRECT_DEFAULT_ALLOWED_HOSTS))


def _compose_target_url(raw_entry: str, environment: Any) -> str | None:
    raw_entry = (raw_entry or "").strip()
    if not raw_entry:
        return None
    # 完整 URL（含 scheme）→ 直接用
    if raw_entry.startswith(("http://", "https://")):
        return raw_entry
    base_url = (getattr(environment, "base_url", "") or "").rstrip("/")
    if not base_url:
        return None
    return f"{base_url}/{raw_entry.lstrip('/')}"


# 让 lint 不报"unused import"（用于 type checking 即可）
_ = MissingDataAlert
_ = StepRunResult


__all__ = [
    "EngineDeps",
    "ExecutionEngine",
    "ExecutionInputs",
    "ExecutionOutcome",
]
