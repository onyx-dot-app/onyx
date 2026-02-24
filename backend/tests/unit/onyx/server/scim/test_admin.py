"""Tests for SCIM admin token management endpoints."""

from datetime import datetime
from unittest.mock import MagicMock
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from ee.onyx.db.scim import ScimDAL
from ee.onyx.server.enterprise_settings.api import create_scim_token
from ee.onyx.server.enterprise_settings.api import get_active_scim_token
from ee.onyx.server.scim.models import ScimTokenCreate
from onyx.db.models import ScimToken
from onyx.db.models import User


@pytest.fixture
def mock_db_session() -> MagicMock:
    return MagicMock(spec=Session)


@pytest.fixture
def scim_dal(mock_db_session: MagicMock) -> ScimDAL:
    return ScimDAL(mock_db_session)


@pytest.fixture
def admin_user() -> User:
    user = User(id=uuid4(), email="admin@test.com")
    user.is_active = True
    return user


def _make_token(token_id: int, name: str, *, is_active: bool = True) -> ScimToken:
    return ScimToken(
        id=token_id,
        name=name,
        hashed_token="h" * 64,
        token_display="onyx_scim_****abcd",
        is_active=is_active,
        created_by_id=uuid4(),
        created_at=datetime(2026, 1, 1),
        last_used_at=None,
    )


class TestGetActiveToken:
    def test_returns_token_metadata(self, scim_dal: ScimDAL, admin_user: User) -> None:
        token = _make_token(1, "prod-token")
        scim_dal._session.scalar.return_value = token  # type: ignore[attr-defined]

        result = get_active_scim_token(_=admin_user, dal=scim_dal)

        assert result.id == 1
        assert result.name == "prod-token"
        assert result.is_active is True

    def test_raises_404_when_no_active_token(
        self, scim_dal: ScimDAL, admin_user: User
    ) -> None:
        scim_dal._session.scalar.return_value = None  # type: ignore[attr-defined]

        with pytest.raises(HTTPException) as exc_info:
            get_active_scim_token(_=admin_user, dal=scim_dal)

        assert exc_info.value.status_code == 404


class TestCreateToken:
    @patch("ee.onyx.server.enterprise_settings.api.generate_scim_token")
    def test_creates_token_and_revokes_previous(
        self,
        mock_generate: MagicMock,
        scim_dal: ScimDAL,
        admin_user: User,
    ) -> None:
        mock_generate.return_value = ("raw_token_val", "hashed_val", "****abcd")

        # Simulate one existing active token that should get revoked
        existing = _make_token(1, "old-token", is_active=True)
        scim_dal._session.scalars.return_value.all.return_value = [existing]  # type: ignore[attr-defined]

        # Simulate DB defaults that would be set on INSERT/flush
        def fake_add(obj: ScimToken) -> None:
            obj.id = 2
            obj.is_active = True
            obj.created_at = datetime(2026, 2, 1)

        scim_dal._session.add.side_effect = fake_add  # type: ignore[attr-defined]

        body = ScimTokenCreate(name="new-token")
        result = create_scim_token(body=body, user=admin_user, dal=scim_dal)

        # Previous token was revoked (by create_token's internal revocation)
        assert existing.is_active is False

        # New token returned with raw value
        assert result.raw_token == "raw_token_val"
        assert result.name == "new-token"
        assert result.is_active is True

        # Session was committed
        scim_dal._session.commit.assert_called_once()  # type: ignore[attr-defined]

    @patch("ee.onyx.server.enterprise_settings.api.generate_scim_token")
    def test_creates_first_token_when_none_exist(
        self,
        mock_generate: MagicMock,
        scim_dal: ScimDAL,
        admin_user: User,
    ) -> None:
        mock_generate.return_value = ("raw_token_val", "hashed_val", "****abcd")

        # No existing tokens
        scim_dal._session.scalars.return_value.all.return_value = []  # type: ignore[attr-defined]

        def fake_add(obj: ScimToken) -> None:
            obj.id = 1
            obj.is_active = True
            obj.created_at = datetime(2026, 2, 1)

        scim_dal._session.add.side_effect = fake_add  # type: ignore[attr-defined]

        body = ScimTokenCreate(name="first-token")
        result = create_scim_token(body=body, user=admin_user, dal=scim_dal)

        assert result.raw_token == "raw_token_val"
        assert result.name == "first-token"
        assert result.is_active is True
