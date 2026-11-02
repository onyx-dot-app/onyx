"""Unit tests for the PAT scopes listing and scope validation."""

from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import pytest

from onyx.db.enums import Permission
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.pat import api as pat_api
from onyx.server.settings.models import Settings, Tier


@pytest.fixture(autouse=True)
def business_tier() -> Iterator[None]:
    with patch.object(pat_api, "get_current_tier", return_value=Tier.BUSINESS):
        yield


def _listed_scopes(gateway_enabled: bool = True) -> list[Permission]:
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


@pytest.mark.parametrize("tier", [Tier.BUSINESS, Tier.ENTERPRISE])
def test_gateway_scope_listed_and_mintable_on_business_plus(tier: Tier) -> None:
    with (
        patch.object(pat_api, "get_current_tier", return_value=tier),
        patch.object(
            pat_api,
            "load_settings",
            MagicMock(return_value=Settings(llm_gateway_enabled=True)),
        ),
    ):
        assert Permission.USE_LLM_GATEWAY in [
            option.scope for option in pat_api.list_selectable_scopes(MagicMock())
        ]
        pat_api._validate_assignable_scopes([Permission.USE_LLM_GATEWAY])


def test_gateway_scope_hidden_and_rejected_on_community() -> None:
    with (
        patch.object(pat_api, "get_current_tier", return_value=Tier.COMMUNITY),
        patch.object(
            pat_api,
            "load_settings",
            MagicMock(return_value=Settings(llm_gateway_enabled=True)),
        ),
    ):
        scopes = [
            option.scope for option in pat_api.list_selectable_scopes(MagicMock())
        ]
        assert Permission.USE_LLM_GATEWAY not in scopes
        assert Permission.READ_SEARCH in scopes
        with pytest.raises(OnyxError) as exc_info:
            pat_api._validate_assignable_scopes(
                [Permission.READ_SEARCH, Permission.USE_LLM_GATEWAY]
            )
        assert exc_info.value.error_code == OnyxErrorCode.FEATURE_NOT_AVAILABLE
        pat_api._validate_assignable_scopes([Permission.READ_SEARCH])
        pat_api._validate_assignable_scopes(None)
