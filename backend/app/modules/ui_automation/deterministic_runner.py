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

    async def run_step(self, page: Any, step: UIActionStep) -> DeterministicRunResult:
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

    async def _navigate(self, page: Any, step: UIActionStep) -> DeterministicRunResult:
        url = self._resolve_value(step.target.url)
        if not url:
            return self._failure(step, error_kind="missing_target", message="navigate missing url")
        await page.goto(url, timeout=self.timeout_ms, wait_until="domcontentloaded")
        structured_evidence = await _collect_post_action_evidence(page)
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
        structured_evidence = await _collect_post_action_evidence(page)
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
        structured_evidence = await _collect_post_action_evidence(page)
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
        structured_evidence = await _collect_post_action_evidence(page)
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
        structured_evidence = await _collect_post_action_evidence(page)
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
        locator = page.get_by_text(text, exact=True)
        count = await locator.count()
        if count <= 0:
            structured_evidence = await _collect_post_action_evidence(page)
            return self._failure(
                step,
                error_kind="assertion_failed",
                message=f"text {text!r} not found",
                fallback_recommended=True,
                details={
                    "text": text,
                    "count": count,
                    "structured_evidence": structured_evidence,
                },
            )
        return self._success(
            step,
            message=f"text {text!r} found",
            details={"text": text, "count": count},
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
        for make_locator, details in candidates:
            locator = make_locator()
            if locator is None:
                continue
            count = await locator.count()
            current_details = {**details, "count": count}
            attempts.append(current_details)
            if count == 1:
                return _LocatorResolution(
                    success=True,
                    locator=locator,
                    details=current_details,
                )
            if count > 1:
                if step.kind in {UIActionKind.FILL, UIActionKind.SELECT}:
                    best_resolution = await _best_visible_editable_locator(
                        locator,
                        current_details,
                        target_text=_target_display_text(target),
                    )
                    if best_resolution is not None:
                        return best_resolution
                visible_resolution = await _single_visible_locator(
                    locator,
                    current_details,
                )
                if visible_resolution is not None:
                    if visible_resolution.success:
                        return visible_resolution
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
                        details=current_details,
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


async def _collect_post_action_evidence(page: Any) -> dict[str, Any]:
    await _wait_after_action(page)
    collector = EvidenceCollector()
    page_identity = await collector.collect_page_identity(page)
    page_text = await _collect_page_text(page)
    form_fields = await collector.collect_form_fields(page)
    table_schema = await collector.collect_table_schema(page)
    table_rows = await collector.collect_table_rows(page, limit=20)
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


async def _wait_after_action(page: Any) -> None:
    wait_for_load_state = getattr(page, "wait_for_load_state", None)
    if callable(wait_for_load_state):
        try:
            await wait_for_load_state("domcontentloaded", timeout=1_500)
        except Exception:  # noqa: BLE001
            pass
    wait_fn = getattr(page, "wait_for_timeout", None)
    if callable(wait_fn):
        await wait_fn(300)


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


def _build_locator_candidates(
    page: Any,
    target: ActionTarget,
) -> list[tuple[Callable[[], Any | None], dict[str, Any]]]:
    candidates: list[tuple[Callable[[], Any | None], dict[str, Any]]] = []

    def add(make_locator: Callable[[], Any | None], details: dict[str, Any]) -> None:
        candidates.append((make_locator, details))

    if target.role and target.name:
        add(
            lambda: _optional_page_method(
                page,
                "get_by_role",
                target.role,
                name=target.name,
            ),
            {
                "strategy": "role",
                "role": target.role,
                "name": target.name,
            },
        )
        if target.role == "button":
            add(
                lambda: _optional_page_method(
                    page,
                    "get_by_text",
                    target.name,
                    exact=True,
                ),
                {"strategy": "text", "text": target.name, "exact": True},
            )
            add(
                lambda: _optional_page_method(
                    page,
                    "get_by_text",
                    target.name,
                    exact=False,
                ),
                {"strategy": "text", "text": target.name, "exact": False},
            )
            add(
                lambda: _optional_css_locator(
                    page,
                    f"button:has-text({_css_string(target.name)})",
                ),
                {
                    "strategy": "css",
                    "selector": f"button:has-text({_css_string(target.name)})",
                },
            )
            add(
                lambda: _optional_css_locator(
                    page,
                    f"[role='button']:has-text({_css_string(target.name)})",
                ),
                {
                    "strategy": "css",
                    "selector": f"[role='button']:has-text({_css_string(target.name)})",
                },
            )
            add(
                lambda: _optional_css_locator(
                    page,
                    ".ant-btn:has-text({0}), .el-button:has-text({0}), "
                    ".n-button:has-text({0})".format(_css_string(target.name)),
                ),
                {
                    "strategy": "css",
                    "selector": (
                        ".ant-btn/.el-button/.n-button has text "
                        f"{target.name}"
                    ),
                },
            )
            button_xpath = (
                "xpath=//*[self::button or @role='button' or "
                "contains(@class, 'button') or contains(@class, 'btn') or "
                "contains(@class, 'el-button') or contains(@class, 'ant-btn') or "
                "contains(@class, 'n-button')]"
                f"[contains(normalize-space(.), {_xpath_string(target.name)})]"
            )
            add(
                lambda: _optional_css_locator(page, button_xpath),
                {"strategy": "xpath", "selector": button_xpath},
            )
        return candidates
    if target.label:
        add(
            lambda: _optional_page_method(page, "get_by_label", target.label),
            {"strategy": "label", "label": target.label},
        )
        add(
            lambda: _optional_page_method(
                page,
                "get_by_placeholder",
                target.label,
            ),
            {"strategy": "placeholder", "placeholder": target.label},
        )
        add(
            lambda: _optional_page_method(
                page,
                "get_by_placeholder",
                f"请输入{target.label}",
            ),
            {"strategy": "placeholder", "placeholder": f"请输入{target.label}"},
        )
        add(
            lambda: _optional_page_method(
                page,
                "get_by_role",
                "textbox",
                name=target.label,
            ),
            {"strategy": "role", "role": "textbox", "name": target.label},
        )
        label_selector = (
            f"input[placeholder*={_css_string(target.label)}], "
            f"textarea[placeholder*={_css_string(target.label)}], "
            f"[aria-label*={_css_string(target.label)}]"
        )
        add(
            lambda: _optional_css_locator(page, label_selector),
            {"strategy": "css", "selector": label_selector},
        )
        input_xpath = (
            "xpath=//input[not(@type='hidden') and "
            f"(contains(@placeholder, {_xpath_string(target.label)}) or "
            f"contains(@aria-label, {_xpath_string(target.label)}) or "
            f"contains(@name, {_xpath_string(target.label)}) or "
            f"contains(@id, {_xpath_string(target.label)}))] | "
            "//textarea["
            f"contains(@placeholder, {_xpath_string(target.label)}) or "
            f"contains(@aria-label, {_xpath_string(target.label)})] | "
            "//*[self::label or self::span or self::div]"
            f"[contains(normalize-space(.), {_xpath_string(target.label)})]"
            "/following::input[not(@type='hidden')][1]"
        )
        add(
            lambda: _optional_css_locator(page, input_xpath),
            {"strategy": "xpath", "selector": input_xpath},
        )
        if _looks_like_search_target(target.label):
            add(
                lambda: _optional_page_method(page, "get_by_role", "searchbox"),
                {"strategy": "role", "role": "searchbox"},
            )
            search_selector = (
                "input[type='search'], [role='searchbox'], "
                "input[name*='search' i], input[id*='search' i], "
                "input[placeholder*='搜索'], input[aria-label*='搜索'], "
                "input[name='wd'], textarea[name='wd'], "
                "input[type='text'], textarea"
            )
            add(
                lambda: _optional_css_locator(page, search_selector),
                {"strategy": "css", "selector": search_selector},
            )
        return candidates
    if target.placeholder:
        add(
            lambda: _optional_page_method(
                page,
                "get_by_placeholder",
                target.placeholder,
            ),
            {
                "strategy": "placeholder",
                "placeholder": target.placeholder,
            },
        )
        placeholder_selector = (
            f"input[placeholder*={_css_string(target.placeholder)}], "
            f"textarea[placeholder*={_css_string(target.placeholder)}]"
        )
        add(
            lambda: _optional_css_locator(page, placeholder_selector),
            {"strategy": "css", "selector": placeholder_selector},
        )
        return candidates
    if target.test_id:
        add(
            lambda: _optional_page_method(page, "get_by_test_id", target.test_id),
            {
                "strategy": "test_id",
                "test_id": target.test_id,
            },
        )
        return candidates
    if target.text:
        add(
            lambda: _optional_page_method(
                page,
                "get_by_text",
                target.text,
                exact=True,
            ),
            {"strategy": "text", "text": target.text, "exact": True},
        )
        return candidates
    if target.name:
        add(
            lambda: _optional_page_method(
                page,
                "get_by_text",
                target.name,
                exact=True,
            ),
            {"strategy": "text", "text": target.name, "exact": True},
        )
        return candidates
    return candidates


def _optional_page_method(page: Any, method: str, *args: Any, **kwargs: Any) -> Any | None:
    fn = getattr(page, method, None)
    if not callable(fn):
        return None
    return fn(*args, **kwargs)


def _looks_like_search_target(value: str | None) -> bool:
    text = str(value or "").strip().lower()
    if not text:
        return False
    return "搜索" in text or "search" in text


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


def _optional_css_locator(page: Any, selector: str) -> Any | None:
    locator_fn = getattr(page, "locator", None)
    if not callable(locator_fn):
        return None
    return locator_fn(selector)


def _css_string(value: str) -> str:
    return repr(str(value))


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


def _xpath_string(value: str) -> str:
    text = str(value)
    if "'" not in text:
        return f"'{text}'"
    if '"' not in text:
        return f'"{text}"'
    parts = text.split("'")
    return "concat(" + ', "\'", '.join(f"'{part}'" for part in parts) + ")"


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
