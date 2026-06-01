"""Phase 15.9 — 成功 locator 持久化与复用 (核心纯函数).

放这里而不是 plan_compiler / locator_candidates 内的原因:

- ``locator_candidates.build_locator_candidates`` 已经够长了, 接 preferred 候选
  会让该模块同时承担"造候选"和"读历史"两件事, 单测不好写.
- ``plan_compiler`` 是 sync side-effect-free 的; "查最近 N 次成功 case" 是
  IO 操作, 不该让它依赖 DB.

本模块只做三件事:

1. ``serialize_locator_signature``: 把 deterministic_runner 落到 evidence 里
   的 locator details (含 strategy + 各种 selector / role 字段) 标准化成"可
   比较 / 可序列化"的签名 dict, 且只保留 4 种白名单 strategy + 5 个白名单字
   段, 防止把整个 evidence (含 attempts / 错误信息等) 写进库.
2. ``intersect_recent_locators``: 给定最近 N 个 case 的 ``successful_locators``
   dict 列表, 按 ``step_number`` 聚合, 当且仅当全部 N 次都给出**同一签名**时
   该 step 的"信任 locator"才被信任 (plan 文档明确"最近 N 次都用同一 locator
   命中"才信任).
3. ``apply_step_outcomes``: 接收"本次执行" + "上次记忆", 输出新的
   ``successful_locators`` 字典写回 case_result. 处理: 命中 → 重置 miss=0; 未
   用记忆但命中 → 写入新签名; 用记忆但 miss → miss++; miss ≥ 阈值 → 删除该
   step 记录.

不依赖 DB / Playwright; 单测直接构造 dict 就能覆盖每条分支.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

# 与 deterministic_runner._AI_LOCATOR_ALLOWED_STRATEGIES 保持一致.
# 仅这 4 种 strategy 进入持久化白名单 -- 其它 (例如 anchor-based input xpath
# 的复合表达式, 长且容易因 DOM 微调失效) 不进记忆库, 让它们靠候选生成器实时
# 重算.
ALLOWED_STRATEGIES: frozenset[str] = frozenset({"role", "text", "css", "xpath"})

# 签名只保留这几个字段 -- 任何 attempts / 错误信息 / 中间状态都不入库.
# (key 顺序固定, 让 dict 比较 + JSON dump 都稳定.)
_SIGNATURE_KEYS: tuple[str, ...] = (
    "strategy",
    "role",
    "name",
    "selector",
    "text",
    "exact",
)


def serialize_locator_signature(details: dict[str, Any] | None) -> dict[str, Any] | None:
    """从 deterministic_runner 命中 ``details`` 抽出"可比较签名".

    入参 ``details`` 通常形如 ``{"strategy": "role", "role": "button",
    "name": "查询", "count": 1, "attempts": [...]}``; 返回值仅含 6 个白名单字
    段, 不在白名单的 strategy 整体返 None.
    """
    if not isinstance(details, dict):
        return None
    strategy = str(details.get("strategy") or "").strip()
    if strategy not in ALLOWED_STRATEGIES:
        return None
    sig: dict[str, Any] = {"strategy": strategy}
    for key in _SIGNATURE_KEYS:
        if key == "strategy":
            continue
        if key in details and details[key] is not None:
            value = details[key]
            if isinstance(value, bool):
                sig[key] = bool(value)
            elif isinstance(value, (str, int, float)):
                sig[key] = value
            else:
                # 非基本类型 (dict/list) 不进签名 -- 它们大概率是 attempts 这
                # 类辅助信息, 比较时不稳定, 也不该回放成 locator.
                continue
    return sig


def _signature_eq(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """两个签名"等价"判定 (忽略 None/空字符串差异)."""
    keys = set(a.keys()) | set(b.keys())
    for k in keys:
        if a.get(k) != b.get(k):
            return False
    return True


def intersect_recent_locators(
    history: Iterable[dict[str, Any]],
    *,
    lookback: int,
) -> dict[int, dict[str, Any]]:
    """计算"最近 N 次成功 case_result 都命中过同一 locator"的 step → 签名映射.

    入参 ``history`` 顺序: 最近的在前 (``[run_n-1, run_n-2, ...]``); 函数只取
    前 ``lookback`` 个判定. 当且仅当某 step 在前 ``lookback`` 次中**都存在**
    且**签名相同**时该 step 的 locator 才被信任.

    返回 dict 形如 ``{1: {"strategy": "role", ...}, 2: {...}, ...}``; 没有任
    何 step 满足条件时返回 ``{}``.

    与 plan 15.9 验收对齐: "最近 3 次都用同一 locator 命中"才信任. lookback=1
    时退化为"用上次的 locator", 但单测会防止这种情况 (由调用方校验
    ``lookback >= 2``, 这里宽容地接受任何 ≥1 整数, 避免崩溃).
    """
    if lookback < 1:
        return {}
    runs = [r for r in history if isinstance(r, dict)][:lookback]
    if len(runs) < lookback:
        return {}

    # 取首条作为候选基准, 其它 N-1 次必须给出"等价签名"才保留.
    head = runs[0]
    if not isinstance(head, dict):
        return {}

    trusted: dict[int, dict[str, Any]] = {}
    for raw_step_key, raw_value in head.items():
        try:
            step_number = int(raw_step_key)
        except (TypeError, ValueError):
            continue
        if not isinstance(raw_value, dict):
            continue
        head_sig = _strip_runtime_fields(raw_value)
        if not head_sig.get("strategy"):
            continue
        all_match = True
        for other in runs[1:]:
            other_record = other.get(str(step_number)) or other.get(raw_step_key)
            if not isinstance(other_record, dict):
                all_match = False
                break
            other_sig = _strip_runtime_fields(other_record)
            if not _signature_eq(head_sig, other_sig):
                all_match = False
                break
        if all_match:
            trusted[step_number] = head_sig
    return trusted


def _strip_runtime_fields(record: dict[str, Any]) -> dict[str, Any]:
    """从持久化 record 里剥掉 miss_count / last_seen_at 等运行时字段, 只留
    locator 签名本身. 用 ``serialize_locator_signature`` 做 strategy 白名单复
    校 -- 库里万一有非白名单 strategy 残留, 这里直接过滤.
    """
    return serialize_locator_signature(record) or {}


def apply_step_outcomes(
    *,
    previous: dict[str, Any] | None,
    outcomes: dict[int, "StepLocatorOutcome"],
    max_miss: int,
) -> dict[str, dict[str, Any]]:
    """根据本次 step 命中结果 + 旧记忆, 算出"该写回 ui_case_results 的 dict".

    输入:
      - ``previous``: 上次 case_result 的 ``successful_locators`` dict (本次执
        行之前, 通常等于"被注入的 trusted 字典派生而来", 也可能是空 dict).
      - ``outcomes``: ``{step_number: StepLocatorOutcome}``, 来自本次执行的
        deterministic 步骤.
      - ``max_miss``: ``UI_LOCATOR_MEMORY_MAX_MISS``, 默认 2.

    输出: 新的 ``successful_locators`` dict, 形如 ``{"1": {strategy, ...,
    miss_count, last_seen_at}, ...}``. 写回时按 plan 文档的策略:

    - 命中且新 signature: 写入 (miss_count=0).
    - 命中且使用了 preferred (复用成功): 重置 miss_count=0.
    - 用了 preferred 但失败 (miss): miss_count+=1; ≥ max_miss 就删除该 step.
    - 失败且没用 preferred: 保留旧 record 不变 (失败可能是数据问题, 不该删).
    - 跳过 / 非 deterministic / unsupported: 不动.
    """
    previous = previous or {}
    new_record: dict[str, dict[str, Any]] = {}

    # 先把所有旧 record 拷过来, 后续按 outcome 更新.
    for raw_key, value in previous.items():
        if not isinstance(value, dict):
            continue
        # 校验合法性: 非白名单 strategy / 缺 strategy 直接不带过来 (相当于清记忆).
        if not _strip_runtime_fields(value).get("strategy"):
            continue
        try:
            int(raw_key)
        except (TypeError, ValueError):
            continue
        new_record[str(raw_key)] = dict(value)

    for step_number, outcome in outcomes.items():
        key = str(step_number)
        if outcome.skipped:
            continue

        if outcome.passed:
            new_sig = serialize_locator_signature(outcome.matched_locator)
            if new_sig:
                new_record[key] = {
                    **new_sig,
                    "miss_count": 0,
                    "last_seen_at": outcome.timestamp_iso,
                }
            elif outcome.used_preferred:
                # passed=True 但没拿到 signature 是异常路径; 至少把 miss
                # 重置, 让旧记忆延长一轮.
                if key in new_record:
                    new_record[key]["miss_count"] = 0
                    new_record[key]["last_seen_at"] = outcome.timestamp_iso
            continue

        # 失败分支
        if outcome.used_preferred:
            current = new_record.get(key)
            if current is None:
                continue
            miss_count = int(current.get("miss_count") or 0) + 1
            if miss_count >= max_miss:
                # 连续 max_miss 次失败 -> 直接清掉该 step 的记忆, 让下一次
                # 重新走候选生成器从头算.
                new_record.pop(key, None)
            else:
                current["miss_count"] = miss_count
                current["last_seen_at"] = outcome.timestamp_iso
        # 未用 preferred 失败: 不动旧记忆 (失败可能跟 locator 无关).

    return new_record


class StepLocatorOutcome:
    """``execution_engine`` 喂给 ``apply_step_outcomes`` 的 step 级输入.

    用普通 class 而不是 dataclass, 是为了让本模块 import 链最浅, 不引入
    ``from dataclasses import dataclass`` 给 backend 启动多走一次解析.
    """

    __slots__ = (
        "passed",
        "used_preferred",
        "matched_locator",
        "skipped",
        "timestamp_iso",
    )

    def __init__(
        self,
        *,
        passed: bool,
        used_preferred: bool,
        matched_locator: dict[str, Any] | None,
        skipped: bool = False,
        timestamp_iso: str = "",
    ) -> None:
        self.passed = bool(passed)
        self.used_preferred = bool(used_preferred)
        self.matched_locator = matched_locator
        self.skipped = bool(skipped)
        self.timestamp_iso = timestamp_iso or ""


__all__ = (
    "ALLOWED_STRATEGIES",
    "serialize_locator_signature",
    "intersect_recent_locators",
    "apply_step_outcomes",
    "StepLocatorOutcome",
)
