from __future__ import annotations

from app.modules.ui_automation.assertion_rules import (
    assert_form_values,
    assert_table_columns,
    assert_table_rows,
    judge_structured_assertion,
)
from app.modules.ui_automation.evidence_collector import (
    FormFieldEvidence,
    FormFieldsEvidence,
    TableRowsEvidence,
    TableSchemaEvidence,
)


def test_assert_table_columns_passes_with_ordered_schema() -> None:
    verdict = assert_table_columns(
        expected_columns=["店铺ID", "店铺名称", "平台"],
        evidence=TableSchemaEvidence(
            table_hint="店铺列表",
            columns=["店铺ID", "店铺名称", "平台", "负责人"],
            visible_columns=["店铺ID", "店铺名称"],
            total_columns=4,
        ),
    )

    assert verdict.passed is True
    assert "3 个表格列" in verdict.reason
    assert "店铺ID" in verdict.evidence


def test_assert_table_columns_normalizes_parenthesis_variants() -> None:
    verdict = assert_table_columns(
        expected_columns=["(分录)科目编码", "(分录)科目名称"],
        evidence=TableSchemaEvidence(
            columns=["提现银行账户", "（分录）科目编码", "（分录）科目名称"],
            visible_columns=["提现银行账户", "（分录）科目编码"],
            total_columns=3,
        ),
    )

    assert verdict.passed is True


def test_assert_table_columns_fails_when_column_missing() -> None:
    verdict = assert_table_columns(
        expected_columns=["店铺ID", "店铺名称", "平台"],
        evidence=TableSchemaEvidence(
            columns=["店铺ID", "店铺名称"],
            visible_columns=["店铺ID", "店铺名称"],
            total_columns=2,
        ),
    )

    assert verdict.passed is False
    assert "平台" in verdict.reason


def test_assert_table_rows_supports_row_count_and_text() -> None:
    evidence = TableRowsEvidence(
        columns=["店铺ID", "店铺名称"],
        rows=[
            {"店铺ID": "S001", "店铺名称": "旗舰店"},
            {"店铺ID": "S002", "店铺名称": "二店"},
        ],
        row_count=2,
    )

    count_verdict = assert_table_rows(expected="列表至少一行数据", evidence=evidence)
    text_verdict = assert_table_rows(expected="列表包含旗舰店", evidence=evidence)

    assert count_verdict.passed is True
    assert "至少一行" in count_verdict.reason
    assert text_verdict.passed is True
    assert "旗舰店" in text_verdict.evidence


def test_assert_table_rows_supports_column_value_match() -> None:
    verdict = assert_table_rows(
        expected="店铺ID为S001的数据存在",
        evidence=TableRowsEvidence(
            columns=["店铺ID", "店铺名称"],
            rows=[{"店铺ID": "S001", "店铺名称": "旗舰店"}],
            row_count=1,
        ),
    )

    assert verdict.passed is True
    assert "店铺ID=S001" in verdict.evidence


def test_assert_form_values_supports_value_and_readonly() -> None:
    evidence = FormFieldsEvidence(
        fields=[
            FormFieldEvidence(label="店铺名称", name="storeName", value="旗舰店"),
            FormFieldEvidence(label="店铺ID", name="storeId", value="S001", readonly=True),
        ],
    )

    value_verdict = assert_form_values(expected="店铺名称为旗舰店", evidence=evidence)
    readonly_verdict = assert_form_values(expected="店铺ID字段只读", evidence=evidence)

    assert value_verdict.passed is True
    assert "店铺名称=旗舰店" in value_verdict.evidence
    assert readonly_verdict.passed is True
    assert "只读" in readonly_verdict.reason


def test_assert_form_values_treats_missing_readonly_field_as_invisible_when_expected_allows_it() -> None:
    verdict = assert_form_values(
        expected="新增列对应的字段为只读状态或不可见，无法进行手动输入或修改",
        evidence=FormFieldsEvidence(fields=[]),
    )

    assert verdict is not None
    assert verdict.passed is True
    assert "不可见" in verdict.reason


def test_assert_form_values_treats_no_edit_entry_as_invisible() -> None:
    verdict = assert_form_values(
        expected="单元格无法进入编辑状态，无输入光标闪烁，无编辑入口",
        evidence=FormFieldsEvidence(fields=[]),
    )

    assert verdict is not None
    assert verdict.passed is True
    assert "无编辑入口" in verdict.reason


def test_judge_structured_assertion_infers_table_columns_from_expected_text() -> None:
    verdict = judge_structured_assertion(
        expected="验证列表列名包含店铺ID、店铺名称、平台",
        structured_evidence={
            "table_schema": {
                "columns": ["店铺ID", "店铺名称", "平台"],
                "visible_columns": ["店铺ID", "店铺名称"],
                "total_columns": 3,
            },
        },
    )

    assert verdict is not None
    assert verdict.passed is True
    assert verdict.method == "text_search"


def test_judge_structured_assertion_accepts_object_columns_from_browser_evaluate() -> None:
    verdict = judge_structured_assertion(
        expected="列表至少一行数据",
        structured_evidence={
            "table_rows": {
                "columns": [{"i": 0, "text": "导出时间"}, {"i": 1, "text": "店铺ID"}],
                "rows": [{"导出时间": "2026-05-22", "店铺ID": "S001"}],
                "row_count": 1,
            },
        },
    )

    assert verdict is not None
    assert verdict.passed is True


def test_judge_structured_assertion_accepts_non_string_table_row_values() -> None:
    verdict = judge_structured_assertion(
        expected="列表至少一行数据",
        structured_evidence={
            "table_rows": {
                "columns": [{"i": 0, "text": "导出时间"}, {"i": 1, "text": "店铺ID"}],
                "rows": [
                    {
                        "row": 0,
                        "cells": [{"text": "2026-05-22"}, {"text": "S001"}],
                        "导出时间": 20260522,
                    },
                ],
                "row_count": 1,
            },
        },
    )

    assert verdict is not None
    assert verdict.passed is True


def test_judge_structured_assertion_filters_verbose_column_suffixes() -> None:
    verdict = judge_structured_assertion(
        expected=(
            "列名分别为：提现银行账户、(分录)科目编码、(分录)科目名称，"
            "括号及文字完全一致，无歧义"
        ),
        structured_evidence={
            "table_schema": {
                "columns": ["提现银行账户", "（分录）科目编码", "（分录）科目名称"],
                "visible_columns": ["提现银行账户", "（分录）科目编码"],
                "total_columns": 3,
            },
        },
    )

    assert verdict is not None
    assert verdict.passed is True


def test_judge_structured_assertion_returns_none_when_rule_not_applicable() -> None:
    verdict = judge_structured_assertion(
        expected="页面整体符合业务预期",
        structured_evidence={},
    )

    assert verdict is None
