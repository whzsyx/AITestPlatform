from __future__ import annotations

from app.modules.ui_automation.action_plan import ActionTarget, UIActionKind, UIActionStep
from app.modules.ui_automation.deterministic_runner import (
    ActionEvidence,
    DeterministicRunResult,
)
from app.modules.ui_automation.execution_engine import _ai_fallback_allowed


def test_ai_fallback_is_disabled_when_external_verification_is_detected() -> None:
    step = UIActionStep(
        source_text="验证搜索结果页面非空",
        kind=UIActionKind.ASSERT_TEXT,
        target=ActionTarget(text="搜索结果"),
    )
    result = DeterministicRunResult(
        success=False,
        fallback_recommended=True,
        evidence=ActionEvidence(
            action_kind=UIActionKind.ASSERT_TEXT,
            success=False,
            error_kind="assertion_failed",
            message="text not found",
            details={
                "structured_evidence": {
                    "page_identity": {
                        "url": "https://wappass.baidu.com/static/captcha/tuxing_v2.html",
                        "title": "安全验证",
                    },
                    "page_text": {"texts": ["请完成安全验证", "验证码"]},
                },
            },
        ),
    )

    assert _ai_fallback_allowed(step, result) is False
