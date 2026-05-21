"""Phase 13 / Task 13.5 — semantic test-data resolver for ConfirmationCard."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from app.core import crypto
from app.modules.skills.builtin.ui_automation.resolver import (
    build_test_data_preview_from_resolver,
)
from app.modules.ui_automation.test_data_resolver import TestDataItem, TestDataResolver


def test_semantic_preview_masks_secret_and_reports_missing() -> None:
    set_id = uuid.uuid4()
    resolver = TestDataResolver.from_merge_dict(
        {
            "username": TestDataItem(
                key="username",
                value_type="string",
                value_text="alice",
                semantic="login_username",
                source_set_id=set_id,
                source_set_name="账号集",
            ),
            "password": TestDataItem(
                key="password",
                value_type="secret",
                value_encrypted=crypto.encrypt("sekrit"),
                semantic="login_password",
                source_set_id=set_id,
                source_set_name="账号集",
            ),
        },
    )
    case = SimpleNamespace(
        required_test_data=[
            {"semantic": "login_username", "required": True},
            {"semantic": "login_password", "required": True},
            {"semantic": "target_user_id", "required": True},
        ],
    )

    preview = build_test_data_preview_from_resolver(
        [case],
        resolver,
        set_summaries=[
            {
                "id": str(set_id),
                "name": "账号集",
                "scope": "project",
                "item_count": 2,
            },
        ],
    )

    assert [item.semantic for item in preview.items] == [
        "login_username",
        "login_password",
    ]
    assert preview.items[0].value_preview == "alice"
    assert preview.items[1].value_preview == "<masked>"
    assert "sekrit" not in str(preview.model_dump(mode="json"))
    assert preview.items[1].is_secret is True
    assert preview.items[1].source == "账号集（project）"
    assert preview.missing_semantics == ["target_user_id"]


def test_preview_falls_back_to_safe_item_list_without_required_semantics() -> None:
    resolver = TestDataResolver.from_merge_dict(
        {
            "token": TestDataItem(
                key="token",
                value_type="secret",
                value_encrypted=crypto.encrypt("plain-token"),
                semantic=None,
            ),
            "display_name": TestDataItem(
                key="display_name",
                value_type="string",
                value_text="Ada Lovelace",
                semantic="display_name",
            ),
        },
    )

    preview = build_test_data_preview_from_resolver([], resolver)

    by_key = {item.key: item for item in preview.items}
    assert by_key["token"].value_preview == "<masked>"
    assert by_key["display_name"].value_preview == "Ada Lovelace"
    assert "plain-token" not in str(preview.model_dump(mode="json"))
