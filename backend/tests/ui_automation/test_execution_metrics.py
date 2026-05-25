from __future__ import annotations

from types import SimpleNamespace

from app.modules.ui_automation.execution_metrics import (
    build_execution_metrics,
    extract_step_execution_meta,
    strip_execution_meta_tool_calls,
)


def _step(
    *,
    tool_calls: list[dict] | None = None,
    tokens_used: int = 0,
    duration_ms: int | None = 100,
    assertion_passed: bool | None = True,
    error_message: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        tool_calls=tool_calls or [],
        tokens_used=tokens_used,
        duration_ms=duration_ms,
        assertion_passed=assertion_passed,
        error_message=error_message,
    )


def _meta(path: str, *, llm_calls: int = 0, fallback_reason: str | None = None) -> dict:
    return {
        "name": "execution_meta",
        "raw_name": "execution_meta",
        "arguments": {},
        "result": {
            "execution_path": path,
            "llm_calls": llm_calls,
            "fallback_reason": fallback_reason,
        },
        "duration_ms": 0,
        "blocked": False,
        "error": None,
    }


def test_build_execution_metrics_counts_paths_and_savings() -> None:
    cases = [
        SimpleNamespace(
            duration_ms=900,
            tokens_used=80,
            step_results=[
                _step(
                    tool_calls=[
                        {"raw_name": "deterministic_runner", "result": {"success": True}},
                        _meta("deterministic"),
                    ],
                    tokens_used=0,
                    assertion_passed=True,
                ),
                _step(
                    tool_calls=[
                        {"raw_name": "deterministic_runner", "result": {"success": False}},
                        {"raw_name": "browser_snapshot", "result": {"ok": True}},
                        _meta("ai_fallback", llm_calls=2, fallback_reason="locator_not_found"),
                    ],
                    tokens_used=50,
                    assertion_passed=True,
                ),
                _step(
                    tool_calls=[
                        {"raw_name": "browser_click", "result": {"ok": True}},
                        _meta("ai_only", llm_calls=3),
                    ],
                    tokens_used=30,
                    assertion_passed=False,
                ),
            ],
        ),
    ]

    metrics = build_execution_metrics(cases)

    assert metrics.total_steps == 3
    assert metrics.deterministic_steps == 1
    assert metrics.ai_fallback_steps == 1
    assert metrics.ai_only_steps == 1
    assert metrics.llm_free_steps == 1
    assert metrics.llm_calls == 5
    assert metrics.tool_calls == 2
    assert metrics.tokens == 80
    assert metrics.deterministic_assertion_passes == 1
    assert metrics.ai_fallback_reasons == {"locator_not_found": 1}
    assert metrics.llm_step_reduction_rate == 33
    assert metrics.avg_case_duration_ms == 900


def test_execution_metrics_fallback_for_legacy_steps_without_meta() -> None:
    metrics = build_execution_metrics([
        SimpleNamespace(
            duration_ms=600,
            step_results=[
                _step(
                    tool_calls=[{"raw_name": "deterministic_runner", "result": {"success": True}}],
                    tokens_used=0,
                    assertion_passed=True,
                ),
                _step(
                    tool_calls=[{"raw_name": "browser_click", "result": {"ok": True}}],
                    tokens_used=42,
                    assertion_passed=True,
                    error_message="断言未通过：LLM 返回空内容",
                ),
            ],
        ),
    ])

    assert metrics.deterministic_steps == 1
    assert metrics.ai_only_steps == 1
    assert metrics.llm_calls == 1
    assert metrics.empty_llm_response_steps == 1


def test_extract_and_strip_execution_meta_tool_call() -> None:
    raw_calls = [
        {"raw_name": "browser_snapshot", "result": {"ok": True}},
        _meta("ai_fallback", llm_calls=1, fallback_reason="locator_not_found"),
    ]

    assert extract_step_execution_meta(raw_calls).execution_path == "ai_fallback"
    assert len(strip_execution_meta_tool_calls(raw_calls)) == 1
