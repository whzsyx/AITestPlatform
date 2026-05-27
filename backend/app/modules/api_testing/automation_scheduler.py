"""API 自动化任务轻量调度器。

沿用项目已有 cleanup_scheduler 的进程内 asyncio 方案，避免为了定时执行引入
额外队列或服务。当前 Docker Compose 是单 backend 进程部署；如果未来扩到多
副本，需要把 run_due_api_automation_tasks_once 加 DB 锁或迁移到外部队列。
"""

from __future__ import annotations

import asyncio
import logging

from app.config import settings
from app.modules.api_testing.automation_service import run_due_api_automation_tasks_once

logger = logging.getLogger(__name__)

_api_automation_task: asyncio.Task[None] | None = None


async def _api_automation_loop(interval_seconds: float) -> None:
    while True:
        try:
            await asyncio.sleep(interval_seconds)
        except asyncio.CancelledError:
            logger.info("API automation scheduler cancelled, exiting")
            raise

        try:
            stats = await run_due_api_automation_tasks_once()
            if stats.get("checked"):
                logger.info("API automation scheduled cycle done: %s", stats)
        except asyncio.CancelledError:
            logger.info("API automation scheduler cancelled mid-cycle, exiting")
            raise
        except Exception:  # noqa: BLE001
            logger.exception("API automation scheduled cycle raised")


def start_api_automation_scheduler() -> bool:
    global _api_automation_task
    interval = settings.API_AUTOMATION_SCHEDULER_INTERVAL_SECONDS
    if interval <= 0:
        logger.info("API automation scheduler disabled")
        return False
    if _api_automation_task is not None and not _api_automation_task.done():
        return False
    _api_automation_task = asyncio.create_task(
        _api_automation_loop(float(interval)),
        name="api-automation-cron",
    )
    logger.info("API automation scheduler started (interval=%ss)", interval)
    return True


async def stop_api_automation_scheduler() -> None:
    global _api_automation_task
    task = _api_automation_task
    if task is None or task.done():
        _api_automation_task = None
        return
    task.cancel()
    try:
        await task
    except (asyncio.CancelledError, Exception):  # noqa: BLE001
        pass
    finally:
        _api_automation_task = None
        logger.info("API automation scheduler stopped")


__all__ = [
    "start_api_automation_scheduler",
    "stop_api_automation_scheduler",
]
