"""Phase 15.8 — dashboard 高频失败用例 (unstable cases) 纯函数单测.

聚焦 ``aggregate_unstable_cases`` 的判定与排序口径:
- 状态归类: passed / failed / error / skipped
- skipped 不计入分母
- failure_rate 按 lookback 切片后计算
- 按 failure_rate desc + last_failure_at desc 排序
- 已删除 testcase 显示 "(已删除)"
- 4 失败 1 通过 (rate=0.8) 应进入卡片; 3 失败 2 通过 (rate=0.6) 不进入

DB 查询路径留给集成测试; 这里走 in-memory rows 模拟 SQL 输出.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from app.modules.dashboard.ui_stats import aggregate_unstable_cases


def _ts(offset_seconds: int = 0) -> datetime:
    return datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc) + timedelta(
        seconds=offset_seconds,
    )


def test_aggregate_4_failures_1_pass_appears_in_card() -> None:
    """文档验收口径: 4 失败 1 通过 (failure_rate=0.8 >= 0.7) 应展示."""
    case_a = uuid.uuid4()
    rows = [
        # case_a: 5 次执行, 4 failed + 1 passed; 时间倒序
        (case_a, "failed", "captcha", _ts(-100)),
        (case_a, "failed", "captcha", _ts(-200)),
        (case_a, "failed", "captcha", _ts(-300)),
        (case_a, "passed", None, _ts(-400)),
        (case_a, "failed", "captcha", _ts(-500)),
    ]
    out = aggregate_unstable_cases(
        rows,
        lookback=5,
        failure_ratio=0.7,
        titles={case_a: "百度搜索-验证天气"},
    )
    assert len(out) == 1
    assert out[0]["testcase_id"] == str(case_a)
    assert out[0]["testcase_title"] == "百度搜索-验证天气"
    assert out[0]["total_runs"] == 5
    assert out[0]["failed_runs"] == 4
    assert out[0]["failure_rate"] == 0.8
    assert len(out[0]["recent_runs"]) == 3
    # 第一项是最近一次, status="failed"
    assert out[0]["recent_runs"][0]["status"] == "failed"


def test_aggregate_3_failures_2_passes_not_shown() -> None:
    """3 失败 2 通过 = 0.6 < 0.7 阈值, 不算 unstable."""
    case_b = uuid.uuid4()
    rows = [
        (case_b, "failed", None, _ts(-100)),
        (case_b, "failed", None, _ts(-200)),
        (case_b, "passed", None, _ts(-300)),
        (case_b, "passed", None, _ts(-400)),
        (case_b, "failed", None, _ts(-500)),
    ]
    out = aggregate_unstable_cases(rows, lookback=5, failure_ratio=0.7)
    assert out == []


def test_aggregate_skipped_excluded_from_denominator() -> None:
    """skipped 不算成功也不算失败. 2 skipped + 2 failed -> failure_rate=1.0 应展示."""
    case_c = uuid.uuid4()
    rows = [
        (case_c, "failed", "x", _ts(-100)),
        (case_c, "skipped", None, _ts(-200)),
        (case_c, "failed", "x", _ts(-300)),
        (case_c, "skipped", None, _ts(-400)),
    ]
    out = aggregate_unstable_cases(
        rows,
        lookback=5,
        failure_ratio=0.7,
        titles={case_c: "C"},
    )
    assert len(out) == 1
    assert out[0]["total_runs"] == 2  # skipped 排除
    assert out[0]["failed_runs"] == 2
    assert out[0]["failure_rate"] == 1.0


def test_aggregate_lookback_truncates_history() -> None:
    """lookback=3 时只看最近 3 次. 历史更早的失败应当被忽略."""
    case_d = uuid.uuid4()
    rows = [
        # 最近 3 次: 1 failed + 2 passed -> rate 0.33, 不算 unstable
        (case_d, "failed", None, _ts(-100)),
        (case_d, "passed", None, _ts(-200)),
        (case_d, "passed", None, _ts(-300)),
        # 更早的历史失败应当不影响最近 3 次的判定
        (case_d, "failed", None, _ts(-400)),
        (case_d, "failed", None, _ts(-500)),
    ]
    out = aggregate_unstable_cases(rows, lookback=3, failure_ratio=0.7)
    assert out == []


def test_aggregate_error_counted_as_failed() -> None:
    """``error`` 跟 ``failed`` 都算失败 (engine 把 budget / crash 标 error)."""
    case_e = uuid.uuid4()
    rows = [
        (case_e, "error", "BudgetExceededError", _ts(-100)),
        (case_e, "failed", "captcha", _ts(-200)),
        (case_e, "passed", None, _ts(-300)),
    ]
    out = aggregate_unstable_cases(rows, lookback=3, failure_ratio=0.6)
    assert len(out) == 1
    assert out[0]["failed_runs"] == 2
    assert out[0]["failure_rate"] == round(2 / 3, 4)


def test_aggregate_sort_failure_rate_then_last_failure_time() -> None:
    """排序: failure_rate desc -> last_failure_at desc -> 稳定."""
    case_high = uuid.uuid4()
    case_mid = uuid.uuid4()
    case_low_late = uuid.uuid4()
    rows = [
        # case_high: 5/5 failed
        (case_high, "failed", None, _ts(-1000)),
        (case_high, "failed", None, _ts(-1100)),
        (case_high, "failed", None, _ts(-1200)),
        (case_high, "failed", None, _ts(-1300)),
        (case_high, "failed", None, _ts(-1400)),
        # case_low_late: 4/5 failed (失败率较低), 但最近失败时间最新
        (case_low_late, "failed", None, _ts(-50)),
        (case_low_late, "failed", None, _ts(-150)),
        (case_low_late, "passed", None, _ts(-250)),
        (case_low_late, "failed", None, _ts(-350)),
        (case_low_late, "failed", None, _ts(-450)),
        # case_mid: 4/5 failed, 失败时间在 case_low_late 之前
        (case_mid, "failed", None, _ts(-2000)),
        (case_mid, "failed", None, _ts(-2100)),
        (case_mid, "passed", None, _ts(-2200)),
        (case_mid, "failed", None, _ts(-2300)),
        (case_mid, "failed", None, _ts(-2400)),
    ]
    out = aggregate_unstable_cases(
        rows,
        lookback=5,
        failure_ratio=0.7,
        titles={case_high: "H", case_mid: "M", case_low_late: "L"},
    )
    assert [c["testcase_title"] for c in out] == ["H", "L", "M"]
    # H 失败率 1.0 排第一; L 与 M 都 0.8, L 最近失败时间更新所以 L 在前


def test_aggregate_missing_title_marked_deleted() -> None:
    case = uuid.uuid4()
    rows = [
        (case, "failed", None, _ts(-100)),
        (case, "failed", None, _ts(-200)),
    ]
    out = aggregate_unstable_cases(rows, lookback=5, failure_ratio=0.7, titles={})
    assert len(out) == 1
    assert out[0]["testcase_title"] == "(已删除)"


def test_aggregate_recent_runs_capped_at_three() -> None:
    """recent_runs 字段始终 <= 3 项, 防把整个历史塞进 dashboard payload."""
    case = uuid.uuid4()
    rows = [
        (case, "failed", "x", _ts(-100)),
        (case, "failed", "x", _ts(-200)),
        (case, "failed", "x", _ts(-300)),
        (case, "failed", "x", _ts(-400)),
        (case, "failed", "x", _ts(-500)),
    ]
    out = aggregate_unstable_cases(rows, lookback=5, failure_ratio=0.7)
    assert len(out[0]["recent_runs"]) == 3


def test_aggregate_only_skipped_runs_excluded() -> None:
    """全是 skipped 的 case 因为分母为 0, 不进入候选."""
    case = uuid.uuid4()
    rows = [
        (case, "skipped", None, _ts(-100)),
        (case, "skipped", None, _ts(-200)),
    ]
    out = aggregate_unstable_cases(rows, lookback=5, failure_ratio=0.7)
    assert out == []
