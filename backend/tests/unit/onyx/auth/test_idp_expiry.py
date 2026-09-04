from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from onyx.auth import idp_expiry
from onyx.auth.idp_expiry import (
    linked_idp_expiry_switches,
    session_follows_idp_expiry,
    tracks_external_idp_expiry,
)
from onyx.utils.sensitive import make_mock_sensitive_value


@pytest.fixture
def global_setting(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    settings = MagicMock()
    settings.track_external_idp_expiry = True
    monkeypatch.setattr(idp_expiry, "get_security_settings", lambda: settings)
    return settings


def _provider(name: str, config: dict[str, Any]) -> MagicMock:
    provider = MagicMock()
    provider.name = name
    provider.config = make_mock_sensitive_value(config)
    return provider


def _user(*oauth_names: str) -> MagicMock:
    user = MagicMock()
    user.oauth_accounts = []
    for oauth_name in oauth_names:
        account = MagicMock()
        account.oauth_name = oauth_name
        user.oauth_accounts.append(account)
    return user


def test_missing_config_follows_global(global_setting: MagicMock) -> None:
    assert tracks_external_idp_expiry(None) is True
    global_setting.track_external_idp_expiry = False
    assert tracks_external_idp_expiry(None) is False
    assert tracks_external_idp_expiry({"client_id": "cid"}) is False
    assert tracks_external_idp_expiry({"track_external_idp_expiry": None}) is False


def test_config_value_overrides_global(global_setting: MagicMock) -> None:
    assert tracks_external_idp_expiry({"track_external_idp_expiry": False}) is False
    global_setting.track_external_idp_expiry = False
    assert tracks_external_idp_expiry({"track_external_idp_expiry": True}) is True


@pytest.mark.asyncio
async def test_switches_per_linked_provider(
    global_setting: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    global_setting.track_external_idp_expiry = False
    rows = [
        _provider("google", {"client_id": "cid"}),
        _provider("okta", {"track_external_idp_expiry": True}),
    ]
    monkeypatch.setattr(
        idp_expiry, "fetch_sso_providers_by_names_async", AsyncMock(return_value=rows)
    )
    # "openid" has no row (legacy env login) and follows the global setting.
    switches = await linked_idp_expiry_switches(
        MagicMock(), _user("google", "okta", "openid")
    )
    assert switches == {"google": False, "okta": True, "openid": False}
    assert await linked_idp_expiry_switches(MagicMock(), _user()) == {}


@pytest.mark.asyncio
@pytest.mark.usefixtures("global_setting")
async def test_unreadable_config_follows_global(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = MagicMock()
    provider.name = "okta"
    provider.config.get_value.side_effect = RuntimeError("wrong encryption key")
    monkeypatch.setattr(
        idp_expiry,
        "fetch_sso_providers_by_names_async",
        AsyncMock(return_value=[provider]),
    )
    assert await linked_idp_expiry_switches(MagicMock(), _user("okta")) == {
        "okta": True
    }


def test_session_follows_any_switch_or_global(global_setting: MagicMock) -> None:
    assert session_follows_idp_expiry({"google": False, "okta": True}) is True
    assert session_follows_idp_expiry({"google": False}) is False
    assert session_follows_idp_expiry({}) is True
    global_setting.track_external_idp_expiry = False
    assert session_follows_idp_expiry({}) is False
