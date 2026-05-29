from __future__ import annotations

from datetime import datetime, timezone

from app.modules.dashboard.api_stats import build_api_dashboard_stats


def test_build_api_dashboard_stats_uses_step_counts_without_environment_count() -> None:
    latest = datetime(2026, 5, 28, 10, 30, tzinfo=timezone.utc)

    payload = build_api_dashboard_stats(
        api_test_count=7,
        api_module_count=3,
        api_automation_task_count=4,
        api_automation_enabled_task_count=2,
        api_automation_run_count=5,
        total_steps=20,
        passed_steps=17,
        failed_steps=2,
        avg_elapsed_ms=1234.56,
        latest_run_at=latest,
        api_recent_executions=[
            {
                "id": "run-1",
                "task_id": "task-1",
                "task_name": "登录接口回归",
                "event_at": latest.isoformat(),
            }
        ],
    )

    assert payload == {
        "api_test_count": 7,
        "api_module_count": 3,
        "api_automation_task_count": 4,
        "api_automation_enabled_task_count": 2,
        "api_automation_run_count": 5,
        "api_automation_total_steps": 20,
        "api_automation_passed_steps": 17,
        "api_automation_failed_steps": 2,
        "api_automation_pass_rate": 85.0,
        "api_automation_avg_elapsed_ms": 1235,
        "api_automation_latest_run_at": latest.isoformat(),
        "api_recent_executions": [
            {
                "id": "run-1",
                "task_id": "task-1",
                "task_name": "登录接口回归",
                "event_at": latest.isoformat(),
            }
        ],
    }
    assert "api_environment_count" not in payload


def test_build_api_dashboard_stats_zero_steps_has_zero_pass_rate() -> None:
    payload = build_api_dashboard_stats(
        api_test_count=0,
        api_module_count=0,
        api_automation_task_count=0,
        api_automation_enabled_task_count=0,
        api_automation_run_count=0,
        total_steps=0,
        passed_steps=0,
        failed_steps=0,
        avg_elapsed_ms=None,
        latest_run_at=None,
    )

    assert payload["api_automation_pass_rate"] == 0.0
    assert payload["api_automation_avg_elapsed_ms"] is None
    assert payload["api_automation_latest_run_at"] is None
    assert payload["api_recent_executions"] == []
