"""Shared fixtures for SCIM endpoint unit tests."""

from __future__ import annotations

import json
from collections.abc import Generator
from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ee.onyx.server.scim.api import ScimJSONResponse
from ee.onyx.server.scim.models import ScimGroupResource
from ee.onyx.server.scim.models import ScimListResponse
from ee.onyx.server.scim.models import ScimName
from ee.onyx.server.scim.models import ScimUserResource
from ee.onyx.server.scim.providers.base import ScimProvider
from ee.onyx.server.scim.providers.okta import OktaProvider
from onyx.db.models import ScimToken
from onyx.db.models import ScimUserMapping
from onyx.db.models import User
from onyx.db.models import UserGroup
from onyx.db.models import UserRole


@pytest.fixture
def mock_db_session() -> MagicMock:
    """A MagicMock standing in for a SQLAlchemy Session."""
    return MagicMock(spec=Session)


@pytest.fixture
def mock_token() -> MagicMock:
    """A MagicMock standing in for a verified ScimToken."""
    token = MagicMock(spec=ScimToken)
    token.id = 1
    return token


@pytest.fixture
def provider() -> ScimProvider:
    """An OktaProvider instance for endpoint tests."""
    return OktaProvider()


@pytest.fixture
def mock_dal() -> Generator[MagicMock, None, None]:
    """Patch ScimDAL construction in api module and yield the mock instance."""
    with patch("ee.onyx.server.scim.api.ScimDAL") as cls:
        dal = cls.return_value
        # User defaults
        dal.get_user.return_value = None
        dal.get_user_by_email.return_value = None
        dal.get_user_mapping_by_user_id.return_value = None
        dal.get_user_mapping_by_external_id.return_value = None
        dal.list_users.return_value = ([], 0)
        # Group defaults
        dal.get_group.return_value = None
        dal.get_group_by_name.return_value = None
        dal.get_group_mapping_by_group_id.return_value = None
        dal.get_group_mapping_by_external_id.return_value = None
        dal.get_group_members.return_value = []
        dal.list_groups.return_value = ([], 0)
        # User-group relationship defaults
        dal.get_user_groups.return_value = []
        dal.get_users_groups_batch.return_value = {}
        yield dal


def make_scim_user(**kwargs: Any) -> ScimUserResource:
    """Build a ScimUserResource with sensible defaults."""
    defaults: dict[str, Any] = {
        "userName": "test@example.com",
        "externalId": "ext-default",
        "active": True,
        "name": ScimName(givenName="Test", familyName="User"),
    }
    defaults.update(kwargs)
    return ScimUserResource(**defaults)


def make_scim_group(**kwargs: Any) -> ScimGroupResource:
    """Build a ScimGroupResource with sensible defaults."""
    defaults: dict[str, Any] = {"displayName": "Engineering"}
    defaults.update(kwargs)
    return ScimGroupResource(**defaults)


def make_db_user(**kwargs: Any) -> MagicMock:
    """Build a mock User ORM object with configurable attributes."""
    user = MagicMock(spec=User)
    user.id = kwargs.get("id", uuid4())
    user.email = kwargs.get("email", "test@example.com")
    user.is_active = kwargs.get("is_active", True)
    user.personal_name = kwargs.get("personal_name", "Test User")
    user.role = kwargs.get("role", UserRole.BASIC)
    return user


def make_db_group(**kwargs: Any) -> MagicMock:
    """Build a mock UserGroup ORM object with configurable attributes."""
    group = MagicMock(spec=UserGroup)
    group.id = kwargs.get("id", 1)
    group.name = kwargs.get("name", "Engineering")
    group.is_up_for_deletion = kwargs.get("is_up_for_deletion", False)
    group.is_up_to_date = kwargs.get("is_up_to_date", True)
    return group


def make_user_mapping(**kwargs: Any) -> MagicMock:
    """Build a mock ScimUserMapping ORM object with configurable attributes."""
    mapping = MagicMock(spec=ScimUserMapping)
    mapping.id = kwargs.get("id", 1)
    mapping.external_id = kwargs.get("external_id", "ext-default")
    mapping.user_id = kwargs.get("user_id", uuid4())
    mapping.scim_username = kwargs.get("scim_username", None)
    mapping.department = kwargs.get("department", None)
    mapping.manager = kwargs.get("manager", None)
    mapping.given_name = kwargs.get("given_name", None)
    mapping.family_name = kwargs.get("family_name", None)
    mapping.scim_emails_json = kwargs.get("scim_emails_json", None)
    return mapping


def assert_scim_error(result: object, expected_status: int) -> None:
    """Assert *result* is a JSONResponse with the given status code."""
    assert isinstance(result, JSONResponse)
    assert result.status_code == expected_status


# ---------------------------------------------------------------------------
# Response parsing helpers
# ---------------------------------------------------------------------------


def parse_scim_user(result: object, *, status: int = 200) -> ScimUserResource:
    """Assert *result* is a ScimJSONResponse and parse as ScimUserResource."""
    assert isinstance(
        result, ScimJSONResponse
    ), f"Expected ScimJSONResponse, got {type(result).__name__}"
    assert result.status_code == status
    return ScimUserResource.model_validate(json.loads(result.body))


def parse_scim_group(result: object, *, status: int = 200) -> ScimGroupResource:
    """Assert *result* is a ScimJSONResponse and parse as ScimGroupResource."""
    assert isinstance(
        result, ScimJSONResponse
    ), f"Expected ScimJSONResponse, got {type(result).__name__}"
    assert result.status_code == status
    return ScimGroupResource.model_validate(json.loads(result.body))


def parse_scim_list(result: object) -> ScimListResponse:
    """Assert *result* is a ScimJSONResponse and parse as ScimListResponse."""
    assert isinstance(
        result, ScimJSONResponse
    ), f"Expected ScimJSONResponse, got {type(result).__name__}"
    assert result.status_code == 200
    return ScimListResponse.model_validate(json.loads(result.body))
