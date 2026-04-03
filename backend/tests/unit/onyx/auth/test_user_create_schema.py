"""
Unit tests for UserCreate schema dict methods.

Verifies that account_type is always included in create_update_dict
and create_update_dict_superuser.
"""

from onyx.auth.schemas import UserCreate
from onyx.db.enums import AccountType


def test_create_update_dict_includes_default_account_type() -> None:
    uc = UserCreate(email="a@b.com", password="secret123")
    d = uc.create_update_dict()
    assert d["account_type"] == AccountType.STANDARD


def test_create_update_dict_includes_explicit_account_type() -> None:
    uc = UserCreate(
        email="a@b.com", password="secret123", account_type=AccountType.SERVICE_ACCOUNT
    )
    d = uc.create_update_dict()
    assert d["account_type"] == AccountType.STANDARD


def test_create_update_dict_superuser_includes_account_type() -> None:
    uc = UserCreate(email="a@b.com", password="secret123")
    d = uc.create_update_dict_superuser()
    assert d["account_type"] == AccountType.STANDARD
