"""Rule-based assertions over structured EvidenceCollector output."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlparse

from app.modules.ui_automation.evidence_collector import (
    FormFieldsEvidence,
    TableRowsEvidence,
    TableSchemaEvidence,
)

RuleMethod = Literal["text_search"]


@dataclass
class RuleAssertionResult:
    passed: bool
    reason: str
    evidence: str = ""
    method: RuleMethod = "text_search"


_SPLIT_RE = re.compile(r"[、,，;；/\n]+")
_COLUMN_TRIGGER_RE = re.compile(r"列名|字段列|表格列|列表列")
_ROW_COUNT_RE = re.compile(
    r"至少(?:存在|有)?\s*(?:一|1)\s*行|不少于\s*(?:一|1)\s*行|有数据|存在数据"
)
_CONTAINS_RE = re.compile(r"(?:包含|存在|显示|展示)\s*(?P<text>[^，,。；;\n]+)")
_MULTI_COLUMN_VALUES_RE = re.compile(
    r"(?P<column>[\w\u4e00-\u9fff]+?)(?:字段|列)?(?:为|是|=|等于)\s*"
    r"(?P<values>[^。；;\n]+?(?:\s*(?:和|及|与|、|,|，)\s*[^。；;\n]+)+)"
)
_COLUMN_VALUE_RE = re.compile(
    r"(?P<column>[\w\u4e00-\u9fff]+?)(?:字段|列)?(?:为|是|=|等于)\s*(?P<value>[\w\u4e00-\u9fff.-]+)"
)
_INPUT_VALUE_RE = re.compile(
    r"(?:输入框|字段|表单项)?值(?:显示)?(?:为|是|=|等于)\s*(?P<value>[^，,。；;\n]+)"
)
_FORM_EXPECTATION_RE = re.compile(r"输入框|搜索框|文本框|表单|表单项|字段值|弹窗|侧边弹窗|抽屉|对话框")
_PAGE_IDENTITY_EXPECTATION_RE = re.compile(r"url|URL|地址栏|链接|页面正常加载|正常加载|标题栏|页面标题")
_FORM_DISPLAY_VALUE_RE = re.compile(
    r"(?:输入框|搜索框|文本框|字段|表单项)[^，,。；;\n]{0,12}"
    r"(?:显示|包含|已输入|输入的|填入)\s*(?P<value>[^，,。；;\n]+)"
)
_READONLY_RE = re.compile(
    r"只读|不可编辑|不能手动编辑|无法编辑|无编辑入口|无法进入编辑状态|无输入光标|无法.*(?:输入|修改|编辑)|disabled|readonly",
    re.IGNORECASE,
)
_EMPTY_VALUE_RE = re.compile(
    r"无文本|为空|空字符串|不输入任何内容|无需输入|不填写|保持.{0,12}空|值为空"
)


def assert_table_columns(
    *,
    expected_columns: list[str],
    evidence: TableSchemaEvidence | dict[str, Any],
    require_order: bool = True,
) -> RuleAssertionResult:
    schema = _table_schema(evidence)
    if not schema.ok:
        return RuleAssertionResult(False, f"表格列证据采集失败：{schema.error or 'unknown'}")

    actual = [_normalize_text(col) for col in schema.columns]
    expected = [_normalize_text(col) for col in expected_columns if _normalize_text(col)]
    missing = [
        expected_columns[idx]
        for idx, normalized in enumerate(expected)
        if normalized not in actual
    ]
    if missing:
        return RuleAssertionResult(
            False,
            f"表格列缺失：{'、'.join(missing)}",
            evidence="、".join(schema.columns),
        )

    if require_order and len(expected) >= 2:
        positions = [actual.index(col) for col in expected]
        if positions != sorted(positions):
            return RuleAssertionResult(
                False,
                "表格列存在但顺序不一致",
                evidence="、".join(schema.columns),
            )

    return RuleAssertionResult(
        True,
        f"结构化证据命中 {len(expected)} 个表格列",
        evidence="、".join(expected_columns),
    )


def assert_table_rows(
    *,
    expected: str,
    evidence: TableRowsEvidence | dict[str, Any],
) -> RuleAssertionResult | None:
    rows_evidence = _table_rows(evidence)
    if not rows_evidence.ok:
        return RuleAssertionResult(False, f"表格行证据采集失败：{rows_evidence.error or 'unknown'}")

    if _ROW_COUNT_RE.search(expected):
        row_count = rows_evidence.row_count or len(rows_evidence.rows)
        passed = row_count >= 1
        return RuleAssertionResult(
            passed,
            "表格至少一行数据" if passed else "表格没有数据行",
            evidence=f"row_count={row_count}",
        )

    multi_match = _MULTI_COLUMN_VALUES_RE.search(expected)
    if multi_match:
        column = _clean_column_reference(multi_match.group("column"))
        values = _extract_expected_values(multi_match.group("values"))
        if len(values) >= 2:
            missing = [
                value
                for value in values
                if not _row_contains_column_value(rows_evidence.rows, column, value)
            ]
            if not missing:
                return RuleAssertionResult(
                    True,
                    "结构化表格行证据命中多值列匹配",
                    evidence=f"{column}={'、'.join(values)}",
                )
            return RuleAssertionResult(
                False,
                f"未找到 {column}={'、'.join(missing)} 的表格行",
                evidence=f"row_count={rows_evidence.row_count}",
            )

    match = _COLUMN_VALUE_RE.search(expected)
    if match:
        column = _clean_column_reference(match.group("column"))
        value = _clean_value(match.group("value"))
        if _row_contains_column_value(rows_evidence.rows, column, value):
            return RuleAssertionResult(
                True,
                "结构化表格行证据命中列值匹配",
                evidence=f"{column}={value}",
            )
        return RuleAssertionResult(
            False,
            f"未找到 {column}={value} 的表格行",
            evidence=f"row_count={rows_evidence.row_count}",
        )

    text = _extract_contains_text(expected)
    if text:
        if _rows_contain_text(rows_evidence.rows, text):
            return RuleAssertionResult(
                True,
                "结构化表格行证据命中文本",
                evidence=text,
            )
        return RuleAssertionResult(
            False,
            f"表格行未包含文本：{text}",
            evidence=f"row_count={rows_evidence.row_count}",
        )

    return None


def assert_form_values(
    *,
    expected: str,
    evidence: FormFieldsEvidence | dict[str, Any],
) -> RuleAssertionResult | None:
    form_evidence = _form_fields(evidence)
    if not form_evidence.ok:
        return RuleAssertionResult(False, f"表单证据采集失败：{form_evidence.error or 'unknown'}")

    if _EMPTY_VALUE_RE.search(expected):
        field = _find_referenced_field(expected, form_evidence)
        if field is None:
            field = _single_editable_field(form_evidence)
        if field is None:
            return RuleAssertionResult(False, "未找到需要校验为空的表单字段")
        value = str(field.value or "").strip()
        field_name = field.label or field.placeholder or field.name or "输入框"
        passed = value == ""
        return RuleAssertionResult(
            passed,
            "结构化表单证据命中空值/无文本" if passed else "表单字段不是空值",
            evidence=f"{field_name}={value}",
        )

    display_value_match = _FORM_DISPLAY_VALUE_RE.search(expected)
    if display_value_match and not _INPUT_VALUE_RE.search(expected):
        value = _clean_value(_strip_expected_value(display_value_match.group("value")))
        field = _find_referenced_field(expected, form_evidence) or _single_editable_field(
            form_evidence
        )
        if field is None:
            return RuleAssertionResult(False, "未找到需要校验显示值的表单字段")
        passed = _normalize_text(value) in _normalize_text(field.value)
        field_name = field.label or field.placeholder or field.name or "输入框"
        return RuleAssertionResult(
            passed,
            "结构化表单证据命中输入框显示值" if passed else "输入框显示值不匹配",
            evidence=f"{field_name}={field.value}，期望={value}",
        )

    if _READONLY_RE.search(expected):
        field = _find_referenced_field(expected, form_evidence)
        if field is None:
            if _allows_invisible_field(expected):
                return RuleAssertionResult(
                    True,
                    "结构化表单证据未发现对应字段，符合不可见/无编辑入口预期",
                    evidence="field_not_visible",
                )
            return None
        if field.readonly or field.disabled:
            return RuleAssertionResult(
                True,
                "结构化表单证据显示字段只读/不可编辑",
                evidence=f"{field.label or field.name}: readonly={field.readonly}, disabled={field.disabled}",
            )
        return RuleAssertionResult(
            False,
            "字段存在但不是只读/不可编辑状态",
            evidence=f"{field.label or field.name}: readonly={field.readonly}, disabled={field.disabled}",
        )

    input_value_match = _INPUT_VALUE_RE.search(expected)
    if input_value_match:
        value = _clean_value(input_value_match.group("value"))
        field = _find_referenced_field(expected, form_evidence)
        if field is not None:
            passed = _normalize_text(value) in _normalize_text(field.value)
            field_name = field.label or field.placeholder or field.name or "输入框"
            return RuleAssertionResult(
                passed,
                "结构化表单证据命中输入框值" if passed else "输入框值不匹配",
                evidence=f"{field_name}={field.value}",
            )

        normalized_value = _normalize_text(value)
        matched = [
            field
            for field in form_evidence.fields
            if normalized_value and normalized_value in _normalize_text(field.value)
        ]
        if matched:
            field = matched[0]
            field_name = field.label or field.placeholder or field.name or "输入框"
            return RuleAssertionResult(
                True,
                "结构化表单证据命中输入框值",
                evidence=f"{field_name}={field.value}",
            )
        available_values = [
            field.value
            for field in form_evidence.fields
            if str(field.value or "").strip()
        ]
        return RuleAssertionResult(
            False,
            f"未找到输入框值：{value}",
            evidence="、".join(available_values[:10]),
        )

    match = _COLUMN_VALUE_RE.search(expected)
    if match:
        label = match.group("column").strip()
        value = _clean_value(match.group("value"))
        field = _find_field(form_evidence, label)
        if field is None:
            return RuleAssertionResult(False, f"未找到表单字段：{label}")
        passed = _normalize_text(value) in _normalize_text(field.value)
        return RuleAssertionResult(
            passed,
            "结构化表单证据命中字段值" if passed else "表单字段值不匹配",
            evidence=f"{label}={field.value}",
        )

    return None


def _allows_invisible_field(expected: str) -> bool:
    return bool(
        re.search(
            r"不可见|不存在|无编辑入口|无法进入编辑状态|无输入光标|无法进行手动输入|无法.*(?:输入|修改|编辑)",
            expected,
        )
    )


def judge_structured_assertion(
    *,
    expected: str,
    structured_evidence: dict[str, Any] | None,
) -> RuleAssertionResult | None:
    if not structured_evidence:
        return None

    page_identity_verdict = _judge_page_identity_structured_assertion(
        expected=expected,
        structured_evidence=structured_evidence,
    )
    if page_identity_verdict is not None:
        return page_identity_verdict

    if table_schema_raw := structured_evidence.get("table_schema"):
        expected_columns = _extract_expected_columns(expected)
        if expected_columns:
            return assert_table_columns(
                expected_columns=expected_columns,
                evidence=table_schema_raw,
            )

    if _prefers_form_assertion(expected):
        form_verdict = _judge_form_structured_assertion(
            expected=expected,
            structured_evidence=structured_evidence,
        )
        if form_verdict is not None:
            return form_verdict

    if table_rows_raw := structured_evidence.get("table_rows"):
        row_verdict = assert_table_rows(expected=expected, evidence=table_rows_raw)
        if row_verdict is not None:
            return row_verdict

    form_verdict = _judge_form_structured_assertion(
        expected=expected,
        structured_evidence=structured_evidence,
    )
    if form_verdict is not None:
        return form_verdict

    return None


def _judge_page_identity_structured_assertion(
    *,
    expected: str,
    structured_evidence: dict[str, Any],
) -> RuleAssertionResult | None:
    if not _PAGE_IDENTITY_EXPECTATION_RE.search(expected):
        return None
    page_identity_raw = structured_evidence.get("page_identity")
    if not isinstance(page_identity_raw, dict):
        return None
    actual_url = str(page_identity_raw.get("url") or "").strip()
    actual_title = str(page_identity_raw.get("title") or "").strip()

    expected_url = _extract_expected_url_or_fragment(expected)
    if expected_url:
        passed = _url_expectation_matches(expected_url, actual_url)
        return RuleAssertionResult(
            passed,
            "结构化页面证据命中地址栏 URL" if passed else "地址栏 URL 不匹配",
            evidence=f"expected={expected_url}; actual={actual_url}",
        )

    expected_title = _extract_expected_title(expected)
    if expected_title:
        passed = _normalize_text(expected_title) in _normalize_text(actual_title)
        return RuleAssertionResult(
            passed,
            "结构化页面证据命中页面标题" if passed else "页面标题不匹配",
            evidence=f"expected={expected_title}; actual={actual_title}",
        )

    if re.search(r"页面正常加载|正常加载", expected):
        passed = bool(actual_url or actual_title)
        return RuleAssertionResult(
            passed,
            "结构化页面证据显示页面已加载" if passed else "未采集到页面 URL 或标题",
            evidence=f"url={actual_url}; title={actual_title}",
        )
    return None


def _prefers_form_assertion(expected: str) -> bool:
    return bool(_FORM_EXPECTATION_RE.search(expected))


def _judge_form_structured_assertion(
    *,
    expected: str,
    structured_evidence: dict[str, Any],
) -> RuleAssertionResult | None:
    if not (form_fields_raw := structured_evidence.get("form_fields")):
        return None
    form_verdict = assert_form_values(expected=expected, evidence=form_fields_raw)
    if form_verdict is not None:
        return form_verdict
    form_contains_verdict = assert_form_contains_fields(
        expected=expected,
        evidence=form_fields_raw,
        page_text=structured_evidence.get("page_text"),
    )
    if form_contains_verdict is not None:
        return form_contains_verdict
    return None


def assert_form_contains_fields(
    *,
    expected: str,
    evidence: FormFieldsEvidence | dict[str, Any],
    page_text: dict[str, Any] | None = None,
) -> RuleAssertionResult | None:
    expected_fields = _extract_expected_form_fields(expected)
    if not expected_fields:
        return None

    form_evidence = _form_fields(evidence)
    available = [
        token
        for field in form_evidence.fields
        for token in (field.label, field.placeholder, field.name)
        if token
    ]
    if isinstance(page_text, dict):
        texts = page_text.get("texts")
        if isinstance(texts, list):
            available.extend(str(item) for item in texts if str(item).strip())

    normalized_available = [_normalize_text(item) for item in available]
    missing = [
        field
        for field in expected_fields
        if _normalize_text(field)
        and not any(_normalize_text(field) in item for item in normalized_available)
    ]
    if missing:
        return RuleAssertionResult(
            False,
            f"表单字段缺失：{'、'.join(missing)}",
            evidence="、".join(available[:20]),
        )
    return RuleAssertionResult(
        True,
        f"结构化表单证据命中 {len(expected_fields)} 个字段",
        evidence="、".join(expected_fields),
    )


def _extract_expected_url_or_fragment(expected: str) -> str:
    match = re.search(
        r"https?://[^\s，,；;。)）\]】》」\"'“”‘’]+",
        expected,
        re.IGNORECASE,
    )
    if match:
        return match.group(0).strip()
    if not re.search(r"url|URL|地址栏|链接", expected):
        return ""
    quoted = re.findall(r"[「“\"']([^」”\"']+)[」”\"']", expected)
    for item in quoted:
        cleaned = item.strip()
        if cleaned and ("/" in cleaned or "." in cleaned or "?" in cleaned):
            return cleaned
    return ""


def _extract_expected_title(expected: str) -> str:
    if not re.search(r"标题栏|页面标题|title", expected, re.IGNORECASE):
        return ""
    quoted = re.findall(r"[「“\"']([^」”\"']+)[」”\"']", expected)
    return quoted[0].strip() if quoted else ""


def _url_expectation_matches(expected: str, actual: str) -> bool:
    if not expected or not actual:
        return False
    if expected.startswith("http://") or expected.startswith("https://"):
        return _normalize_url_for_assertion(expected) == _normalize_url_for_assertion(actual)
    return expected in actual


def _normalize_url_for_assertion(value: str) -> str:
    text = str(value or "").strip()
    try:
        parsed = urlparse(text)
    except Exception:  # noqa: BLE001
        return text.rstrip("/")
    path = parsed.path.rstrip("/")
    if not path:
        path = ""
    query = f"?{parsed.query}" if parsed.query else ""
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{path}{query}"


def _extract_expected_columns(expected: str) -> list[str]:
    if not _COLUMN_TRIGGER_RE.search(expected) and "列名" not in expected:
        return []
    match = re.search(r"(?:包含|包括|依次展示|展示|为|：|:)\s*(?P<cols>.+)$", expected)
    if not match:
        return []
    raw = re.split(
        r"[，,；;。]\s*(?:括号及文字|无歧义|顺序|位置|样式|显示|展示)\S*",
        match.group("cols"),
        maxsplit=1,
    )[0]
    out: list[str] = []
    for part in _SPLIT_RE.split(raw):
        cleaned = _clean_expected_column_label(part)
        if cleaned:
            out.append(cleaned)
    return out


def _extract_expected_form_fields(expected: str) -> list[str]:
    if not re.search(r"表单|字段|输入框|弹窗", expected):
        return []
    match = _last_match(
        r"(?:表单|页面)(?:中)?(?:包含|包括|展示|显示)\s*"
        r"(?P<fields>[^。；;\n]+?)(?:等?字段|等?输入框|$)",
        expected,
    )
    if not match:
        match = _last_match(
            r"表单(?:包含|包括|展示|显示)\s*(?P<fields>[^。；;\n]+?)(?:等?字段|等?输入框|$)",
            expected,
        )
    if not match:
        match = _last_match(
            r"(?:包含|包括|展示|显示)\s*(?P<fields>[^。；;\n]+?)(?:等?字段|等?输入框|$)",
            expected,
        )
    if not match:
        return []
    raw = match.group("fields")
    out: list[str] = []
    for part in _SPLIT_RE.split(raw):
        cleaned = _clean_form_field_label(part)
        cleaned = re.sub(r"(?:等字段|字段|输入框|等)$", "", cleaned).strip()
        if cleaned and cleaned not in {"表单", "弹窗", "右侧弹出侧边弹窗"}:
            out.append(cleaned)
    return out


def _last_match(pattern: str, text: str) -> re.Match[str] | None:
    matches = list(re.finditer(pattern, text))
    return matches[-1] if matches else None


def _extract_contains_text(expected: str) -> str:
    match = _CONTAINS_RE.search(expected)
    if not match:
        return ""
    return _clean_label(match.group("text"))


def _strip_expected_value(value: str) -> str:
    quoted = re.findall(r"[「“\"']([^」”\"']+)[」”\"']", str(value or ""))
    if quoted:
        return quoted[0]
    return value


def _extract_expected_values(raw: str) -> list[str]:
    out: list[str] = []
    for part in re.split(r"\s*(?:和|及|与|、|,|，)\s*", str(raw or "")):
        cleaned = _clean_value(part)
        if cleaned:
            out.append(cleaned)
    return out


def _row_contains_column_value(rows: list[dict[str, str]], column: str, value: str) -> bool:
    normalized_column = _normalize_text(column)
    normalized_value = _normalize_text(value)
    for row in rows:
        for key, cell_value in row.items():
            if _columns_match(key, normalized_column) and normalized_value in _normalize_text(cell_value):
                return True
    return False


def _columns_match(actual: str, normalized_expected: str) -> bool:
    normalized_actual = _normalize_text(actual)
    return (
        normalized_actual == normalized_expected
        or normalized_actual in normalized_expected
        or normalized_expected in normalized_actual
    )


def _rows_contain_text(rows: list[dict[str, str]], text: str) -> bool:
    needle = _normalize_text(text)
    return any(
        needle in _normalize_text(cell)
        for row in rows
        for cell in row.values()
    )


def _find_referenced_field(expected: str, evidence: FormFieldsEvidence):
    candidates = sorted(
        evidence.fields,
        key=lambda field: len(field.label or field.name),
        reverse=True,
    )
    normalized_expected = _normalize_text(expected)
    for field in candidates:
        for token in (field.label, field.name, field.placeholder):
            if token and _normalize_text(token) in normalized_expected:
                return field
        if _field_matches_semantic_reference(field, normalized_expected):
            return field
    return None


def _single_editable_field(evidence: FormFieldsEvidence):
    editable_fields = [
        candidate
        for candidate in evidence.fields
        if not candidate.disabled and not candidate.readonly
    ]
    if len(editable_fields) == 1:
        return editable_fields[0]
    return None


def _find_field(evidence: FormFieldsEvidence, label: str):
    normalized = _normalize_text(label)
    for field in evidence.fields:
        if normalized in {
            _normalize_text(field.label),
            _normalize_text(field.name),
            _normalize_text(field.placeholder),
        }:
            return field
    return None


def _field_matches_semantic_reference(field: Any, normalized_expected: str) -> bool:
    if "搜索框" in normalized_expected or "searchbox" in normalized_expected:
        semantic_tokens = [
            getattr(field, "type", ""),
            getattr(field, "name", ""),
            getattr(field, "placeholder", ""),
            getattr(field, "label", ""),
        ]
        normalized_tokens = [_normalize_text(token) for token in semantic_tokens if token]
        return any(
            token in {"search", "wd", "q", "keyword"}
            or "search" in token
            or "搜索" in token
            for token in normalized_tokens
        )
    if "输入框" in normalized_expected:
        tag = _normalize_text(getattr(field, "tag_name", ""))
        field_type = _normalize_text(getattr(field, "type", ""))
        return tag in {"input", "textarea"} or field_type in {"text", "search"}
    return False


def _table_schema(value: TableSchemaEvidence | dict[str, Any]) -> TableSchemaEvidence:
    if isinstance(value, TableSchemaEvidence):
        return value
    cleaned = dict(value)
    cleaned["columns"] = _coerce_string_list(cleaned.get("columns"))
    cleaned["visible_columns"] = _coerce_string_list(cleaned.get("visible_columns"))
    return TableSchemaEvidence.model_validate(cleaned)


def _table_rows(value: TableRowsEvidence | dict[str, Any]) -> TableRowsEvidence:
    if isinstance(value, TableRowsEvidence):
        return value
    cleaned = dict(value)
    cleaned["columns"] = _coerce_string_list(cleaned.get("columns"))
    cleaned["rows"] = _coerce_table_rows(cleaned.get("rows"))
    return TableRowsEvidence.model_validate(cleaned)


def _form_fields(value: FormFieldsEvidence | dict[str, Any]) -> FormFieldsEvidence:
    if isinstance(value, FormFieldsEvidence):
        return value
    return FormFieldsEvidence.model_validate(value)


def _normalize_text(value: str) -> str:
    text = str(value or "")
    text = (
        text.replace("（", "(")
        .replace("）", ")")
        .replace("：", ":")
        .replace("，", ",")
    )
    return re.sub(r"\s+", "", text).strip().lower()


def _coerce_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if isinstance(item, str):
            text = item.strip()
        elif isinstance(item, dict):
            text = str(
                item.get("text")
                or item.get("label")
                or item.get("name")
                or item.get("title")
                or "",
            ).strip()
        else:
            text = str(item or "").strip()
        if text:
            out.append(text)
    return out


def _coerce_table_rows(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    rows: list[dict[str, str]] = []
    for row in value:
        if not isinstance(row, dict):
            continue
        rows.append({str(key): _stringify_cell(val) for key, val in row.items()})
    return rows


def _stringify_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except TypeError:
        return str(value)


def _clean_expected_column_label(value: str) -> str:
    cleaned = _clean_label(value)
    cleaned = cleaned.lstrip(":：").strip()
    if not cleaned:
        return ""
    if cleaned in {"正确", "正常", "完整", "一致", "顺序"}:
        return ""
    if re.search(r"括号|无歧义|完全一致|顺序完全一致|文字完全一致", cleaned):
        return ""
    return cleaned


def _clean_column_reference(value: str) -> str:
    cleaned = _clean_label(value)
    prefix_re = re.compile(
        r"^(?:查询结果中所有行的?|查询结果中?|所有行的|每一行的|对应的?|当前|同时包含|同时|包含|其|该|此)"
    )
    while True:
        next_cleaned = prefix_re.sub("", cleaned).strip()
        if next_cleaned == cleaned:
            break
        cleaned = next_cleaned
    cleaned = re.sub(r"(?:字段|列)$", "", cleaned).strip()
    return cleaned


def _clean_form_field_label(value: str) -> str:
    cleaned = _clean_label(value)
    cleaned = re.sub(
        r"^(?:页面|表单|弹窗|侧边弹窗|右侧弹出侧边弹窗)?(?:包含|包括|展示|显示)",
        "",
        cleaned,
    ).strip()
    return cleaned


def _clean_label(value: str) -> str:
    cleaned = str(value or "").strip().strip("\"'“”‘’「」《》[]【】 ")
    cleaned = cleaned.lstrip(":：").strip()
    cleaned = re.sub(r"(?:字段|列名|列|数据|的)$", "", cleaned).strip()
    return cleaned.rstrip("。；;，,")


def _clean_value(value: str) -> str:
    cleaned = str(value or "").strip().strip("\"'“”‘’「」《》[]【】 ")
    cleaned = re.split(
        r"(?:的行数据|行数据|的行|行|的数据|数据|存在|展示|显示|应|需)",
        cleaned,
        maxsplit=1,
    )[0]
    return cleaned.rstrip("。；;，,")
