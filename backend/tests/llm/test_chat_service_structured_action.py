"""Phase 13 / Task 13.8 — chat 流结构化 action meta 提取。"""

from __future__ import annotations

import json

from app.modules.llm.chat_service import _extract_structured_action_meta


def test_extract_structured_fix_action_meta() -> None:
    payload = {
        "action_type": "fix_action",
        "task_id": "task-1",
        "diagnosis": {"root_cause": "按钮不可点", "evidence": [], "confidence": 0.8},
        "suggested_actions": [{"action": "retry_with_correction", "label": "重试"}],
    }

    assert _extract_structured_action_meta(json.dumps(payload, ensure_ascii=False)) == payload


def test_extract_structured_action_ignores_plain_tool_result() -> None:
    payload = {"count": 1, "results": []}

    assert _extract_structured_action_meta(json.dumps(payload, ensure_ascii=False)) is None
