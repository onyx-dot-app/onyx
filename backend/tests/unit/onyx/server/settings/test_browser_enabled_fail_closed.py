"""The browser stays off when the settings cannot be read: `Settings()`
defaults `browser_enabled` to True."""

import pytest

from onyx.server.settings import store
from onyx.server.settings.models import Settings
from onyx.server.settings.store import load_browser_enabled


def test_off_when_settings_cannot_be_loaded(monkeypatch: pytest.MonkeyPatch) -> None:
    def load_settings(raise_on_error: bool = False) -> Settings:
        if raise_on_error:
            raise RuntimeError("kv down")
        return Settings()

    monkeypatch.setattr(store, "load_settings", load_settings)
    assert load_browser_enabled() is False


@pytest.mark.parametrize("stored", [True, False])
def test_follows_stored_setting(monkeypatch: pytest.MonkeyPatch, stored: bool) -> None:
    monkeypatch.setattr(
        store,
        "load_settings",
        lambda raise_on_error=False: Settings(browser_enabled=stored),  # noqa: ARG005
    )
    assert load_browser_enabled() is stored
