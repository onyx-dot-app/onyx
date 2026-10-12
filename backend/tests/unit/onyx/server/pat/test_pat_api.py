"""Unit tests for PAT scope tier gating."""

from unittest.mock import MagicMock, patch

import pytest

from onyx.db.enums import Permission
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.pat import api as pat_api
from onyx.server.settings.models import Tier


def _listed_scopes() -> list[Permission]:
    return [option.scope for option in pat_api.list_selectable_scopes(MagicMock())]


@pytest.mark.parametrize("tier", [Tier.BUSINESS, Tier.ENTERPRISE])
def test_gateway_scope_listed_and_mintable_on_business_plus(tier: Tier) -> None:
    with patch.object(pat_api, "_current_tier", return_value=tier):
        assert Permission.USE_LLM_GATEWAY in _listed_scopes()
        pat_api._validate_assignable_scopes([Permission.USE_LLM_GATEWAY])


def test_gateway_scope_hidden_and_rejected_on_community() -> None:
    with patch.object(pat_api, "_current_tier", return_value=Tier.COMMUNITY):
        scopes = _listed_scopes()
        assert Permission.USE_LLM_GATEWAY not in scopes
        assert Permission.READ_SEARCH in scopes
        with pytest.raises(OnyxError) as exc_info:
            pat_api._validate_assignable_scopes(
                [Permission.READ_SEARCH, Permission.USE_LLM_GATEWAY]
            )
        assert exc_info.value.error_code == OnyxErrorCode.FEATURE_NOT_AVAILABLE
        pat_api._validate_assignable_scopes([Permission.READ_SEARCH])
        pat_api._validate_assignable_scopes(None)


def test_current_tier_is_community_without_ee() -> None:
    with patch.object(pat_api.global_version, "is_ee_version", return_value=False):
        assert pat_api._current_tier() is Tier.COMMUNITY
