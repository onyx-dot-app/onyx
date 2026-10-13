"""Unit tests for the PAT scopes listing and scope validation."""

from unittest.mock import MagicMock, patch

import pytest

from onyx.db.enums import Permission
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.pat import api as pat_api
from onyx.server.settings.models import Settings


def _listed_scopes(gateway_enabled: bool) -> list[Permission]:
    with patch.object(
        pat_api,
        "load_settings",
        MagicMock(return_value=Settings(llm_gateway_enabled=gateway_enabled)),
    ):
        return [option.scope for option in pat_api.list_selectable_scopes(MagicMock())]


def test_scopes_include_gateway_when_enabled() -> None:
    assert Permission.USE_LLM_GATEWAY in _listed_scopes(gateway_enabled=True)


def test_scopes_hide_gateway_when_disabled() -> None:
    scopes = _listed_scopes(gateway_enabled=False)
    assert Permission.USE_LLM_GATEWAY not in scopes
    # Other scopes are unaffected.
    assert Permission.READ_SEARCH in scopes


def test_validate_scopes_rejects_gateway_scope_when_disabled() -> None:
    with patch.object(
        pat_api,
        "load_settings",
        MagicMock(return_value=Settings(llm_gateway_enabled=False)),
    ):
        with pytest.raises(OnyxError) as exc_info:
            pat_api._validate_assignable_scopes([Permission.USE_LLM_GATEWAY])
    assert exc_info.value.error_code == OnyxErrorCode.INVALID_INPUT


def test_validate_scopes_allows_gateway_scope_when_enabled() -> None:
    with patch.object(
        pat_api,
        "load_settings",
        MagicMock(return_value=Settings(llm_gateway_enabled=True)),
    ):
        pat_api._validate_assignable_scopes([Permission.USE_LLM_GATEWAY])
