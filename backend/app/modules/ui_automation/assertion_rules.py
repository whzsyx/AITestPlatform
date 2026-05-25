"""Rule-based assertions over structured EvidenceCollector output."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Literal

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
_ROW_COUNT_RE = re.compile(r"至少\s*一\s*行|有数据|存在数据|不少于\s*1\s*行")
_CONTAINS_RE = re.compile(r"(?:包含|存在|显示|展示)\s*(?P<text>[^，,。；;\n]+)")
_COLUMN_VALUE_RE = re.compile(
    r"(?P<column>[\w\u4e00-\u9fff]+?)(?:字段|列)?(?:为|是|=|等于)\s*(?P<value>[\w\u4e00-\u9fff.-]+)"
)
_READONLY_RE = re.compile(
    r"只读|不可编辑|不能手动编辑|无法编辑|无编辑入口|无法进入编辑状态|无输入光标|无法.*(?:输入|修改|编辑)|disabled|readonly",
    re.IGNORECASE,
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

    match = _COLUMN_VALUE_RE.search(expected)
    if match:
        column = match.group("column").strip()
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

    if table_schema_raw := structured_evidence.get("table_schema"):
        expected_columns = _extract_expected_columns(expected)
        if expected_columns:
            return assert_table_columns(
                expected_columns=expected_columns,
                evidence=table_schema_raw,
            )

    if table_rows_raw := structured_evidence.get("table_rows"):
        row_verdict = assert_table_rows(expected=expected, evidence=table_rows_raw)
        if row_verdict is not None:
            return row_verdict

    if form_fields_raw := structured_evidence.get("form_fields"):
        form_verdict = assert_form_values(expected=expected, evidence=form_fields_raw)
        if form_verdict is not None:
            return form_verdict

    return None


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


def _extract_contains_text(expected: str) -> str:
    match = _CONTAINS_RE.search(expected)
    if not match:
        return ""
    return _clean_label(match.group("text"))


def _row_contains_column_value(rows: list[dict[str, str]], column: str, value: str) -> bool:
    normalized_column = _normalize_text(column)
    normalized_value = _normalize_text(value)
    for row in rows:
        for key, cell_value in row.items():
            if _normalize_text(key) == normalized_column and normalized_value in _normalize_text(cell_value):
                return True
    return False


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


def _clean_label(value: str) -> str:
    cleaned = str(value or "").strip().strip("\"'“”‘’「」《》[]【】 ")
    cleaned = cleaned.lstrip(":：").strip()
    cleaned = re.sub(r"(?:字段|列名|列|数据|的)$", "", cleaned).strip()
    return cleaned.rstrip("。；;，,")


def _clean_value(value: str) -> str:
    cleaned = str(value or "").strip().strip("\"'“”‘’「」《》[]【】 ")
    cleaned = re.split(r"(?:的数据|数据|存在|展示|显示|应|需)", cleaned, maxsplit=1)[0]
    return cleaned.rstrip("。；;，,")
