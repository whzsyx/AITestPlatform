"""Deterministic UIActionPlan runner for low-risk Playwright operations."""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Callable, Mapping
from typing import Any

from pydantic import BaseModel, Field

from app.modules.ui_automation.action_plan import ActionTarget, UIActionKind, UIActionStep
from app.modules.ui_automation.assertion_rules import (
    assert_form_values,
    assert_table_columns,
    assert_table_rows,
)
from app.modules.ui_automation.evidence_collector import EvidenceCollector
from app.modules.ui_automation.locator_candidates import (
    build_locator_candidates as _build_locator_candidates,
)

_DANGEROUS_ACTION_WORDS = ("删除", "提交", "支付", "发布", "清空", "批量", "禁用")
_VAR_RE = re.compile(r"\{\{\s*([\w.-]+)\s*\}\}")
_LOCATOR_POLL_INTERVAL_SEC = 0.2
_LOCATOR_RESOLVE_TIMEOUT_CAP_MS = 3_000


class ActionEvidence(BaseModel):
    action_kind: UIActionKind
    execution_path: str = "deterministic"
    success: bool
    message: str = ""
    error_kind: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class DeterministicRunResult(BaseModel):
    success: bool
    evidence: ActionEvidence
    fallback_recommended: bool = False


class DeterministicRunner:
    """Execute supported UIActionStep objects through Playwright SDK APIs.

    This runner does not call LLMs and does not execute caller-provided JS.
    """

    def __init__(
        self,
        *,
        variables: Mapping[str, str] | None = None,
        timeout_ms: int = 10_000,
    ) -> None:
        self.variables = dict(variables or {})
        self.timeout_ms = timeout_ms
        # Phase 15.4b: AI fallback 自愈循环传入的额外 locator 候选 (来自
        # decide_self_heal_action). 仅在 run_step 内部生效, 出口被清空, 避免
        # 跨步骤泄漏. 候选格式见 ``_extra_candidates_to_make_locator``.
        self._extra_locator_candidates: list[dict[str, Any]] = []
        # Phase 15.9: 来自 ui_case_results.successful_locators 的"信任候选",
        # 形式同 extra_locator_candidates (``{strategy, value, ...}``); 区别
        # 是会被**前置**追加到 _build_locator_candidates 之前 -- 让历史命中
        # 过的 locator 第一时间被尝试, 减少候选扫描耗时. 命中后由
        # ``last_run_used_preferred_locator`` 标记, 让 engine 区分"用了记忆
        # 命中"和"用了候选生成器命中"以更新 miss_count.
        self._preferred_locator_candidates: list[dict[str, Any]] = []
        self.last_run_used_preferred_locator: bool = False

    async def run_step(
        self,
        page: Any,
        step: UIActionStep,
        *,
        extra_locator_candidates: list[dict[str, Any]] | None = None,
        preferred_locator_candidates: list[dict[str, Any]] | None = None,
    ) -> DeterministicRunResult:
        # Phase 15.4b: 把 LLM 自愈给出的 candidate_locators 临时挂到 instance 上,
        # _strict_locator 读取时会并入 _build_locator_candidates 末尾 (保持
        # 稳定 locator 优先, 仅在前面候选都未命中时才尝试). run_step 结束清空.
        self._extra_locator_candidates = list(extra_locator_candidates or [])
        # Phase 15.9: preferred 候选放最前面; 仅当 engine 启用 UI_LOCATOR_MEMORY
        # 且本 step 在最近 N 次成功 case 里命中过同一签名时才会传入, 这里不
        # 重新校验 strategy 白名单 (engine 侧已用 locator_memory 模块过滤过).
        self._preferred_locator_candidates = list(preferred_locator_candidates or [])
        self.last_run_used_preferred_locator = False
        try:
            if step.kind == UIActionKind.NAVIGATE:
                return await self._navigate(page, step)
            if step.kind == UIActionKind.CLICK:
                return await self._click(page, step)
            if step.kind == UIActionKind.FILL:
                return await self._fill(page, step)
            if step.kind == UIActionKind.PRESS_KEY:
                return await self._press_key(page, step)
            if step.kind == UIActionKind.SELECT:
                return await self._select(page, step)
            if step.kind == UIActionKind.WAIT_FOR_URL:
                return await self._wait_for_url(page, step)
            if step.kind == UIActionKind.ASSERT_TEXT:
                return await self._assert_text(page, step)
            if step.kind == UIActionKind.ASSERT_URL:
                return await self._assert_url(page, step)
            if step.kind == UIActionKind.ASSERT_PAGE_LOADED:
                return await self._assert_page_loaded(page, step)
            if step.kind == UIActionKind.ASSERT_TABLE_COLUMNS:
                return await self._assert_table_columns(page, step)
            if step.kind == UIActionKind.ASSERT_TABLE_ROWS:
                return await self._assert_table_rows(page, step)
            if step.kind == UIActionKind.ASSERT_FORM_VALUES:
                return await self._assert_form_values(page, step)
            return self._failure(
                step,
                error_kind="unsupported_action",
                message=f"deterministic runner does not support action {step.kind.value!r}",
                fallback_recommended=True,
            )
        except Exception as exc:  # noqa: BLE001
            return self._failure(
                step,
                error_kind="action_failed",
                message=str(exc),
                fallback_recommended=True,
            )
        finally:
            # 清空, 避免下一次 run_step 误用上一步的 self_heal 候选.
            self._extra_locator_candidates = []
            self._preferred_locator_candidates = []

    async def _navigate(self, page: Any, step: UIActionStep) -> DeterministicRunResult:
        url = self._resolve_value(step.target.url)
        if not url:
            return self._failure(step, error_kind="missing_target", message="navigate missing url")
        await page.goto(url, timeout=self.timeout_ms, wait_until="domcontentloaded")
        structured_evidence = await _collect_post_action_evidence(page, step)
        return self._success(
            step,
            message=f"navigated to {url}",
            details={"url": url, "structured_evidence": structured_evidence},
        )

    async def _click(self, page: Any, step: UIActionStep) -> DeterministicRunResult:
        target_text = _target_display_text(step.target)
        if _is_dangerous_target(target_text) and not _source_allows_dangerous_action(
            step.source_text,
            target_text,
        ):
            return self._failure(
                step,
                error_kind="dangerous_action_blocked",
                message=f"dangerous click target {target_text!r} is not explicit in source step",
                fallback_recommended=False,
            )
        locator_result = await self._strict_locator(page, step)
        if not locator_result.success:
            return locator_result.result
        await locator_result.locator.click(timeout=self.timeout_ms)
        structured_evidence = await _collect_post_action_evidence(page, step)
        return self._success(
            step,
            message=f"clicked {target_text or 'target'}",
            details={
                **locator_result.details,
                "structured_evidence": structured_evidence,
            },
        )

    async def _fill(self, page: Any, step: UIActionStep) -> DeterministicRunResult:
        value = self._resolve_value(step.value)
        locator_result = await self._strict_locator(page, step)
        if not locator_result.success:
            return locator_result.result
        await locator_result.locator.fill(value or "", timeout=self.timeout_ms)
        structured_evidence = await _collect_post_action_evidence(page, step)
        return self._success(
            step,
            message=f"filled {_target_display_text(step.target) or 'target'}",
            details={
                **locator_result.details,
                "value_length": len(value or ""),
                "structured_evidence": structured_evidence,
            },
        )

    async def _press_key(self, page: Any, step: UIActionStep) -> DeterministicRunResult:
        key = self._resolve_value(step.value) or ""
        key = _normalize_key(key)
        if not key:
            return self._failure(step, error_kind="missing_value", message="press_key missing key")
        keyboard = getattr(page, "keyboard", None)
        press = getattr(keyboard, "press", None)
        if not callable(press):
            return self._failure(
                step,
                error_kind="unsupported_action",
                message="page keyboard is unavailable",
                fallback_recommended=True,
            )
        await press(key)
        structured_evidence = await _collect_post_action_evidence(page, step)
        return self._success(
            step,
            message=f"pressed {key}",
            details={"key": key, "structured_evidence": structured_evidence},
        )

    async def _select(self, page: Any, step: UIActionStep) -> DeterministicRunResult:
        value = self._resolve_value(step.value)
        if not value:
            return self._failure(step, error_kind="missing_value", message="select missing value")
        locator_result = await self._strict_locator(page, step)
        if not locator_result.success:
            return locator_result.result
        await locator_result.locator.select_option(value, timeout=self.timeout_ms)
        structured_evidence = await _collect_post_action_evidence(page, step)
        return self._success(
            step,
            message=f"selected {value}",
            details={
                **locator_result.details,
                "value": value,
                "structured_evidence": structured_evidence,
            },
        )

    async def _wait_for_url(self, page: Any, step: UIActionStep) -> DeterministicRunResult:
        url = self._resolve_value(step.target.url)
        if not url:
            return self._failure(step, error_kind="missing_target", message="wait_for_url missing url")
        await page.wait_for_url(url, timeout=self.timeout_ms)
        return self._success(step, message=f"waited for url {url}", details={"url": url})

    async def _assert_text(self, page: Any, step: UIActionStep) -> DeterministicRunResult:
        text = self._resolve_value(step.target.text)
        if not text:
            return self._failure(step, error_kind="missing_target", message="assert_text missing text")

        # Phase 15.6: 三级降级匹配, evidence.details["match_strategy"] 标命中级别.
        #   level 1: get_by_text(exact=True)         -- 严格命中, 命中即过.
        #   level 2: get_by_text(exact=False)         -- 含糊命中 (contains).
        #   level 3: :text-is OR :has-text             -- 宽松命中 (loose).
        # 受 settings.UI_ASSERT_TEXT_DEGRADE_LEVEL 控制 (1/2/3, 默认 3),
        # 单测 / 严苛环境可强制只走 level 1 还原 Phase 15.5 之前的行为.
        degrade_level = _resolved_assert_text_degrade_level()

        levels: list[tuple[str, Callable[[], Any]]] = [
            ("exact", lambda: page.get_by_text(text, exact=True)),
        ]
        if degrade_level >= 2:
            levels.append(
                ("contains", lambda: page.get_by_text(text, exact=False)),
            )
        if degrade_level >= 3:
            levels.append(("loose", lambda: _build_loose_text_locator(page, text)))

        attempts: list[dict[str, Any]] = []
        for strategy_name, builder in levels:
            try:
                locator = builder()
            except Exception:  # noqa: BLE001
                attempts.append({"match_strategy": strategy_name, "ok": False})
                continue
            if locator is None:
                attempts.append({"match_strategy": strategy_name, "ok": False})
                continue
            count = await locator.count()
            # Phase 15.3 polling: 第一级没命中时给 2s 短窗口等 SPA 最后一帧;
            # 第二/三级在 polling 后还没命中说明真不在 DOM 上, 不必再 polling.
            if count <= 0 and strategy_name == "exact":
                count = await _poll_locator_count(
                    page, locator, max_ms=2000, interval_ms=500,
                )
            attempts.append(
                {"match_strategy": strategy_name, "count": int(count), "ok": count > 0},
            )
            if count > 0:
                return self._success(
                    step,
                    message=(
                        f"text {text!r} found via {strategy_name}"
                        if strategy_name != "exact"
                        else f"text {text!r} found"
                    ),
                    details={
                        "text": text,
                        "count": int(count),
                        "match_strategy": strategy_name,
                        "match_attempts": attempts,
                    },
                )

        structured_evidence = await _collect_post_action_evidence(page, step)
        attempted_levels = ", ".join(a["match_strategy"] for a in attempts)
        return self._failure(
            step,
            error_kind="assertion_failed",
            message=(
                f"text {text!r} not found (tried levels: {attempted_levels})"
            ),
            fallback_recommended=True,
            details={
                "text": text,
                "count": 0,
                "match_strategy": None,
                "match_attempts": attempts,
                "structured_evidence": structured_evidence,
            },
        )

    async def _assert_url(self, page: Any, step: UIActionStep) -> DeterministicRunResult:
        expected = self._resolve_value(step.target.url)
        if not expected:
            return self._failure(step, error_kind="missing_target", message="assert_url missing url")
        current_url = str(getattr(page, "url", "") or "")
        passed = current_url == expected or expected in current_url
        if not passed:
            return self._failure(
                step,
                error_kind="assertion_failed",
                message=f"url {current_url!r} does not match {expected!r}",
                fallback_recommended=False,
                details={"expected": expected, "actual": current_url},
            )
        return self._success(
            step,
            message=f"url matched {expected}",
            details={"expected": expected, "actual": current_url},
        )

    async def _assert_page_loaded(
        self,
        page: Any,
        step: UIActionStep,
    ) -> DeterministicRunResult:
        expected = self._resolve_value(step.target.url)
        current_url = str(getattr(page, "url", "") or "")
        if expected and current_url != expected and expected not in current_url:
            return self._failure(
                step,
                error_kind="assertion_failed",
                message=f"url {current_url!r} does not match {expected!r}",
                fallback_recommended=False,
                details={"expected": expected, "actual": current_url},
            )

        collector = EvidenceCollector()
        page_identity = await collector.collect_page_identity(page)
        table_schema = await collector.collect_table_schema(
            page,
            table_hint=step.target.table_hint,
        )
        details = {
            "expected": expected,
            "actual": current_url,
            "structured_evidence": {
                "page_identity": page_identity.model_dump(mode="json"),
                "table_schema": table_schema.model_dump(mode="json"),
            },
        }
        columns = table_schema.columns or table_schema.visible_columns
        if table_schema.ok and columns:
            preview = "、".join(columns[:8])
            suffix = "..." if len(columns) > 8 else ""
            return self._success(
                step,
                message=f"页面已加载，URL 匹配并采集到 {len(columns)} 个表格列：{preview}{suffix}",
                details=details,
            )

        if page_identity.ok and (page_identity.title or page_identity.headings):
            heading = "、".join(page_identity.headings[:3]) or page_identity.title
            return self._success(
                step,
                message=f"页面已加载，URL 匹配并采集到页面标识：{heading}",
                details=details,
            )

        return self._failure(
            step,
            error_kind="assertion_failed",
            message="URL 匹配，但未采集到可证明页面已加载的标题或表格结构证据",
            fallback_recommended=True,
            details=details,
        )

    async def _assert_table_columns(
        self,
        page: Any,
        step: UIActionStep,
    ) -> DeterministicRunResult:
        expected_columns = list(step.target.columns or [])
        if not expected_columns:
            return self._failure(
                step,
                error_kind="missing_target",
                message="assert_table_columns missing expected columns",
            )
        evidence = await EvidenceCollector().collect_table_schema(
            page,
            table_hint=step.target.table_hint,
        )
        if not evidence.ok:
            return self._failure(
                step,
                error_kind="evidence_collection_failed",
                message=evidence.error or "table schema evidence collection failed",
                fallback_recommended=True,
            )
        verdict = assert_table_columns(expected_columns=expected_columns, evidence=evidence)
        details = {
            "expected_columns": expected_columns,
            "structured_evidence": {"table_schema": evidence.model_dump(mode="json")},
        }
        if verdict.passed:
            return self._success(step, message=verdict.reason, details=details)
        return self._failure(
            step,
            error_kind="assertion_failed",
            message=verdict.reason,
            details=details,
        )

    async def _assert_table_rows(
        self,
        page: Any,
        step: UIActionStep,
    ) -> DeterministicRunResult:
        evidence = await EvidenceCollector().collect_table_rows(
            page,
            table_hint=step.target.table_hint,
        )
        if not evidence.ok:
            return self._failure(
                step,
                error_kind="evidence_collection_failed",
                message=evidence.error or "table row evidence collection failed",
                fallback_recommended=True,
            )
        verdict = assert_table_rows(
            expected=self._resolve_value(step.value) or step.source_text,
            evidence=evidence,
        )
        structured_evidence = {"table_rows": evidence.model_dump(mode="json")}
        if verdict is None:
            structured_evidence.update(await _collect_lightweight_context_evidence(page))
            return self._failure(
                step,
                error_kind="assertion_not_applicable",
                message="table row assertion rule was not applicable",
                fallback_recommended=True,
                details={"structured_evidence": structured_evidence},
            )
        if verdict.passed:
            return self._success(
                step,
                message=verdict.reason,
                details={"structured_evidence": structured_evidence},
            )
        structured_evidence.update(await _collect_lightweight_context_evidence(page))
        return self._failure(
            step,
            error_kind="assertion_failed",
            message=verdict.reason,
            fallback_recommended=True,
            details={"structured_evidence": structured_evidence},
        )

    async def _assert_form_values(
        self,
        page: Any,
        step: UIActionStep,
    ) -> DeterministicRunResult:
        evidence = await EvidenceCollector().collect_form_fields(page)
        if not evidence.ok:
            return self._failure(
                step,
                error_kind="evidence_collection_failed",
                message=evidence.error or "form field evidence collection failed",
                fallback_recommended=True,
            )
        expected_text = self._resolve_value(step.value) or step.source_text
        verdict = assert_form_values(expected=expected_text, evidence=evidence)
        details = {
            "structured_evidence": {"form_fields": evidence.model_dump(mode="json")},
        }
        if verdict is None:
            return self._failure(
                step,
                error_kind="assertion_not_applicable",
                message="form field assertion rule was not applicable",
                fallback_recommended=True,
                details=details,
            )
        if verdict.passed:
            return self._success(step, message=verdict.reason, details=details)
        return self._failure(
            step,
            error_kind="assertion_failed",
            message=verdict.reason,
            details=details,
        )

    async def _strict_locator(
        self,
        page: Any,
        step: UIActionStep,
    ) -> "_LocatorResolution":
        target = step.target
        candidates = _build_locator_candidates(page, target)
        # Phase 15.9: 信任候选放最前. 与 extra (AI 自愈) 候选区别:
        # - preferred 来自历史最近 N 次成功 case 的 locator 记忆, 信任度高;
        # - extra 是 LLM 当场猜的 locator, 信任度低, 只能兜底.
        # 用 ``source=memory`` 标记以便 _resolve_locator_once 命中时回写 flag.
        preferred_specs: list[tuple[Any, dict[str, Any]]] = []
        for memo in list(self._preferred_locator_candidates):
            spec = _extra_candidate_to_make_locator(page, memo)
            if spec is not None:
                make_locator, details = spec
                preferred_specs.append(
                    (make_locator, {**details, "source": "memory"}),
                )
        candidates = preferred_specs + candidates
        # Phase 15.4b: 在末尾追加 LLM 自愈候选, 优先级最低; 经历同一套
        # count==1 / 评分降级校验, 不会因为引入 AI locator 直接 short-circuit.
        for ai_cand in list(self._extra_locator_candidates):
            spec = _extra_candidate_to_make_locator(page, ai_cand)
            if spec is not None:
                candidates.append(spec)
        if not candidates:
            return _LocatorResolution(
                success=False,
                result=self._failure(
                    step,
                    error_kind="missing_target",
                    message="no supported locator fields present",
                    fallback_recommended=True,
                ),
            )

        resolve_timeout_ms = max(
            50,
            min(self.timeout_ms, _LOCATOR_RESOLVE_TIMEOUT_CAP_MS),
        )
        deadline = time.monotonic() + resolve_timeout_ms / 1000
        while True:
            resolution = await self._resolve_locator_once(step, candidates)
            if resolution.success:
                return resolution
            error_kind = (
                resolution.result.evidence.error_kind
                if resolution.result is not None
                else None
            )
            if error_kind == "locator_ambiguous":
                return resolution
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return resolution
            await asyncio.sleep(min(_LOCATOR_POLL_INTERVAL_SEC, remaining))

    async def _resolve_locator_once(
        self,
        step: UIActionStep,
        candidates: list[tuple[Callable[[], Any | None], dict[str, Any]]],
    ) -> "_LocatorResolution":
        target = step.target
        attempts: list[dict[str, Any]] = []
        # Phase 15.6: click 类多匹配也走评分降级 (历史只对 FILL/SELECT 启用,
        # click 直接 fail 浪费一次机会). 命中范围扩到所有 click + fill + select.
        score_eligible_kinds = {
            UIActionKind.CLICK,
            UIActionKind.FILL,
            UIActionKind.SELECT,
        }
        for make_locator, details in candidates:
            locator = make_locator()
            if locator is None:
                continue
            count = await locator.count()
            current_details = {**details, "count": count}
            attempts.append(current_details)
            if count == 1:
                # Phase 15.6: 成功路径也把 attempts 写入, 让 evidence_collector
                # / 历史详情页能展示"共扫了几条候选 / 最终命中第几条". 多 5
                # 个 dict 字段不足以拖累 SSE 体积.
                # Phase 15.9: 命中且来源是 memory -> 标记本次使用了 preferred,
                # 让 engine 在 case finalize 时把 miss_count 重置为 0.
                if details.get("source") == "memory":
                    self.last_run_used_preferred_locator = True
                return _LocatorResolution(
                    success=True,
                    locator=locator,
                    details={
                        **current_details,
                        "attempts": list(attempts),
                        "attempts_skipped": False,
                    },
                )
            if count > 1:
                if step.kind in score_eligible_kinds:
                    best_resolution = await _best_visible_editable_locator(
                        locator,
                        current_details,
                        target_text=_target_display_text(target),
                    )
                    if best_resolution is not None:
                        # 评分降级命中也带 attempts, 与上面成功路径一致.
                        best_resolution = _LocatorResolution(
                            success=best_resolution.success,
                            locator=best_resolution.locator,
                            details={
                                **best_resolution.details,
                                "attempts": list(attempts),
                            },
                        )
                        return best_resolution
                visible_resolution = await _single_visible_locator(
                    locator,
                    current_details,
                )
                if visible_resolution is not None:
                    if visible_resolution.success:
                        return _LocatorResolution(
                            success=True,
                            locator=visible_resolution.locator,
                            details={
                                **visible_resolution.details,
                                "attempts": list(attempts),
                            },
                        )
                    current_details = visible_resolution.details
                return _LocatorResolution(
                    success=False,
                    result=self._failure(
                        step,
                        error_kind="locator_ambiguous",
                        message=(
                            f"locator matched {count} elements for "
                            f"{_target_display_text(target)!r}"
                        ),
                        fallback_recommended=True,
                        details={**current_details, "attempts": list(attempts)},
                    ),
                )

        return _LocatorResolution(
            success=False,
            result=self._failure(
                step,
                error_kind="locator_not_found",
                message=f"locator not found for {_target_display_text(target)!r}",
                fallback_recommended=True,
                details={"attempts": attempts},
            ),
        )

    def _resolve_value(self, value: str | None) -> str | None:
        if value is None:
            return None

        def replace(match: re.Match[str]) -> str:
            key = match.group(1)
            return self.variables.get(key, match.group(0))

        return _VAR_RE.sub(replace, value).strip()

    def _success(
        self,
        step: UIActionStep,
        *,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> DeterministicRunResult:
        return DeterministicRunResult(
            success=True,
            evidence=ActionEvidence(
                action_kind=step.kind,
                success=True,
                message=message,
                details=details or {},
            ),
        )

    def _failure(
        self,
        step: UIActionStep,
        *,
        error_kind: str,
        message: str,
        fallback_recommended: bool = False,
        details: dict[str, Any] | None = None,
    ) -> DeterministicRunResult:
        return DeterministicRunResult(
            success=False,
            fallback_recommended=fallback_recommended,
            evidence=ActionEvidence(
                action_kind=step.kind,
                success=False,
                error_kind=error_kind,
                message=message,
                details=details or {},
            ),
        )


class _LocatorResolution(BaseModel):
    success: bool
    locator: Any = None
    result: DeterministicRunResult | None = None
    details: dict[str, Any] = Field(default_factory=dict)

    @property
    def fallback_recommended(self) -> bool:
        return self.result.fallback_recommended if self.result is not None else False

    @property
    def evidence(self) -> ActionEvidence:
        if self.result is None:
            raise RuntimeError("successful locator resolution has no evidence")
        return self.result.evidence


async def _best_visible_editable_locator(
    locator: Any,
    details: dict[str, Any],
    *,
    target_text: str,
) -> _LocatorResolution | None:
    evaluate_all = getattr(locator, "evaluate_all", None)
    nth = getattr(locator, "nth", None)
    if not callable(evaluate_all) or not callable(nth):
        return None
    try:
        result = await evaluate_all(_BEST_EDITABLE_LOCATOR_SCRIPT, {"target": target_text})
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(result, dict):
        return None
    best_index = result.get("best_index")
    if not isinstance(best_index, int) or best_index < 0:
        return None
    try:
        best_locator = nth(best_index)
    except Exception:  # noqa: BLE001
        return None
    if best_locator is None:
        return None
    refined_details = {
        **details,
        "best_index": best_index,
        "disambiguation": "visible_editable_score",
    }
    candidates = result.get("candidates")
    if isinstance(candidates, list):
        refined_details["candidate_scores"] = candidates[:5]
    return _LocatorResolution(
        success=True,
        locator=best_locator,
        details=refined_details,
    )


async def _single_visible_locator(
    locator: Any,
    details: dict[str, Any],
) -> _LocatorResolution | None:
    filter_fn = getattr(locator, "filter", None)
    if not callable(filter_fn):
        return None
    try:
        visible_locator = filter_fn(visible=True)
    except TypeError:
        return None
    if visible_locator is None:
        return None
    visible_count = await visible_locator.count()
    refined_details = {**details, "visible_count": visible_count}
    if visible_count == 1:
        return _LocatorResolution(
            success=True,
            locator=visible_locator,
            details=refined_details,
        )
    return _LocatorResolution(success=False, details=refined_details)


async def _collect_post_action_evidence(
    page: Any,
    step: "UIActionStep | None" = None,
) -> dict[str, Any]:
    """Phase 15.3: step 透传到 ``_wait_after_action`` + 决定 table polling.

    向后兼容: ``step=None`` 时 quick 等待 + polling=0, 与旧行为完全一致.
    """
    await _wait_after_action(page, step)
    expects_refresh = bool(getattr(step, "expects_data_refresh", False)) if step else False
    # 数据刷新档下给 table 采集 6s polling: 后端 ajax 返回慢 / antd 列表渲
    # 染晚的场景, 让 collector 自带短窗口探活, 避免 "快照只显示加载中" 的
    # 假阴.
    table_polling_ms = 6000 if expects_refresh else 0
    collector = EvidenceCollector()
    page_identity = await collector.collect_page_identity(page)
    page_text = await _collect_page_text(page)
    form_fields = await collector.collect_form_fields(page)
    table_schema = await collector.collect_table_schema(
        page,
        polling_ms=table_polling_ms,
    )
    table_rows = await collector.collect_table_rows(
        page,
        limit=20,
        polling_ms=table_polling_ms,
    )
    return {
        "page_identity": page_identity.model_dump(mode="json"),
        "page_text": page_text,
        "form_fields": form_fields.model_dump(mode="json"),
        "table_schema": table_schema.model_dump(mode="json"),
        "table_rows": table_rows.model_dump(mode="json"),
    }


async def _collect_lightweight_context_evidence(page: Any) -> dict[str, Any]:
    collector = EvidenceCollector()
    page_identity = await collector.collect_page_identity(page)
    page_text = await _collect_page_text(page)
    return {
        "page_identity": page_identity.model_dump(mode="json"),
        "page_text": page_text,
    }


# Phase 15.3: SPA 数据刷新场景下用于探测加载状态的 selectors. 注意:
#   * Antd      .ant-table-loading / .ant-spin-spinning / .ant-skeleton-active
#   * Element+  .el-loading-mask / .el-loading-spinner
#   * Naive UI  .n-spin-container--show-spin / .n-data-table--loading
#   * 通用      [aria-busy="true"] / [role="progressbar"]
# 取并集; 任何一个还在则视为 "加载未结束". loading mask 消失即可视为数据
# 准备好被 EvidenceCollector 采集.
_LOADING_INDICATOR_SELECTORS: tuple[str, ...] = (
    ".ant-table-loading",
    ".ant-spin-spinning",
    ".ant-skeleton-active",
    ".el-loading-mask",
    ".el-loading-spinner",
    ".n-spin-container--show-spin",
    ".n-data-table--loading",
    "[aria-busy='true']",
    "[role='progressbar']",
)


async def _wait_after_action(
    page: Any,
    step: "UIActionStep | None" = None,
) -> None:
    """Phase 15.3: 动作后等待页面稳定. 两档:

    * quick (默认): 1.5s domcontentloaded + 300ms 兜底, 与历史行为一致.
    * data_refresh: 适用 expects_data_refresh=True 或显式 wait_strategy=
      "data_refresh" 的步骤; 依次 race networkidle / loading-mask 消失,
      由 settings.UI_POST_ACTION_WAIT_MAX_MS (默认 8000ms) 兜底总上界.

    每段都用 try/except 包住, 失败回退继续走, **不能让等待变成新失败源**.
    所有等待都用 Playwright 内置 API, 不引入 time.sleep / 固定 asyncio.sleep.
    """
    strategy = _resolve_wait_strategy(step)

    # 任一档都先做最便宜的 domcontentloaded 探测 -- 历史行为, 不动
    wait_for_load_state = getattr(page, "wait_for_load_state", None)
    if callable(wait_for_load_state):
        try:
            await wait_for_load_state("domcontentloaded", timeout=1_500)
        except Exception:  # noqa: BLE001
            pass

    if strategy == "quick":
        wait_fn = getattr(page, "wait_for_timeout", None)
        if callable(wait_fn):
            try:
                await wait_fn(300)
            except Exception:  # noqa: BLE001
                pass
        return

    # data_refresh 档 -- 依次 race, 任意一段触发即可往下走;
    # 总耗时受 budget 截断.
    from app.config import settings as _settings
    budget_ms = max(
        500,
        int(getattr(_settings, "UI_POST_ACTION_WAIT_MAX_MS", 8000) or 8000),
    )
    started = _monotonic_ms()

    def _remaining() -> int:
        return max(0, budget_ms - (_monotonic_ms() - started))

    # (a) networkidle: 拿到 "网络上无 inflight 请求超过 500ms" 信号; 上限
    # 3000ms 或 budget 剩余, 取小者. 注意 SPA 可能因为长轮询 / WS 永远不
    # idle, 所以必须有上限. 失败保险吞掉.
    if callable(wait_for_load_state):
        try:
            await wait_for_load_state(
                "networkidle",
                timeout=min(3_000, _remaining()) or 1,
            )
        except Exception:  # noqa: BLE001
            pass

    # (b) 等 loading mask 消失. 用 page.locator(...).first.wait_for(
    # state="hidden") 时单 selector 没匹配会立即返回, 行为是符合预期的.
    # 我们对每个 selector 都让步一段小预算 (1000ms), 但总和受 budget 截.
    locator_fn = getattr(page, "locator", None)
    if callable(locator_fn):
        for sel in _LOADING_INDICATOR_SELECTORS:
            if _remaining() <= 0:
                break
            try:
                indicator = locator_fn(sel)
                first = getattr(indicator, "first", indicator)
                wait_for = getattr(first, "wait_for", None)
                if callable(wait_for):
                    await wait_for(
                        state="hidden",
                        timeout=min(1_000, _remaining()) or 1,
                    )
            except Exception:  # noqa: BLE001
                continue

    # (c) 兜底 200ms 让最后一帧 paint 落地, 不让断言抢在浏览器渲染之前.
    # 失败保险吞掉, 避免 page 桩 / 异常 page 把整个等待变成失败源.
    wait_fn = getattr(page, "wait_for_timeout", None)
    if callable(wait_fn) and _remaining() > 0:
        try:
            await wait_fn(min(200, _remaining()))
        except Exception:  # noqa: BLE001
            pass


async def _poll_locator_count(
    page: Any,
    locator: Any,
    *,
    max_ms: int = 2000,
    interval_ms: int = 500,
) -> int:
    """Phase 15.3: 短窗口轮询 locator.count(), 命中即返回, 否则到上限返回 0.

    用于 ``_assert_text`` 这类 "动作刚结束 SPA 还在渲染" 的边界:
    元素一两帧后就出现, 但同步 count() 抢在了渲染之前. 全部异常吞掉,
    polling 自身不能变成新的失败源.
    """
    deadline = _monotonic_ms() + max(0, max_ms)
    wait_fn = getattr(page, "wait_for_timeout", None)
    while _monotonic_ms() < deadline:
        try:
            if callable(wait_fn):
                await wait_fn(interval_ms)
            count = await locator.count()
        except Exception:  # noqa: BLE001
            return 0
        if count > 0:
            return int(count)
    return 0


# Phase 15.4b: AI 自愈候选 strategy 白名单. 不接受 evaluate / runJavaScript
# 之类的执行型策略, 只接受 "查询 DOM" 类的 4 种.
_AI_LOCATOR_ALLOWED_STRATEGIES = frozenset({"role", "text", "css", "xpath"})


def _extra_candidate_to_make_locator(
    page: Any,
    spec: dict[str, Any],
) -> tuple[Callable[[], Any | None], dict[str, Any]] | None:
    """把 LLM 自愈给出的 ``{strategy, value, rationale}`` dict 转为 locator factory.

    安全约束:
    - ``strategy`` 必须在 _AI_LOCATOR_ALLOWED_STRATEGIES 内, 不放 ``evaluate``;
    - ``value`` 必须是非空字符串, 否则跳过;
    - role 策略要求 ``value`` 形如 ``role:name`` (用冒号分隔), 任一段空也跳过.
    任何形式不合规直接返回 None, 让上层把这条 AI 候选静默丢掉.
    """
    if not isinstance(spec, dict):
        return None
    strategy = str(spec.get("strategy") or "").strip().lower()
    raw_value = spec.get("value")
    if strategy not in _AI_LOCATOR_ALLOWED_STRATEGIES:
        return None
    value = str(raw_value or "").strip()
    if not value:
        return None
    rationale = str(spec.get("rationale") or "")[:200]

    details_base = {
        "strategy": strategy,
        "selector": value,
        "source": "ai_self_heal",
        "rationale": rationale,
    }

    if strategy == "css":
        def _make_css() -> Any | None:
            locator_fn = getattr(page, "locator", None)
            if not callable(locator_fn):
                return None
            return locator_fn(value)
        return _make_css, details_base

    if strategy == "xpath":
        xpath_value = value if value.startswith("xpath=") else f"xpath={value}"

        def _make_xpath() -> Any | None:
            locator_fn = getattr(page, "locator", None)
            if not callable(locator_fn):
                return None
            return locator_fn(xpath_value)
        return _make_xpath, {**details_base, "selector": xpath_value}

    if strategy == "text":
        def _make_text() -> Any | None:
            fn = getattr(page, "get_by_text", None)
            if not callable(fn):
                return None
            return fn(value, exact=False)
        return _make_text, details_base

    if strategy == "role":
        # value 期望 "role:name" 形式; 没有 ':' 也允许只传 role (没有 name).
        if ":" in value:
            role, name = value.split(":", 1)
            role = role.strip()
            name = name.strip()
        else:
            role = value
            name = ""
        if not role:
            return None

        def _make_role() -> Any | None:
            fn = getattr(page, "get_by_role", None)
            if not callable(fn):
                return None
            if name:
                return fn(role, name=name)
            return fn(role)
        return _make_role, {**details_base, "role": role, "name": name or None}

    return None


def _resolved_assert_text_degrade_level() -> int:
    """Phase 15.6: 读取 settings.UI_ASSERT_TEXT_DEGRADE_LEVEL, 默认 3.

    1 = 严格 (回到 Phase 15.5 之前的 exact 行为, 用于诊断假阳性).
    2 = 宽松到 contains.
    3 = 宽松到 :text-is / :has-text 联合.
    """
    try:
        from app.config import settings as _settings  # noqa: PLC0415
        raw = getattr(_settings, "UI_ASSERT_TEXT_DEGRADE_LEVEL", 3)
        level = int(raw or 3)
    except Exception:  # noqa: BLE001
        level = 3
    if level < 1:
        return 1
    if level > 3:
        return 3
    return level


def _build_loose_text_locator(page: Any, text: str) -> Any | None:
    """Phase 15.6: level 3 宽松匹配 -- :text-is(text) 与 :has-text(text) 取并集.

    :text-is 用于"元素自己内容等于 text", :has-text 用于"元素或子节点包含 text".
    Playwright 的 ``Locator.or_`` 会把两条 selector 的结果合并去重, 总计 count
    任意 > 0 即视为命中. 任一 selector 不可用 (page.locator 桩 / 旧版 Playwright)
    就直接返回 None, 让上层降级 fail.
    """
    locator_fn = getattr(page, "locator", None)
    if not callable(locator_fn):
        return None
    text_is = locator_fn(f":text-is({_quote_text_for_selector(text)})")
    has_text = locator_fn(f":has-text({_quote_text_for_selector(text)})")
    or_fn = getattr(text_is, "or_", None)
    if callable(or_fn):
        try:
            return or_fn(has_text)
        except Exception:  # noqa: BLE001
            return text_is
    return text_is


def _quote_text_for_selector(text: str) -> str:
    """Playwright text engine 接受的字符串字面量: 单/双引号视情况转义."""
    if '"' not in text:
        return f'"{text}"'
    if "'" not in text:
        return f"'{text}'"
    escaped = text.replace('"', '\\"')
    return f'"{escaped}"'


def _resolve_wait_strategy(step: "UIActionStep | None") -> str:
    """Phase 15.3: step.wait_strategy 显式 > expects_data_refresh 隐式 > quick."""
    if step is None:
        return "quick"
    explicit = getattr(step, "wait_strategy", None)
    if explicit:
        return explicit
    if getattr(step, "expects_data_refresh", False):
        return "data_refresh"
    return "quick"


def _monotonic_ms() -> int:
    import time as _t  # 局部 import 避免污染本模块顶部命名空间; 调用频率低.
    return int(_t.monotonic() * 1000)


async def _collect_page_text(page: Any) -> dict[str, Any]:
    evaluate = getattr(page, "evaluate", None)
    if not callable(evaluate):
        return {"ok": False, "texts": [], "error": "page.evaluate unavailable"}
    try:
        raw = await evaluate(_PAGE_TEXT_SUMMARY_SCRIPT)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "texts": [], "error": str(exc)}
    if not isinstance(raw, dict):
        return {"ok": False, "texts": [], "error": "page text script returned non-dict"}
    texts = raw.get("texts") if isinstance(raw.get("texts"), list) else []
    return {
        "ok": bool(raw.get("ok", True)),
        "texts": [str(item).strip() for item in texts if str(item).strip()][:120],
        "error": raw.get("error"),
    }


def _normalize_key(value: str) -> str:
    text = str(value or "").strip().strip("\"'“”‘’「」")
    aliases = {
        "回车": "Enter",
        "enter": "Enter",
        "esc": "Escape",
        "escape": "Escape",
        "退出": "Escape",
        "tab": "Tab",
        "制表": "Tab",
        "空格": "Space",
        "space": "Space",
    }
    return aliases.get(text.lower(), aliases.get(text, text))


_BEST_EDITABLE_LOCATOR_SCRIPT = """
(elements, arg) => {
  const target = String((arg && arg.target) || '').trim();
  const clean = (value) => String(value || '').replace(/\\s+/g, ' ').trim();
  const visible = (el) => {
    const style = window.getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style.display !== 'none'
      && style.visibility !== 'hidden'
      && Number(style.opacity || 1) !== 0
      && rect.width > 0
      && rect.height > 0
      && rect.bottom >= 0
      && rect.right >= 0
      && rect.top <= window.innerHeight
      && rect.left <= window.innerWidth;
  };
  const editable = (el) => {
    const tag = clean(el.tagName).toLowerCase();
    const type = clean(el.getAttribute('type')).toLowerCase();
    if (type === 'hidden' || type === 'submit' || type === 'button') return false;
    if (el.disabled || el.getAttribute('aria-disabled') === 'true') return false;
    if (tag === 'input' || tag === 'textarea' || tag === 'select') return true;
    return el.isContentEditable || el.getAttribute('contenteditable') === 'true';
  };
  const inTable = (el) => Boolean(el.closest(
    'table,[role="table"],[role="grid"],.ant-table,.el-table,.n-data-table'
  ));
  const inDialog = (el) => Boolean(el.closest(
    '.ant-drawer,.el-drawer,.n-drawer,[role="dialog"],.drawer,[class*="drawer"]'
  ));
  const textOf = (el) => clean([
    el.getAttribute('placeholder'),
    el.getAttribute('aria-label'),
    el.getAttribute('name'),
    el.id,
    el.textContent,
  ].filter(Boolean).join(' '));
  const scored = elements.map((el, index) => {
    const rect = el.getBoundingClientRect();
    let score = 0;
    if (visible(el)) score += 100;
    if (editable(el)) score += 100;
    if (!inTable(el)) score += 40;
    if (inDialog(el)) score += 35;
    if (target && textOf(el).includes(target)) score += 30;
    if (rect.top >= 0 && rect.top < 260) score += 20;
    if (rect.left >= 0 && rect.left < window.innerWidth * 0.7) score += 10;
    return {
      index,
      score,
      visible: visible(el),
      editable: editable(el),
      inTable: inTable(el),
      inDialog: inDialog(el),
      top: Math.round(rect.top),
      left: Math.round(rect.left),
      text: textOf(el).slice(0, 80),
    };
  }).filter((item) => item.visible && item.editable);
  scored.sort((a, b) => b.score - a.score || a.top - b.top || a.left - b.left);
  return {
    best_index: scored.length ? scored[0].index : null,
    candidates: scored.slice(0, 5),
  };
}
"""


_PAGE_TEXT_SUMMARY_SCRIPT = """
(() => {
  const clean = (value) => String(value || '').replace(/\\s+/g, ' ').trim();
  const visible = (el) => {
    const style = window.getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style.display !== 'none'
      && style.visibility !== 'hidden'
      && Number(style.opacity || 1) !== 0
      && rect.width > 0
      && rect.height > 0;
  };
  const visibleText = (el) => {
    if (!visible(el)) {
      return '';
    }
    return clean(el.innerText || el.textContent || el.getAttribute('aria-label') || '');
  };
  const overlaySelectors = [
    '.ant-drawer',
    '.ant-modal',
    '.el-drawer',
    '.el-dialog',
    '.n-drawer',
    '.n-modal',
    '[role="dialog"]',
    '.drawer',
    '[class*="drawer"]',
  ];
  const overlays = Array.from(document.querySelectorAll(overlaySelectors.join(',')))
    .filter(visible);
  const activeRoots = overlays.length ? [overlays[overlays.length - 1]] : [document];
  const selectors = [
    'h1,h2,h3,h4,h5,h6,[role="heading"]',
    'button,[role="button"]',
    'label',
    '.ant-drawer,.el-drawer,.n-drawer,[role="dialog"],.drawer,[class*="drawer"]',
    '.ant-form-item-label,.el-form-item__label,.n-form-item-label',
  ];
  const seen = new Set();
  const texts = [];
  const push = (value) => {
    const text = clean(value);
    if (!text || seen.has(text)) return;
    seen.add(text);
    texts.push(text.slice(0, 120));
  };
  for (const root of activeRoots) {
    for (const el of Array.from(root.querySelectorAll(selectors.join(',')))) {
      push(visibleText(el));
    }
    for (const el of Array.from(root.querySelectorAll('input,textarea,select')).slice(0, 80)) {
      if (!visible(el)) continue;
      push(el.getAttribute('placeholder'));
      push(el.getAttribute('aria-label'));
    }
  }
  return { ok: true, texts: texts.slice(0, 120) };
})()
"""


def _target_display_text(target: ActionTarget) -> str:
    return (
        target.name
        or target.text
        or target.label
        or target.placeholder
        or target.test_id
        or target.url
        or ""
    )


def _is_dangerous_target(text: str) -> bool:
    return any(word in text for word in _DANGEROUS_ACTION_WORDS)


def _source_allows_dangerous_action(source_text: str, target_text: str) -> bool:
    dangerous_words = [word for word in _DANGEROUS_ACTION_WORDS if word in target_text]
    if not dangerous_words:
        return True
    return all(word in source_text for word in dangerous_words)
