"""Derived performance and reliability metrics for UI automation executions."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from pydantic import BaseModel, Field

_META_TOOL = "execution_meta"
_EMPTY_LLM_MARKERS = (
    "LLM 返回空内容",
    "LLM输出为空",
    "empty content",
    "empty response",
)


class StepExecutionMeta(BaseModel):
    execution_path: str | None = None
    fallback_reason: str | None = None
    llm_calls: int = 0


class ExecutionMetrics(BaseModel):
    total_steps: int = 0
    deterministic_steps: int = 0
    ai_fallback_steps: int = 0
    ai_only_steps: int = 0
    llm_free_steps: int = 0
    llm_calls: int = 0
    tool_calls: int = 0
    tokens: int = 0
    deterministic_assertion_passes: int = 0
    empty_llm_response_steps: int = 0
    ai_fallback_reasons: dict[str, int] = Field(default_factory=dict)
    llm_step_reduction_rate: int = 0
    avg_case_duration_ms: int | None = None


def make_execution_meta_tool_call(
    *,
    execution_path: str,
    fallback_reason: str | None = None,
    llm_calls: int = 0,
) -> dict[str, Any]:
    """Return a compact metadata record stored inside ``UIStepResult.tool_calls``.

    This avoids a schema migration while giving history/detail pages a stable
    audit source. API serializers strip this record from the visible tool-call
    timeline so it does not inflate user-facing tool call counts.
    """
    return {
        "name": _META_TOOL,
        "raw_name": _META_TOOL,
        "arguments": {},
        "result": {
            "execution_path": execution_path,
            "fallback_reason": fallback_reason,
            "llm_calls": max(0, int(llm_calls or 0)),
        },
        "duration_ms": 0,
        "blocked": False,
        "error": None,
    }


def extract_step_execution_meta(tool_calls: Sequence[dict[str, Any]] | None) -> StepExecutionMeta:
    for rec in tool_calls or []:
        if not isinstance(rec, dict):
            continue
        if rec.get("raw_name") != _META_TOOL and rec.get("name") != _META_TOOL:
            continue
        result = rec.get("result")
        if not isinstance(result, dict):
            result = {}
        return StepExecutionMeta(
            execution_path=_normalize_execution_path(result.get("execution_path")),
            fallback_reason=(
                str(result.get("fallback_reason"))
                if result.get("fallback_reason") is not None
                else None
            ),
            llm_calls=max(0, _safe_int(result.get("llm_calls"))),
        )
    return StepExecutionMeta()


def strip_execution_meta_tool_calls(
    tool_calls: Sequence[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    return [
        rec
        for rec in list(tool_calls or [])
        if isinstance(rec, dict)
        and rec.get("raw_name") != _META_TOOL
        and rec.get("name") != _META_TOOL
    ]


def build_execution_metrics(cases: Iterable[Any]) -> ExecutionMetrics:
    metrics = ExecutionMetrics()
    case_durations: list[int] = []

    for case in cases:
        duration = getattr(case, "duration_ms", None)
        if isinstance(duration, int) and duration >= 0:
            case_durations.append(duration)

        for step in getattr(case, "step_results", []) or getattr(case, "steps", []) or []:
            _accumulate_step(metrics, step)

    if metrics.total_steps:
        metrics.llm_step_reduction_rate = round(
            (metrics.llm_free_steps / metrics.total_steps) * 100,
        )
    if case_durations:
        metrics.avg_case_duration_ms = round(sum(case_durations) / len(case_durations))
    return metrics


def _accumulate_step(metrics: ExecutionMetrics, step: Any) -> None:
    metrics.total_steps += 1
    raw_tool_calls = list(getattr(step, "tool_calls", []) or [])
    visible_tool_calls = strip_execution_meta_tool_calls(raw_tool_calls)
    meta = extract_step_execution_meta(raw_tool_calls)
    execution_path = meta.execution_path or _infer_execution_path(step, visible_tool_calls)

    if execution_path == "deterministic":
        metrics.deterministic_steps += 1
        metrics.llm_free_steps += 1
        if getattr(step, "assertion_passed", None) is True:
            metrics.deterministic_assertion_passes += 1
    elif execution_path == "ai_fallback":
        metrics.ai_fallback_steps += 1
    else:
        metrics.ai_only_steps += 1

    fallback_reason = meta.fallback_reason or _infer_fallback_reason(visible_tool_calls)
    if execution_path == "ai_fallback" and fallback_reason:
        metrics.ai_fallback_reasons[fallback_reason] = (
            metrics.ai_fallback_reasons.get(fallback_reason, 0) + 1
        )

    tokens = _safe_int(getattr(step, "tokens_used", 0))
    metrics.tokens += max(0, tokens)
    metrics.tool_calls += sum(
        1 for rec in visible_tool_calls if _raw_name(rec) != "deterministic_runner"
    )
    metrics.llm_calls += meta.llm_calls if meta.llm_calls > 0 else _infer_llm_calls(
        execution_path,
        tokens,
    )
    if _looks_like_empty_llm_response(getattr(step, "error_message", None)):
        metrics.empty_llm_response_steps += 1


def _infer_execution_path(step: Any, visible_tool_calls: Sequence[dict[str, Any]]) -> str:
    if any(_raw_name(rec) == "deterministic_runner" for rec in visible_tool_calls):
        has_ai_tools = any(_raw_name(rec) != "deterministic_runner" for rec in visible_tool_calls)
        tokens = _safe_int(getattr(step, "tokens_used", 0))
        if has_ai_tools or tokens > 0:
            return "ai_fallback"
        return "deterministic"
    return "ai_only"


def _infer_fallback_reason(visible_tool_calls: Sequence[dict[str, Any]]) -> str | None:
    for rec in visible_tool_calls:
        if _raw_name(rec) != "deterministic_runner":
            continue
        result = rec.get("result") if isinstance(rec, dict) else None
        if not isinstance(result, dict):
            continue
        details = result.get("details")
        if isinstance(details, dict) and details.get("fallback_reason"):
            return str(details["fallback_reason"])
        if result.get("error_kind"):
            return str(result["error_kind"])
    return None


def _infer_llm_calls(execution_path: str, tokens: int) -> int:
    if execution_path == "deterministic":
        return 0
    return 1 if tokens > 0 else 0


def _normalize_execution_path(value: Any) -> str | None:
    if value in ("deterministic", "ai_fallback", "ai_only"):
        return str(value)
    if value == "ai_step_runner":
        return "ai_only"
    return None


def _raw_name(rec: dict[str, Any]) -> str:
    return str(rec.get("raw_name") or rec.get("name") or "")


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _looks_like_empty_llm_response(value: Any) -> bool:
    text = str(value or "")
    return any(marker in text for marker in _EMPTY_LLM_MARKERS)


__all__ = [
    "ExecutionMetrics",
    "StepExecutionMeta",
    "build_execution_metrics",
    "extract_step_execution_meta",
    "make_execution_meta_tool_call",
    "strip_execution_meta_tool_calls",
]
