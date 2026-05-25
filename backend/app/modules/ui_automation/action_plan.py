"""Lightweight UI action plan DSL for deterministic-first automation."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class UIActionKind(str, Enum):
    NAVIGATE = "navigate"
    CLICK = "click"
    FILL = "fill"
    SELECT = "select"
    WAIT_FOR_URL = "wait_for_url"
    ASSERT_TEXT = "assert_text"
    ASSERT_URL = "assert_url"
    ASSERT_PAGE_LOADED = "assert_page_loaded"
    ASSERT_TABLE_COLUMNS = "assert_table_columns"
    ASSERT_TABLE_ROWS = "assert_table_rows"
    ASSERT_FORM_VALUES = "assert_form_values"
    UNSUPPORTED = "unsupported"


RiskLevel = Literal["low", "medium", "high"]


class ActionTarget(BaseModel):
    url: str | None = None
    role: str | None = None
    name: str | None = None
    text: str | None = None
    label: str | None = None
    placeholder: str | None = None
    test_id: str | None = None
    table_hint: str | None = None
    columns: list[str] | None = None


class UIActionStep(BaseModel):
    source_step_number: int | None = Field(None, ge=0)
    source_text: str = ""
    kind: UIActionKind
    target: ActionTarget = Field(default_factory=ActionTarget)
    value: str | None = None
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    requires_evidence: list[str] = Field(default_factory=list)
    risk_level: RiskLevel = "low"
    unsupported_reason: str | None = None


class UIActionPlan(BaseModel):
    version: str = "ui-plan/v1"
    case_id: str | None = None
    module_entry: str | None = None
    execution_mode: str = "deterministic_first"
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    steps: list[UIActionStep] = Field(default_factory=list)
    fallback_policy: str = "step_runner_on_unsupported"


class PlanCompileResult(BaseModel):
    plan: UIActionPlan
    supported_step_count: int = 0
    unsupported_step_count: int = 0
    warnings: list[str] = Field(default_factory=list)
