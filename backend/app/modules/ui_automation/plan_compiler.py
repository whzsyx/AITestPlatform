"""Rule-first compiler from natural-language test steps to UIActionPlan."""

from __future__ import annotations

import re
from typing import Any

from app.modules.ui_automation.action_plan import (
    ActionTarget,
    PlanCompileResult,
    UIActionKind,
    UIActionPlan,
    UIActionStep,
)

_CLICK_RE = re.compile(r"(?:点击|单击|点一下|点选)\s*(?P<name>.+?)(?:按钮|按键|$)")
_DANGEROUS_WORDS = ("删除", "清空", "提交", "发布", "支付", "批量")
_SPLIT_RE = re.compile(r"[、,，;；/\n]+")


def compile_action_plan(
    testcase: Any,
    *,
    module_entry_path: str | None = None,
) -> PlanCompileResult:
    """Compile one testcase into a lightweight, auditable action plan.

    This function is intentionally side-effect free: it does not touch browser,
    database, execution rows, or existing StepRunner behavior.
    """
    module_entry = _normalize_module_entry(
        module_entry_path
        if module_entry_path is not None
        else getattr(getattr(testcase, "module", None), "entry_path", None),
    )
    plan_steps: list[UIActionStep] = []
    warnings: list[str] = []

    if module_entry:
        plan_steps.append(
            UIActionStep(
                source_step_number=0,
                source_text="打开模块入口",
                kind=UIActionKind.NAVIGATE,
                target=ActionTarget(url="{{module.entry_url}}"),
                confidence=1.0,
                requires_evidence=["page_identity"],
                risk_level="low",
            ),
        )

    raw_steps = sorted(
        list(getattr(testcase, "steps", []) or []),
        key=lambda step: int(getattr(step, "step_number", 0) or 0),
    )
    for raw_step in raw_steps:
        compiled = _compile_step(raw_step, has_module_entry=bool(module_entry))
        plan_steps.append(compiled)
        if compiled.kind == UIActionKind.UNSUPPORTED and compiled.unsupported_reason:
            warnings.append(
                f"step {compiled.source_step_number}: {compiled.unsupported_reason}",
            )

    supported_count = sum(1 for step in plan_steps if step.kind != UIActionKind.UNSUPPORTED)
    unsupported_count = sum(1 for step in plan_steps if step.kind == UIActionKind.UNSUPPORTED)
    confidence = _average_confidence(plan_steps)

    plan = UIActionPlan(
        case_id=_string_or_none(getattr(testcase, "id", None)),
        module_entry=module_entry,
        confidence=confidence,
        steps=plan_steps,
    )
    return PlanCompileResult(
        plan=plan,
        supported_step_count=supported_count,
        unsupported_step_count=unsupported_count,
        warnings=warnings,
    )


def _compile_step(raw_step: Any, *, has_module_entry: bool = False) -> UIActionStep:
    step_number = int(getattr(raw_step, "step_number", 0) or 0)
    source_text = _clean_text(getattr(raw_step, "action", "") or "")
    expected_text = _clean_text(getattr(raw_step, "expected_result", "") or "")
    combined = " ".join(part for part in (source_text, expected_text) if part)

    if not source_text:
        return _unsupported(step_number, source_text, "步骤动作为空")

    if step := _compile_assert_url(step_number, source_text, combined):
        return step
    if step := _compile_module_entry_loaded(step_number, source_text, combined, has_module_entry):
        return step
    if step := _compile_table_columns(step_number, source_text, combined):
        return step
    if step := _compile_table_rows(step_number, source_text, combined):
        return step
    if step := _compile_form_assertion(step_number, source_text, combined):
        return step
    if step := _compile_fill(step_number, source_text):
        return step
    if step := _compile_click(step_number, source_text):
        return step
    if step := _compile_assert_text(step_number, source_text, combined):
        return step

    return _unsupported(step_number, source_text, "规则编译器无法安全识别该步骤")


def _compile_assert_url(
    step_number: int,
    source_text: str,
    combined: str,
) -> UIActionStep | None:
    if not re.search(r"url|URL|链接|地址", combined):
        return None
    match = re.search(
        r"(?:url|URL|链接|地址)\s*(?:包含|为|等于|是|匹配)\s*(?P<url>\S+)",
        combined,
    )
    if not match:
        return None
    target_url = _strip_quotes(match.group("url").rstrip("。；;，,"))
    if not target_url:
        return None
    return UIActionStep(
        source_step_number=step_number,
        source_text=source_text,
        kind=UIActionKind.ASSERT_URL,
        target=ActionTarget(url=target_url),
        confidence=0.86,
        requires_evidence=["page_identity"],
        risk_level="low",
    )


def _compile_module_entry_loaded(
    step_number: int,
    source_text: str,
    combined: str,
    has_module_entry: bool,
) -> UIActionStep | None:
    if not has_module_entry:
        return None
    if not re.search(r"进入|打开|加载|访问|登录", source_text):
        return None
    if not re.search(r"列表页面|列表页|菜单下的列表|页面正常加载|正常加载", combined):
        return None
    return UIActionStep(
        source_step_number=step_number,
        source_text=source_text,
        kind=UIActionKind.ASSERT_PAGE_LOADED,
        target=ActionTarget(url="{{module.entry_url}}"),
        confidence=0.84,
        requires_evidence=["page_identity", "table_schema"],
        risk_level="low",
    )


def _compile_table_columns(
    step_number: int,
    source_text: str,
    combined: str,
) -> UIActionStep | None:
    if not _looks_like_table_column_check(combined):
        return None
    columns = _extract_columns(combined)
    if not columns:
        return _unsupported(step_number, source_text, "未识别出需要断言的表格列名")
    return UIActionStep(
        source_step_number=step_number,
        source_text=source_text,
        kind=UIActionKind.ASSERT_TABLE_COLUMNS,
        target=ActionTarget(table_hint=_extract_table_hint(combined), columns=columns),
        confidence=0.88,
        requires_evidence=["table_schema"],
        risk_level="low",
    )


def _compile_table_rows(
    step_number: int,
    source_text: str,
    combined: str,
) -> UIActionStep | None:
    if not re.search(r"数据行|表格数据|列表数据|数据展示|展示情况", combined):
        return None
    if not re.search(r"正常|有数据|存在数据|展示|显示", combined):
        return None
    return UIActionStep(
        source_step_number=step_number,
        source_text=source_text,
        kind=UIActionKind.ASSERT_TABLE_ROWS,
        target=ActionTarget(table_hint=_extract_table_hint(combined)),
        value="有数据",
        confidence=0.72,
        requires_evidence=["table_rows"],
        risk_level="low",
    )


def _compile_form_assertion(
    step_number: int,
    source_text: str,
    combined: str,
) -> UIActionStep | None:
    if not re.search(r"只读|不可见|不可编辑|无法.*(?:输入|修改|编辑)|无编辑入口", combined):
        return None
    if not re.search(r"字段|表单|编辑|输入|修改|列", combined):
        return None
    expected = _extract_expected_text(combined) or combined
    return UIActionStep(
        source_step_number=step_number,
        source_text=source_text,
        kind=UIActionKind.ASSERT_FORM_VALUES,
        value=expected,
        confidence=0.7,
        requires_evidence=["form_fields"],
        risk_level="low",
    )


def _compile_fill(step_number: int, source_text: str) -> UIActionStep | None:
    if not re.search(r"输入|填写|填入|录入", source_text):
        return None

    patterns = [
        r"(?:在|向)?(?P<label>.+?)(?:输入框|文本框|字段|栏|项)?(?:中)?(?:输入|填写|填入|录入)(?P<value>.+)",
        r"(?:输入|填写|填入|录入)(?P<label>.+?)(?:为|=|：|:)(?P<value>.+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, source_text)
        if not match:
            continue
        label = _clean_label(match.group("label"))
        value = _clean_value(match.group("value"))
        if label and value:
            return UIActionStep(
                source_step_number=step_number,
                source_text=source_text,
                kind=UIActionKind.FILL,
                target=ActionTarget(label=label),
                value=value,
                confidence=0.78,
                requires_evidence=["form_fields"],
                risk_level="low",
            )
    return None


def _compile_click(step_number: int, source_text: str) -> UIActionStep | None:
    if re.search(r"单元格|数据行|表格行", source_text) and "按钮" not in source_text:
        return None
    match = _CLICK_RE.search(source_text)
    if not match:
        return None
    name = _clean_label(match.group("name"))
    if not name:
        return None
    return UIActionStep(
        source_step_number=step_number,
        source_text=source_text,
        kind=UIActionKind.CLICK,
        target=ActionTarget(role="button", name=name),
        confidence=0.82,
        requires_evidence=["locator_match"],
        risk_level="high" if any(word in name for word in _DANGEROUS_WORDS) else "medium",
    )


def _compile_assert_text(
    step_number: int,
    source_text: str,
    combined: str,
) -> UIActionStep | None:
    if not re.search(r"验证|检查|确认|断言", combined):
        return None
    match = re.search(
        r"(?:显示|出现|包含|看到)\s*(?P<text>.+?)(?:提示|文本|信息|内容|$)",
        combined,
    )
    if not match:
        return None
    text = _clean_label(match.group("text"))
    if not text:
        return None
    return UIActionStep(
        source_step_number=step_number,
        source_text=source_text,
        kind=UIActionKind.ASSERT_TEXT,
        target=ActionTarget(text=text),
        confidence=0.76,
        requires_evidence=["text"],
        risk_level="low",
    )


def _unsupported(
    step_number: int,
    source_text: str,
    reason: str,
) -> UIActionStep:
    return UIActionStep(
        source_step_number=step_number,
        source_text=source_text,
        kind=UIActionKind.UNSUPPORTED,
        confidence=0.0,
        requires_evidence=[],
        risk_level="low",
        unsupported_reason=reason,
    )


def _looks_like_table_column_check(text: str) -> bool:
    if "列名" in text or "字段列" in text:
        return True
    # ``列表`` 本身包含"列"，不能把"点击查询按钮，期望列表刷新"误判成列名断言。
    text_without_list_word = text.replace("列表", "")
    return "列" in text_without_list_word and ("列表" in text or "表格" in text)


def _extract_columns(text: str) -> list[str]:
    match = re.search(r"(?:包含|包括|依次展示|分别为|为|：|:)\s*(?P<cols>.+)$", text)
    if not match:
        return []
    raw = match.group("cols")
    raw = re.split(
        r"[，,；;。]\s*(?:括号及文字|无歧义|顺序|位置|样式|显示|展示)\S*",
        raw,
        maxsplit=1,
    )[0]
    columns: list[str] = []
    for part in _SPLIT_RE.split(raw):
        cleaned = _clean_column_name(part)
        if cleaned:
            columns.append(cleaned)
    return columns


def _extract_table_hint(text: str) -> str | None:
    match = re.search(r"(?P<hint>[\w\u4e00-\u9fff]+?)(?:列表|表格)", text)
    if not match:
        return None
    hint = _clean_label(match.group("hint"))
    if not hint:
        return None
    return f"{hint}列表"


def _extract_expected_text(text: str) -> str:
    parts = re.split(r"\s+", text, maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ""


def _clean_column_name(value: str) -> str:
    cleaned = _strip_quotes(value)
    cleaned = cleaned.lstrip("：:，,;； ")
    cleaned = re.sub(r"(?:列名|字段|列)$", "", cleaned).strip()
    cleaned = cleaned.rstrip("。；;，,")
    noise = {
        "正确",
        "正常",
        "完整",
        "一致",
        "顺序",
        "顺序完全一致",
        "括号及文字完全一致",
        "无歧义",
        "展示正确",
        "显示正常",
    }
    return "" if cleaned in noise else cleaned


def _clean_label(value: str) -> str:
    cleaned = _strip_quotes(value)
    cleaned = re.sub(r"^(?:页面|列表|表格|的|在|向)", "", cleaned).strip()
    cleaned = re.sub(r"(?:按钮|输入框|文本框|字段|栏|项)$", "", cleaned).strip()
    return cleaned.rstrip("。；;，,")


def _clean_value(value: str) -> str:
    return _strip_quotes(value).rstrip("。；;，,")


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _strip_quotes(value: str) -> str:
    return value.strip().strip("\"'“”‘’「」《》[]【】 ")


def _normalize_module_entry(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _average_confidence(steps: list[UIActionStep]) -> float:
    if not steps:
        return 0.0
    return round(sum(step.confidence for step in steps) / len(steps), 4)


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)
