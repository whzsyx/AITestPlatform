"""仪表盘统计数据 API。"""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.deps import get_current_user, get_db
from app.core.response import success_response
from app.modules.api_testing.models import (
    ApiAutomationRun,
    ApiAutomationTask,
    ApiTestCase,
    ApiTestModule,
)
from app.modules.auth.models import User
from app.modules.dashboard.api_stats import build_api_dashboard_stats
from app.modules.dashboard.ui_stats import (
    get_project_ui_stats,
    get_project_unstable_cases,
)
from app.modules.llm.models import ChatSession
from app.modules.projects.models import Project
from app.modules.requirements.models import AIReview, RequirementDocument
from app.modules.testcases.models import AIGenerationBatch, Testcase, TestcaseModule

router = APIRouter(prefix="/api", tags=["仪表盘"])


@router.get("/dashboard/stats", response_model=dict)
async def get_dashboard_stats(
    project_id: uuid.UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取仪表盘概览统计数据。可按项目筛选。"""
    data = {}

    # ── Project stats ──
    project_count_q = select(func.count()).select_from(Project)
    result = await db.execute(project_count_q)
    data["project_count"] = result.scalar() or 0

    # ── Requirement document stats ──
    doc_q = select(func.count()).select_from(RequirementDocument)
    if project_id:
        doc_q = doc_q.where(RequirementDocument.project_id == project_id)
    result = await db.execute(doc_q)
    data["document_count"] = result.scalar() or 0

    doc_parsed_q = (
        select(func.count())
        .select_from(RequirementDocument)
        .where(RequirementDocument.status == "parsed")
    )
    if project_id:
        doc_parsed_q = doc_parsed_q.where(RequirementDocument.project_id == project_id)
    result = await db.execute(doc_parsed_q)
    data["document_parsed_count"] = result.scalar() or 0

    # ── Review stats ──
    review_q = select(func.count()).select_from(AIReview)
    if project_id:
        review_q = review_q.join(
            RequirementDocument, AIReview.document_id == RequirementDocument.id
        ).where(RequirementDocument.project_id == project_id)
    result = await db.execute(review_q)
    data["review_count"] = result.scalar() or 0

    review_completed_q = (
        select(func.count())
        .select_from(AIReview)
        .where(AIReview.status == "completed")
    )
    if project_id:
        review_completed_q = review_completed_q.join(
            RequirementDocument, AIReview.document_id == RequirementDocument.id
        ).where(RequirementDocument.project_id == project_id)
    result = await db.execute(review_completed_q)
    data["review_completed_count"] = result.scalar() or 0

    avg_score_q = select(func.avg(AIReview.overall_score)).where(
        AIReview.status == "completed", AIReview.overall_score.is_not(None)
    )
    if project_id:
        avg_score_q = avg_score_q.join(
            RequirementDocument, AIReview.document_id == RequirementDocument.id
        ).where(RequirementDocument.project_id == project_id)
    result = await db.execute(avg_score_q)
    avg = result.scalar()
    data["review_avg_score"] = round(avg, 1) if avg else None

    # ── Testcase stats ──
    tc_q = select(func.count()).select_from(Testcase)
    if project_id:
        tc_q = tc_q.where(Testcase.project_id == project_id)
    result = await db.execute(tc_q)
    data["testcase_count"] = result.scalar() or 0

    # By priority
    for priority in ("high", "medium", "low"):
        pq = (
            select(func.count())
            .select_from(Testcase)
            .where(Testcase.priority == priority)
        )
        if project_id:
            pq = pq.where(Testcase.project_id == project_id)
        result = await db.execute(pq)
        data[f"testcase_{priority}_count"] = result.scalar() or 0

    # By source
    tc_manual_q = (
        select(func.count())
        .select_from(Testcase)
        .where(Testcase.source == "manual")
    )
    if project_id:
        tc_manual_q = tc_manual_q.where(Testcase.project_id == project_id)
    result = await db.execute(tc_manual_q)
    data["testcase_manual_count"] = result.scalar() or 0

    tc_ai_q = (
        select(func.count())
        .select_from(Testcase)
        .where(Testcase.source == "ai_generated")
    )
    if project_id:
        tc_ai_q = tc_ai_q.where(Testcase.project_id == project_id)
    result = await db.execute(tc_ai_q)
    data["testcase_ai_count"] = result.scalar() or 0

    # By exec_result
    for er in ("not_run", "passed", "failed", "blocked"):
        eq = (
            select(func.count())
            .select_from(Testcase)
            .where(Testcase.exec_result == er)
        )
        if project_id:
            eq = eq.where(Testcase.project_id == project_id)
        result = await db.execute(eq)
        data[f"testcase_{er}_count"] = result.scalar() or 0

    # ── Module stats ──
    module_q = select(func.count()).select_from(TestcaseModule)
    if project_id:
        module_q = module_q.where(TestcaseModule.project_id == project_id)
    result = await db.execute(module_q)
    data["module_count"] = result.scalar() or 0

    # ── AI generation batch stats ──
    batch_q = select(func.count()).select_from(AIGenerationBatch)
    if project_id:
        batch_q = batch_q.where(AIGenerationBatch.project_id == project_id)
    result = await db.execute(batch_q)
    data["generation_batch_count"] = result.scalar() or 0

    # ── Chat session stats ──
    chat_q = select(func.count()).select_from(ChatSession)
    if project_id:
        chat_q = chat_q.where(ChatSession.project_id == project_id)
    result = await db.execute(chat_q)
    data["chat_session_count"] = result.scalar() or 0

    # ── API management stats ──
    api_case_q = select(func.count()).select_from(ApiTestCase)
    if project_id:
        api_case_q = api_case_q.where(ApiTestCase.project_id == project_id)
    result = await db.execute(api_case_q)
    api_test_count = result.scalar() or 0

    api_module_q = select(func.count()).select_from(ApiTestModule)
    if project_id:
        api_module_q = api_module_q.where(ApiTestModule.project_id == project_id)
    result = await db.execute(api_module_q)
    api_module_count = result.scalar() or 0

    api_task_q = select(func.count()).select_from(ApiAutomationTask)
    if project_id:
        api_task_q = api_task_q.where(ApiAutomationTask.project_id == project_id)
    result = await db.execute(api_task_q)
    api_automation_task_count = result.scalar() or 0

    api_enabled_task_q = (
        select(func.count())
        .select_from(ApiAutomationTask)
        .where(ApiAutomationTask.enabled.is_(True))
    )
    if project_id:
        api_enabled_task_q = api_enabled_task_q.where(ApiAutomationTask.project_id == project_id)
    result = await db.execute(api_enabled_task_q)
    api_automation_enabled_task_count = result.scalar() or 0

    api_run_q = select(
        func.count(ApiAutomationRun.id),
        func.coalesce(func.sum(ApiAutomationRun.total_steps), 0),
        func.coalesce(func.sum(ApiAutomationRun.passed_steps), 0),
        func.coalesce(func.sum(ApiAutomationRun.failed_steps), 0),
        func.avg(ApiAutomationRun.elapsed_ms),
        func.max(func.coalesce(ApiAutomationRun.completed_at, ApiAutomationRun.started_at)),
    ).select_from(ApiAutomationRun)
    if project_id:
        api_run_q = api_run_q.where(ApiAutomationRun.project_id == project_id)
    result = await db.execute(api_run_q)
    (
        api_automation_run_count,
        api_automation_total_steps,
        api_automation_passed_steps,
        api_automation_failed_steps,
        api_automation_avg_elapsed_ms,
        api_automation_latest_run_at,
    ) = result.one()

    api_recent_q = (
        select(ApiAutomationRun)
        .options(selectinload(ApiAutomationRun.task))
        .order_by(
            func.coalesce(
                ApiAutomationRun.completed_at,
                ApiAutomationRun.started_at,
                ApiAutomationRun.created_at,
            ).desc()
        )
        .limit(10)
    )
    if project_id:
        api_recent_q = api_recent_q.where(ApiAutomationRun.project_id == project_id)
    result = await db.execute(api_recent_q)
    api_recent_executions = []
    for run in result.scalars().unique().all():
        event_at = run.completed_at or run.started_at or run.created_at
        total_steps = int(run.total_steps or 0)
        passed_steps = int(run.passed_steps or 0)
        api_recent_executions.append(
            {
                "id": str(run.id),
                "project_id": str(run.project_id),
                "task_id": str(run.task_id),
                "task_name": run.task.name if run.task else None,
                "status": run.status,
                "trigger_type": run.trigger_type,
                "total_steps": total_steps,
                "passed_steps": passed_steps,
                "failed_steps": int(run.failed_steps or 0),
                "skipped_steps": int(run.skipped_steps or 0),
                "elapsed_ms": int(run.elapsed_ms or 0),
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "completed_at": run.completed_at.isoformat() if run.completed_at else None,
                "created_at": run.created_at.isoformat() if run.created_at else None,
                "event_at": event_at.isoformat() if event_at else None,
                "pass_rate": round((passed_steps / total_steps) * 100, 2)
                if total_steps
                else 0.0,
            }
        )

    data.update(
        build_api_dashboard_stats(
            api_test_count=api_test_count,
            api_module_count=api_module_count,
            api_automation_task_count=api_automation_task_count,
            api_automation_enabled_task_count=api_automation_enabled_task_count,
            api_automation_run_count=api_automation_run_count,
            total_steps=api_automation_total_steps,
            passed_steps=api_automation_passed_steps,
            failed_steps=api_automation_failed_steps,
            avg_elapsed_ms=api_automation_avg_elapsed_ms,
            latest_run_at=api_automation_latest_run_at,
            api_recent_executions=api_recent_executions,
        )
    )

    return success_response(data=data)


@router.get("/dashboard/recent-activity", response_model=dict)
async def get_recent_activity(
    project_id: uuid.UUID | None = Query(None),
    limit: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取最近活动记录（最近评审 + 最近生成批次）。"""
    activities: list[dict] = []

    # Recent reviews
    review_q = (
        select(AIReview)
        .options(selectinload(AIReview.document), selectinload(AIReview.reviewer))
        .order_by(AIReview.created_at.desc())
        .limit(limit)
    )
    if project_id:
        review_q = review_q.join(
            RequirementDocument, AIReview.document_id == RequirementDocument.id
        ).where(RequirementDocument.project_id == project_id)
    result = await db.execute(review_q)
    for r in result.scalars().unique().all():
        activities.append({
            "type": "review",
            "id": str(r.id),
            "title": f"评审文档: {r.document.filename}" if r.document else "文档评审",
            "status": r.status,
            "score": r.overall_score,
            "user": (r.reviewer.display_name or r.reviewer.username) if r.reviewer else None,
            "created_at": r.created_at.isoformat(),
        })

    # Recent generation batches
    batch_q = (
        select(AIGenerationBatch)
        .options(selectinload(AIGenerationBatch.document), selectinload(AIGenerationBatch.user))
        .order_by(AIGenerationBatch.created_at.desc())
        .limit(limit)
    )
    if project_id:
        batch_q = batch_q.where(AIGenerationBatch.project_id == project_id)
    result = await db.execute(batch_q)
    for b in result.scalars().unique().all():
        activities.append({
            "type": "generation",
            "id": str(b.id),
            "title": f"生成用例: {b.document.filename}" if b.document else "AI 生成用例",
            "status": b.status,
            "generated_count": b.generated_count,
            "accepted_count": b.accepted_count,
            "user": (b.user.display_name or b.user.username) if b.user else None,
            "created_at": b.created_at.isoformat(),
        })

    # Recent document uploads
    doc_q = (
        select(RequirementDocument)
        .options(selectinload(RequirementDocument.uploader))
        .order_by(RequirementDocument.created_at.desc())
        .limit(limit)
    )
    if project_id:
        doc_q = doc_q.where(RequirementDocument.project_id == project_id)
    result = await db.execute(doc_q)
    for d in result.scalars().unique().all():
        activities.append({
            "type": "upload",
            "id": str(d.id),
            "title": f"上传文档: {d.filename}",
            "status": d.status,
            "user": (d.uploader.display_name or d.uploader.username) if d.uploader else None,
            "created_at": d.created_at.isoformat(),
        })

    # Recent testcase creations
    tc_q = (
        select(Testcase)
        .options(selectinload(Testcase.creator))
        .order_by(Testcase.created_at.desc())
        .limit(limit)
    )
    if project_id:
        tc_q = tc_q.where(Testcase.project_id == project_id)
    result = await db.execute(tc_q)
    for tc in result.scalars().unique().all():
        activities.append({
            "type": "testcase",
            "id": str(tc.id),
            "title": f"创建用例: {tc.title}",
            "status": tc.status,
            "user": (tc.creator.display_name or tc.creator.username) if tc.creator else None,
            "created_at": tc.created_at.isoformat(),
        })

    # Sort combined by created_at desc, take limit
    activities.sort(key=lambda a: a["created_at"], reverse=True)
    activities = activities[:limit]

    return success_response(data=activities)


@router.get("/projects/{project_id}/ui-stats", response_model=dict)
async def get_project_ui_stats_api(
    project_id: uuid.UUID,
    view: str = Query("business", pattern="^(business|execution)$"),
    recent_limit: int = Query(10, ge=1, le=30),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Task 11.1 — 项目维度 UI 自动化统计。

    业务视图（默认）：通过率分母排除"data_failure"用例（因为这些是物料缺失，
    不是被测系统的问题）。执行视图：原始通过率，反映测试基础设施的健康度。
    两个口径同时返回，前端切换无需重新请求。

    返回字段详见 ``app.modules.dashboard.ui_stats.get_project_ui_stats``。
    """
    data = await get_project_ui_stats(
        db,
        project_id,
        current_user,
        view=view,
        recent_limit=recent_limit,
    )
    return success_response(data=data)


@router.get("/projects/{project_id}/ui-stats/unstable-cases", response_model=dict)
async def get_project_unstable_cases_api(
    project_id: uuid.UUID,
    lookback: int = Query(5, ge=1, le=50),
    failure_ratio: float = Query(0.7, ge=0.0, le=1.0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Phase 15.8 — 高频失败用例 (unstable cases) 看板.

    返回最近 ``lookback`` 次执行里失败率 >= ``failure_ratio`` 的 testcase 列表,
    按失败率降序排列, 每项含最近 3 次的状态摘要. 前端 dashboard "高频失败用例"
    卡片消费此端点; 仅展示, 不做"自动移出回归集"破坏性操作.
    """
    data = await get_project_unstable_cases(
        db,
        project_id,
        current_user,
        lookback=lookback,
        failure_ratio=failure_ratio,
    )
    return success_response(data=data)
