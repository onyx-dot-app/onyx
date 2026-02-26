from unittest.mock import MagicMock
from uuid import UUID
from uuid import uuid4

from ee.onyx.server.scim.models import SCIM_USER_SCHEMA
from ee.onyx.server.scim.models import ScimEmail
from ee.onyx.server.scim.models import ScimGroupMember
from ee.onyx.server.scim.models import ScimGroupResource
from ee.onyx.server.scim.models import ScimMeta
from ee.onyx.server.scim.models import ScimName
from ee.onyx.server.scim.models import ScimUserGroupRef
from ee.onyx.server.scim.models import ScimUserResource
from ee.onyx.server.scim.providers.base import COMMON_IGNORED_PATCH_PATHS
from ee.onyx.server.scim.providers.base import get_default_provider
from ee.onyx.server.scim.providers.okta import OktaProvider


def _make_mock_user(
    user_id: UUID | None = None,
    email: str = "test@example.com",
    personal_name: str | None = "Test User",
    is_active: bool = True,
) -> MagicMock:
    user = MagicMock()
    user.id = user_id or uuid4()
    user.email = email
    user.personal_name = personal_name
    user.is_active = is_active
    return user


def _make_mock_group(group_id: int = 42, name: str = "Engineering") -> MagicMock:
    group = MagicMock()
    group.id = group_id
    group.name = name
    return group


class TestOktaProvider:
    def test_name(self) -> None:
        assert OktaProvider().name == "okta"

    def test_ignored_patch_paths(self) -> None:
        assert OktaProvider().ignored_patch_paths == COMMON_IGNORED_PATCH_PATHS

    def test_build_user_resource_basic(self) -> None:
        provider = OktaProvider()
        user = _make_mock_user()
        result = provider.build_user_resource(user, "ext-123")

        assert result == ScimUserResource(
            id=str(user.id),
            externalId="ext-123",
            userName="test@example.com",
            name=ScimName(givenName="Test", familyName="User", formatted="Test User"),
            displayName="Test User",
            emails=[ScimEmail(value="test@example.com", type="work", primary=True)],
            active=True,
            groups=[],
            meta=ScimMeta(resourceType="User"),
        )

    def test_build_user_resource_has_core_schema_only(self) -> None:
        provider = OktaProvider()
        user = _make_mock_user()
        result = provider.build_user_resource(user, "ext-123")
        assert result.schemas == [SCIM_USER_SCHEMA]

    def test_build_user_resource_with_groups(self) -> None:
        provider = OktaProvider()
        user = _make_mock_user()
        groups = [(1, "Engineering"), (2, "Design")]
        result = provider.build_user_resource(user, "ext-123", groups=groups)

        assert result.groups == [
            ScimUserGroupRef(value="1", display="Engineering"),
            ScimUserGroupRef(value="2", display="Design"),
        ]

    def test_build_user_resource_empty_groups(self) -> None:
        provider = OktaProvider()
        user = _make_mock_user()
        result = provider.build_user_resource(user, "ext-123", groups=[])

        assert result.groups == []

    def test_build_user_resource_no_groups(self) -> None:
        provider = OktaProvider()
        user = _make_mock_user()
        result = provider.build_user_resource(user, "ext-123")

        assert result.groups == []

    def test_build_user_resource_name_parsing(self) -> None:
        provider = OktaProvider()
        user = _make_mock_user(personal_name="Jane Doe")
        result = provider.build_user_resource(user, None)

        assert result.name == ScimName(
            givenName="Jane", familyName="Doe", formatted="Jane Doe"
        )

    def test_build_user_resource_single_name(self) -> None:
        provider = OktaProvider()
        user = _make_mock_user(personal_name="Madonna")
        result = provider.build_user_resource(user, None)

        assert result.name == ScimName(
            givenName="Madonna", familyName=None, formatted="Madonna"
        )

    def test_build_user_resource_no_name(self) -> None:
        provider = OktaProvider()
        user = _make_mock_user(personal_name=None)
        result = provider.build_user_resource(user, None)

        assert result.name is None
        assert result.displayName is None

    def test_build_user_resource_scim_username_preserves_case(self) -> None:
        """When scim_username is set, userName and emails use original case."""
        provider = OktaProvider()
        user = _make_mock_user(email="alice@example.com")
        result = provider.build_user_resource(
            user, "ext-1", scim_username="Alice@Example.com"
        )

        assert result.userName == "Alice@Example.com"
        assert result.emails[0].value == "Alice@Example.com"

    def test_build_user_resource_scim_username_none_falls_back(self) -> None:
        """When scim_username is None, userName falls back to user.email."""
        provider = OktaProvider()
        user = _make_mock_user(email="alice@example.com")
        result = provider.build_user_resource(user, "ext-1", scim_username=None)

        assert result.userName == "alice@example.com"
        assert result.emails[0].value == "alice@example.com"

    def test_build_group_resource(self) -> None:
        provider = OktaProvider()
        group = _make_mock_group()
        uid1, uid2 = uuid4(), uuid4()
        members: list[tuple[UUID, str | None]] = [
            (uid1, "alice@example.com"),
            (uid2, "bob@example.com"),
        ]

        result = provider.build_group_resource(group, members, "ext-g-1")

        assert result == ScimGroupResource(
            id="42",
            externalId="ext-g-1",
            displayName="Engineering",
            members=[
                ScimGroupMember(value=str(uid1), display="alice@example.com"),
                ScimGroupMember(value=str(uid2), display="bob@example.com"),
            ],
            meta=ScimMeta(resourceType="Group"),
        )

    def test_build_group_resource_empty_members(self) -> None:
        provider = OktaProvider()
        group = _make_mock_group()
        result = provider.build_group_resource(group, [])

        assert result.members == []


class TestGetDefaultProvider:
    def test_returns_okta(self) -> None:
        provider = get_default_provider()
        assert isinstance(provider, OktaProvider)
