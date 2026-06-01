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


def test_compiler_does_not_harden_vague_related_route_expectation() -> None:
    result = compile_action_plan(
        _case_with_steps(
            (
                "进入创作者管理页面",
                "页面正常加载，URL 包含 /creator-management 或相关路由，页面顶部显示标题",
            ),
        ),
        module_entry_path="/author-list",
    )

    assert [step.kind for step in result.plan.steps] == [
        UIActionKind.NAVIGATE,
        UIActionKind.ASSERT_PAGE_LOADED,
    ]
    assert result.plan.steps[1].target.url == "{{module.entry_url}}"


def test_compiler_does_not_treat_column_value_placeholder_as_column_name() -> None:
    result = compile_action_plan(
        _case_with_steps(
            (
                "点击查询按钮",
                "列表刷新，创作者ID列均包含 {{existing_creator_id}}",
            ),
        ),
    )

    step = result.plan.steps[0]
    assert step.kind == UIActionKind.CLICK


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


def test_compiler_normalizes_comma_separated_fill_values_when_step_requests_english_comma() -> None:
    result = compile_action_plan(
        _case(
            "在「创作者ID」输入框输入 {{creator_id_1}}、{{creator_id_2}}（使用英文逗号分隔）",
        ),
    )

    step = result.plan.steps[0]
    assert step.kind == UIActionKind.FILL
    assert step.target.label == "创作者ID"
    assert step.value == "{{creator_id_1}},{{creator_id_2}}"


def test_click_step_with_list_expected_is_not_misclassified_as_table_columns() -> None:
    result = compile_action_plan(
        _case_with_steps(("点击查询按钮", "列表刷新并展示查询结果")),
    )

    step = result.plan.steps[0]
    assert step.kind == UIActionKind.CLICK
    assert step.target.name == "查询"


def test_compiler_treats_browser_address_url_input_as_navigation() -> None:
    result = compile_action_plan(
        _case("在浏览器地址栏输入 https://www.baidu.com 并回车"),
    )

    step = result.plan.steps[0]
    assert step.kind == UIActionKind.NAVIGATE
    assert step.target.url == "https://www.baidu.com"


def test_compiler_strips_cjk_closing_quote_from_explicit_url() -> None:
    result = compile_action_plan(
        _case("打开浏览器，访问「https://www.baidu.com」"),
    )

    step = result.plan.steps[0]
    assert step.kind == UIActionKind.NAVIGATE
    assert step.target.url == "https://www.baidu.com"


def test_compiler_maps_no_input_empty_step_to_form_assertion() -> None:
    result = compile_action_plan(
        _case_with_steps(
            ("保持「搜索框」为空，不输入任何内容", "搜索框内无文本"),
        ),
    )

    step = result.plan.steps[0]
    assert step.kind == UIActionKind.ASSERT_FORM_VALUES
    assert step.target.label == "搜索框"
    assert step.value == "搜索框内无文本"


def test_compiler_maps_enter_key_to_deterministic_press_key() -> None:
    result = compile_action_plan(
        _case_with_steps(
            ("按下键盘「Enter」键", "页面跳转至搜索结果页，地址栏包含关键字「/s?」"),
        ),
    )

    step = result.plan.steps[0]
    assert step.kind == UIActionKind.PRESS_KEY
    assert step.value == "Enter"


def test_compiler_maps_common_loaded_step_to_page_loaded_assertion() -> None:
    result = compile_action_plan(
        _case_with_steps(
            ("进入百度首页，等待页面加载完成", "页面正常显示，搜索框可见"),
        ),
        module_entry_path="https://www.baidu.com",
    )

    assert result.unsupported_step_count == 0
    step = result.plan.steps[1]
    assert step.kind == UIActionKind.ASSERT_PAGE_LOADED
    assert step.target.url == "{{module.entry_url}}"


def test_compiler_maps_result_list_non_empty_to_table_row_assertion() -> None:
    result = compile_action_plan(
        _case_with_steps(
            ("验证搜索结果页面非空", "页面显示搜索结果列表，至少存在 1 条结果"),
        ),
    )

    step = result.plan.steps[0]
    assert step.kind == UIActionKind.ASSERT_TABLE_ROWS
    assert step.value == "页面显示搜索结果列表，至少存在 1 条结果"


def test_compiler_prioritizes_click_action_over_url_assertion_from_expected() -> None:
    result = compile_action_plan(
        _case_with_steps(
            (
                "点击「百度一下」按钮",
                "页面跳转，URL 包含 /s?wd= 或 /s?，且页面不再显示空白首页状态",
            ),
        ),
    )

    step = result.plan.steps[0]
    assert step.kind == UIActionKind.CLICK
    assert step.target.name == "百度一下"


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


# ─── Phase 15.8: public anti-bot host 识别 ────────────────────────────────


def test_detect_public_anti_bot_module_entry_url_baidu() -> None:
    from app.modules.ui_automation.plan_compiler import detect_public_anti_bot_target

    case = _case("访问百度首页搜索北京天气")
    hit = detect_public_anti_bot_target(
        case, module_entry_url="https://www.baidu.com/",
    )
    assert hit == "baidu.com"


def test_detect_public_anti_bot_step_action_google() -> None:
    from app.modules.ui_automation.plan_compiler import detect_public_anti_bot_target

    case = _case_with_steps(
        ("打开 https://www.google.com 输入 Cursor", None),
    )
    hit = detect_public_anti_bot_target(case)
    assert hit == "google.com"


def test_detect_public_anti_bot_step_expected_cloudflare() -> None:
    from app.modules.ui_automation.plan_compiler import detect_public_anti_bot_target

    case = _case_with_steps(
        ("点击查询", "页面应当出现 challenges.cloudflare.com 验证"),
    )
    hit = detect_public_anti_bot_target(case)
    assert hit == "challenges.cloudflare.com"


def test_detect_public_anti_bot_internal_host_not_matched() -> None:
    from app.modules.ui_automation.plan_compiler import detect_public_anti_bot_target

    # 内网业务页面里出现 "verify" 字样不会命中 public 关键字 (我们只匹配 host)
    case = _case_with_steps(
        ("点击 verify 按钮完成账号校验", "页面提示 verification success"),
    )
    hit = detect_public_anti_bot_target(
        case,
        module_entry_url="https://staging.internal.example.com/users",
    )
    assert hit is None


def test_detect_public_anti_bot_module_entry_path_attribute() -> None:
    """没显式传 module_entry_url 时, 从 testcase.module.entry_path 兜底读."""
    from app.modules.ui_automation.plan_compiler import detect_public_anti_bot_target

    case = _case("点击百度一下按钮")
    case.module = SimpleNamespace(entry_path="https://www.baidu.com/s")
    hit = detect_public_anti_bot_target(case)
    assert hit == "baidu.com"
