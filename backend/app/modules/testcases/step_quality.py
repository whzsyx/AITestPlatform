"""Phase 15.5 - 用例步骤质量校验器。

设计目标：在 ``create_testcase`` / ``update_testcase`` 入口扫一遍 step 文本，给
出**非阻断**警告，让用例作者尽早发现"占位符没替换 / 探索性词汇 / 公共反爬
host"等历史上反复污染执行结果的写法。

返回的 ``StepWarning`` 列表会原样挂到 router 响应里；前端 ``TestcaseDetail.vue``
保存成功后弹一段折叠提示。**永不抛异常**：质量校验是辅助手段，业务路径不应被
它打断。

历史依据（来自 docs/SMART_UI_AUTOMATION_RELIABILITY_FIX_PLAN.md §15.5）：

- 458 条 testcase_steps 里 15 条仍含 ``{{}}``，12 条含"若有/尝试"等探索性词。
- 占位符泄漏到执行链路引发 5+ 条数据噪音类失败步骤。
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Literal

from pydantic import BaseModel, Field

WarningKind = Literal[
    "unresolved_placeholder",
    "exploratory_phrasing",
    "step_too_long",
    "external_anti_bot_host",
    "empty_action",
]


class StepWarning(BaseModel):
    """一条用例步骤上的质量提示。"""

    step_number: int = Field(..., ge=0)
    kind: WarningKind
    message: str
    """面向用户的中文一句话提示。"""


# ─── 检测规则 ─────────────────────────────────────────────────────────


_PLACEHOLDER_RE = re.compile(r"\{\{\s*([\w.-]+)\s*\}\}")

# 与 execution_engine._FALLBACK_HEDGING_PATTERN 同步；同时包括 "如果存在"
# 这种搭配。15.4a 已经在 fallback 一侧拒绝, 这里只做"提示用例作者"的轻量校验.
_HEDGING_RE = re.compile(
    r"(若有|如有|如果(?:存在|有)?|尝试|试试|可能|或许|也许|视情况|看情况|建议|或者|可以)"
)

# 公共反爬 host 黑名单 -- 历史失败案例里出现过让 AI 跑通用搜索引擎 / cloudflare
# 验证页, 显然不是自动化测试该做的事; 用例里写到这些直接报警, 让作者把目标
# 改成受控环境.
_ANTI_BOT_HOSTS = (
    "baidu.com",
    "google.com",
    "google.cn",
    "bing.com",
    "cloudflare.com",
    "captcha-delivery.com",
    "wappass.baidu.com",
    "recaptcha.net",
)

# 步骤长度阈值: 超过 80 字 + 含两个及以上 "输入 / ;" 视为 "复合步骤", 建议拆分.
_LONG_STEP_LEN = 80
_COMPOSITE_INDICATOR_RE = re.compile(r"输入|；|;")


class _StepLike:
    """duck-typing 兼容: TestcaseStep ORM / StepRequest pydantic 都能用."""

    step_number: int
    action: str | None
    expected_result: str | None


def validate_step_quality(
    steps: Iterable[_StepLike] | Iterable[dict],
) -> list[StepWarning]:
    """扫描一组 step, 返回质量提示列表 (永不抛异常).

    支持两种输入:
    - ORM ``TestcaseStep`` / pydantic ``StepRequest`` 等 attribute 访问对象;
    - dict (``{"step_number": ..., "action": ..., "expected_result": ...}``).

    设计原则:
    - 每条 step 至多产出一种 warning 的多个实例 (同 kind 多次命中合并为一条).
    - 输出按 ``step_number`` 升序; 同 step_number 内按 kind 字典序保持稳定.
    - 不修改入参, 不查 DB, 不调 LLM.
    """
    warnings: list[StepWarning] = []
    for raw in steps:
        step_number, action, expected = _extract(raw)
        action_text = (action or "").strip()
        expected_text = (expected or "").strip()

        if not action_text:
            warnings.append(
                StepWarning(
                    step_number=step_number,
                    kind="empty_action",
                    message=f"步骤 {step_number}: 动作描述为空，建议补充明确动作 (点击 / 输入 / 验证 ...)。",
                ),
            )
            continue

        full_text = (action_text + " " + expected_text).strip()

        # 1) 未解析占位符 -- 含 {{xxx}} 视为未渲染, 给出缺失 key 列表
        placeholder_keys = sorted(set(_PLACEHOLDER_RE.findall(full_text)))
        if placeholder_keys:
            warnings.append(
                StepWarning(
                    step_number=step_number,
                    kind="unresolved_placeholder",
                    message=(
                        f"步骤 {step_number}: 含未解析占位符 "
                        f"{{{{ {', '.join(placeholder_keys)} }}}}，"
                        "执行时若启用严格物料模式将被拦截。"
                    ),
                ),
            )

        # 2) 探索性词汇 -- 让用例作者把 \"试试 / 若有\" 改成明确动作
        if _HEDGING_RE.search(action_text):
            warnings.append(
                StepWarning(
                    step_number=step_number,
                    kind="exploratory_phrasing",
                    message=(
                        f"步骤 {step_number}: 含探索性词汇（若有 / 尝试 / 可能 / 如果...），"
                        "建议改为明确动作；当前 AI fallback 默认不再兜探索性步骤。"
                    ),
                ),
            )

        # 3) 步骤过长 + 含多动作信号 -- 提醒拆步骤
        if len(action_text) > _LONG_STEP_LEN:
            indicator_count = len(_COMPOSITE_INDICATOR_RE.findall(action_text))
            if indicator_count >= 2:
                warnings.append(
                    StepWarning(
                        step_number=step_number,
                        kind="step_too_long",
                        message=(
                            f"步骤 {step_number}: 文本超 {_LONG_STEP_LEN} 字且含 {indicator_count} 处"
                            "输入/分号，建议拆为多个步骤以提高 deterministic 命中率。"
                        ),
                    ),
                )

        # 4) 公共反爬 host -- 让作者切到受控环境
        lowered = full_text.lower()
        hits = [host for host in _ANTI_BOT_HOSTS if host in lowered]
        if hits:
            warnings.append(
                StepWarning(
                    step_number=step_number,
                    kind="external_anti_bot_host",
                    message=(
                        f"步骤 {step_number}: 含公共反爬 host ({', '.join(hits)})，"
                        "测试自动化应在受控环境上跑，建议改为内部测试地址。"
                    ),
                ),
            )

    warnings.sort(key=lambda w: (w.step_number, w.kind))
    return warnings


def _extract(raw: object) -> tuple[int, str | None, str | None]:
    """统一从 ORM / pydantic / dict 中取 (step_number, action, expected)."""
    if isinstance(raw, dict):
        return (
            int(raw.get("step_number") or 0),
            raw.get("action"),
            raw.get("expected_result"),
        )
    return (
        int(getattr(raw, "step_number", 0) or 0),
        getattr(raw, "action", None),
        getattr(raw, "expected_result", None),
    )


__all__ = ["StepWarning", "validate_step_quality"]
