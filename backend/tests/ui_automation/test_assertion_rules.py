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


def test_assert_table_rows_supports_at_least_one_row_wording() -> None:
    verdict = assert_table_rows(
        expected="创作者列表表格至少存在 1 行数据",
        evidence=TableRowsEvidence(
            columns=["创作者ID", "创作者名称"],
            rows=[{"创作者ID": "2013", "创作者名称": "测试050801"}],
            row_count=1,
        ),
    )

    assert verdict is not None
    assert verdict.passed is True
    assert "至少一行" in verdict.reason


def test_assert_table_rows_strips_pronoun_prefix_from_column_name() -> None:
    verdict = assert_table_rows(
        expected="其创作者ID=2013 的表格行存在",
        evidence=TableRowsEvidence(
            columns=["创作者ID", "创作者名称"],
            rows=[{"创作者ID": "2013", "创作者名称": "测试050801"}],
            row_count=1,
        ),
    )

    assert verdict is not None
    assert verdict.passed is True
    assert "创作者ID=2013" in verdict.evidence


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


def test_assert_form_values_supports_empty_searchbox_semantics() -> None:
    verdict = assert_form_values(
        expected="搜索框内无文本",
        evidence=FormFieldsEvidence(
            fields=[
                FormFieldEvidence(
                    placeholder="请输入搜索内容",
                    name="wd",
                    value="",
                    type="search",
                ),
            ],
        ),
    )

    assert verdict is not None
    assert verdict.passed is True
    assert "空值" in verdict.reason or "无文本" in verdict.reason


def test_assert_form_values_fails_empty_expectation_when_field_has_value() -> None:
    verdict = assert_form_values(
        expected="搜索框内无文本",
        evidence=FormFieldsEvidence(
            fields=[
                FormFieldEvidence(
                    placeholder="请输入搜索内容",
                    name="wd",
                    value="北京天气",
                    type="search",
                ),
            ],
        ),
    )

    assert verdict is not None
    assert verdict.passed is False
    assert "北京天气" in verdict.evidence


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


def test_judge_structured_assertion_prefers_page_url_over_empty_table_rows() -> None:
    verdict = judge_structured_assertion(
        expected="页面正常加载，地址栏显示 https://www.baidu.com",
        structured_evidence={
            "page_identity": {
                "url": "https://www.baidu.com/",
                "title": "百度一下，你就知道",
            },
            "table_rows": {"columns": [], "rows": [], "row_count": 0},
        },
    )

    assert verdict is not None
    assert verdict.passed is True
    assert "地址栏" in verdict.reason or "URL" in verdict.reason


def test_judge_structured_assertion_reports_url_mismatch_without_table_row_reason() -> None:
    verdict = judge_structured_assertion(
        expected="页面正常加载，地址栏显示 https://www.baidu.com",
        structured_evidence={
            "page_identity": {
                "url": "https://wappass.baidu.com/static/captcha/tuxing_v2.html",
                "title": "安全验证",
            },
            "table_rows": {"columns": [], "rows": [], "row_count": 0},
        },
    )

    assert verdict is not None
    assert verdict.passed is False
    assert "表格行" not in verdict.reason
    assert "https://www.baidu.com" in verdict.evidence


def test_judge_structured_assertion_prefers_searchbox_value_over_empty_table_rows() -> None:
    verdict = judge_structured_assertion(
        expected="搜索框内显示「测试」",
        structured_evidence={
            "form_fields": {
                "fields": [
                    {"placeholder": "热点新闻", "name": "chat-textarea", "value": "测试"},
                ],
            },
            "table_rows": {"columns": [], "rows": [], "row_count": 0},
        },
    )

    assert verdict is not None
    assert verdict.passed is True
    assert "测试" in verdict.evidence


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


def test_judge_structured_assertion_verifies_form_contains_expected_fields() -> None:
    verdict = judge_structured_assertion(
        expected="右侧弹出侧边弹窗，弹窗标题显示“添加创作者”，表单包含创作者名称、创作者简介、创作者头像等字段",
        structured_evidence={
            "form_fields": {
                "fields": [
                    {"label": "创作者名称", "placeholder": "创作者名称"},
                    {"label": "创作者简介", "placeholder": "创作者简介"},
                    {"label": "创作者头像", "placeholder": "创作者头像"},
                ],
            },
            "page_text": {
                "texts": ["添加创作者", "创作者名称", "创作者简介", "创作者头像"],
            },
        },
    )

    assert verdict is not None
    assert verdict.passed is True
    assert "创作者名称" in verdict.evidence


def test_judge_structured_assertion_prefers_form_value_for_input_value_expectation() -> None:
    verdict = judge_structured_assertion(
        expected="输入框值显示为 2013",
        structured_evidence={
            "table_rows": {
                "columns": ["创作者ID", "创作者名称"],
                "rows": [{"创作者ID": "1001", "创作者名称": "其他"}],
                "row_count": 20,
            },
            "form_fields": {
                "fields": [
                    {"placeholder": "创作者ID", "value": "2013"},
                    {"placeholder": "创作者名称", "value": ""},
                ],
            },
        },
    )

    assert verdict is not None
    assert verdict.passed is True
    assert "2013" in verdict.evidence


def test_judge_structured_assertion_prefers_form_dialog_over_existing_table_rows() -> None:
    verdict = judge_structured_assertion(
        expected="右侧弹出侧边弹窗，弹窗标题显示“添加创作者”，表单包含创作者名称、创作者简介、创作者头像等字段",
        structured_evidence={
            "table_rows": {
                "columns": ["创作者ID", "创作者名称"],
                "rows": [{"创作者ID": "2013", "创作者名称": "测试050801"}],
                "row_count": 20,
            },
            "form_fields": {
                "fields": [
                    {"label": "创作者名称", "placeholder": "创作者名称"},
                    {"label": "创作者简介", "placeholder": "创作者简介"},
                    {"label": "创作者头像", "placeholder": "创作者头像"},
                ],
            },
            "page_text": {
                "texts": ["添加创作者", "创作者名称", "创作者简介", "创作者头像"],
            },
        },
    )

    assert verdict is not None
    assert verdict.passed is True
    assert "创作者名称" in verdict.evidence


def test_judge_structured_assertion_extracts_fields_after_page_contains_clause() -> None:
    verdict = judge_structured_assertion(
        expected="右侧弹出侧边弹窗，弹窗标题显示“新增创作者”，页面包含创作者名称、创作者简介、创作者头像等字段",
        structured_evidence={
            "form_fields": {
                "fields": [
                    {"placeholder": "创作者ID"},
                    {"placeholder": "请输入创作者名称"},
                    {"placeholder": "请输入创作者简介"},
                    {"name": "file", "type": "file"},
                ],
            },
            "page_text": {
                "texts": [
                    "新增创作者",
                    "创作者名称 0/20 创作者简介 0/100 创作者头像 形象照片 取消 保存",
                    "创作者名称",
                    "创作者简介",
                    "创作者头像",
                ],
            },
            "table_rows": {
                "columns": ["创作者ID", "创作者名称"],
                "rows": [{"创作者ID": "2013", "创作者名称": "测试050801"}],
                "row_count": 20,
            },
        },
    )

    assert verdict is not None
    assert verdict.passed is True
    assert "页面包含创作者名称" not in verdict.evidence


def test_assert_table_rows_requires_each_value_in_multi_value_column_expectation() -> None:
    passed = assert_table_rows(
        expected="查询结果中同时包含创作者ID为 2013 和 2012 的行数据",
        evidence=TableRowsEvidence(
            columns=["创作者ID", "创作者名称"],
            rows=[
                {"创作者ID": "2013", "创作者名称": "测试050801"},
                {"创作者ID": "2012", "创作者名称": "长轻优选"},
            ],
            row_count=2,
        ),
    )
    failed = assert_table_rows(
        expected="查询结果中同时包含创作者ID为 2013 和 2012 的行数据",
        evidence=TableRowsEvidence(
            columns=["创作者ID", "创作者名称"],
            rows=[{"创作者ID": "2013", "创作者名称": "测试050801"}],
            row_count=1,
        ),
    )

    assert passed is not None
    assert passed.passed is True
    assert passed.evidence.startswith("创作者ID=")
    assert "2013、2012" in passed.evidence
    assert failed is not None
    assert failed.passed is False
    assert "2012" in failed.reason


def test_assert_form_values_does_not_misroute_to_first_input_when_placeholder_is_specific() -> None:
    """Phase 15.12 回归 — 现场 #c5332835.

    搜索表单含两个 input (placeholder=创作者ID, placeholder=创作者名称).
    expected="创作者名称输入框值显示为 测试" 必须命中 placeholder="创作者名称"
    的字段, 不能被 _field_matches_semantic_reference 兜底误绑到第一个
    input (placeholder="创作者ID") 拿出无关 evidence "创作者ID=571222".
    """
    evidence = FormFieldsEvidence(
        fields=[
            FormFieldEvidence(
                placeholder="创作者ID",
                value="571222",
                type="text",
                tag_name="input",
            ),
            FormFieldEvidence(
                placeholder="创作者名称",
                value="测试",
                type="text",
                tag_name="input",
            ),
        ],
    )

    verdict = assert_form_values(
        expected="创作者名称输入框值显示为 测试",
        evidence=evidence,
    )

    assert verdict is not None
    assert verdict.passed is True, (
        f"应命中 placeholder=创作者名称 字段 (value=测试), "
        f"实际 reason={verdict.reason!r} evidence={verdict.evidence!r}"
    )
    assert "创作者名称" in verdict.evidence
    assert "571222" not in verdict.evidence


def test_assert_form_values_does_not_misroute_creator_id_to_creator_name() -> None:
    """反向不回归: expected 指 ID 字段时, 仍命中 ID 字段, 不被名称字段抢走."""
    evidence = FormFieldsEvidence(
        fields=[
            FormFieldEvidence(
                placeholder="创作者ID",
                value="571222",
                type="text",
                tag_name="input",
            ),
            FormFieldEvidence(
                placeholder="创作者名称",
                value="测试",
                type="text",
                tag_name="input",
            ),
        ],
    )

    verdict = assert_form_values(
        expected="创作者ID输入框值显示为 571222",
        evidence=evidence,
    )

    assert verdict is not None
    assert verdict.passed is True
    assert "创作者ID=571222" in verdict.evidence
    # 反向回归断言: 不能拿到名称字段的 value=测试
    assert "测试" not in verdict.evidence


def test_assert_form_values_falls_back_to_semantic_reference_when_no_token_match() -> None:
    """语义兜底仍然有效: expected 没有任何具体 label, 只有泛指"搜索框", 仍能命中."""
    evidence = FormFieldsEvidence(
        fields=[
            FormFieldEvidence(
                placeholder="请输入搜索内容",
                name="wd",
                value="北京",
                type="search",
                tag_name="input",
            ),
        ],
    )

    verdict = assert_form_values(
        expected="搜索框值显示为 北京",
        evidence=evidence,
    )

    assert verdict is not None
    assert verdict.passed is True
    assert "北京" in verdict.evidence
