"""ConfirmationCard / ExecutionPlan 数据契约（Phase 13 / Task 13.1）。

设计依据：``docs/PHASE3_DESIGN.md §10.3.2 / §10.7 / §10.8`` 与
``docs/PHASE3_IMPLEMENTATION_PLAN.md Task 13.1``。

本模块定义"agent → 前端 ConfirmationCard 协议"的全部 Pydantic 类型；UI
自动化查询 / 解析 / propose tools 的返回都基于此。schema 字段全部显式声明 + 文档化，
方便 OpenAPI 暴露给前端 / Swagger UI 直接生成 TS 类型。

关键不变量：
- ``run_ui_test`` 不在 LLM tool list 中——LLM 只能调 ``propose_execution_plan``
  生成 plan_id；用户在前端 ConfirmationCard 上点"确认执行"后，由前端走专门
  的 ``POST /api/ui-executions { plan_id, ... }`` API 真正派发（task 13.3 接通）。
- ``risk_level`` 来自 ``ui_environments.risk_level``；老桩缺字段时后端仍会
  启发式兜底，协议本身保持不变。
"""

from __future__ import annotations

import uuid
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field

# ─────────────────── 枚举 ───────────────────


class ConfirmationStrength(str, Enum):
    """ConfirmationCard 确认强度。

    设计 §10.3.2：
    - ``NONE``：自动开始（low 风险 + 单一候选）；前端不弹按钮，1s 倒计时后派发
    - ``SOFT``：单按钮"确认执行"（默认）
    - ``STRICT``：必须输入挑战短语（如 "YES PROD"）+ "我已知晓风险"勾选；high
      风险或批量删除等高危操作必走
    """

    NONE = "none"
    SOFT = "soft"
    STRICT = "strict"


class EnvRiskLevel(str, Enum):
    """环境风险分级。

    Phase 13 / Task 13.5 后由 ``ui_environments.risk_level`` 配置驱动；旧数据
    / 单测桩缺字段时后端仍保留启发式兜底。
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


# ─────────────────── 子结构 ───────────────────


class CaseSummary(BaseModel):
    """ConfirmationCard 中渲染的单条用例摘要。

    M1：``relevance_score`` / ``matched_via`` 仅在 search_test_cases 调用链中
    填充；propose_execution_plan 拿到 case 后会把 score 透传到 plan 里供前端
    排序与"为什么命中此用例"提示。
    """

    id: uuid.UUID = Field(..., description="用例 UUID（DB 主键）")
    case_no: int = Field(..., description="项目内递增编号；前端用 TC-{:04d} 渲染")
    title: str = Field(..., description="用例标题")
    priority: str = Field("medium", description="用例优先级 (high/medium/low)")
    status: str = Field("active", description="用例状态 (active / archived ...)")
    relevance_score: float | None = Field(
        None,
        description="search_test_cases 命中得分 [0, 1]；propose 阶段透传",
    )
    matched_via: list[str] = Field(
        default_factory=list,
        description=(
            "命中策略列表（id_exact / title_fulltext / tag_match / step_content / "
            "recent_fallback）；前端可据此显示'通过 xx 命中'徽章"
        ),
    )


class TestcaseModuleSummary(BaseModel):
    """UI 自动化执行前供用户选择的用例模块摘要。"""

    id: uuid.UUID = Field(..., description="模块 UUID，后续 search_test_cases.module_id 使用")
    name: str = Field(..., description="模块名")
    path: str = Field(..., description="完整模块路径，如 '店铺管理 / 列表字段'")
    parent_id: uuid.UUID | None = Field(None, description="父模块 UUID")
    depth: int = Field(0, ge=0, description="树深度，顶层为 0")
    case_count: int = Field(0, ge=0, description="模块自身与后代模块的用例总数")
    entry_path: str | None = Field(None, description="模块入口路径，可为空")


class EnvironmentSummary(BaseModel):
    """ConfirmationCard 中渲染的执行环境摘要。"""

    id: uuid.UUID = Field(..., description="环境 UUID")
    name: str = Field(..., description="环境名（用于人类辨识）")
    base_url: str = Field(..., description="目标根 URL（含 scheme）")
    risk_level: EnvRiskLevel = Field(
        EnvRiskLevel.LOW,
        description="风险等级；优先读 ui_environments.risk_level，缺字段时启发式兜底",
    )
    risk_reason: str | None = Field(
        None,
        description="为什么判为该 risk（前端 tooltip 用），如 'name 含 prod'",
    )


class LLMProviderSummary(BaseModel):
    """ConfirmationCard 中显示的 LLM provider 摘要。"""

    id: uuid.UUID | None = Field(
        None, description="LLMConfig UUID；None 表示用项目默认配置",
    )
    name: str = Field(..., description="配置展示名（如 'DeepSeek Chat'）")
    provider: str = Field(..., description="provider 标识（openai / deepseek / qwen ...）")
    model: str = Field(..., description="model 名称")


class TestDataPreviewItem(BaseModel):
    """物料预览单项（含来源溯源）。

    Phase 13 / Task 13.5：按用例 ``required_test_data`` 与物料项 ``semantic``
    匹配；无声明时退回安全的合并物料摘要。
    """

    __test__ = False  # 避免 pytest 把"Test"开头的类当测试类收集


    semantic: str | None = Field(
        None, description="物料项语义标签（M2 后启用；M1 固定为 None）",
    )
    key: str = Field(..., description="原始 key（步骤模板 ``{{key}}`` 引用名）")
    value_preview: str = Field(
        ...,
        description="值预览：secret 项一律返回 ``<masked>``；普通项最长 64 字符",
    )
    source: str = Field(
        ...,
        description="来源溯源描述，如 '测试环境-默认账号集 #12'",
    )
    source_set_id: uuid.UUID | None = Field(
        None, description="来源 test_data_sets.id（前端可点击跳转）",
    )
    is_secret: bool = Field(
        False, description="是否敏感字段（前端显示 mask + 点击查看权限校验）",
    )


class TestDataPreview(BaseModel):
    """ConfirmationCard 中物料区整体预览。"""

    __test__ = False  # 避免 pytest 把"Test"开头的类当测试类收集


    items: list[TestDataPreviewItem] = Field(
        default_factory=list,
        description="按用例需要的物料项列出（M1 走默认物料集首批）",
    )
    missing_semantics: list[str] = Field(
        default_factory=list,
        description="缺失的语义清单，前端高亮提示 '请补 / 自动生成'",
    )
    set_summaries: list[dict[str, Any]] = Field(
        default_factory=list,
        description="本次预览用到的物料集摘要 ``[{id, name, scope, item_count}]``",
    )


class RuntimeDataEdge(BaseModel):
    """用例间数据流转的单条边。Task 13.7 接入。"""

    from_case_id: uuid.UUID
    to_case_id: uuid.UUID
    runtime_keys: list[str]


class AdhocStepDraft(BaseModel):
    """即席用例草稿中的单个步骤（Task 13.6）。"""

    step_number: int = Field(..., ge=1, le=200, description="步骤序号，从 1 开始")
    action: str = Field(..., min_length=1, max_length=2_000, description="操作描述")
    expected_result: str | None = Field(
        None, max_length=2_000, description="预期结果 / 断言描述",
    )


class AdhocCaseDraft(BaseModel):
    """即席执行草稿。只在用户确认执行后写入 ``ui_executions.adhoc_steps``。"""

    title: str = Field(..., min_length=1, max_length=200)
    target_url: str | None = Field(
        None,
        max_length=2_000,
        description="可选入口 URL；相对路径会在 Engine 中拼到环境 base_url",
    )
    steps: list[AdhocStepDraft] = Field(default_factory=list, min_length=1, max_length=50)
    required_test_data: list[dict[str, Any]] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list, max_length=20)
    draft_confidence: float = Field(
        0.5, ge=0.0, le=1.0, description="草稿置信度；低于 0.6 必须 STRICT 确认",
    )


# ─────────────────── 4 个 tool 的返回结构 ───────────────────


class SearchTestCasesResult(BaseModel):
    """``system__ui_automation__search_test_cases`` 返回结构。"""

    count: int = Field(..., description="命中数")
    cases: list[CaseSummary] = Field(default_factory=list)
    query: str | None = Field(None, description="实际搜索关键字（截断后）")
    module_id: uuid.UUID | None = Field(None, description="本次搜索限定的模块 UUID")
    requires_module_selection: bool = Field(
        False,
        description="True 表示用户指令过泛，应先列模块并让用户选择模块",
    )
    message: str | None = Field(None, description="给 LLM/用户的下一步提示")


class ListTestcaseModulesResult(BaseModel):
    """``system__ui_automation__list_testcase_modules`` 返回结构。"""

    count: int = Field(..., description="返回的模块数量")
    modules: list[TestcaseModuleSummary] = Field(default_factory=list)
    query: str | None = Field(None, description="模块过滤关键字")


class ResolvedEnvironmentDefault(BaseModel):
    """``list_environments`` 附带返回的"5 层优先级解析"结果。

    Phase 13 / Task 13.2：让 LLM 不必自己跑决策树，后端直接给一个
    ``recommended_environment_id``——AI 理论上应优先用此 id 作为
    ``propose_execution_plan`` 的 ``environment_id`` 参数；只有用户明确说
    "不是这个 / 切到 xxx" 时才覆盖。
    """

    environment_id: uuid.UUID | None = Field(
        None,
        description="推荐环境 UUID；missing=True 时为 None，由 LLM 反问用户",
    )
    name: str | None = Field(None, description="推荐环境名（人类可读）")
    layer: str = Field(
        ...,
        description=(
            "命中层级：user_explicit / session_bound / project_default / "
            "user_history / fallback_low_risk / none"
        ),
    )
    reason: str = Field("", description="为什么是这条；前端 tooltip / 卡片副标题用")
    missing: bool = Field(False, description="True 表示无法解析，需要让用户选")


class ListEnvironmentsResult(BaseModel):
    """``system__ui_automation__list_environments`` 返回结构。"""

    count: int = Field(...)
    environments: list[EnvironmentSummary] = Field(default_factory=list)
    resolved_default: ResolvedEnvironmentDefault | None = Field(
        None,
        description=(
            "5 层优先级解析得到的推荐默认环境；AI 应优先采用此环境 id。"
            "若 ``missing=True`` 表示无法解析，LLM 必须反问用户选环境。"
        ),
    )


class TestDataSetSummary(BaseModel):
    """list_test_data_sets 返回的单条物料集摘要。"""

    __test__ = False  # 避免 pytest 把"Test"开头的类当测试类收集


    id: uuid.UUID
    name: str
    description: str | None = None
    category: str | None = None
    purpose: str | None = None
    tags: list[str] = Field(default_factory=list)
    scope: Literal["project", "environment", "personal"] = "project"
    environment_id: uuid.UUID | None = None
    is_default: bool = False
    item_count: int = Field(..., description="物料项条数（不含 secret 内容）")


class ListTestDataSetsResult(BaseModel):
    """``system__ui_automation__list_test_data_sets`` 返回结构。"""

    count: int = Field(...)
    test_data_sets: list[TestDataSetSummary] = Field(default_factory=list)


class ExecutionPlanCard(BaseModel):
    """ConfirmationCard 主体协议（``propose_execution_plan`` 返回的核心 payload）。

    前端 ``ConfirmationCard.vue`` 直接消费此结构。``plan_id`` 由后端缓存，
    前端"确认执行"按钮触发 ``POST /api/ui-executions { plan_id, source: 'chat',
    triggered_chat_session_id }`` 时只送 plan_id，避免用户在前端篡改其它字段
    冒充已确认的 plan。
    """

    kind: Literal["case_plan", "adhoc_plan"] = Field(
        "case_plan",
        description="确认卡类型：正式用例执行计划 / 即席步骤草稿计划",
    )
    plan_id: uuid.UUID = Field(
        ...,
        description="后端缓存的 plan 标识；TTL 10 分钟。前端 confirm 时仅送此 id",
    )
    project_id: uuid.UUID
    cases: list[CaseSummary] = Field(
        default_factory=list,
        description="本次执行计划包含的用例（多用例时支持前端调整顺序）",
    )
    adhoc_case: AdhocCaseDraft | None = Field(
        None,
        description="kind=adhoc_plan 时前端渲染并允许编辑的即席步骤草稿",
    )
    environment: EnvironmentSummary
    llm_provider: LLMProviderSummary
    test_data_preview: TestDataPreview
    estimated_duration_seconds: int = Field(
        ...,
        description="粗略估算总耗时（cases × 每用例 baseline）",
    )
    confirmation_strength: ConfirmationStrength = Field(...)
    confirmation_payload: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "strict 强度下含 ``challenge`` / ``message`` 等字段；"
            "soft / none 下为空字典"
        ),
    )
    runtime_data_flow: list[RuntimeDataEdge] | None = Field(
        None, description="多用例计划中的 runtime_data 流转边；无依赖时为 None",
    )
    expires_at: str | None = Field(
        None,
        description="plan_id 过期时间 ISO8601；前端可据此提示用户尽快确认",
    )
    # Phase 13 / Task 13.3 —— skill_card 落库后会把对应 chat_messages.id 写到这里，
    # 前端"确认执行"成功后用这个 id **原地变身** 当前消息为 task_badge（避免用户
    # 看到两条消息）。LLM 看不到也用不到此字段；仅前端消费。
    skill_card_message_id: uuid.UUID | None = Field(
        None,
        description=(
            "Phase 13 / Task 13.3 — kind=skill_card 消息 id；前端 confirm 后"
            "用此 id 把当前 ConfirmationCard 原地变成 TaskBadge"
        ),
    )


__all__ = [
    "AdhocCaseDraft",
    "AdhocStepDraft",
    "CaseSummary",
    "ConfirmationStrength",
    "EnvironmentSummary",
    "EnvRiskLevel",
    "ExecutionPlanCard",
    "ListEnvironmentsResult",
    "ListTestcaseModulesResult",
    "ListTestDataSetsResult",
    "LLMProviderSummary",
    "ResolvedEnvironmentDefault",
    "RuntimeDataEdge",
    "SearchTestCasesResult",
    "TestDataPreview",
    "TestDataPreviewItem",
    "TestDataSetSummary",
    "TestcaseModuleSummary",
]
