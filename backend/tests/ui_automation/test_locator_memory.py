"""Phase 15.9 — locator_memory 纯函数单测.

只覆盖 ``serialize_locator_signature`` / ``intersect_recent_locators`` /
``apply_step_outcomes`` 三个纯函数; engine / DB 端的集成会由 test_engine /
test_persistence 顺路守住, 本文件不接 DB.
"""

from __future__ import annotations

import pytest

from app.modules.ui_automation.locator_memory import (
    StepLocatorOutcome,
    apply_step_outcomes,
    intersect_recent_locators,
    serialize_locator_signature,
)

# ─── serialize_locator_signature ────────────────────────────────────


def test_serialize_signature_keeps_whitelisted_strategy_fields():
    sig = serialize_locator_signature({
        "strategy": "role",
        "role": "button",
        "name": "查询",
        # 这两个字段不在白名单, 必须被剥掉.
        "count": 1,
        "attempts": [{"strategy": "role"}],
    })
    assert sig == {"strategy": "role", "role": "button", "name": "查询"}


def test_serialize_signature_rejects_non_whitelisted_strategy():
    # anchor / evaluate / 等其它 strategy 不进白名单 -- 完整返 None, 调用
    # 方应该把这种命中视为"不参与记忆".
    assert serialize_locator_signature({"strategy": "anchor", "selector": "x"}) is None
    assert serialize_locator_signature({"strategy": "evaluate"}) is None


def test_serialize_signature_handles_invalid_input():
    assert serialize_locator_signature(None) is None
    assert serialize_locator_signature({}) is None
    assert serialize_locator_signature({"strategy": ""}) is None


def test_serialize_signature_drops_complex_value_types():
    sig = serialize_locator_signature({
        "strategy": "css",
        "selector": "button.x",
        "exact": True,
        "name": {"unexpected": "dict"},  # 复杂类型不入签名
    })
    assert sig == {"strategy": "css", "selector": "button.x", "exact": True}


# ─── intersect_recent_locators ──────────────────────────────────────


def _record(strategy: str, **fields) -> dict[str, object]:
    """构造一条 step 记录 (含 miss_count / last_seen_at, 模拟库里读出来形态)."""
    return {
        "strategy": strategy,
        "miss_count": 0,
        "last_seen_at": "2026-05-29T17:00:00Z",
        **fields,
    }


def test_intersect_three_runs_all_match_returns_signature():
    history = [
        {"1": _record("role", role="button", name="查询")},
        {"1": _record("role", role="button", name="查询")},
        {"1": _record("role", role="button", name="查询")},
    ]
    out = intersect_recent_locators(history, lookback=3)
    assert out == {1: {"strategy": "role", "role": "button", "name": "查询"}}


def test_intersect_signature_mismatch_excludes_step():
    history = [
        {"1": _record("role", role="button", name="查询")},
        {"1": _record("css", selector="button.q")},
        {"1": _record("role", role="button", name="查询")},
    ]
    assert intersect_recent_locators(history, lookback=3) == {}


def test_intersect_lookback_not_enough_history_returns_empty():
    # 只有 2 次成功记录, lookback=3 时不应该信任任何 step.
    history = [
        {"1": _record("role", role="button", name="查询")},
        {"1": _record("role", role="button", name="查询")},
    ]
    assert intersect_recent_locators(history, lookback=3) == {}


def test_intersect_handles_missing_step_in_some_runs():
    history = [
        {"1": _record("role", role="button", name="查询"),
         "2": _record("css", selector="input.q")},
        {"1": _record("role", role="button", name="查询")},  # 缺 step 2
        {"1": _record("role", role="button", name="查询"),
         "2": _record("css", selector="input.q")},
    ]
    out = intersect_recent_locators(history, lookback=3)
    assert out == {1: {"strategy": "role", "role": "button", "name": "查询"}}


def test_intersect_skips_invalid_strategy_in_head():
    # head 里的 step 用了非白名单 strategy -> 直接跳过 (相当于无记忆).
    history = [
        {"1": {"strategy": "anchor", "miss_count": 0, "last_seen_at": ""}},
        {"1": {"strategy": "anchor", "miss_count": 0, "last_seen_at": ""}},
        {"1": {"strategy": "anchor", "miss_count": 0, "last_seen_at": ""}},
    ]
    assert intersect_recent_locators(history, lookback=3) == {}


def test_intersect_lookback_zero_returns_empty():
    assert intersect_recent_locators([{"1": _record("role")}], lookback=0) == {}


# ─── apply_step_outcomes ───────────────────────────────────────────


def _ok_outcome(**details) -> StepLocatorOutcome:
    return StepLocatorOutcome(
        passed=True,
        used_preferred=False,
        matched_locator={"strategy": "role", **details},
        timestamp_iso="2026-05-29T17:30:00Z",
    )


def _miss_outcome() -> StepLocatorOutcome:
    return StepLocatorOutcome(
        passed=False,
        used_preferred=True,
        matched_locator=None,
        timestamp_iso="2026-05-29T17:30:00Z",
    )


def test_apply_first_pass_writes_new_signature():
    out = apply_step_outcomes(
        previous={},
        outcomes={1: _ok_outcome(role="button", name="查询")},
        max_miss=2,
    )
    assert out["1"]["strategy"] == "role"
    assert out["1"]["role"] == "button"
    assert out["1"]["name"] == "查询"
    assert out["1"]["miss_count"] == 0
    assert out["1"]["last_seen_at"]


def test_apply_pass_resets_miss_count():
    previous = {
        "1": {
            "strategy": "role",
            "role": "button",
            "name": "查询",
            "miss_count": 1,
            "last_seen_at": "2026-05-29T16:00:00Z",
        }
    }
    out = apply_step_outcomes(
        previous=previous,
        outcomes={1: _ok_outcome(role="button", name="查询")},
        max_miss=2,
    )
    assert out["1"]["miss_count"] == 0
    assert out["1"]["last_seen_at"] != previous["1"]["last_seen_at"]


def test_apply_used_preferred_miss_increments_counter():
    previous = {
        "1": {
            "strategy": "role",
            "role": "button",
            "name": "查询",
            "miss_count": 0,
            "last_seen_at": "2026-05-29T16:00:00Z",
        }
    }
    out = apply_step_outcomes(
        previous=previous,
        outcomes={1: _miss_outcome()},
        max_miss=2,
    )
    assert out["1"]["miss_count"] == 1


def test_apply_consecutive_miss_clears_record():
    previous = {
        "1": {
            "strategy": "role",
            "role": "button",
            "name": "查询",
            "miss_count": 1,  # 已经 miss 过一次
            "last_seen_at": "2026-05-29T16:00:00Z",
        }
    }
    out = apply_step_outcomes(
        previous=previous,
        outcomes={1: _miss_outcome()},
        max_miss=2,
    )
    # 累计 2 次 miss -> 清掉
    assert "1" not in out


def test_apply_unrelated_failure_keeps_record():
    """没用 preferred 的失败 step (locator 无关原因) 不应清记忆."""
    previous = {
        "1": {
            "strategy": "role",
            "role": "button",
            "name": "查询",
            "miss_count": 0,
            "last_seen_at": "2026-05-29T16:00:00Z",
        }
    }
    failure_no_preferred = StepLocatorOutcome(
        passed=False,
        used_preferred=False,
        matched_locator=None,
        timestamp_iso="2026-05-29T17:30:00Z",
    )
    out = apply_step_outcomes(
        previous=previous,
        outcomes={1: failure_no_preferred},
        max_miss=2,
    )
    assert out["1"] == previous["1"]


def test_apply_skipped_outcome_does_not_change_record():
    previous = {
        "1": {
            "strategy": "role",
            "role": "button",
            "name": "查询",
            "miss_count": 0,
            "last_seen_at": "2026-05-29T16:00:00Z",
        }
    }
    skipped = StepLocatorOutcome(
        passed=False,
        used_preferred=False,
        matched_locator=None,
        skipped=True,
    )
    out = apply_step_outcomes(
        previous=previous,
        outcomes={1: skipped},
        max_miss=2,
    )
    assert out["1"] == previous["1"]


def test_apply_strips_invalid_previous_records():
    previous = {
        "1": {"strategy": "anchor", "miss_count": 0},  # 非白名单 strategy
        "abc": {"strategy": "role"},  # 非数字 key
        "2": {"strategy": "role", "role": "button", "name": "OK", "miss_count": 0,
              "last_seen_at": ""},
    }
    out = apply_step_outcomes(previous=previous, outcomes={}, max_miss=2)
    assert "1" not in out  # 非白名单被清
    assert "abc" not in out
    assert out["2"]["strategy"] == "role"


@pytest.mark.parametrize("strategy", ["role", "text", "css", "xpath"])
def test_apply_accepts_all_whitelisted_strategies(strategy):
    out = apply_step_outcomes(
        previous={},
        outcomes={
            1: StepLocatorOutcome(
                passed=True,
                used_preferred=False,
                matched_locator={"strategy": strategy, "selector": "x"},
                timestamp_iso="2026-05-29T17:30:00Z",
            ),
        },
        max_miss=2,
    )
    assert out["1"]["strategy"] == strategy
