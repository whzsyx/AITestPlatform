from __future__ import annotations

from datetime import datetime
from typing import Any


def build_api_dashboard_stats(
    *,
    api_test_count: int | None,
    api_module_count: int | None,
    api_automation_task_count: int | None,
    api_automation_enabled_task_count: int | None,
    api_automation_run_count: int | None,
    total_steps: int | None,
    passed_steps: int | None,
    failed_steps: int | None,
    avg_elapsed_ms: float | int | None,
    latest_run_at: datetime | None,
    api_recent_executions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    steps = int(total_steps or 0)
    passed = int(passed_steps or 0)
    failed = int(failed_steps or 0)
    pass_rate = round((passed / steps) * 100, 2) if steps > 0 else 0.0

    return {
        "api_test_count": int(api_test_count or 0),
        "api_module_count": int(api_module_count or 0),
        "api_automation_task_count": int(api_automation_task_count or 0),
        "api_automation_enabled_task_count": int(api_automation_enabled_task_count or 0),
        "api_automation_run_count": int(api_automation_run_count or 0),
        "api_automation_total_steps": steps,
        "api_automation_passed_steps": passed,
        "api_automation_failed_steps": failed,
        "api_automation_pass_rate": pass_rate,
        "api_automation_avg_elapsed_ms": round(avg_elapsed_ms) if avg_elapsed_ms is not None else None,
        "api_automation_latest_run_at": latest_run_at.isoformat() if latest_run_at else None,
        "api_recent_executions": api_recent_executions or [],
    }
