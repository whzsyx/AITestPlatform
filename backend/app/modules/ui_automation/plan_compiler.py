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
_ABSOLUTE_HTTP_URL_RE = re.compile(
    r"https?://[^\s，,；;。)）\]】》」\"'“”‘’]+",
    re.IGNORECASE,
)
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

    # 操作类步骤必须优先按 action 本身编译；expected_result 只作为后置断言输入。
    # 否则「点击按钮，预期 URL 包含 /x」会被误编译成纯 URL 断言，实际不会点击。
    if step := _compile_url_navigation(step_number, source_text):
        return step
    if step := _compile_no_input_empty_assertion(step_number, source_text, expected_text):
        return step
    if step := _compile_fill(step_number, source_text):
        return step
    if step := _compile_press_key(step_number, source_text):
        return step
    if step := _compile_click(step_number, source_text):
        return step

    if step := _compile_module_entry_loaded(step_number, source_text, combined, has_module_entry):
        return step
    if step := _compile_table_columns(step_number, source_text, combined):
        return step
    if step := _compile_table_rows(step_number, source_text, combined):
        return step
    if step := _compile_form_assertion(step_number, source_text, combined):
        return step
    if step := _compile_assert_url(step_number, source_text, combined):
        return step
    if step := _compile_assert_text(step_number, source_text, combined):
        return step

    return _unsupported(step_number, source_text, "规则编译器无法安全识别该步骤")


def _compile_url_navigation(step_number: int, source_text: str) -> UIActionStep | None:
    match = _ABSOLUTE_HTTP_URL_RE.search(source_text)
    if not match:
        return None
    if not re.search(r"地址栏|浏览器地址|访问|打开|进入|跳转|导航|回车", source_text):
        return None
    return UIActionStep(
        source_step_number=step_number,
        source_text=source_text,
        kind=UIActionKind.NAVIGATE,
        target=ActionTarget(url=match.group(0)),
        confidence=0.92,
        requires_evidence=["page_identity"],
        risk_level="low",
    )


def _compile_assert_url(
    step_number: int,
    source_text: str,
    combined: str,
) -> UIActionStep | None:
    if not re.search(r"url|URL|链接|地址", combined):
        return None
    if _contains_alternative_route_wording(combined):
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
    if not re.search(r"进入|打开|加载|访问|登录|等待", source_text):
        return None
    if not re.search(
        r"列表页面|列表页|菜单下的列表|页面正常加载|正常加载|"
        r"页面正常显示|正常显示|页面加载完成|搜索框可见|页面出现|标题栏显示|"
        r"页面标题|logo|Logo|可见",
        combined,
    ):
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
    if not re.search(
        r"数据行|表格数据|列表数据|数据展示|展示情况|"
        r"列表.{0,20}(?:非空|至少(?:存在|有)?\s*(?:一|1)\s*条)|"
        r"结果列表.{0,20}(?:非空|至少(?:存在|有)?\s*(?:一|1)\s*条)|"
        r"至少(?:存在|有)?\s*(?:一|1)\s*条(?:结果|记录|数据)",
        combined,
    ):
        return None
    if not re.search(r"正常|有数据|存在数据|展示|显示|非空|至少|存在|有", combined):
        return None
    assertion_text = (
        combined[len(source_text) :].strip()
        if source_text and combined.startswith(f"{source_text} ")
        else combined
    )
    value = (
        assertion_text
        if re.search(r"非空|至少(?:存在|有)?\s*(?:一|1)\s*(?:条|行|个)", combined)
        else "有数据"
    )
    return UIActionStep(
        source_step_number=step_number,
        source_text=source_text,
        kind=UIActionKind.ASSERT_TABLE_ROWS,
        target=ActionTarget(table_hint=_extract_table_hint(combined)),
        value=value,
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


def _compile_no_input_empty_assertion(
    step_number: int,
    source_text: str,
    expected_text: str,
) -> UIActionStep | None:
    if not re.search(r"保持|不输入|无需输入|不填写|清空|置空", source_text):
        return None
    if not re.search(r"空|无文本|不输入|不填写|置空", source_text + expected_text):
        return None
    label = _extract_quoted_text(source_text) or _extract_empty_target_label(source_text)
    expected = expected_text or source_text
    return UIActionStep(
        source_step_number=step_number,
        source_text=source_text,
        kind=UIActionKind.ASSERT_FORM_VALUES,
        target=ActionTarget(label=label) if label else ActionTarget(),
        value=expected,
        confidence=0.74,
        requires_evidence=["form_fields"],
        risk_level="low",
    )


def _compile_press_key(step_number: int, source_text: str) -> UIActionStep | None:
    if not re.search(r"按下|按键|键盘|回车|Enter|Tab|Esc|Escape", source_text, re.IGNORECASE):
        return None
    key = _extract_key_name(source_text)
    if not key:
        return None
    return UIActionStep(
        source_step_number=step_number,
        source_text=source_text,
        kind=UIActionKind.PRESS_KEY,
        value=key,
        confidence=0.82,
        requires_evidence=["page_identity"],
        risk_level="low",
    )


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
    if _looks_like_column_value_check(text):
        return False
    if "列名" in text or "字段列" in text:
        return True
    # ``列表`` 本身包含"列"，不能把"点击查询按钮，期望列表刷新"误判成列名断言。
    text_without_list_word = text.replace("列表", "")
    return "列" in text_without_list_word and ("列表" in text or "表格" in text)


def _contains_alternative_route_wording(text: str) -> bool:
    return bool(
        re.search(r"相关路由", text)
        or re.search(r"(?:或|或者).{0,12}(?:路由|地址|URL|url|链接)", text)
    )


def _looks_like_column_value_check(text: str) -> bool:
    return bool(
        re.search(
            r"[\w\u4e00-\u9fff]+列(?:均)?(?:包含|显示|展示|为|是|等于|匹配)\s*\{\{",
            text,
        )
    )


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


def _extract_quoted_text(text: str) -> str:
    match = re.search(r"[「“\"']([^」”\"']+)[」”\"']", text)
    return _clean_label(match.group(1)) if match else ""


def _extract_empty_target_label(text: str) -> str:
    match = re.search(r"保持(?P<label>.+?)(?:为空|为(?:空|空字符串)|不输入|不填写)", text)
    if not match:
        return ""
    return _clean_label(match.group("label"))


def _extract_key_name(text: str) -> str:
    quoted = _extract_quoted_text(text)
    raw = quoted or text
    if re.search(r"Enter|回车", raw, re.IGNORECASE):
        return "Enter"
    if re.search(r"Esc|Escape|退出", raw, re.IGNORECASE):
        return "Escape"
    if re.search(r"Tab|制表", raw, re.IGNORECASE):
        return "Tab"
    if re.search(r"空格|Space", raw, re.IGNORECASE):
        return "Space"
    return ""


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
    cleaned = _strip_quotes(value).rstrip("。；;，,").strip()
    if re.search(r"(?:英文|半角)?逗号(?:分隔|隔开)?", cleaned):
        cleaned = re.sub(
            r"[（(][^）)]*(?:英文|半角)?逗号(?:分隔|隔开)?[^）)]*[）)]",
            "",
            cleaned,
        )
        cleaned = re.sub(
            r"\s*(?:使用|用|以)?(?:英文|半角)?逗号(?:分隔|隔开)?\s*",
            "",
            cleaned,
        )
        cleaned = re.sub(r"\s*[、，]\s*", ",", cleaned)
        cleaned = re.sub(r"\s*,\s*", ",", cleaned)
    return cleaned.strip()


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
