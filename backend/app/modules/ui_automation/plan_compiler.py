"""Rule-first compiler from natural-language test steps to UIActionPlan."""

from __future__ import annotations

import re
from typing import Any, Protocol

from app.modules.ui_automation.action_plan import (
    ActionTarget,
    PlanCompileResult,
    UIActionKind,
    UIActionPlan,
    UIActionStep,
)


# Phase 15.5: plan_compiler 接 data_resolver. 用结构化 Protocol 而不是直接 import
# TestDataResolver 避免循环依赖, 同时保留可注入测试桩的能力.
class _TemplateRenderer(Protocol):
    def render_template(self, text: str) -> str: ...


# Phase 15.5: render 后仍含 {{xxx}} 视作"未解析占位符", 编译为 UNSUPPORTED 步骤,
# unsupported_reason 列出缺失 key 列表. 与 preflight_data_check 协同: preflight
# 给 SSE 警告 + strict 拒绝, 这里给"哪一步具体被拦"的细粒度信息, 便于前端定位.
_UNRESOLVED_VAR_RE = re.compile(r"\{\{\s*([\w.-]+)\s*\}\}")

# Phase 15.8: 公共反爬关键词. 历史 16 次执行 100% 失败的 demo 用例都集中在
# 这几个 host 上 (5 条百度搜索类). 命中即标 unsupported_reason
# ``public_anti_bot_target``, preflight 阶段直接拒绝, 让用户改去内网受控环境.
# 关键字使用小写明文匹配 (会先把待检文本 .lower()), 仅匹配 public host 域名片段
# 减少误伤 (内网 *.example.com 不会命中, 即便业务功能里出现 "verify" 字样也不算).
_PUBLIC_ANTI_BOT_KEYWORDS: tuple[str, ...] = (
    "baidu.com",
    "google.com",
    "google.cn",
    "cloudflare-challenge",
    "challenges.cloudflare.com",
    "hcaptcha.com",
    "recaptcha.net",
    "wappass.baidu.com",
)

_CLICK_RE = re.compile(r"(?:点击|单击|点一下|点选)\s*(?P<name>.+?)(?:按钮|按键|$)")
_ABSOLUTE_HTTP_URL_RE = re.compile(
    r"https?://[^\s，,；;。)）\]】》」\"'“”‘’]+",
    re.IGNORECASE,
)
_DANGEROUS_WORDS = ("删除", "清空", "提交", "发布", "支付", "批量")

# Phase 15.3: 点击这些按钮通常会触发 ajax 数据刷新, 后端往返几百 ms 才能拿到
# 真实数据. 编译期识别后, deterministic_runner 会把等待级别从 quick 升到
# data_refresh (networkidle + loading mask 消失探测). 命中即标记, 取广不取窄.
_DATA_REFRESH_BUTTON_WORDS = (
    "查询", "搜索", "刷新", "确定", "确认", "提交", "登录",
    "导入", "导出", "应用", "过滤",
)
_SPLIT_RE = re.compile(r"[、,，;；/\n]+")


def compile_action_plan(
    testcase: Any,
    *,
    module_entry_path: str | None = None,
    data_resolver: _TemplateRenderer | None = None,
) -> PlanCompileResult:
    """Compile one testcase into a lightweight, auditable action plan.

    This function is intentionally side-effect free: it does not touch browser,
    database, execution rows, or existing StepRunner behavior.

    Phase 15.5: 当传入 ``data_resolver`` 时, 编译每条 step 之前会先调
    ``resolver.render_template`` 把 ``{{key}}`` 替换为实际值; 渲染后仍含
    ``{{...}}`` 的步骤视为"占位符未解析", 直接编译为 ``UNSUPPORTED``,
    ``unsupported_reason`` 列出缺失 key. 不传 resolver 时保持旧行为 (兼容
    所有现有调用点 + 离线 plan 预览路径).
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
        rendered_step, unresolved_keys = _maybe_render_step(raw_step, data_resolver)
        if unresolved_keys:
            step_number = int(getattr(raw_step, "step_number", 0) or 0)
            keys_text = ", ".join(f"{{{{{k}}}}}" for k in unresolved_keys)
            compiled = _unsupported(
                step_number,
                _clean_text(getattr(raw_step, "action", "") or ""),
                f"unresolved_placeholder: {keys_text}",
            )
        else:
            compiled = _compile_step(rendered_step, has_module_entry=bool(module_entry))
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
    # Phase 15.3: 回车键在搜索框 / 表单上 99% 触发提交查询, 一律置位.
    expects_data_refresh = key.lower() == "enter"
    return UIActionStep(
        source_step_number=step_number,
        source_text=source_text,
        kind=UIActionKind.PRESS_KEY,
        value=key,
        confidence=0.82,
        requires_evidence=["page_identity"],
        risk_level="low",
        expects_data_refresh=expects_data_refresh,
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
    # Phase 15.3: 按钮名命中 _DATA_REFRESH_BUTTON_WORDS 时, 标记
    # expects_data_refresh -- runner 会等到 networkidle / loading mask 消失
    # 才采证, 避免 "点击查询 -> 立刻拿空快照断言" 的伪失败.
    expects_data_refresh = any(word in name for word in _DATA_REFRESH_BUTTON_WORDS)
    return UIActionStep(
        source_step_number=step_number,
        source_text=source_text,
        kind=UIActionKind.CLICK,
        target=ActionTarget(role="button", name=name),
        confidence=0.82,
        requires_evidence=["locator_match"],
        risk_level="high" if any(word in name for word in _DANGEROUS_WORDS) else "medium",
        expects_data_refresh=expects_data_refresh,
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
    # Phase 15.13b: 与 assertion_rules._extract_expected_columns 保持一致 --
    # 之前 Phase 15.13 只修了 assertion_rules 那份, 但实际链路是 plan_compiler
    # 在 case 启动期就把 expected 切成 step.target.columns 落进 ActionStep,
    # deterministic_runner._assert_table_columns 直接用 step.target.columns,
    # 根本不再走 assertion_rules 那份提取函数 -- 导致 #0e8f196c 仍复发
    # "表格列缺失：且这7列均位于「创建时间」列之前" 假阳性. 这里补齐.
    raw = re.split(
        r"[，,；;。]\s*"
        r"(?:括号及文字|无歧义|顺序|位置|样式|显示|展示"
        r"|且|同时|并|以及|而且|另外|此外|其中)"
        r"\S*",
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
    if cleaned in noise:
        return ""
    # Phase 15.13b: 第二道防线 -- 即便上游切分漏过, 这里识别"看起来是描述句而非
    # 列名"的内容直接丢. 真实列名罕见包含"位于/之前/之后/这\d+列/^且/均位于"
    # 等位置/数量短语; 单元长度 > 12 且含 (且|均|包含|完整|可见|对齐|无遮挡|未截断)
    # 这种"完整子句"特征词时丢弃. 列名极少超 12 字; 真要有, 也不会同时含子句词.
    # 与 assertion_rules._clean_expected_column_label 同步.
    if re.search(r"位于|之前|之后|这\d+列|^且|均位于", cleaned):
        return ""
    if len(cleaned) > 12 and re.search(
        r"且|均|包含|完整|可见|对齐|无遮挡|未截断", cleaned,
    ):
        return ""
    return cleaned


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


def _maybe_render_step(
    raw_step: Any,
    resolver: _TemplateRenderer | None,
) -> tuple[Any, list[str]]:
    """Phase 15.5: 用 resolver 渲染 step 文本; 返回 (渲染后 step-like, 缺 key 列表).

    - resolver 为 None 时直接返回原对象 + 空列表 (旧行为).
    - 渲染后扫描 ``{{xxx}}`` 残留, 列出缺失 key 给上层做 UNSUPPORTED 标记.
    - 不修改入参, 用 SimpleNamespace 仿造 ``step_number / action / expected_result``
      三个字段, 维持 ``getattr`` 接口兼容.
    """
    if resolver is None:
        return raw_step, []

    action_raw = getattr(raw_step, "action", "") or ""
    expected_raw = getattr(raw_step, "expected_result", "") or ""

    rendered_action = resolver.render_template(action_raw) if action_raw else action_raw
    rendered_expected = (
        resolver.render_template(expected_raw) if expected_raw else expected_raw
    )

    combined = " ".join(
        part for part in (rendered_action or "", rendered_expected or "") if part
    )
    unresolved = sorted(set(_UNRESOLVED_VAR_RE.findall(combined)))

    if (
        rendered_action == action_raw
        and rendered_expected == expected_raw
        and not unresolved
    ):
        return raw_step, []

    from types import SimpleNamespace

    surrogate = SimpleNamespace(
        step_number=int(getattr(raw_step, "step_number", 0) or 0),
        action=rendered_action,
        expected_result=rendered_expected,
    )
    return surrogate, unresolved


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


# Phase 15.8: public anti-bot host 识别 ──────────────────────────────────


def detect_public_anti_bot_target(
    testcase: Any,
    *,
    module_entry_url: str | None = None,
) -> str | None:
    """识别测试用例是否在打公网反爬 host (baidu / google / cloudflare 等).

    扫描范围 (按优先级):
      1. ``module_entry_url`` 显式传入的目标 URL
      2. testcase.module.entry_path (容错读取)
      3. 每条 step 的 ``action`` / ``expected_result`` (含 URL 引用 / 提示词)

    返回:
      - None         -> 未命中, 走正常编译路径
      - 命中关键字   -> 字符串形式的关键字 (例如 ``baidu.com``), 调用方据此把整条
                       case 标 ``public_anti_bot_target`` 拒绝执行.

    误判保护: 关键字仅含明确的 public host 域名片段 (不含纯英文 ``verify`` /
    ``captcha`` 词), 内网 *.example.com 业务页面里出现 "verify" 字样不会命中.
    """
    haystacks: list[str] = []
    if module_entry_url:
        haystacks.append(module_entry_url)
    module = getattr(testcase, "module", None)
    entry_path = getattr(module, "entry_path", None) if module is not None else None
    if entry_path:
        haystacks.append(str(entry_path))
    for step in getattr(testcase, "steps", []) or []:
        action = getattr(step, "action", None)
        if action:
            haystacks.append(str(action))
        expected = getattr(step, "expected_result", None)
        if expected:
            haystacks.append(str(expected))

    blob = "\n".join(haystacks).lower()
    if not blob:
        return None
    for keyword in _PUBLIC_ANTI_BOT_KEYWORDS:
        if keyword in blob:
            return keyword
    return None
