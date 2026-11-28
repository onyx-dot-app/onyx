"""`/settings` reports the deployment flags the server was started with."""

from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest

from onyx.configs.constants import ANONYMOUS_USER_UUID
from onyx.db.models import User
from onyx.key_value_store.interface import KvKeyNotFoundError
from onyx.server import playground as playground_module
from onyx.server.playground import PlaygroundRestrictedFeature
from onyx.server.settings import api as settings_api
from onyx.server.settings.models import Settings, UserSettings


def _fetch_settings(
    monkeypatch: pytest.MonkeyPatch, user: User | None = None
) -> UserSettings:
    """Call the endpoint (by default with no user), with no store behind it."""
    kv_store = MagicMock()
    kv_store.load.side_effect = KvKeyNotFoundError()
    monkeypatch.setattr(settings_api, "get_kv_store", lambda: kv_store)
    monkeypatch.setattr(
        settings_api,
        "load_settings",
        lambda raise_on_error=False: Settings(),  # noqa: ARG005
    )
    monkeypatch.setattr(
        settings_api,
        "get_settings_notifications",
        lambda *_a: [],  # noqa: ARG005
    )
    monkeypatch.setattr(
        settings_api,
        "fetch_versioned_implementation_with_fallback",
        lambda _module, _name, fallback: fallback,
    )
    monkeypatch.setattr(settings_api.global_version, "is_ee_version", lambda: False)
    monkeypatch.setattr(
        settings_api, "is_craft_available_for_deployment", lambda _user: False
    )
    caller: Any = user
    return settings_api.fetch_settings(user=caller, db_session=MagicMock())


@pytest.mark.parametrize("playground", [False, True])
def test_is_playground_follows_the_flag(
    playground: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings_api, "IS_PLAYGROUND", playground)
    assert _fetch_settings(monkeypatch).is_playground is playground


@pytest.mark.parametrize("playground", [False, True])
def test_restricted_features_are_listed_only_on_the_playground(
    playground: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(playground_module, "IS_PLAYGROUND", playground)
    listed = _fetch_settings(monkeypatch).playground_restrictions
    if playground:
        assert PlaygroundRestrictedFeature.LLM_PROVIDERS in listed
        assert PlaygroundRestrictedFeature.LLM_GATEWAY in listed
    else:
        assert listed == []


def test_the_browser_is_available_to_signed_in_users_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings_api, "HARNESS_SANDBOX_ENABLED", True)
    signed_in = User(id=uuid4(), email="user@example.com")
    anonymous = User(id=UUID(ANONYMOUS_USER_UUID), email="anonymous@example.com")

    assert _fetch_settings(monkeypatch, signed_in).chat_browser_available
    # The browser routes refuse the anonymous user.
    assert not _fetch_settings(monkeypatch, anonymous).chat_browser_available
    assert not _fetch_settings(monkeypatch).chat_browser_available
