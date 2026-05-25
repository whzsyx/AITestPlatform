from __future__ import annotations

import uuid
from types import SimpleNamespace

from app.modules.ui_automation.action_plan import UIActionKind
from app.modules.ui_automation.plan_compiler import compile_action_plan


def _case(*actions: str) -> SimpleNamespace:
    case_id = uuid.uuid4()
    return SimpleNamespace(
        id=case_id,
        title="店铺列表列名验证",
        required_test_data=[],
        steps=[
            SimpleNamespace(
                step_number=idx,
                action=action,
                expected_result=None,
            )
            for idx, action in enumerate(actions, start=1)
        ],
    )


def _case_with_steps(*steps: tuple[str, str | None]) -> SimpleNamespace:
    case_id = uuid.uuid4()
    return SimpleNamespace(
        id=case_id,
        title="店铺列表查询",
        required_test_data=[],
        steps=[
            SimpleNamespace(
                step_number=idx,
                action=action,
                expected_result=expected,
            )
            for idx, (action, expected) in enumerate(steps, start=1)
        ],
    )


def test_compiler_adds_module_entry_navigate_and_table_columns() -> None:
    result = compile_action_plan(
        _case("验证店铺列表列名包含店铺ID、店铺名称、平台"),
        module_entry_path="/admin/stores",
    )

    plan = result.plan
    assert plan.version == "ui-plan/v1"
    assert plan.module_entry == "/admin/stores"
    assert plan.execution_mode == "deterministic_first"
    assert result.unsupported_step_count == 0

    assert [step.kind for step in plan.steps] == [
        UIActionKind.NAVIGATE,
        UIActionKind.ASSERT_TABLE_COLUMNS,
    ]
    assert plan.steps[0].source_step_number == 0
    assert plan.steps[0].source_text == "打开模块入口"
    assert plan.steps[0].target.url == "{{module.entry_url}}"
    assert plan.steps[0].requires_evidence == ["page_identity"]
    assert plan.steps[0].risk_level == "low"

    columns_step = plan.steps[1]
    assert columns_step.source_step_number == 1
    assert columns_step.source_text == "验证店铺列表列名包含店铺ID、店铺名称、平台"
    assert columns_step.target.columns == ["店铺ID", "店铺名称", "平台"]
    assert columns_step.requires_evidence == ["table_schema"]
    assert columns_step.confidence >= 0.8


def test_compiler_uses_module_entry_assertion_for_list_page_entry_steps() -> None:
    result = compile_action_plan(
        _case_with_steps(
            ("进入电商平台管理菜单下的列表页面", "列表页面正常加载"),
            ("登录电商平台管理系统，进入电商平台管理菜单下的列表页面", "列表页面正常加载，无报错"),
        ),
        module_entry_path="/funds/ecommerce-platform",
    )

    assert [step.kind for step in result.plan.steps] == [
        UIActionKind.NAVIGATE,
        UIActionKind.ASSERT_PAGE_LOADED,
        UIActionKind.ASSERT_PAGE_LOADED,
    ]
    assert result.unsupported_step_count == 0
    assert result.plan.steps[1].target.url == "{{module.entry_url}}"
    assert result.plan.steps[2].target.url == "{{module.entry_url}}"
    assert result.plan.steps[1].requires_evidence == ["page_identity", "table_schema"]


def test_compiler_extracts_only_real_columns_from_verbose_expectations() -> None:
    result = compile_action_plan(
        _case_with_steps(
            (
                "逐一核对新增7列的列名文本",
                "列名分别为：提现银行账户、(分录)科目编码、(分录)科目名称、"
                "(分录)商户号编码、(分录)商户号名称、(分录)部门编码、"
                "(分录)部门名称，括号及文字完全一致，无歧义",
            ),
            (
                "查看列表表头，定位“创建时间”列及其前面的列",
                "在“创建时间”列之前，依次展示：提现银行账户、（分录）科目编码、"
                "（分录）科目名称、（分录）商户号编码、（分录）商户号名称、"
                "（分录）部门编码、（分录）部门名称，顺序完全一致",
            ),
        ),
    )

    first, second = result.plan.steps
    assert first.kind == UIActionKind.ASSERT_TABLE_COLUMNS
    assert first.target.columns == [
        "提现银行账户",
        "(分录)科目编码",
        "(分录)科目名称",
        "(分录)商户号编码",
        "(分录)商户号名称",
        "(分录)部门编码",
        "(分录)部门名称",
    ]
    assert second.kind == UIActionKind.ASSERT_TABLE_COLUMNS
    assert second.target.columns == [
        "提现银行账户",
        "（分录）科目编码",
        "（分录）科目名称",
        "（分录）商户号编码",
        "（分录）商户号名称",
        "（分录）部门编码",
        "（分录）部门名称",
    ]


def test_compiler_maps_generic_table_data_display_to_row_count_assertion() -> None:
    result = compile_action_plan(
        _case_with_steps(
            ("查看新增列的数据行展示情况", "新增列数据展示正常，样式与原有列保持一致"),
        ),
    )

    step = result.plan.steps[0]
    assert step.kind == UIActionKind.ASSERT_TABLE_ROWS
    assert step.value == "有数据"
    assert step.requires_evidence == ["table_rows"]


def test_compiler_maps_readonly_or_invisible_field_checks_to_form_assertion() -> None:
    result = compile_action_plan(
        _case_with_steps(
            (
                "尝试通过行编辑功能（若有）查看新增列",
                "新增列对应的字段为只读状态或不可见，无法进行手动输入或修改",
            ),
        ),
    )

    step = result.plan.steps[0]
    assert step.kind == UIActionKind.ASSERT_FORM_VALUES
    assert step.value == "新增列对应的字段为只读状态或不可见，无法进行手动输入或修改"
    assert step.requires_evidence == ["form_fields"]


def test_compiler_marks_vague_step_as_unsupported_without_guessing_click() -> None:
    result = compile_action_plan(_case("检查页面正常"))

    assert result.supported_step_count == 0
    assert result.unsupported_step_count == 1
    assert len(result.plan.steps) == 1
    step = result.plan.steps[0]
    assert step.kind == UIActionKind.UNSUPPORTED
    assert step.source_step_number == 1
    assert step.source_text == "检查页面正常"
    assert step.unsupported_reason
    assert step.target.model_dump(exclude_none=True) == {}


def test_compiler_preserves_audit_metadata_for_click_and_fill() -> None:
    result = compile_action_plan(
        _case(
            "点击新增按钮",
            "在店铺名称输入框填写{{data.store_name}}",
        ),
    )

    click_step, fill_step = result.plan.steps
    assert click_step.kind == UIActionKind.CLICK
    assert click_step.target.role == "button"
    assert click_step.target.name == "新增"
    assert click_step.requires_evidence == ["locator_match"]
    assert click_step.risk_level == "medium"
    assert click_step.confidence >= 0.7

    assert fill_step.kind == UIActionKind.FILL
    assert fill_step.target.label == "店铺名称"
    assert fill_step.value == "{{data.store_name}}"
    assert fill_step.requires_evidence == ["form_fields"]
    assert fill_step.risk_level == "low"
    assert fill_step.unsupported_reason is None


def test_click_step_with_list_expected_is_not_misclassified_as_table_columns() -> None:
    result = compile_action_plan(
        _case_with_steps(("点击查询按钮", "列表刷新并展示查询结果")),
    )

    step = result.plan.steps[0]
    assert step.kind == UIActionKind.CLICK
    assert step.target.name == "查询"


def test_compiler_supports_assert_text_and_assert_url() -> None:
    result = compile_action_plan(
        _case(
            "验证页面显示保存成功提示",
            "验证URL包含/admin/stores",
        ),
    )

    text_step, url_step = result.plan.steps
    assert text_step.kind == UIActionKind.ASSERT_TEXT
    assert text_step.target.text == "保存成功"
    assert text_step.requires_evidence == ["text"]

    assert url_step.kind == UIActionKind.ASSERT_URL
    assert url_step.target.url == "/admin/stores"
    assert url_step.requires_evidence == ["page_identity"]
