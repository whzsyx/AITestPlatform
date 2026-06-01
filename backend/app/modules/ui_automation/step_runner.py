"""StepRunner — 单步骤执行单元（Task 9.4）。

复刻一期 ``chat_service._handle_chat_stream`` 的 tool-calling 循环骨架：

1. 组 system / user prompt（含裁剪后 snapshot + 物料清单 ``data_manifest``）
2. tools = MCP browser_* 工具（来自 ``BrowserBundle.register_mcp_tools_for_agent``）
   + 可选 ``platform_*`` 物料工具（来自 ``data_resolver``）
3. for iter in range(MAX_STEP_TOOL_ITERATIONS):
    a. 调一轮 LLM（默认 ``stream_chat`` + chunk 累积；测试可注入 ``chat_round_fn``）
    b. budget.add(usage_total)；over_limit → BudgetExceededError
    c. 本轮没产生 tool_calls 则跳出（不依赖 finish_reason —— GLM 等
       gateway 在带 tool_calls 时仍会给出 ``finish_reason="stop"``）
    d. 每个 tool_call 走 ``SecurityGuard.check`` → ``run_tool`` → 把结果塞
       回 messages（tool 角色）→ 解析 snapshot 喂给 ``snapshot_clipper``
4. 返回 ``StepRunResult``（成功 / 失败 + 工具序列 + reasoning + tokens）

设计要点：
- **不**直接判定"步骤通过 / 失败"——这是 ``AssertionJudge`` 的职责
- 任何 secret 工具的 result（带 ``_test_data_secret_used``）都不进 reasoning
  日志，只留 ``<secret used>`` 占位
- ``LLMConfigLike`` Protocol 让 Engine 可以传 ORM 实例 / dataclass / 测试桩；
  本模块不依赖 LLMConfig 表
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from app.modules.llm.agent_tools import run_tool as _default_run_tool
from app.modules.llm.providers import MAX_TOKENS_LONG, safe_max_tokens, stream_chat
from app.modules.ui_automation.data_platform_tools import (
    platform_tools_openai_schemas,
    redact_tool_result_for_reasoning,
)
from app.modules.ui_automation.prompts.step_runner_system import (
    build_step_system_prompt,
    build_step_user_message,
)
from app.modules.ui_automation.security import (
    BudgetExceededError,
    SecurityError,
    SecurityGuard,
    TokenBudget,
)
from app.modules.ui_automation.snapshot_clipper import (
    MAX_SNAPSHOT_CHARS,
    ClippedSnapshot,
    RefCache,
    clip_for_llm,
)

if TYPE_CHECKING:
    from app.modules.ui_automation.security import EnvironmentLike
    from app.modules.ui_automation.test_data_resolver import TestDataResolver


logger = logging.getLogger(__name__)


# 单步骤内模型主动工具尝试轮次上限（每轮 = 一次 ``stream_chat``；一轮里可含多个
# tool_calls）。额外追加 1 轮强制 ``tool_choice="none"``，只产出文字总结，不占
# 「再调一次 snapshot」的名额。
#
# 历史 5 → 8 → 12 → 20：
# - 5：连「数据兜底 + 重试」都不够；
# - 8：modal 场景常见「点确定 → 再等一轮 browser_snapshot 看清结果」时被末轮
#   总结截断（用户看到 reasoning 里「已到工具调用上限」但仍未拿到点击后快照）；
# - 12：在仍由 ``TokenBudget`` 防失控的前提下，多给约 4 轮纯工具空间，覆盖
#   导航 / 多段输入 / 一次物料 fallback / 提交 / **提交后再 snapshot**。
# - 20：复杂后台列表 / 表单 / 弹窗链路可能需要多次 snapshot + 点击 + 等待
#   才能拿到稳定状态。最终仍由 token budget、环境安全策略和额外总结轮
#   ``tool_choice="none"`` 防止无限循环。
#
# Phase 15.7: 历史上 20 太宽松, 单步 22 toolcall / 472s / 86 万 tokens 暴走
# 样本就是从这条线放出来的. 改成"模块默认值 + settings.UI_MAX_STEP_TOOL_ROUNDS
# 覆盖 + StepRunner(max_iterations=...) 单步覆盖" 的三层结构, 默认收到 8.
MAX_STEP_TOOL_CALL_ROUNDS = 8
MAX_STEP_TOOL_ITERATIONS = MAX_STEP_TOOL_CALL_ROUNDS + 1


# ─── Public types ────────────────────────────────────────────────────


@runtime_checkable
class LLMConfigLike(Protocol):
    """StepRunner 调用 LLM 的最小契约。"""

    provider: str
    model: str
    temperature: float
    max_tokens: int
    base_url: str | None
    api_key: str | None
    """**已解密**的明文 api key；上层在传入前应调 ``crypto.decrypt``。"""


@runtime_checkable
class _BundleLike(Protocol):
    """StepRunner 只读 bundle 的少量字段，剩下的交给 SecurityGuard / tool 自行调度。"""

    execution_id: uuid.UUID


@dataclass
class ToolCallEmit:
    """模型本轮发起的一次工具调用（尚未执行）。"""

    id: str
    name: str
    arguments_json: str


@dataclass
class ChatRound:
    """一轮 LLM 调用的累积结果（不含 SSE）。"""

    content: str = ""
    reasoning: str = ""
    tool_calls: list[ToolCallEmit] = field(default_factory=list)
    finish_reason: str | None = None
    usage_total: int = 0


ChatRoundFn = Callable[..., Awaitable[ChatRound]]
ToolRunner = Callable[[str, str], Awaitable[str]]


@dataclass
class ToolCallRecord:
    """已执行（或被拦截）的 tool_call 记录。"""

    name: str
    raw_name: str
    arguments: dict[str, Any]
    result: dict[str, Any]
    duration_ms: int = 0
    blocked: bool = False
    error: str | None = None
    snapshot_after_text: str | None = None
    snapshot_after_chars: int = 0


@dataclass
class StepRunResult:
    """StepRunner 输出。``success=True`` 表示循环正常收尾；步骤通过 / 失败由
    ``AssertionJudge`` 判定。"""

    success: bool
    iterations: int
    tokens_used: int
    reasoning: str
    final_message: str
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    last_snapshot_text: str | None = None
    last_clipped: ClippedSnapshot | None = None
    error: str | None = None
    error_kind: str | None = None
    """``budget_exceeded`` / ``security_blocked`` / ``tool_failed`` / ``model_error`` /
    ``max_iterations`` / ``llm_error`` 之一；正常返回为 None。"""
    loop_break_reason: str | None = None
    """Phase 15.2 — StepRunner 循环退出原因诊断字段, 正常退出为 None.

    取值:
      - ``reasoning_drift_recovered``: 首轮 0 toolcall + reasoning 命中动作词,
        被强制 ``tool_choice="required"`` 第二轮真正调到了工具.
      - ``reasoning_drift_unrecoverable``: 救场后第二轮仍 0 toolcall, 放弃, 让
        AssertionJudge 凭原快照判定 (大概率失败, 但不会整批拖死).
      - 其它新增 reason 后续在文档 §15 追加, 不要在这里硬编码闭集合.
    """


# ─── default_chat_round：基于一期 stream_chat 的实现 ─────────────────


async def default_chat_round(
    *,
    llm: LLMConfigLike,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    tool_choice: str | dict | None = None,
) -> ChatRound:
    """流式跑一轮 chat completion，把 chunks 累积成 ChatRound。"""
    out = ChatRound()
    pending: dict[int, dict[str, Any]] = {}
    last_chunk = None
    try:
        async for chunk in stream_chat(
            provider=llm.provider,
            model=llm.model,
            messages=messages,
            api_key=llm.api_key,
            base_url=llm.base_url,
            temperature=llm.temperature,
            # 8K cap：见 providers.py MAX_TOKENS_LONG 注释；防 32K+ 配置触发 400。
            max_tokens=safe_max_tokens(llm.max_tokens, MAX_TOKENS_LONG),
            tools=tools,
            tool_choice=tool_choice,
        ):
            last_chunk = chunk
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            delta = choice.delta

            piece_reason = getattr(delta, "reasoning_content", None)
            if piece_reason:
                out.reasoning += piece_reason
            piece_text = getattr(delta, "content", None)
            if piece_text:
                out.content += piece_text

            for tc in (delta.tool_calls or []):
                slot = pending.setdefault(
                    tc.index,
                    {"id": None, "name": "", "arguments": ""},
                )
                if getattr(tc, "id", None):
                    slot["id"] = tc.id
                fn = getattr(tc, "function", None)
                if fn is not None:
                    if getattr(fn, "name", None):
                        slot["name"] = fn.name
                    if getattr(fn, "arguments", None):
                        slot["arguments"] += fn.arguments

            if choice.finish_reason:
                out.finish_reason = choice.finish_reason
    except Exception as exc:  # noqa: BLE001
        logger.exception("default_chat_round LLM call failed")
        out.finish_reason = out.finish_reason or "error"
        out.content = out.content or f"[LLM ERROR] {type(exc).__name__}: {exc}"
        out.tool_calls = []
        return out

    if last_chunk is not None and getattr(last_chunk, "usage", None):
        usage_total = getattr(last_chunk.usage, "total_tokens", None)
        if usage_total:
            out.usage_total = int(usage_total)

    for idx in sorted(pending):
        item = pending[idx]
        out.tool_calls.append(
            ToolCallEmit(
                id=item["id"] or f"call_{idx}",
                name=item["name"],
                arguments_json=item["arguments"] or "{}",
            ),
        )
    return out


# ─── helpers ─────────────────────────────────────────────────────────


def _parse_args(arguments_json: str) -> dict[str, Any]:
    if not arguments_json:
        return {}
    try:
        parsed = json.loads(arguments_json)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def _strip_namespace(name: str) -> str:
    # 命名空间分隔符为 ``__``（详见 ``data_platform_tools._tool_name`` /
    # ``mcp_bridge.MCPBridge.register_into_agent_tools``）。兼容旧记录里
    # 可能存在的 ``:`` 前缀（早期 namespaced tool 持久化在 ai_review.tool_calls /
    # state_snapshot 等地方），所以两种都剥。
    if "__" in name:
        return name.rsplit("__", 1)[-1]
    if ":" in name:
        return name.rsplit(":", 1)[-1]
    return name


def _extract_snapshot_text(result: dict[str, Any]) -> str | None:
    """从 MCP tool 返回里抽 snapshot 文本（兼容多种字段命名）。"""
    if not isinstance(result, dict):
        return None
    for key in ("snapshot", "text", "ariaSnapshot", "aria_snapshot"):
        val = result.get(key)
        if isinstance(val, str) and val.strip():
            return val
    content = result.get("content")
    if isinstance(content, str) and content.strip():
        return content
    return None


def _is_secret_tool_result(result: dict[str, Any]) -> bool:
    return isinstance(result, dict) and bool(result.get("_test_data_secret_used"))


def _tool_result_for_reasoning(tool_name: str, rec: ToolCallRecord) -> dict[str, Any]:
    """构造写回 LLM messages 的 tool result。

    ``ToolCallRecord.result`` 保留原始 MCP 返回供审计；但 browser_snapshot 的
    原始 a11y 树可能有数十万字符，若原样塞回下一轮 LLM 会迅速撑爆上下文。
    这里仅对 LLM 回灌做裁剪，避免影响落库 / 前端回放。
    """
    result = redact_tool_result_for_reasoning(tool_name, rec.result)
    if not isinstance(result, dict):
        return result

    snapshot_text = rec.snapshot_after_text
    if not snapshot_text:
        return result

    raw_snapshot = _extract_snapshot_text(rec.result)
    compact: dict[str, Any] = {
        "content": snapshot_text,
        "is_error": bool(result.get("is_error", False)),
        "_snapshot_clipped_for_reasoning": True,
        "_snapshot_original_chars": len(raw_snapshot) if raw_snapshot else len(snapshot_text),
        "_snapshot_chars": len(snapshot_text),
    }
    for key in ("error", "error_kind", "blocked_by_security"):
        if key in result:
            compact[key] = result[key]
    return compact


# 视为"不会改变页面 a11y 状态"的只读 / 元信息工具集合 —— 这些工具调用之后**不**
# 需要 auto-finalize browser_snapshot（因为它们的 tool result 里通常已经带 a11y
# 文本，或者它们本就是查询性而无 mutation）。
#
# 反之，``browser_navigate`` / ``browser_type`` / ``browser_click`` / ``browser_fill_form``
# 这类**有副作用**的工具调用之后，playwright-mcp 0.x 默认**不**返回 inline 的 a11y
# 树（只给一行 ``[Snapshot](.playwright-mcp/page-...yml)`` 文件链接），所以必须由
# StepRunner 自己强制再调一次 ``browser_snapshot`` 兜底，否则后续 ``AssertionJudge``
# 拿到的 ``last_snapshot_text`` 是操作**之前**的状态——典型表现：
# "在 X 文本框输入 9999" 通过了，但断言阶段说"快照里看不到 9999"。
_NON_MUTATING_TOOLS: frozenset[str] = frozenset({
    "browser_snapshot",
    "browser_take_screenshot", "browser_screenshot",
    "browser_console_messages", "browser_network_requests",
    "browser_tabs", "browser_tabs_list",
    # platform_* 系列（凭据 / 物料拉取等）也不影响页面，不需要 finalize
    "platform_get_secret", "platform_solve_captcha",
})

_FALLBACK_READONLY_TOOLS: frozenset[str] = frozenset({
    "browser_snapshot",
    "browser_screenshot",
    "browser_take_screenshot",
    "browser_console_messages",
    "browser_network_requests",
})
_FALLBACK_MAX_ITERATIONS = 4


def _is_mutating_tool(raw_name: str) -> bool:
    """判断 tool_call 是否是 mutation 类（需要在循环退出前 auto-finalize a11y）。"""
    if not raw_name:
        return False
    if raw_name in _NON_MUTATING_TOOLS:
        return False
    # 兜底白名单：MCP / platform 工具新版本可能加新名字，只要不是 known non-mutating
    # 都按 mutating 处理。代价：偶尔多一次冗余 snapshot，比"漏 finalize"代价低得多。
    return True


# Phase 15.2: reasoning_drift 防护 ───────────────────────────────────────
#
# 现象: thinking 类模型 (火山方舟 GLM, doubao-1.5-pro 等) 偶发把动作意图写在
# reasoning_content 里 ("我已点击查询按钮", "Submitted the form") 但**没有**
# 真正调 tool. StepRunner 看到 0 toolcall 就 break, AssertionJudge 拿到操作前
# 的快照判失败. 这一类 false negative 在 Phase 14 复盘里能稳定占 ~15% 失败步骤.
#
# 修复策略: 仅在首轮 (iteration==0) 出现 "0 toolcall + reasoning 命中动作词"
# 时, 强制再跑一轮且 ``tool_choice="required"`` -- 协议层逼模型必须选一个工具.
# 第二轮真调到工具 -> ``loop_break_reason="reasoning_drift_recovered"``;
# 第二轮仍 0 toolcall -> ``loop_break_reason="reasoning_drift_unrecoverable"``,
# 让 AssertionJudge 凭原快照判, 大概率失败但不阻塞整批.
#
# 词典选择原则: 只匹配**已发生**的动作动词 / 即将发生的明确动作动词, 不匹配纯
# 观察词 ("我看到 / This page shows"). 中文动词后会跟"按钮 / 框 / 链接"这种
# UI 元素时容易判定; 英文取常见过去时 / 现在分词 (clicked, typed, submitted,
# navigating). 误报代价只是多调一轮 LLM, 不会改变最终断言结果.
_ACTION_INTENT_PATTERN = re.compile(
    r"("
    r"已?(点击|点选|单击|双击|选中|勾选|点了|按下|按了)"
    r"|已?(输入|填入|填写|键入|敲入)"
    r"|已?(提交|确认|保存|发送|上传)"
    r"|(切换|跳转|跳到|前往|进入)(到|至)?[^\s]{0,8}(页面|路径|链接|地址)?"
    r"|\bclicked\b|\bclicking\b|\btyped\b|\btyping\b"
    r"|\bsubmitted\b|\bsubmitting\b"
    r"|\bnavigated\b|\bnavigating\b"
    r"|\bselected\b|\bselecting\b"
    r"|\bpressed\b|\bpressing\b"
    r")",
    re.IGNORECASE,
)


def _looks_like_action_intent(text: str | None) -> bool:
    """是否 reasoning / content 里出现"动作类"动词 -> 触发 drift 救场.

    None / 空串直接 False; 不抛错, 不硬依赖外部 settings -- 调用方自己判 enabled.
    """
    if not text:
        return False
    return bool(_ACTION_INTENT_PATTERN.search(text))


def _runtime_settings() -> Any:
    """延迟拿 settings, 方便 monkeypatch -- 直接 ``from app.config import settings``
    在 import 时就绑死引用, 测试 ``monkeypatch.setattr(settings, ...)`` 看不到.
    """
    from app.config import settings as _settings

    return _settings


# ─── Phase 15.7: Loop guard helpers ───────────────────────────────────


def _tool_signature(emit: ToolCallEmit) -> str:
    """组合 (raw_name, sorted-args) 的签名, 用于早停信号 a 比对连续重复工具调用.

    args 这里只 hash sorted JSON 的 sha-1 前 16 字节, 防"参数大但完全相同"
    场景下签名也跟着大. 解析失败 (非合法 JSON) 时退化为原始字符串截断.
    """
    raw = _strip_namespace(emit.name)
    try:
        args_obj = json.loads(emit.arguments_json or "{}")
        args_canon = json.dumps(args_obj, sort_keys=True, ensure_ascii=False)
    except (json.JSONDecodeError, TypeError):
        args_canon = emit.arguments_json or ""
    import hashlib
    digest = hashlib.sha1(args_canon.encode("utf-8")).hexdigest()[:16]
    return f"{raw}:{digest}"


def _snapshot_diff_pct(prev: str | None, curr: str | None) -> float:
    """估算 prev -> curr 的"变更占比", 基于行级 set diff 的归一化.

    返回 [0.0, 1.0]:
      - 0.0 = 两个 snapshot 完全一致 / 都为空
      - 1.0 = 没有重叠或 prev 为空但 curr 不为空
    历史经验: SPA 真在加载 / 弹窗出现时, 行级新增/删除 ≥ 10%; 5% 是宽松阈值,
    不会把 "data table 多了一行" 误判为 unchanged.
    """
    if prev == curr:
        return 0.0
    prev_lines = [ln for ln in (prev or "").splitlines() if ln.strip()]
    curr_lines = [ln for ln in (curr or "").splitlines() if ln.strip()]
    if not prev_lines and not curr_lines:
        return 0.0
    if not prev_lines or not curr_lines:
        return 1.0
    prev_set = set(prev_lines)
    curr_set = set(curr_lines)
    union = prev_set | curr_set
    if not union:
        return 0.0
    diff = (prev_set ^ curr_set)
    return len(diff) / len(union)


def _estimate_step_token_soft_budget(
    *,
    total_budget: int,
    estimated_total_steps: int | None,
    floor: int,
) -> int:
    """计算 Phase 15.7 信号 c 的单步软上限.

    公式 (与文档一致): ``max(floor, total * 1.5 / max(estimated, 5))``
    - total_budget <=0 / estimated 缺失 -> 直接 floor
    - 兜底确保返回正整数
    """
    if total_budget <= 0:
        return max(1, floor)
    est = estimated_total_steps if (estimated_total_steps and estimated_total_steps > 0) else 5
    derived = int(total_budget * 1.5 / max(est, 5))
    return max(floor, derived)


# ─── StepRunner ──────────────────────────────────────────────────────


class StepRunner:
    """复用一期 agent tool-calling 循环跑单步骤；不判断步骤通过 / 失败。"""

    __test__ = False

    def __init__(
        self,
        *,
        llm: LLMConfigLike,
        environment: EnvironmentLike,
        budget: TokenBudget,
        execution_id: uuid.UUID | str | None = None,
        chat_round_fn: ChatRoundFn | None = None,
        tool_runner: ToolRunner | None = None,
        ref_cache: RefCache | None = None,
        max_iterations: int | None = None,
    ) -> None:
        self.llm = llm
        self.environment = environment
        self.budget = budget
        self.execution_id = str(execution_id) if execution_id is not None else None
        self._chat_round = chat_round_fn or self._default_chat_round_default
        self._tool_runner = tool_runner or _default_run_tool
        self.ref_cache = ref_cache or RefCache()
        # Phase 15.7: max_iterations 解析三层覆盖, 优先级:
        #   1) 调用方显式传入的 max_iterations (最高, 给单步调试 / 测试用)
        #   2) settings.UI_MAX_STEP_TOOL_ROUNDS + 1 (运维通过 env 调)
        #   3) 模块默认 MAX_STEP_TOOL_ITERATIONS (本轮 9 = 8 toolcall + 1 收尾)
        if max_iterations is not None:
            self.max_iterations = int(max_iterations)
        else:
            settings_rounds = getattr(
                _runtime_settings(), "UI_MAX_STEP_TOOL_ROUNDS", None
            )
            if isinstance(settings_rounds, int) and settings_rounds > 0:
                self.max_iterations = settings_rounds + 1  # +1 留收尾轮
            else:
                self.max_iterations = MAX_STEP_TOOL_ITERATIONS
        self._guard = SecurityGuard(environment=environment, budget=budget)

    async def _default_chat_round_default(self, **kw: Any) -> ChatRound:
        return await default_chat_round(llm=self.llm, **kw)

    async def run_one(
        self,
        *,
        step_description: str,
        expected: str | None = None,
        bundle: _BundleLike | None = None,
        data_manifest: str = "",
        data_resolver: TestDataResolver | None = None,
        prev_snapshot: str | None = None,
        focus_hint: str | None = None,
        mcp_tool_specs: list[dict[str, Any]] | None = None,
        current_url: str = "(未知)",
        page_title: str = "(未知)",
        initial_snapshot_text: str | None = None,
        target_url: str | None = None,
        requirement_context: str = "",
        fallback_context: dict[str, Any] | None = None,
        estimated_total_steps: int | None = None,
    ) -> StepRunResult:
        """执行单条步骤。失败不抛错，把状态写入 ``StepRunResult.error_kind``。

        Phase 15.7: ``estimated_total_steps`` 用于推算单步 token 软上限
        (``UI_LOOP_GUARD_STEP_TOKEN_SOFT``). 没传时按 5 兜底, 与文档 §15.7 一致.
        """
        execution_id = self._resolve_execution_id(bundle)
        fallback_policy_tools = (
            _FALLBACK_READONLY_TOOLS if fallback_context else None
        )
        iteration_limit = (
            min(self.max_iterations, _FALLBACK_MAX_ITERATIONS)
            if fallback_context
            else self.max_iterations
        )

        clipped_initial: ClippedSnapshot | None = None
        if initial_snapshot_text:
            clipped_initial = clip_for_llm(
                initial_snapshot_text,
                prev_snapshot=prev_snapshot,
                max_chars=MAX_SNAPSHOT_CHARS,
                focus_hint=focus_hint,
            )
            self.ref_cache.update(clipped_initial.text)

        system_prompt = build_step_system_prompt(
            step_description=step_description,
            expected=expected,
            current_url=current_url,
            page_title=page_title,
            snapshot_block=(clipped_initial.text if clipped_initial else ""),
            data_manifest=data_manifest,
            target_url=target_url,
            requirement_context=requirement_context,
            fallback_context=fallback_context,
            enable_browser_evaluate=bool(
                getattr(self.environment, "enable_browser_evaluate", False)
            ),
        )
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": build_step_user_message(step_description, expected=expected)},
        ]

        tools = self._build_tools(
            execution_id,
            mcp_specs=mcp_tool_specs,
            data_resolver=data_resolver,
            allowed_raw_tools=fallback_policy_tools,
        )

        last_snapshot_text: str | None = (clipped_initial.text if clipped_initial else None)
        last_clipped: ClippedSnapshot | None = clipped_initial
        full_reasoning = ""
        full_content = ""
        tool_calls: list[ToolCallRecord] = []
        iterations = 0
        # Phase 15.2: drift 救场状态机. ``drift_recovery_used`` 仅允许触发一次,
        # 防"模型每轮都画饼但都不调工具"被无限循环救场拖死预算.
        # ``last_round_was_drift_forced`` 用于精确区分:
        #   - "救场中本轮就是 required 且仍 0 tc" -> 标 unrecoverable
        #   - "救场后又跑了几轮, 收尾时正常 0 tc" -> 不能误判 unrecoverable
        drift_recovery_used = False
        drift_force_required = False
        last_round_was_drift_forced = False
        loop_break_reason: str | None = None

        # Phase 15.7: loop guard 状态. 每个信号都可以单独由 settings 关掉,
        # 默认全开. 进入循环前先把"基线" 锁好, 后面对比用.
        _settings = _runtime_settings()
        loop_guard_enabled_dup = bool(
            getattr(_settings, "UI_LOOP_GUARD_DUP_TOOL", True)
        )
        loop_guard_dup_threshold = max(
            2, int(getattr(_settings, "UI_LOOP_GUARD_DUP_THRESHOLD", 2) or 2)
        )
        loop_guard_enabled_diff = bool(
            getattr(_settings, "UI_LOOP_GUARD_SNAPSHOT_DIFF", True)
        )
        loop_guard_diff_rounds = max(
            2, int(getattr(_settings, "UI_LOOP_GUARD_SNAPSHOT_DIFF_ROUNDS", 3) or 3)
        )
        loop_guard_diff_pct = float(
            getattr(_settings, "UI_LOOP_GUARD_SNAPSHOT_DIFF_PCT", 0.05) or 0.05
        )
        loop_guard_enabled_token = bool(
            getattr(_settings, "UI_LOOP_GUARD_STEP_TOKEN_SOFT", True)
        )
        step_token_floor = int(
            getattr(_settings, "UI_STEP_TOKEN_SOFT_FLOOR", 20_000) or 20_000
        )
        step_token_baseline = int(self.budget.consumed)
        step_soft_budget = _estimate_step_token_soft_budget(
            total_budget=int(self.budget.limit or 0),
            estimated_total_steps=estimated_total_steps,
            floor=step_token_floor,
        )
        tool_signature_history: list[str] = []
        snapshot_diff_history: list[float] = []
        loop_guard_meta: dict[str, Any] | None = None

        for iteration in range(iteration_limit):
            iterations = iteration + 1

            # 进入下一轮 LLM 之前先做预算守卫 —— 已超的话直接终止
            if self.budget.over_limit:
                return StepRunResult(
                    success=False,
                    iterations=iteration,
                    tokens_used=self.budget.consumed,
                    reasoning=full_reasoning,
                    final_message=full_content,
                    tool_calls=tool_calls,
                    last_snapshot_text=last_snapshot_text,
                    last_clipped=last_clipped,
                    error=(
                        f"已超过 token 预算 {self.budget.limit:,}（消耗 {self.budget.consumed:,}）"
                    ),
                    error_kind="budget_exceeded",
                )

            is_last = iteration == iteration_limit - 1
            tool_choice: str | None = None
            if drift_force_required:
                # Phase 15.2 救场: 协议层强制本轮必须选一个工具.
                tool_choice = "required"
                drift_force_required = False
                last_round_was_drift_forced = True
            else:
                last_round_was_drift_forced = False
            if is_last and iteration > 0:
                tool_choice = "none"
                last_round_was_drift_forced = False
                # 最后一轮工具被强制关掉，给 AI 一个明确收尾指令；不限制长度，
                # 让推理模型把判断过程交代清楚（早期版本写"用一句话"会截断 reasoning，
                # 推理模型典型表现：reasoning_content 写满 max_tokens 后 final content
                # 截空，AssertionJudge 拿到空快照判失败 —— 二期验收 #f6513ebb 类）
                messages.append({
                    "role": "user",
                    "content": (
                        "本步骤的单步 LLM 轮次已达安全上限（防无限循环）；本轮不能再调用工具。\n"
                        "请基于**已经返回的**快照与工具结果用中文自然语言总结：\n"
                        "1) 你完成了哪些关键操作；\n"
                        "2) 就现有信息看，页面可能处于什么状态（若最后一轮操作后尚未来得及"
                        "快照，请明说，并指出哪些证据仍来自点击/提交**之前**的快照）；\n"
                        "3) 若曾按「数据使用与兜底原则」替换过占位数据，说明依据与所用物料 key。\n"
                        "推理写充分即可。步骤是否通过与期望比对由断言评判结合最新快照再判定。"
                    ),
                })

            try:
                round_out: ChatRound = await self._chat_round(
                    messages=messages,
                    tools=tools,
                    tool_choice=tool_choice,
                )
            except (SecurityError, BudgetExceededError) as exc:
                return StepRunResult(
                    success=False,
                    iterations=iterations,
                    tokens_used=self.budget.consumed,
                    reasoning=full_reasoning,
                    final_message=full_content,
                    tool_calls=tool_calls,
                    last_snapshot_text=last_snapshot_text,
                    last_clipped=last_clipped,
                    error=str(exc),
                    error_kind=(
                        "budget_exceeded"
                        if isinstance(exc, BudgetExceededError)
                        else "security_blocked"
                    ),
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("StepRunner LLM round failed")
                return StepRunResult(
                    success=False,
                    iterations=iterations,
                    tokens_used=self.budget.consumed,
                    reasoning=full_reasoning,
                    final_message=full_content,
                    tool_calls=tool_calls,
                    last_snapshot_text=last_snapshot_text,
                    last_clipped=last_clipped,
                    error=f"{type(exc).__name__}: {exc}",
                    error_kind="llm_error",
                )

            full_reasoning += round_out.reasoning
            full_content += round_out.content
            self.budget.add(round_out.usage_total)

            if self.budget.over_limit:
                return StepRunResult(
                    success=False,
                    iterations=iterations,
                    tokens_used=self.budget.consumed,
                    reasoning=full_reasoning,
                    final_message=full_content,
                    tool_calls=tool_calls,
                    last_snapshot_text=last_snapshot_text,
                    last_clipped=last_clipped,
                    error=(
                        f"已超过 token 预算 {self.budget.limit:,}（消耗 {self.budget.consumed:,}）"
                    ),
                    error_kind="budget_exceeded",
                )

            if is_last:
                # 最后一轮强制不再 tool_call，直接收尾
                break

            # 终止条件：本轮模型没产生任何 tool_call。
            # 注意 ⚠️ 不能只看 ``finish_reason == "tool_calls"`` —— GLM (火山方舟) 等
            # 部分 OpenAI-compat 网关在带 tool_calls 的回复里仍然把 finish_reason
            # 标成 ``"stop"``，按 OpenAI 标准是 bug，但这是事实部署。我们以
            # ``tool_calls`` 是否为空作为唯一判据，更宽容也更稳。
            if not round_out.tool_calls:
                # Phase 15.2: drift 救场判定.
                # 触发条件 (全部满足):
                #   1) 配置开关 UI_REASONING_DRIFT_RECOVERY 打开 (默认 True)
                #   2) 救场未用过 (drift_recovery_used=False, 防无限救场)
                #   3) **本步骤至今 0 tool_calls** -- 否则就是"工具已调过, 模型在
                #      用文字总结收尾", 这是合法终态, 不能误判成 drift.
                #   4) 本轮 reasoning 或 content 里命中动作词
                #   5) 不是最后一轮 (last 已 break, 进不到这里, 显式判一下放心)
                drift_enabled = bool(
                    getattr(_runtime_settings(), "UI_REASONING_DRIFT_RECOVERY", True)
                )
                action_intent = _looks_like_action_intent(round_out.reasoning) or \
                    _looks_like_action_intent(round_out.content)
                if (
                    drift_enabled
                    and not drift_recovery_used
                    and not tool_calls  # 关键: 还没有任何工具调用成功过
                    and action_intent
                    and not is_last
                ):
                    drift_recovery_used = True
                    drift_force_required = True
                    # 把模型本轮的 assistant 回复 (含 reasoning_content) 放进
                    # messages, 让下一轮 LLM 看到自己上一轮"画的饼".
                    assistant_msg: dict[str, Any] = {
                        "role": "assistant",
                        "content": round_out.content or None,
                    }
                    if round_out.reasoning:
                        assistant_msg["reasoning_content"] = round_out.reasoning
                    messages.append(assistant_msg)
                    messages.append({
                        "role": "user",
                        "content": (
                            "你上一轮在思考里描述了已经完成动作 (例如点击 / 输入 / 提交), "
                            "但**没真正调用工具**, 这意味着浏览器**并没有产生任何动作**, "
                            "页面状态和上一轮快照完全一致.\n"
                            "请立即用一次 ``browser_*`` 工具调用真正执行你刚才描述的动作; "
                            "如果不需要任何动作 (步骤其实已经满足), 请只调一次 "
                            "``browser_snapshot`` 取最新快照供断言. 不要再只在文字里描述."
                        ),
                    })
                    continue
                # Phase 15.2: 救场用过 + 本轮就是被强制 required 还 0 tc -> unrecoverable.
                # 注意要看 ``last_round_was_drift_forced`` 而不是 drift_recovery_used,
                # 否则"救场后第二轮真调到工具, 第三轮收尾时 0 tc"会被误判.
                if drift_recovery_used and last_round_was_drift_forced:
                    loop_break_reason = "reasoning_drift_unrecoverable"
                break

            # Phase 15.2: 走到这里 = 本轮真有 tool_call. 如果之前用过救场,
            # 标记本步骤是"靠救场救回来的", 用于审计. 注意只在第一次救场命中
            # 后才打这个 reason, 后续轮次不再覆写.
            if drift_recovery_used and loop_break_reason is None:
                loop_break_reason = "reasoning_drift_recovered"

            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": round_out.content or None,
                "tool_calls": [
                    {
                        "id": emit.id,
                        "type": "function",
                        "function": {"name": emit.name, "arguments": emit.arguments_json},
                    }
                    for emit in round_out.tool_calls
                ],
            }
            # 思维链回填：火山方舟 / 智谱 GLM 的 thinking 模式契约 ——
            # 模型返回的 ``reasoning_content`` 必须随下一轮 assistant message 一并回传，
            # 否则下一轮请求会 400 ``The reasoning_content in the thinking mode must
            # be passed back to the API``。OpenAI 标准 chat.completions 接口会忽略
            # 未识别字段，所以无脑回传对其它 provider 安全。
            if round_out.reasoning:
                assistant_msg["reasoning_content"] = round_out.reasoning
            messages.append(assistant_msg)

            # Phase 15.7: 每轮 LLM 工具调用前快照基线 -- 用于本轮结束后算 diff%
            snapshot_before_round = last_snapshot_text

            for emit in round_out.tool_calls:
                # Phase 15.7 信号 a 准备: 把签名压栈, 但**不在循环内 break**, 等
                # 整个 round 的工具都执行完再判, 防止"两个连续相同动作"卡在中间
                # 只执行了一个就退出, 让 _meta_loop_guard 的统计不完整.
                tool_signature_history.append(_tool_signature(emit))

                rec, snapshot_for_next = await self._invoke_tool(
                    emit,
                    prev_snapshot=last_snapshot_text,
                    allowed_raw_tools=fallback_policy_tools,
                )
                tool_calls.append(rec)
                # 工具结果（脱敏后）回填到 messages
                messages.append({
                    "role": "tool",
                    "tool_call_id": emit.id,
                    "content": json.dumps(
                        _tool_result_for_reasoning(emit.name, rec),
                        ensure_ascii=False,
                    ),
                })
                if rec.blocked and isinstance(rec.error, str):
                    # 安全拦截：不一定终止整个 step，让模型看到拒绝理由后选择放弃 / 改路径
                    pass
                if snapshot_for_next is not None:
                    last_snapshot_text = snapshot_for_next.text
                    last_clipped = snapshot_for_next

            # Phase 15.7: 三种 early-stop 信号检测 -- 全部在 tool round 结束后判,
            # 命中即填 ``loop_break_reason`` + ``loop_guard_meta`` 并跳出主 for 循环.
            # 主循环外的 _auto_finalize_snapshot 仍会跑, _meta_loop_guard 节点也会
            # 在 return 前追加, AssertionJudge 拿到的快照仍是"操作后"的版本.

            # 信号 a: 同名工具同参数连续重复 >= dup_threshold 次.
            if (
                loop_guard_enabled_dup
                and len(tool_signature_history) >= loop_guard_dup_threshold
            ):
                tail = tool_signature_history[-loop_guard_dup_threshold:]
                if len(set(tail)) == 1:
                    loop_break_reason = "repeated_tool_signature"
                    loop_guard_meta = {
                        "break_reason": loop_break_reason,
                        "signature_history": list(tool_signature_history[-10:]),
                        "snapshot_diff_pct": (
                            list(snapshot_diff_history[-loop_guard_diff_rounds:])
                            if snapshot_diff_history else []
                        ),
                        "tokens_used_in_step": int(
                            self.budget.consumed - step_token_baseline
                        ),
                        "step_soft_budget": step_soft_budget,
                    }
                    break

            # 信号 b: 连续 N 轮快照 diff% <= loop_guard_diff_pct.
            # 只在本轮真有 tool_call 且产生过 snapshot 时才算 diff (otherwise
            # 0 toolcall 已经被前面 drift / break 处理了).
            diff_pct_this_round = _snapshot_diff_pct(
                snapshot_before_round, last_snapshot_text
            )
            snapshot_diff_history.append(diff_pct_this_round)
            if (
                loop_guard_enabled_diff
                and len(snapshot_diff_history) >= loop_guard_diff_rounds
                and all(
                    pct <= loop_guard_diff_pct
                    for pct in snapshot_diff_history[-loop_guard_diff_rounds:]
                )
            ):
                loop_break_reason = "snapshot_unchanged"
                loop_guard_meta = {
                    "break_reason": loop_break_reason,
                    "signature_history": list(tool_signature_history[-10:]),
                    "snapshot_diff_pct": list(
                        snapshot_diff_history[-loop_guard_diff_rounds:]
                    ),
                    "tokens_used_in_step": int(
                        self.budget.consumed - step_token_baseline
                    ),
                    "step_soft_budget": step_soft_budget,
                }
                break

            # 信号 c: 单步 token 软上限 (区别于全局 budget, 不影响其它步骤).
            consumed_in_step = int(self.budget.consumed - step_token_baseline)
            if (
                loop_guard_enabled_token
                and step_soft_budget > 0
                and consumed_in_step >= step_soft_budget
            ):
                loop_break_reason = "step_token_soft_budget_exceeded"
                loop_guard_meta = {
                    "break_reason": loop_break_reason,
                    "signature_history": list(tool_signature_history[-10:]),
                    "snapshot_diff_pct": (
                        list(snapshot_diff_history[-loop_guard_diff_rounds:])
                        if snapshot_diff_history else []
                    ),
                    "tokens_used_in_step": consumed_in_step,
                    "step_soft_budget": step_soft_budget,
                }
                break

        # 退出循环：is_last 已强制 tool_choice="none"，正常拿到最终回答；
        # 标记 success=True，是否真"通过"由 AssertionJudge 二次判定。
        # 在 return 前 auto-finalize 一次 a11y 快照——保证 AssertionJudge 看到
        # 的是"操作之后"的页面，而不是"操作之前"。详见 _auto_finalize_snapshot
        # docstring（修复 #f6513ebb 案例：browser_type 后没 snapshot 导致断言
        # 总是说"快照里看不到刚输入的值"）。
        last_snapshot_text, last_clipped = await self._auto_finalize_snapshot(
            execution_id=execution_id,
            tool_calls=tool_calls,
            last_snapshot_text=last_snapshot_text,
            last_clipped=last_clipped,
        )

        # Phase 15.7: 早停信号触发时, 在 tool_calls 末尾追加一个合成节点,
        # 让前端时间线 / SQL 审计都能直接看到 break_reason + 信号统计.
        # 注意要在 auto-finalize 之后追加, 保证 _meta_loop_guard 永远是最后一项.
        if loop_guard_meta is not None:
            tool_calls.append(
                ToolCallRecord(
                    name="_meta_loop_guard",
                    raw_name="_meta_loop_guard",
                    arguments={},
                    result=loop_guard_meta,
                    duration_ms=0,
                    blocked=False,
                    error=None,
                ),
            )

        return StepRunResult(
            success=True,
            iterations=iterations,
            tokens_used=self.budget.consumed,
            reasoning=full_reasoning,
            final_message=full_content.strip(),
            tool_calls=tool_calls,
            last_snapshot_text=last_snapshot_text,
            last_clipped=last_clipped,
            error=None,
            error_kind=None,
            loop_break_reason=loop_break_reason,
        )

    # ── internal ─────────────────────────────────────────────────

    async def _auto_finalize_snapshot(
        self,
        *,
        execution_id: str | None,
        tool_calls: list[ToolCallRecord],
        last_snapshot_text: str | None,
        last_clipped: ClippedSnapshot | None,
    ) -> tuple[str | None, ClippedSnapshot | None]:
        """循环退出前的 a11y 快照兜底刷新。

        触发条件（同时满足）：
        1. ``execution_id`` 已知（能拼 ``<exec_id>__browser_snapshot`` namespaced 名）
        2. 至少有过一次 tool_call（说明是真用了 MCP，不是空 step）
        3. 最后一次 tool_call 的 raw_name 是 mutating 类（见 ``_is_mutating_tool``）

        为什么必须做：playwright-mcp 0.x 在 ``browser_navigate / type / click / fill``
        这类副作用工具的 result 里**不**内联 a11y 树（只给文件链接），导致
        ``last_snapshot_text`` 一直停留在最后一次 ``browser_snapshot`` 的状态——
        如果 AI 在 type/click 之后没自觉再调 snapshot，断言阶段拿到的就是操作**前**
        的快照，文本搜索 / LLM 兜底都看不到刚刚输入 / 点击的产物，假阳性失败。

        失败容忍：tool_runner 抛错 / mcp_unavailable / 工具未注册 → INFO log，
        返回原 ``last_snapshot_text`` 不抛错，让步骤继续按原状态走断言。
        """
        if not execution_id:
            return last_snapshot_text, last_clipped
        if not tool_calls:
            return last_snapshot_text, last_clipped
        if tool_calls[-1].blocked:
            return last_snapshot_text, last_clipped
        if not _is_mutating_tool(tool_calls[-1].raw_name):
            return last_snapshot_text, last_clipped

        ns_tool = f"{execution_id}__browser_snapshot"
        started = time.monotonic()
        try:
            raw_result = await self._tool_runner(ns_tool, "{}")
        except Exception as exc:  # noqa: BLE001
            # 不阻塞 step：兜底失败的最常见原因是 mcp_unavailable / 工具未在
            # 该 execution 注册（典型 mock 测试场景），交给 AssertionJudge 用
            # 既有 last_snapshot_text 走原流程。
            logger.info(
                "StepRunner auto-finalize browser_snapshot failed (%s); "
                "assertion will use the previous snapshot",
                f"{type(exc).__name__}: {exc}",
            )
            return last_snapshot_text, last_clipped
        duration_ms = int((time.monotonic() - started) * 1000)

        try:
            parsed = json.loads(raw_result) if raw_result else {}
            if not isinstance(parsed, dict):
                parsed = {"value": parsed}
        except json.JSONDecodeError:
            parsed = {"raw": raw_result}

        snap_text = _extract_snapshot_text(parsed)
        if not snap_text:
            # MCP 返回了但里面没 a11y 文本（罕见）：保持原状态
            return last_snapshot_text, last_clipped

        clipped = clip_for_llm(
            snap_text,
            prev_snapshot=last_snapshot_text,
            max_chars=MAX_SNAPSHOT_CHARS,
            focus_hint=None,
        )
        self.ref_cache.update(clipped.text)

        # 把 auto-finalize 这次调用也记录进 tool_calls，方便前端审计 / 回放时
        # 看清"哦，最后一次 snapshot 是平台兜底刷的，不是模型主动调的"。
        tool_calls.append(
            ToolCallRecord(
                name=ns_tool,
                raw_name="browser_snapshot",
                arguments={"_auto_finalize": True},
                result=parsed,
                duration_ms=duration_ms,
                blocked=False,
                error=None,
                snapshot_after_text=clipped.text,
                snapshot_after_chars=clipped.clipped_chars,
            ),
        )
        return clipped.text, clipped

    def _resolve_execution_id(self, bundle: _BundleLike | None) -> str | None:
        if self.execution_id:
            return self.execution_id
        if bundle is not None and getattr(bundle, "execution_id", None) is not None:
            return str(bundle.execution_id)
        return None

    def _tool_spec_allowed_for_model(
        self,
        spec: dict[str, Any],
        *,
        allowed_raw_tools: frozenset[str] | None = None,
    ) -> bool:
        """过滤掉模型不应看见的 MCP tool schema。

        SecurityGuard 仍是执行前的最终防线；这里是在 LLM 调用前收窄 tools 列表，
        避免模型先看到危险/禁用工具再触发安全拦截。
        """
        fn = spec.get("function") if isinstance(spec, dict) else None
        name = fn.get("name") if isinstance(fn, dict) else None
        if not isinstance(name, str) or not name.strip():
            return False
        raw_name = _strip_namespace(name)
        if allowed_raw_tools is not None and raw_name not in allowed_raw_tools:
            return False
        return raw_name.startswith("platform_") or raw_name in self._guard.allowed_tools

    def _build_tools(
        self,
        execution_id: str | None,
        mcp_specs: list[dict[str, Any]] | None,
        data_resolver: TestDataResolver | None,
        allowed_raw_tools: frozenset[str] | None = None,
    ) -> list[dict[str, Any]] | None:
        merged: list[dict[str, Any]] = []
        merged.extend(
            spec
            for spec in (mcp_specs or [])
            if self._tool_spec_allowed_for_model(
                spec,
                allowed_raw_tools=allowed_raw_tools,
            )
        )
        if data_resolver is not None and allowed_raw_tools is None:
            ns = execution_id or "default"
            merged.extend(platform_tools_openai_schemas(execution_id=ns))
        return merged or None

    async def _invoke_tool(
        self,
        emit: ToolCallEmit,
        *,
        prev_snapshot: str | None,
        allowed_raw_tools: Iterable[str] | None = None,
    ) -> tuple[ToolCallRecord, ClippedSnapshot | None]:
        args = _parse_args(emit.arguments_json)
        raw_name = _strip_namespace(emit.name)
        if allowed_raw_tools is not None and raw_name not in set(allowed_raw_tools):
            err = (
                f"fallback policy blocked tool {raw_name}; only read-only observation "
                "tools are allowed during AI fallback"
            )
            return (
                ToolCallRecord(
                    name=emit.name,
                    raw_name=raw_name,
                    arguments=args,
                    result={
                        "error": err,
                        "error_kind": "fallback_policy",
                        "blocked_by_security": True,
                    },
                    duration_ms=0,
                    blocked=True,
                    error=err,
                ),
                None,
            )

        # 1) SecurityGuard：白名单 / 域名 / 预算
        try:
            self._guard.check(emit.name, args)
        except (SecurityError, BudgetExceededError) as exc:
            error_kind = (
                "budget_exceeded" if isinstance(exc, BudgetExceededError) else "security"
            )
            err_payload = {
                "error": str(exc),
                "error_kind": error_kind,
                "blocked_by_security": True,
            }
            return (
                ToolCallRecord(
                    name=emit.name,
                    raw_name=raw_name,
                    arguments=args,
                    result=err_payload,
                    duration_ms=0,
                    blocked=True,
                    error=str(exc),
                ),
                None,
            )

        started = time.monotonic()
        try:
            raw_result = await self._tool_runner(emit.name, emit.arguments_json or "{}")
        except Exception as exc:  # noqa: BLE001
            logger.exception("StepRunner tool execution failed: %s", emit.name)
            return (
                ToolCallRecord(
                    name=emit.name,
                    raw_name=raw_name,
                    arguments=args,
                    result={"error": f"{type(exc).__name__}: {exc}"},
                    duration_ms=int((time.monotonic() - started) * 1000),
                    blocked=False,
                    error=str(exc),
                ),
                None,
            )
        duration_ms = int((time.monotonic() - started) * 1000)

        try:
            parsed_result = json.loads(raw_result) if raw_result else {}
            if not isinstance(parsed_result, dict):
                parsed_result = {"value": parsed_result}
        except json.JSONDecodeError:
            parsed_result = {"raw": raw_result}

        # secret 工具：result 不会进 reasoning，由 redact 在写入 messages 时再处理
        if _is_secret_tool_result(parsed_result):
            logger.debug(
                "StepRunner secret tool used: %s (plaintext omitted from reasoning)",
                emit.name,
            )

        snap_text = _extract_snapshot_text(parsed_result)
        clipped: ClippedSnapshot | None = None
        if snap_text:
            clipped = clip_for_llm(
                snap_text,
                prev_snapshot=prev_snapshot,
                max_chars=MAX_SNAPSHOT_CHARS,
                focus_hint=None,
            )
            self.ref_cache.update(clipped.text)

        return (
            ToolCallRecord(
                name=emit.name,
                raw_name=raw_name,
                arguments=args,
                result=parsed_result,
                duration_ms=duration_ms,
                blocked=False,
                error=None,
                snapshot_after_text=clipped.text if clipped else None,
                snapshot_after_chars=clipped.clipped_chars if clipped else 0,
            ),
            clipped,
        )


# ─── Phase 15.4b: AI fallback 自愈决策 ────────────────────────────────


@dataclass
class SelfHealDecision:
    """LLM 单轮 strict JSON 输出.

    decision (与 docs §15.4b 一致):
      - retry_with_locator       -> 用 candidate_locators 跑一次 deterministic 二次验证
      - wait_and_retry           -> sleep `UI_AI_FALLBACK_WAIT_MS` 后再跑一次 deterministic
      - confirm_external_blocked -> 标 verdict.method=triage_external, 不再跑断言
      - mark_unsupported         -> 直接落 deterministic 原 verdict (失败兜底)

    解析失败 / decision 不在白名单 / retry 但无 candidate -> mark_unsupported.
    """

    decision: str
    candidate_locators: list[dict[str, Any]] = field(default_factory=list)
    rationale: str = ""
    raw_response: str = ""
    parse_error: str | None = None

    @property
    def is_retry_with_locator(self) -> bool:
        return self.decision == "retry_with_locator" and bool(self.candidate_locators)


_SELF_HEAL_DECISIONS = frozenset({
    "retry_with_locator",
    "wait_and_retry",
    "confirm_external_blocked",
    "mark_unsupported",
})

_SELF_HEAL_LOCATOR_STRATEGIES = frozenset({"role", "text", "css", "xpath"})

_SELF_HEAL_SYSTEM_PROMPT = (
    "你是 UI 自动化测试平台的 self-heal 决策器. 一个 deterministic 浏览器执行器"
    "已经按结构化 locator 跑过这一步并失败了, 现在让你**只做一次决策**, 不允许"
    "调用任何工具, 也不允许返回 markdown 文本.\n"
    "\n"
    "你必须输出**且仅输出**一个 JSON 对象, 字段如下:\n"
    "{\n"
    '  "decision": "retry_with_locator" | "wait_and_retry" | '
    '"confirm_external_blocked" | "mark_unsupported",\n'
    '  "candidate_locators": [{"strategy": "role|text|css|xpath", '
    '"value": "...", "rationale": "..."}],\n'
    '  "rationale": "为什么这样判断 (依据用例步骤 + deterministic evidence)"\n'
    "}\n"
    "\n"
    "决策规则:\n"
    "- retry_with_locator: 你看快照能确定**另一个具体元素**就是步骤要操作的目标, "
    "  给出 1~3 个候选; 每个 strategy 严格限定为 role / text / css / xpath, "
    "  不允许 evaluate / runJavaScript; role 用 'button:保存' 这种 'role:name' 格式. "
    "  Runner 会用 strict count==1 校验通过后才执行你给的候选.\n"
    "- wait_and_retry: deterministic 报的是元素未出现 / 数据未刷新, 但快照里有 "
    "  loading / 骨架屏证据, 短暂等待后再试一次更可能成功.\n"
    "- confirm_external_blocked: 页面被外部反爬 / 验证码 / 第三方弹窗劫持, 自动化无法继续.\n"
    "- mark_unsupported: 步骤本身就不该用 deterministic 跑 (例如全屏拖拽 / canvas 内绘制), "
    "  或 evidence 完全无法判断.\n"
    "\n"
    "**严禁**:\n"
    "- 输出任何 JSON 之外的文字 / 解释 / markdown 围栏;\n"
    "- 在 candidate_locators 里使用 evaluate / page.evaluate / runJavaScript;\n"
    "- value 留空字符串.\n"
)


def _build_self_heal_user_message(
    *,
    step_description: str,
    expected: str | None,
    deterministic_message: str,
    deterministic_evidence: dict[str, Any] | None,
    snapshot_text: str | None,
) -> str:
    parts: list[str] = [f"### 步骤目标\n{step_description}"]
    if expected:
        parts.append(f"### 预期结果\n{expected}")
    parts.append(f"### deterministic 失败原因\n{deterministic_message}")
    if isinstance(deterministic_evidence, dict):
        keep = {
            k: deterministic_evidence[k]
            for k in ("error_kind", "details", "message", "selector", "match_strategy")
            if k in deterministic_evidence
        }
        parts.append(
            "### deterministic evidence (摘要)\n"
            + json.dumps(keep, ensure_ascii=False, indent=2)[:4000]
        )
    if snapshot_text:
        parts.append(f"### 当前页面快照 (clipped)\n{snapshot_text[:6000]}")
    parts.append(
        "请输出 JSON 决策, 不要任何其它字符. retry_with_locator 时 candidate_locators 必填."
    )
    return "\n\n".join(parts)


def _parse_self_heal_response(raw: str) -> SelfHealDecision:
    """从 LLM 文本里抽出**第一个**完整 JSON 对象并解析.

    失败兜底: mark_unsupported + parse_error 字段, 让上游能落 fallback_reason.
    """
    text = (raw or "").strip()
    if text.startswith("```"):
        # 去 markdown fence (虽然 prompt 里禁止, 但实战不少模型还是会包)
        stripped = text.strip("`")
        if stripped.lower().startswith("json"):
            stripped = stripped[4:].lstrip()
        text = stripped.strip("`").strip()

    try:
        start = text.index("{")
        end = text.rindex("}")
        payload = json.loads(text[start : end + 1])
    except (ValueError, json.JSONDecodeError) as exc:
        return SelfHealDecision(
            decision="mark_unsupported",
            raw_response=raw,
            parse_error=f"json_parse_failed: {type(exc).__name__}",
        )

    if not isinstance(payload, dict):
        return SelfHealDecision(
            decision="mark_unsupported",
            raw_response=raw,
            parse_error="non_object_payload",
        )

    decision = str(payload.get("decision") or "").strip()
    if decision not in _SELF_HEAL_DECISIONS:
        return SelfHealDecision(
            decision="mark_unsupported",
            raw_response=raw,
            parse_error=f"unknown_decision: {decision!r}",
        )

    raw_locators = payload.get("candidate_locators") or []
    candidates: list[dict[str, Any]] = []
    if isinstance(raw_locators, list):
        for item in raw_locators[:5]:  # 多了截断, 防 prompt 注入式刷屏
            if not isinstance(item, dict):
                continue
            strategy = str(item.get("strategy") or "").strip().lower()
            value = str(item.get("value") or "").strip()
            if strategy not in _SELF_HEAL_LOCATOR_STRATEGIES or not value:
                continue
            candidates.append({
                "strategy": strategy,
                "value": value,
                "rationale": str(item.get("rationale") or "")[:200],
            })

    rationale = str(payload.get("rationale") or "")[:500]

    if decision == "retry_with_locator" and not candidates:
        # 协议上 retry 必须给候选, 没给视作 mark_unsupported.
        return SelfHealDecision(
            decision="mark_unsupported",
            rationale=rationale,
            raw_response=raw,
            parse_error="retry_without_candidate",
        )

    return SelfHealDecision(
        decision=decision,
        candidate_locators=candidates,
        rationale=rationale,
        raw_response=raw,
    )


async def decide_self_heal_action(
    *,
    llm: LLMConfigLike,
    step_description: str,
    expected: str | None,
    deterministic_message: str,
    deterministic_evidence: dict[str, Any] | None,
    snapshot_text: str | None,
    chat_round_fn: ChatRoundFn | None = None,
) -> SelfHealDecision:
    """Phase 15.4b — AI fallback 单轮 strict JSON 决策入口.

    - 强制 ``tool_choice="none"``, 不传 tools, 协议层禁止任何 tool_call.
    - LLM 调用失败 / 解析失败 / 字段非法 -> mark_unsupported 兜底, 不抛错.
    - chat_round_fn 可注入测试桩.
    """
    chat = chat_round_fn or _build_default_chat_round(llm)
    messages = [
        {"role": "system", "content": _SELF_HEAL_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": _build_self_heal_user_message(
                step_description=step_description,
                expected=expected,
                deterministic_message=deterministic_message,
                deterministic_evidence=deterministic_evidence,
                snapshot_text=snapshot_text,
            ),
        },
    ]
    try:
        round_out: ChatRound = await chat(
            messages=messages,
            tools=None,
            tool_choice="none",
        )
    except Exception as exc:  # noqa: BLE001
        # LLM 走丢 (网络 / 超时 / provider 报 400) 不能拖死整个步骤, 走兜底.
        logger.exception("decide_self_heal_action LLM 调用失败")
        return SelfHealDecision(
            decision="mark_unsupported",
            raw_response="",
            parse_error=f"llm_call_failed: {type(exc).__name__}: {exc}",
        )

    raw_text = getattr(round_out, "content", "") or ""
    return _parse_self_heal_response(raw_text)


def _build_default_chat_round(llm: LLMConfigLike) -> ChatRoundFn:
    """把 default_chat_round 的 llm 入参 partial 掉, 与 ChatRoundFn 协议一致."""

    async def fn(*, messages, tools, tool_choice):
        return await default_chat_round(
            llm=llm,
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
        )

    return fn


__all__ = [
    "MAX_STEP_TOOL_ITERATIONS",
    "MAX_STEP_TOOL_CALL_ROUNDS",
    "ChatRound",
    "ChatRoundFn",
    "LLMConfigLike",
    "SelfHealDecision",
    "StepRunResult",
    "StepRunner",
    "ToolCallEmit",
    "ToolCallRecord",
    "_ACTION_INTENT_PATTERN",
    "_looks_like_action_intent",
    "decide_self_heal_action",
    "default_chat_round",
]
