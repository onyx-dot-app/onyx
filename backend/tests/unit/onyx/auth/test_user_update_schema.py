"""
Unit tests for UserUpdate schema dict methods.

PATCH /users/me builds its update from create_update_dict, so that path must not
carry email or password. The is_superuser-gated admin route uses
create_update_dict_superuser, which keeps both on purpose.
"""

from typing import Any

from onyx.auth.schemas import UserUpdate


def test_create_update_dict_drops_email_and_password() -> None:
    uu: UserUpdate = UserUpdate(email="attacker@evil.com", password="newpassword123")
    d: dict[str, Any] = uu.create_update_dict()
    assert "email" not in d
    assert "password" not in d


def test_create_update_dict_superuser_retains_email_and_password() -> None:
    """Deliberate carve-out: an admin may set both for another user."""
    uu: UserUpdate = UserUpdate(email="new@b.com", password="newpassword123")
    d: dict[str, Any] = uu.create_update_dict_superuser()
    assert d["email"] == "new@b.com"
    assert d["password"] == "newpassword123"
