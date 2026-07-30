"""The invite-only check fails closed: a settings-read error is treated as
invite-only ON so a transient KV/DB failure can't silently admit uninvited
users."""

import pytest

import onyx.auth.users as users
from onyx.server.settings.models import Settings


def test_returns_setting_value_when_load_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        users,
        "load_settings",
        lambda raise_on_error=False: Settings(invite_only_enabled=False),  # noqa: ARG005
    )
    assert users.workspace_invite_only_enabled() is False


def test_fails_closed_when_load_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(raise_on_error: bool = False) -> Settings:  # noqa: ARG001
        raise RuntimeError("kv down")

    monkeypatch.setattr(users, "load_settings", _boom)
    assert users.workspace_invite_only_enabled() is True
