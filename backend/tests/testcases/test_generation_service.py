import uuid

import pytest

from app.core.exceptions import AppException
from app.modules.testcases.generation_service import _resolve_required_accept_module_id


def test_accept_module_prefers_explicit_request_module() -> None:
    batch_module_id = uuid.uuid4()
    request_module_id = uuid.uuid4()

    assert _resolve_required_accept_module_id(
        batch_module_id=batch_module_id,
        request_module_id=request_module_id,
    ) == request_module_id


def test_accept_module_falls_back_to_batch_module() -> None:
    batch_module_id = uuid.uuid4()

    assert _resolve_required_accept_module_id(
        batch_module_id=batch_module_id,
        request_module_id=None,
    ) == batch_module_id


def test_accept_module_requires_a_module() -> None:
    with pytest.raises(AppException) as excinfo:
        _resolve_required_accept_module_id(
            batch_module_id=None,
            request_module_id=None,
        )

    assert excinfo.value.code == "MODULE_REQUIRED"
    assert "模块" in excinfo.value.message
