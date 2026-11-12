"""`/settings` reports the deployment flags the server was started with."""

from typing import Any
from unittest.mock import MagicMock

import pytest

from onyx.key_value_store.interface import KvKeyNotFoundError
from onyx.server.settings import api as settings_api
from onyx.server.settings.models import Settings, UserSettings


def _fetch_settings(monkeypatch: pytest.MonkeyPatch) -> UserSettings:
    """Call the endpoint as an anonymous visitor, with no store behind it."""
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
    user: Any = None
    return settings_api.fetch_settings(user=user, db_session=MagicMock())


@pytest.mark.parametrize("playground", [False, True])
def test_is_playground_follows_the_flag(
    playground: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings_api, "IS_PLAYGROUND", playground)
    assert _fetch_settings(monkeypatch).is_playground is playground
