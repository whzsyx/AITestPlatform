"""Post-step failure triage and safe self-heal for UI automation.

This module intentionally stays evidence-first: it may only turn a failed
verdict into passed when the captured page evidence already satisfies a narrow,
auditable expectation. Otherwise it rewrites low-signal failures into clearer
diagnostic messages without hiding the failure.
"""

from __future__ import annotations

import json
import re
from urllib.parse import urlparse

from app.modules.ui_automation.assertion_judge import AssertionVerdict
from app.modules.ui_automation.step_runner import StepRunResult

_EXTERNAL_VERIFICATION_TERMS = (
    "安全验证",
    "验证码",
    "滑块验证",
    "请完成下方验证",
    "人机验证",
    "verify you are human",
    "captcha",
)
_OBSERVE_ONLY_RE = re.compile(r"^(?:查看|检查|确认|验证|核对)")
_DEPENDENT_STATE_RE = re.compile(
    r"结果页|搜索后|再次|仍|保留|当前结果|已有|已出现|继续|返回后|列表刷新后"
)
_ACTION_SETUP_RE = re.compile(r"输入|填写|填入|录入|点击|单击|搜索|提交|访问|打开|进入|跳转")
_QUOTED_RE = re.compile(r"[「“\"']([^」”\"']+)[」”\"']")
_TITLE_CONTAINS_RE = re.compile(r"标题(?:或页面内显著标题)?包含(?P<value>.+?)(?:，|,|且|。|$)")
_BUTTON_RE = re.compile(r"[「“\"']([^」”\"']+)[」”\"']按钮")
_PAGE_URL_RE = re.compile(r"Page URL:\s*(\S+)", re.IGNORECASE)


def triage_step_failure(
    *,
    verdict: AssertionVerdict,
    run_result: StepRunResult,
    step_description: str,
    expected: str,
    target_url: str | None = None,
) -> AssertionVerdict:
    """Return a safer and more useful verdict for common low-level failures."""
    if verdict.passed:
        return verdict

    context = _build_context(run_result)
    if _has_external_verification(context):
        # Phase 15.8: 命中外部反爬时, 不仅把单步 verdict 改写得更友好, 还要置
        # ``early_terminate=True`` 信号, 让 ExecutionEngine 把整条 case 剩余
        # 步骤全部跳过 -- 历史上 5 条百度搜索类用例 4 周累计 16 次 100% 失败,
        # 22 个 captcha 阻断步骤全部来自这 5 条用例, 继续跑只会浪费 token.
        # 该信号可由 ``UI_EARLY_TERMINATE_ON_CAPTCHA=false`` 关掉, 退化为 15.7
        # 之前的 "判失败但继续跑下一步" 行为.
        from app.config import settings as _settings  # noqa: PLC0415

        early_terminate = bool(
            getattr(_settings, "UI_EARLY_TERMINATE_ON_CAPTCHA", True)
        )
        return AssertionVerdict(
            passed=False,
            reason=(
                "外部安全验证/验证码阻断了页面验证，当前失败不能证明被测功能异常；"
                "建议改用稳定测试环境、登录态/代理白名单，或避开公开搜索引擎反爬页面。"
            ),
            evidence=_first_matching_line(context, _EXTERNAL_VERIFICATION_TERMS),
            method=verdict.method,
            early_terminate=early_terminate,
            early_terminate_reason=(
                "external_verification_blocked" if early_terminate else None
            ),
        )

    if _page_load_expectation_satisfied(expected, context):
        return AssertionVerdict(
            passed=True,
            reason=(
                "自愈通过：原始操作或断言失败，但执行后页面证据已满足本步骤预期。"
            ),
            evidence="页面已满足预期：" + _page_evidence_summary(expected, context),
            method="deterministic",
        )

    if _looks_like_missing_precondition(
        step_description=step_description,
        expected=expected,
        context=context,
        target_url=target_url,
    ):
        return AssertionVerdict(
            passed=False,
            reason=(
                "用例缺少前置操作：当前步骤依赖搜索/跳转/结果页等前序状态，"
                "但 UI 自动化会从模块入口开始执行单条用例。请把输入、点击查询/搜索、"
                "等待结果等前置动作写进同一条用例，或合并为多步骤流程用例。"
            ),
            evidence=_current_page_evidence(context),
            method=verdict.method,
        )

    if _looks_like_empty_llm(verdict) and _has_successful_deterministic_action(run_result):
        return AssertionVerdict(
            passed=False,
            reason=(
                "断言模型空响应：确定性动作已完成，但断言阶段 LLM 未返回可解析内容，"
                "系统不能把该步骤判为通过；建议改写为可规则化验证的预期，或重试。"
            ),
            evidence=_deterministic_action_evidence(run_result),
            method=verdict.method,
        )

    return verdict


def _build_context(run_result: StepRunResult) -> str:
    parts = [
        run_result.last_snapshot_text or "",
        run_result.final_message or "",
        run_result.reasoning or "",
    ]
    for rec in run_result.tool_calls:
        try:
            parts.append(json.dumps(rec.result, ensure_ascii=False))
        except TypeError:
            parts.append(str(rec.result))
        if rec.error:
            parts.append(rec.error)
    return "\n".join(part for part in parts if part)[:50_000]


def _has_external_verification(context: str) -> bool:
    lowered = context.lower()
    return any(term.lower() in lowered for term in _EXTERNAL_VERIFICATION_TERMS)


def _page_load_expectation_satisfied(expected: str, context: str) -> bool:
    if "页面加载完成" not in expected and "正常加载" not in expected:
        return False
    if "Page URL:" not in context and "Page Title:" not in context:
        return False

    checks: list[bool] = [True]
    title_options = _extract_title_options(expected)
    if title_options:
        checks.append(any(option and option in context for option in title_options))

    if "搜索框" in expected:
        checks.append(
            "搜索框" in context
            or "searchbox" in context.lower()
            or "textbox" in context.lower()
            or "input" in context.lower()
        )

    for button_name in _BUTTON_RE.findall(expected):
        checks.append(button_name in context and "button" in context.lower())

    return len(checks) > 1 and all(checks)


def _extract_title_options(expected: str) -> list[str]:
    match = _TITLE_CONTAINS_RE.search(expected)
    if not match:
        return []
    raw = match.group("value")
    out: list[str] = []
    for item in re.split(r"或|或者|/", raw):
        cleaned = item.strip(" ：:，,。；;且'\"“”「」")
        if cleaned:
            out.append(cleaned)
    return out


def _page_evidence_summary(expected: str, context: str) -> str:
    lines = []
    for prefix in ("Page URL:", "Page Title:"):
        line = _line_containing(context, prefix)
        if line:
            lines.append(line)
    for item in _QUOTED_RE.findall(expected):
        if item in context:
            lines.append(item)
    return "；".join(lines[:6]) or "页面证据命中"


def _looks_like_missing_precondition(
    *,
    step_description: str,
    expected: str,
    context: str,
    target_url: str | None,
) -> bool:
    combined = f"{step_description}\n{expected}"
    quoted_keywords = [
        item for item in _QUOTED_RE.findall(expected)
        if len(item.strip()) >= 2 and item not in {"搜索框", "按钮"}
    ]
    missing_keywords = [
        item for item in quoted_keywords
        if item not in context
    ]
    if not missing_keywords:
        return False

    dependent = bool(_DEPENDENT_STATE_RE.search(combined))
    observe_only = bool(_OBSERVE_ONLY_RE.search(step_description)) and not bool(
        _ACTION_SETUP_RE.search(step_description)
    )
    at_entry = _context_at_target_entry(context, target_url)
    return (dependent or observe_only) and at_entry


def _context_at_target_entry(context: str, target_url: str | None) -> bool:
    if not target_url:
        return False
    current = _current_url(context)
    if not current:
        return False
    return _normalize_url(current) == _normalize_url(target_url)


def _current_url(context: str) -> str | None:
    match = _PAGE_URL_RE.search(context)
    return match.group(1).strip() if match else None


def _normalize_url(value: str) -> str:
    try:
        parsed = urlparse(value.strip())
    except Exception:  # noqa: BLE001
        return value.strip().rstrip("/")
    path = parsed.path.rstrip("/")
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{path}"


def _looks_like_empty_llm(verdict: AssertionVerdict) -> bool:
    text = f"{verdict.reason}\n{verdict.evidence}".lower()
    return "llm 返回空内容" in text or "llm empty" in text or "空响应" in text


def _has_successful_deterministic_action(run_result: StepRunResult) -> bool:
    for rec in run_result.tool_calls:
        if rec.raw_name != "deterministic_runner":
            continue
        result = rec.result if isinstance(rec.result, dict) else {}
        if result.get("success") is True:
            return True
    return False


def _deterministic_action_evidence(run_result: StepRunResult) -> str:
    for rec in run_result.tool_calls:
        if rec.raw_name != "deterministic_runner":
            continue
        result = rec.result if isinstance(rec.result, dict) else {}
        if result.get("success") is True:
            return str(result.get("message") or "deterministic action succeeded")
    return ""


def _first_matching_line(context: str, terms: tuple[str, ...]) -> str:
    for line in context.splitlines():
        if any(term.lower() in line.lower() for term in terms):
            return line.strip()[:300]
    return ""


def _line_containing(context: str, needle: str) -> str:
    for line in context.splitlines():
        if needle in line:
            return line.strip()[:200]
    return ""


def _current_page_evidence(context: str) -> str:
    lines = []
    for prefix in ("Page URL:", "Page Title:"):
        line = _line_containing(context, prefix)
        if line:
            lines.append(line)
    return "；".join(lines)
