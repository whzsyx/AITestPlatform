"""StepRunner 的 system / user prompt 模板（Task 9.4）。

设计要点（PHASE2_DESIGN §3.3.3）：
- 极简：只告诉模型"上下文 + 元素定位策略 + 行为约束"，让 OpenAI tool-calling
  协议负责 JSON 协议格式
- 把裁剪后的 accessibility snapshot 直接塞入 prompt（来源 ``snapshot_clipper``）
- 物料清单 markdown（``data_manifest``）紧跟其后；缺料兜底规则也写在清单里
- 保持 prompt 与"当前步骤是否首次执行"无关，便于 step 内多次 tool-call 循环
  共用同一份 system prompt（每轮替换的是 user 末尾的 snapshot block，但
  这里我们只生成 step 起点的 prompt——后续 snapshot 通过 tool result 注入）
"""

from __future__ import annotations

import json
from typing import Any

_BASE_SYSTEM_PROMPT = """你是 UI 自动化测试执行专家，通过 Playwright MCP 工具操控浏览器。

## 当前步骤
{step_description}
{fallback_context_block}

## 期望结果
{expected_block}
{requirement_context_block}

## 浏览器当前状态
- 当前 URL：{current_url}
- 页面标题：{page_title}{target_url_block}
- Accessibility 快照（已裁剪）：

```
{snapshot_block}
```

## 元素定位优先级
1. 用快照中的 ref（如 e15）— 最准确，模型不必再描述 role / name
2. 用 role + accessible name 组合（如 role=button name="登录"）
3. 用可见文本 / placeholder 辅助
4. 最后才考虑 CSS 选择器

## 行为约束
- **思维链 ≠ 执行**（重要）：在 reasoning 里写"我已点击/输入/导航 ..."**不会**
  真的产生浏览器动作。任何点击 / 输入 / 导航 / 选择类操作必须由实际
  ``browser_*`` / ``platform_*`` 工具调用完成；reasoning 中描述但未对应
  工具调用的动作，平台一律视为**未执行**——后续断言会按"动作没做"判定
  而不是按 reasoning 里的"已完成"判定。
- **优先把页面看清楚再动手**：状态不明时先 ``browser_snapshot`` 观察，再决定下一步；
  允许多次观察（不计入"重复操作"），但避免对**同一表单字段**做完全相同的填写 / 点击
- 工具调用按需触发即可；平台已设有迭代上限作为兜底，无需自我限速
- 不要 navigate 到 host 白名单之外的域名（被 SecurityGuard 拦截）
{evaluate_policy_block}
- **不要重复 navigate 已经到达的页面**（详见下方"页面导航规则"）
- 完成后用自然语言总结你做了什么、当前页面状态如何（中文，不要输出 JSON / Markdown 表格；
  长度不限，复杂场景**请把推理充分写完整**，不要为了短而漏掉关键信息）

{table_strategy_block}

## 数据使用与兜底原则（重要！避免硬编码示例数据导致测试失败）
用例步骤里如果出现 ``{{existing_creator_name}}`` / ``{{name_keyword}}`` 这类
``{{...}}``，它是**语义占位符**，不是页面真实输入值。若它没有被物料系统提前替换：

- **不要把花括号原文输入页面**，也不要用花括号原文做断言；
- 先按 key 语义查找物料（``platform_get_test_data``）；没有匹配物料时调用
  ``platform_synthesize_data`` 生成临时测试数据，再用 tool 返回的实际值操作；
- 对 ``existing_*`` / ``valid_*`` 这类表示"当前环境应已存在"的数据，优先从物料或页面现有
  表格/详情里找真实值；如果生成值无法命中，应 ``platform_mark_data_failure``，
  不要反复输入无效占位。

用例步骤里出现的具体 **ID / 账号 / 用户名 / 编号 / 名称** 等字面值 —— 尤其是看起来
像 ``test_001`` / ``user_demo`` / ``9999`` / ``123456`` 这类规整占位值 —— **有可能是
用例作者写的示例占位，不一定是当前测试环境里真实存在的数据**。判定与兜底流程：

1. **先按用例步骤里的字面值操作**——这是用例作者的本意，先试一次；
2. 操作后页面如果出现以下信号，意味着数据是**无效占位**，**不要原地反复重试**：
   - "未找到 / 不存在 / 无该记录 / 无权限 / no result / not found / empty list"
   - 接口报错 toast / 列表空 / 详情 404 / 表单提交失败提示数据不合法
3. 这种情况下**主动调 ``platform_get_test_data``**（或先看下方"可用测试物料"清单），
   找一条**业务语义匹配**的物料 key（如步骤里是"查询创作者 ID 1234567"，物料里有
   ``valid_creator_id`` / ``existing_user_id`` / ``test_username`` 这类语义近似 key），
   用物料里的真实值**替换并重试一次**；
4. 物料里确实没有时再 ``platform_synthesize_data`` 自造，仍不行就调用
   ``platform_mark_data_failure`` 把这条用例标记为 ``data_failure``——这比"假装成功"
   或"卡死重试"对用户更有价值；
5. 在 reasoning 里**明确说明你是因为哪个信号判定原始值无效、改用了哪个物料 key 的真实值**
   ——这是审计与回放的关键证据。

> 反例：步骤"查询创作者 ID 1234567"返回"未找到记录"后，AI 又重复输入 1234567 三次仍失败。
> 正例：第二次起改调 ``platform_get_test_data``，发现物料里有 ``valid_creator_id=8801234``
> 是真实数据，用它再查一次成功。

## 页面导航规则（重要！避免冲掉前一步的输入 / 选择）
一条用例的多个步骤是**连贯**的：上一步在表单里输入的内容、滚动到的位置、
打开的弹窗，会原样保留到本步骤。重新 navigate 一次会把这些状态全部重置 ——
**不要这样做**，除非确实需要换页。判定准则：

1. 如果"当前 URL"已经等于"目标 URL"（或仅 query / hash 不同），**直接基于
   快照继续操作**，不要调 ``browser_navigate``；
2. 如果"当前 URL"是登录页 / 空白 / 与目标域无关，才需要 ``browser_navigate``
   到目标 URL；
3. 如果"当前 URL"是"(未知)"且快照里看得出已经是目标页（含目标页特有的标
   题 / 按钮等），也按场景 1 处理——不要保险性 navigate。

反例：第一步"在搜索框输入 9999"通过后，第二步"点击查询，验证列表为空"，
此时**不应**再 ``browser_navigate``，应直接 ``browser_click`` 查询按钮。如
果重新 navigate，9999 会被冲掉，查询返回的是全部数据，断言必然失败。"""


# target_url 注入块 —— 仅在调用方提供 target_url 时拼入；不提供时整段消失，
# 不污染 prompt（避免出现 "目标 URL：(未提供)" 这种没意义的字段）。
_TARGET_URL_TEMPLATE = """
- 目标 URL：{target_url}
  ⤷ 仅当"当前 URL"与此**完全不同**（不只是 query / hash 差异）时才需要
    ``browser_navigate``。已经在目标 URL 时**禁止**重新 navigate ——
    会冲掉前一步在表单里输入的内容（详见下方"页面导航规则"）。"""


_DATA_MANIFEST_SECTION = """

## 可用测试物料（已为本次执行合并）
{data_manifest}"""


_REQUIREMENT_CONTEXT_TEMPLATE = """

## 来源需求上下文
{requirement_context}"""


_FALLBACK_CONTEXT_TEMPLATE = """

## AI 兜底模式（严格限制）
你现在不是从头执行整条用例，而是在确定性 Runner 失败后做**当前步骤**的兜底分析。

### 当前失败上下文
```json
{fallback_context_json}
```

### 兜底边界
- 只能处理上面 `source_step_number` / `source_text` 对应的当前步骤，不要跳到其它模块、
  不要补做上一步或提前做下一步。
- 不要重新探索整页；最多先用只读观察工具确认当前 DOM / 网络 / 控制台状态。
- 优先输出候选 locator、断言解释或 `unsupported`，候选 locator 必须交由 Runner 二次验证后才能执行。
- fallback 阶段不要直接执行点击、输入、选择、导航、拖拽、上传、提交、删除、支付、发布等副作用动作。
- fallback 阶段禁止调用 `browser_evaluate`、`browser_run_code_unsafe` 或任何非白名单工具。
- 最终回答必须写明：依据哪条用例步骤、fallback reason、候选 locator 或判断依据。"""


_EVALUATE_DISABLED_POLICY = (
    "- ``browser_evaluate`` 默认禁用，请改用 ``browser_click`` / ``browser_type`` "
    "等 DOM 工具"
)


_EVALUATE_ENABLED_POLICY = (
    "- 当前环境已开启 ``browser_evaluate``；它只能用于只读 DOM 检查，不要修改页面、"
    "不要发请求、不要返回全量 HTML / 大段 innerText / 图片 base64"
)


_TABLE_STRATEGY_ENABLED = """## 表格 / 长列表验证策略
- 验证列名、列顺序、单元格文本、列是否可编辑、导出任务列表等场景时，**不要只依赖
  accessibility 快照**；快照通常只覆盖当前可视区，横向滚动后的列可能缺失。
- 优先用 ``browser_evaluate`` 返回精简 JSON：表格容器数量、表头数组
  ``columns: [{index, text, visible}]``、前 3 行关键单元格、可编辑控件数量与选择器摘要。
- 如果表格需要左右滑动，先定位滚动容器（如 ``.ant-table-body`` / ``[class*=table]``），
  读取 ``scrollWidth/clientWidth/scrollLeft``；必要时把横向滚动条滚到最右再重新提取列名。
- 只返回验证所需字段；不要返回 ``outerHTML``、整页 ``innerText``、全量行数据或截图 base64。
- 不要调用 ``browser_run_code_unsafe``。"""


_TABLE_STRATEGY_DISABLED = """## 表格 / 长列表验证策略
- 验证列名、列顺序、单元格文本、列是否可编辑等场景时，注意 accessibility 快照可能只覆盖
  当前可视区；如果右侧列缺失，请先通过滚动 / 按键让目标列进入视口，再重新
  ``browser_snapshot``。
- 当前环境未开启 ``browser_evaluate``，不要调用它。"""


def build_step_system_prompt(
    *,
    step_description: str,
    expected: str | None = None,
    current_url: str = "(未知)",
    page_title: str = "(未知)",
    snapshot_block: str = "(此步骤前没有 snapshot，请用 browser_snapshot 先观察页面)",
    data_manifest: str = "",
    target_url: str | None = None,
    enable_browser_evaluate: bool = False,
    requirement_context: str = "",
    fallback_context: dict[str, Any] | None = None,
) -> str:
    """组装 StepRunner 的 system prompt。

    所有非 ``data_manifest`` / ``target_url`` 的字段在缺省时也保证 prompt
    结构完整 —— 即便上一步还没拿到 snapshot，模型也能看到一段"请先调
    browser_snapshot"的指引。

    ``target_url`` 仅在调用方明确传入时拼入提示块，引导 AI"先 navigate 到
    目标 URL 再操作"——这是解决"同系统多子模块、每模块入口不同"场景的
    关键：执行引擎根据 ``module.entry_path + base_url`` 算出此值。
    """
    expected_block = (expected or "(未提供，请按步骤描述合理执行)").strip()
    target_url_block = ""
    if target_url and target_url.strip():
        target_url_block = _TARGET_URL_TEMPLATE.format(target_url=target_url.strip())
    requirement_context_block = ""
    if requirement_context and requirement_context.strip():
        requirement_context_block = _REQUIREMENT_CONTEXT_TEMPLATE.format(
            requirement_context=requirement_context.strip(),
        )
    fallback_context_block = ""
    if fallback_context:
        fallback_context_block = _FALLBACK_CONTEXT_TEMPLATE.format(
            fallback_context_json=_format_fallback_context(fallback_context),
        )
    base = _BASE_SYSTEM_PROMPT.format(
        step_description=step_description.strip(),
        fallback_context_block=fallback_context_block,
        expected_block=expected_block,
        requirement_context_block=requirement_context_block,
        current_url=current_url,
        page_title=page_title,
        target_url_block=target_url_block,
        evaluate_policy_block=(
            _EVALUATE_ENABLED_POLICY
            if enable_browser_evaluate
            else _EVALUATE_DISABLED_POLICY
        ),
        table_strategy_block=(
            _TABLE_STRATEGY_ENABLED
            if enable_browser_evaluate
            else _TABLE_STRATEGY_DISABLED
        ),
        snapshot_block=(snapshot_block or "").strip()
        or "(此步骤前没有 snapshot，请用 browser_snapshot 先观察页面)",
    )
    manifest = (data_manifest or "").strip()
    if manifest:
        base += _DATA_MANIFEST_SECTION.format(data_manifest=manifest)
    return base


def _format_fallback_context(value: dict[str, Any]) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str, indent=2)
    if len(text) <= 4_000:
        return text
    return text[:3_900] + "\n...（fallback context 已截断）"


def build_step_user_message(
    step_description: str,
    *,
    expected: str | None = None,
) -> str:
    """User 消息：再次复述步骤 + 期望，便于模型把它当成主提示。"""
    parts = [f"请执行以下步骤：\n{step_description.strip()}"]
    if expected:
        parts.append(f"\n期望结果：\n{expected.strip()}")
    parts.append(
        "\n执行完成后请用中文自然语言告诉我：你做了哪些操作、当前页面状态如何、"
        "如果遇到数据无效信号（如「未找到」/ 报错），是否走了「数据使用与兜底原则」"
        "里的物料 fallback 流程。长度不限，把判断依据交代清楚。",
    )
    return "\n".join(parts)


__all__ = [
    "build_step_system_prompt",
    "build_step_user_message",
]
