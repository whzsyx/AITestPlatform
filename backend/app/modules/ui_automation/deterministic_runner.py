"""Deterministic UIActionPlan runner for low-risk Playwright operations."""

from __future__ import annotations

import re
from collections.abc import Mapping
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
        return self._success(step, message=f"navigated to {url}", details={"url": url})

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
        return self._success(
            step,
            message=f"clicked {target_text or 'target'}",
            details=locator_result.details,
        )

    async def _fill(self, page: Any, step: UIActionStep) -> DeterministicRunResult:
        value = self._resolve_value(step.value)
        locator_result = await self._strict_locator(page, step)
        if not locator_result.success:
            return locator_result.result
        await locator_result.locator.fill(value or "", timeout=self.timeout_ms)
        return self._success(
            step,
            message=f"filled {_target_display_text(step.target) or 'target'}",
            details={**locator_result.details, "value_length": len(value or "")},
        )

    async def _select(self, page: Any, step: UIActionStep) -> DeterministicRunResult:
        value = self._resolve_value(step.value)
        if not value:
            return self._failure(step, error_kind="missing_value", message="select missing value")
        locator_result = await self._strict_locator(page, step)
        if not locator_result.success:
            return locator_result.result
        await locator_result.locator.select_option(value, timeout=self.timeout_ms)
        return self._success(
            step,
            message=f"selected {value}",
            details={**locator_result.details, "value": value},
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
            return self._failure(
                step,
                error_kind="assertion_failed",
                message=f"text {text!r} not found",
                fallback_recommended=True,
                details={"text": text, "count": count},
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
        details = {
            "structured_evidence": {"table_rows": evidence.model_dump(mode="json")},
        }
        if verdict.passed:
            return self._success(step, message=verdict.reason, details=details)
        return self._failure(
            step,
            error_kind="assertion_failed",
            message=verdict.reason,
            details=details,
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
        locator, details = _build_locator(page, target)
        if locator is None:
            return _LocatorResolution(
                success=False,
                result=self._failure(
                    step,
                    error_kind="missing_target",
                    message="no supported locator fields present",
                    fallback_recommended=True,
                ),
            )
        count = await locator.count()
        details["count"] = count
        if count == 0:
            return _LocatorResolution(
                success=False,
                result=self._failure(
                    step,
                    error_kind="locator_not_found",
                    message=f"locator not found for {_target_display_text(target)!r}",
                    fallback_recommended=True,
                    details=details,
                ),
            )
        if count > 1:
            return _LocatorResolution(
                success=False,
                result=self._failure(
                    step,
                    error_kind="locator_ambiguous",
                    message=f"locator matched {count} elements for {_target_display_text(target)!r}",
                    fallback_recommended=True,
                    details=details,
                ),
            )
        return _LocatorResolution(success=True, locator=locator, details=details)

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


def _build_locator(page: Any, target: ActionTarget) -> tuple[Any | None, dict[str, Any]]:
    if target.role and target.name:
        return (
            page.get_by_role(target.role, name=target.name),
            {"strategy": "role", "role": target.role, "name": target.name},
        )
    if target.label:
        return page.get_by_label(target.label), {"strategy": "label", "label": target.label}
    if target.placeholder:
        return (
            page.get_by_placeholder(target.placeholder),
            {"strategy": "placeholder", "placeholder": target.placeholder},
        )
    if target.test_id:
        return (
            page.get_by_test_id(target.test_id),
            {"strategy": "test_id", "test_id": target.test_id},
        )
    if target.text:
        return (
            page.get_by_text(target.text, exact=True),
            {"strategy": "text", "text": target.text},
        )
    if target.name:
        return (
            page.get_by_text(target.name, exact=True),
            {"strategy": "text", "text": target.name},
        )
    return None, {}


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
