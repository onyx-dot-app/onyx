"""Invite-only gating: when the toggle is on, the invite list governs every
signup regardless of login method, and a permission-sync placeholder never
counts as an existing member."""

from contextlib import contextmanager
from typing import Any, Iterator
from unittest.mock import MagicMock

import pytest

import onyx.auth.users as users
from onyx.auth.users import verify_email_in_whitelist, verify_email_is_invited
from onyx.db.enums import AccountType
from onyx.error_handling.exceptions import OnyxError


def test_verify_email_is_invited_enforced_for_uninvited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(users, "workspace_invite_only_enabled", lambda: True)
    monkeypatch.setattr(
        users,
        "get_invited_users",
        lambda: ["allowed@example.com"],
        raising=False,
    )

    with pytest.raises(OnyxError) as exc:
        verify_email_is_invited("newuser@example.com")
    assert exc.value.status_code == 403


def test_verify_email_is_invited_skipped_when_invite_only_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(users, "workspace_invite_only_enabled", lambda: False)
    monkeypatch.setattr(
        users,
        "get_invited_users",
        lambda: ["allowed@example.com"],
        raising=False,
    )

    verify_email_is_invited("newuser@example.com")


@contextmanager
def _fake_session() -> Iterator[MagicMock]:
    yield MagicMock()


def _patch_whitelist_deps(monkeypatch: pytest.MonkeyPatch, existing_user: Any) -> None:
    monkeypatch.setattr(
        users,
        "get_session_with_tenant",
        lambda tenant_id: _fake_session(),  # noqa: ARG005
    )
    monkeypatch.setattr(
        users,
        "get_user_by_email",
        lambda email, db: existing_user,  # noqa: ARG005
    )
    monkeypatch.setattr(users, "workspace_invite_only_enabled", lambda: True)
    monkeypatch.setattr(
        users,
        "get_invited_users",
        lambda: ["allowed@example.com"],
        raising=False,
    )


def test_whitelist_treats_placeholder_as_not_a_member(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A permission-sync EXT_PERM_USER row must not satisfy invite-only:
    ACL visibility is not membership."""
    placeholder = MagicMock()
    placeholder.account_type = AccountType.EXT_PERM_USER
    _patch_whitelist_deps(monkeypatch, placeholder)

    with pytest.raises(OnyxError):
        verify_email_in_whitelist("newuser@example.com", "public")


def test_whitelist_skips_check_for_real_member(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An account that has actually joined is never re-gated on login."""
    member = MagicMock()
    member.account_type = AccountType.STANDARD
    _patch_whitelist_deps(monkeypatch, member)

    verify_email_in_whitelist("member@example.com", "public")


def test_whitelist_enforces_for_unknown_email(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_whitelist_deps(monkeypatch, None)

    with pytest.raises(OnyxError):
        verify_email_in_whitelist("newuser@example.com", "public")
