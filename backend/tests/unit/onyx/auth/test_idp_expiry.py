from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from onyx.auth import idp_expiry
from onyx.auth.idp_expiry import (
    account_tracks_external_idp_expiry,
    tracks_external_idp_expiry,
    user_tracks_external_idp_expiry,
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


def test_user_without_linked_account_follows_global(
    global_setting: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        idp_expiry, "fetch_sso_providers_by_names", lambda _db, _names: []
    )
    global_setting.track_external_idp_expiry = False
    assert user_tracks_external_idp_expiry(MagicMock(), _user()) is False


def test_user_follows_any_linked_provider(
    global_setting: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    global_setting.track_external_idp_expiry = False
    rows = [
        _provider("google", {"client_id": "cid"}),
        _provider("okta", {"track_external_idp_expiry": True}),
    ]
    monkeypatch.setattr(
        idp_expiry,
        "fetch_sso_providers_by_names",
        lambda _db, names: [row for row in rows if row.name in names],
    )
    assert user_tracks_external_idp_expiry(MagicMock(), _user("google", "okta"))
    assert not user_tracks_external_idp_expiry(MagicMock(), _user("google"))
    # A login with no provider row (legacy env config) follows the global setting.
    assert not user_tracks_external_idp_expiry(MagicMock(), _user("openid"))


@pytest.mark.usefixtures("global_setting")
def test_unreadable_config_follows_global(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = MagicMock()
    provider.name = "okta"
    provider.config.get_value.side_effect = RuntimeError("wrong encryption key")
    monkeypatch.setattr(
        idp_expiry, "fetch_sso_providers_by_names", lambda _db, _names: [provider]
    )
    assert user_tracks_external_idp_expiry(MagicMock(), _user("okta")) is True


@pytest.mark.asyncio
async def test_account_lookup_by_provider_name(
    global_setting: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    global_setting.track_external_idp_expiry = True
    row = _provider("okta", {"track_external_idp_expiry": False})
    monkeypatch.setattr(
        idp_expiry,
        "fetch_sso_providers_by_names_async",
        AsyncMock(return_value=[row]),
    )
    assert await account_tracks_external_idp_expiry(MagicMock(), "okta") is False
