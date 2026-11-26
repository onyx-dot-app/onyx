"""The browser stays off when the settings cannot be read: `Settings()`
defaults `browser_enabled` to True."""

from unittest.mock import MagicMock, patch

import pytest

from onyx.server.settings.store import load_browser_enabled

_STORE = "onyx.server.settings.store"


def test_off_when_settings_cannot_be_loaded() -> None:
    kv_store = MagicMock()
    kv_store.load.side_effect = RuntimeError("kv down")
    with patch(f"{_STORE}.get_kv_store", return_value=kv_store):
        assert load_browser_enabled() is False


@pytest.mark.parametrize("stored", [True, False])
def test_follows_stored_setting(stored: bool) -> None:
    kv_store = MagicMock()
    kv_store.load.return_value = {"browser_enabled": stored}
    cache = MagicMock()
    cache.get.return_value = None
    with (
        patch(f"{_STORE}.get_kv_store", return_value=kv_store),
        patch(f"{_STORE}.get_cache_backend", return_value=cache),
    ):
        assert load_browser_enabled() is stored
