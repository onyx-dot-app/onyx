import datetime
from unittest.mock import MagicMock
from uuid import uuid4

from onyx.db.enums import AccountType
from onyx.server.models import FullUserSnapshot
from onyx.server.models import UserGroupInfo


def _mock_user(
    personal_name: str | None = "Test User",
    created_at: datetime.datetime | None = None,
    updated_at: datetime.datetime | None = None,
) -> MagicMock:
    user = MagicMock()
    user.id = uuid4()
    user.email = "test@example.com"
    user.is_active = True
    user.password_configured = True
    user.personal_name = personal_name
    user.created_at = created_at or datetime.datetime(
        2025, 1, 1, tzinfo=datetime.timezone.utc
    )
    user.updated_at = updated_at or datetime.datetime(
        2025, 6, 15, tzinfo=datetime.timezone.utc
    )
    user.account_type = AccountType.STANDARD
    return user


def test_from_user_model_includes_new_fields() -> None:
    user = _mock_user(personal_name="Alice")
    groups = [UserGroupInfo(id=1, name="Engineering")]

    snapshot = FullUserSnapshot.from_user_model(user, groups=groups)

    assert snapshot.personal_name == "Alice"
    assert snapshot.created_at == user.created_at
    assert snapshot.updated_at == user.updated_at
    assert snapshot.groups == groups


def test_from_user_model_defaults_groups_to_empty() -> None:
    user = _mock_user()
    snapshot = FullUserSnapshot.from_user_model(user)

    assert snapshot.groups == []


def test_from_user_model_personal_name_none() -> None:
    user = _mock_user(personal_name=None)
    snapshot = FullUserSnapshot.from_user_model(user)

    assert snapshot.personal_name is None


def test_from_user_model_is_admin() -> None:
    user = _mock_user()
    snapshot = FullUserSnapshot.from_user_model(user, is_admin=True)

    assert snapshot.is_admin is True
    assert snapshot.account_type == AccountType.STANDARD


def test_from_user_model_defaults_is_admin_to_false() -> None:
    user = _mock_user()
    snapshot = FullUserSnapshot.from_user_model(user)

    assert snapshot.is_admin is False
