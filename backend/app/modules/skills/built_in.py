"""内置 ``system_*`` skill 同步（Task 12.4）。"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.skills.builtin.failure_diagnosis.tools import FAILURE_DIAGNOSIS_TOOL_NAMES
from app.modules.skills.models import Skill, SkillSafetyScan, SkillVersion
from app.modules.skills.safety_scanner import SafetyScanner

#: Phase 13：内置 SKILL 文案/触发策略版本。版本号变更触发
#: ``sync_built_in_skills`` 幂等重写已有项目内置 skill。
SYSTEM_SKILLS_VERSION = "2.3"

_EXPECTED_SLUGS = frozenset({
    "system_ui_automation",
    "system_failure_diagnosis",
    "system_requirement_review",
    "system_testcase_generation",
})


@dataclass(frozen=True, slots=True)
class _BuiltinSpec:
    name: str
    slug: str
    description: str
    body: str
    triggers: list[str]
    tools_required: list[str]
    activation_mode: str
    category: str
    extra_metadata: dict


_BODY_UI = """# UI 自动化（内置 · Phase 13）

AI 对话触发 UI 自动化入口已停用。用例执行只从"用例管理"页面的执行入口发起。

## 何时使用

不要在 AI 对话中使用本技能。若用户在对话里要求"跑用例 / 执行 UI 自动化"，
请提示用户前往"用例管理"页面选择用例后点击执行。

## 兼容说明

后端仍保留 ``system__ui_automation__*`` 工具实现和 UI 执行 API，供历史计划、
内部调试和用例管理执行链路兼容；这些工具不再暴露给 AI 对话路由。
"""

_BODY_FAILURE_DIAGNOSIS = """# UI 执行失败诊断（内置 · Phase 13）

仅在用户主动询问"为什么失败"、"诊断下"、"帮我看下错误"等场景使用。
不要在每次执行失败后自动展开，避免打扰正常执行链路。

## 何时使用

- 用户明确说"诊断 / 为什么失败 / 没跑通怎么办 / 看下错误"。
- 用户指向某个 UI 执行任务并要求解释失败原因或给出修复建议。

## 标准诊断顺序

1. ``system__failure_diagnosis__get_execution_detail``：读取执行、用例、步骤、
   物料快照与整体错误信息。
2. ``system__failure_diagnosis__get_step_screenshots``：查看失败步骤截图与页面
   快照摘要。
3. ``system__failure_diagnosis__get_failed_step_trace``：查看失败步骤 tool_call、
   AI reasoning 与断言证据。
4. ``system__failure_diagnosis__propose_fix_action``：输出前端可渲染的
   FixActionCard meta。

## 安全约束

- 所有诊断输出都必须保持 secret 脱敏；不要复述密码、token、cookie、API key。
- 本 skill 只提出修复动作，不直接重新执行任务；重试必须重新生成计划并由用户确认。
"""

_BODY_REVIEW = """# 需求评审（兼容占位）

> **deprecated_path**：实际评审由一期 ``review_service`` / 对话意图快通道完成。
> 本 skill 仅用于 ClawHub 导出兼容与平台能力清单展示；**不要依赖本 skill 触发评审**。
"""

_BODY_GEN = """# 测试用例生成（兼容占位）

> **deprecated_path**：实际生成由一期生成意图快通道完成。
> 本 skill 仅用于导出兼容展示；**不要依赖本 skill 触发生成**。
"""


def _scan_notes(findings: list) -> str | None:
    if not findings:
        return None
    first = findings[0]
    if isinstance(first, dict):
        return str(first.get("snippet", ""))[:500]
    return None


BUILTIN_SPECS: tuple[_BuiltinSpec, ...] = (
    _BuiltinSpec(
        name="内置 · UI 自动化",
        slug="system_ui_automation",
        description=(
            "AI 对话触发入口已停用；UI 自动化执行请从用例管理页面发起。"
        ),
        body=_BODY_UI,
        triggers=[],
        tools_required=[],
        activation_mode="agent_callable",
        category="system",
        extra_metadata={},
    ),
    _BuiltinSpec(
        name="内置 · UI 执行失败诊断",
        slug="system_failure_diagnosis",
        description=(
            "在用户主动询问失败原因时读取执行详情、截图和失败步骤 trace，"
            "输出结构化 FixActionCard 修复建议。"
        ),
        body=_BODY_FAILURE_DIAGNOSIS,
        triggers=[
            "失败",
            "为什么没跑通",
            "诊断",
            "怎么办",
            "看下错误",
            "帮我看下",
        ],
        tools_required=list(FAILURE_DIAGNOSIS_TOOL_NAMES),
        activation_mode="agent_callable",
        category="system",
        extra_metadata={},
    ),
    _BuiltinSpec(
        name="内置 · 需求评审（占位）",
        slug="system_requirement_review",
        description="deprecated_path：评审走一期意图通道；本条目仅为兼容导出。",
        body=_BODY_REVIEW,
        triggers=[],
        tools_required=[],
        activation_mode="manual",
        category="system",
        extra_metadata={"deprecated_path": True},
    ),
    _BuiltinSpec(
        name="内置 · 用例生成（占位）",
        slug="system_testcase_generation",
        description="deprecated_path：生成走一期意图通道；本条目仅为兼容导出。",
        body=_BODY_GEN,
        triggers=[],
        tools_required=[],
        activation_mode="manual",
        category="system",
        extra_metadata={"deprecated_path": True},
    ),
)


def _bundle_meta(spec: _BuiltinSpec) -> dict:
    m = dict(spec.extra_metadata)
    m["_system_bundle_version"] = SYSTEM_SKILLS_VERSION
    m["_builtin_slug"] = spec.slug
    return m


async def sync_built_in_skills(
    db: AsyncSession,
    project_id: uuid.UUID,
    *,
    created_by: uuid.UUID,
) -> int:
    """幂等：缺失或版本不一致时重写本项目全部内置 skill。返回新建条数。"""
    stmt = select(Skill).where(Skill.project_id == project_id, Skill.source == "built_in")
    existing = list((await db.execute(stmt)).scalars().all())

    need_rewrite = False
    if not existing:
        need_rewrite = True
    elif len(existing) != len(BUILTIN_SPECS):
        need_rewrite = True
    elif {s.slug for s in existing} != _EXPECTED_SLUGS:
        need_rewrite = True
    else:
        for s in existing:
            ver = (s.extra_metadata or {}).get("_system_bundle_version")
            if ver != SYSTEM_SKILLS_VERSION:
                need_rewrite = True
                break

    if not need_rewrite:
        return 0

    await db.execute(delete(Skill).where(Skill.project_id == project_id, Skill.source == "built_in"))
    await db.flush()

    scanner = SafetyScanner()
    created = 0
    for spec in BUILTIN_SPECS:
        scan = scanner.scan(spec.body, _bundle_meta(spec))
        findings = [f.as_dict() for f in scan.findings]
        scan_status = scan.status
        is_enabled = scan_status != "blocked"

        skill = Skill(
            project_id=project_id,
            name=spec.name[:200],
            slug=spec.slug[:100],
            description=spec.description,
            semantic_version="1.0.0",
            category=spec.category[:50],
            tags=[],
            triggers=list(spec.triggers),
            tools_required=list(spec.tools_required),
            activation_mode=spec.activation_mode,
            body=spec.body,
            extra_metadata=_bundle_meta(spec),
            attachments=[],
            source="built_in",
            source_url=None,
            is_enabled=is_enabled,
            safety_scan_status=scan_status,
            safety_scan_notes=_scan_notes(findings),
            db_version=1,
            created_by=created_by,
        )
        db.add(skill)
        await db.flush()

        sv = SkillVersion(
            skill_id=skill.id,
            db_version=skill.db_version,
            body=skill.body,
            extra_metadata=dict(skill.extra_metadata),
            change_note="built_in_sync",
            created_by=created_by,
        )
        db.add(sv)
        db.add(
            SkillSafetyScan(
                skill_id=skill.id,
                skill_db_version=skill.db_version,
                status=scan_status,
                findings=findings,
                scanner_version=SafetyScanner.VERSION,
            ),
        )
        created += 1

    await db.flush()
    return created
