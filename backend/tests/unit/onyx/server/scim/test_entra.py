"""Comprehensive Entra ID (Azure AD) SCIM compatibility tests.

Covers the full Entra provisioning lifecycle: service discovery, user CRUD
with enterprise extension schema, group CRUD with excludedAttributes, and
all Entra-specific behavioral quirks (PascalCase ops, enterprise URN in
PATCH value dicts).
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi import Response

from ee.onyx.server.scim.api import create_user
from ee.onyx.server.scim.api import delete_user
from ee.onyx.server.scim.api import get_group
from ee.onyx.server.scim.api import get_resource_types
from ee.onyx.server.scim.api import get_schemas
from ee.onyx.server.scim.api import get_service_provider_config
from ee.onyx.server.scim.api import get_user
from ee.onyx.server.scim.api import list_groups
from ee.onyx.server.scim.api import list_users
from ee.onyx.server.scim.api import patch_group
from ee.onyx.server.scim.api import patch_user
from ee.onyx.server.scim.api import replace_user
from ee.onyx.server.scim.api import ScimJSONResponse
from ee.onyx.server.scim.models import SCIM_ENTERPRISE_USER_SCHEMA
from ee.onyx.server.scim.models import SCIM_USER_SCHEMA
from ee.onyx.server.scim.models import ScimEnterpriseExtension
from ee.onyx.server.scim.models import ScimGroupMember
from ee.onyx.server.scim.models import ScimGroupResource
from ee.onyx.server.scim.models import ScimManagerRef
from ee.onyx.server.scim.models import ScimMappingFields
from ee.onyx.server.scim.models import ScimName
from ee.onyx.server.scim.models import ScimPatchOperation
from ee.onyx.server.scim.models import ScimPatchOperationType
from ee.onyx.server.scim.models import ScimPatchRequest
from ee.onyx.server.scim.models import ScimPatchResourceValue
from ee.onyx.server.scim.models import ScimUserResource
from ee.onyx.server.scim.providers.base import ScimProvider
from ee.onyx.server.scim.providers.entra import EntraProvider
from tests.unit.onyx.server.scim.conftest import make_db_group
from tests.unit.onyx.server.scim.conftest import make_db_user
from tests.unit.onyx.server.scim.conftest import make_scim_user
from tests.unit.onyx.server.scim.conftest import make_user_mapping
from tests.unit.onyx.server.scim.conftest import parse_scim_group
from tests.unit.onyx.server.scim.conftest import parse_scim_list
from tests.unit.onyx.server.scim.conftest import parse_scim_user


@pytest.fixture
def entra_provider() -> ScimProvider:
    """An EntraProvider instance for Entra-specific endpoint tests."""
    return EntraProvider()


# ---------------------------------------------------------------------------
# Service Discovery
# ---------------------------------------------------------------------------


class TestEntraServiceDiscovery:
    """Entra expects enterprise extension in discovery endpoints."""

    def test_service_provider_config_advertises_patch(self) -> None:
        config = get_service_provider_config()
        assert config.patch.supported is True

    def test_resource_types_include_enterprise_extension(self) -> None:
        result = get_resource_types()
        assert isinstance(result, ScimJSONResponse)
        parsed = json.loads(result.body)
        assert "Resources" in parsed
        user_type = next(rt for rt in parsed["Resources"] if rt["id"] == "User")
        extension_schemas = [ext["schema"] for ext in user_type["schemaExtensions"]]
        assert SCIM_ENTERPRISE_USER_SCHEMA in extension_schemas

    def test_schemas_include_enterprise_user(self) -> None:
        result = get_schemas()
        assert isinstance(result, ScimJSONResponse)
        parsed = json.loads(result.body)
        schema_ids = [s["id"] for s in parsed["Resources"]]
        assert SCIM_ENTERPRISE_USER_SCHEMA in schema_ids

    def test_enterprise_schema_has_expected_attributes(self) -> None:
        result = get_schemas()
        assert isinstance(result, ScimJSONResponse)
        parsed = json.loads(result.body)
        enterprise = next(
            s for s in parsed["Resources"] if s["id"] == SCIM_ENTERPRISE_USER_SCHEMA
        )
        attr_names = {a["name"] for a in enterprise["attributes"]}
        assert "department" in attr_names
        assert "manager" in attr_names

    def test_service_discovery_content_type(self) -> None:
        """SCIM responses must use application/scim+json content type."""
        result = get_resource_types()
        assert isinstance(result, ScimJSONResponse)
        assert result.media_type == "application/scim+json"


# ---------------------------------------------------------------------------
# User Lifecycle (Entra-specific)
# ---------------------------------------------------------------------------


class TestEntraUserLifecycle:
    """Test user CRUD through Entra's lens: enterprise schemas, PascalCase ops."""

    @patch("ee.onyx.server.scim.api._check_seat_availability", return_value=None)
    def test_create_user_includes_enterprise_schema(
        self,
        mock_seats: MagicMock,  # noqa: ARG002
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
        entra_provider: ScimProvider,
    ) -> None:
        mock_dal.get_user_by_email.return_value = None
        resource = make_scim_user(userName="alice@contoso.com")

        result = create_user(
            user_resource=resource,
            _token=mock_token,
            provider=entra_provider,
            db_session=mock_db_session,
        )

        resource = parse_scim_user(result, status=201)
        assert SCIM_ENTERPRISE_USER_SCHEMA in resource.schemas
        assert SCIM_USER_SCHEMA in resource.schemas

    @patch("ee.onyx.server.scim.api._check_seat_availability", return_value=None)
    def test_create_user_with_enterprise_extension(
        self,
        mock_seats: MagicMock,  # noqa: ARG002
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
        entra_provider: ScimProvider,
    ) -> None:
        """Enterprise extension department/manager should round-trip on create."""
        mock_dal.get_user_by_email.return_value = None
        resource = make_scim_user(
            userName="alice@contoso.com",
            enterprise_extension=ScimEnterpriseExtension(
                department="Engineering",
                manager=ScimManagerRef(value="mgr-uuid-123"),
            ),
        )

        result = create_user(
            user_resource=resource,
            _token=mock_token,
            provider=entra_provider,
            db_session=mock_db_session,
        )

        resource = parse_scim_user(result, status=201)
        assert resource.enterprise_extension is not None
        assert resource.enterprise_extension.department == "Engineering"
        assert resource.enterprise_extension.manager is not None
        assert resource.enterprise_extension.manager.value == "mgr-uuid-123"

        # Verify DAL received the enterprise fields
        mock_dal.create_user_mapping.assert_called_once()
        call_kwargs = mock_dal.create_user_mapping.call_args[1]
        assert call_kwargs["fields"] == ScimMappingFields(
            department="Engineering",
            manager="mgr-uuid-123",
            given_name="Test",
            family_name="User",
        )

    def test_get_user_includes_enterprise_schema(
        self,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
        entra_provider: ScimProvider,
    ) -> None:
        user = make_db_user(email="alice@contoso.com")
        mock_dal.get_user.return_value = user

        result = get_user(
            user_id=str(user.id),
            _token=mock_token,
            provider=entra_provider,
            db_session=mock_db_session,
        )

        resource = parse_scim_user(result)
        assert SCIM_ENTERPRISE_USER_SCHEMA in resource.schemas

    def test_get_user_returns_enterprise_extension_data(
        self,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
        entra_provider: ScimProvider,
    ) -> None:
        """GET should return stored enterprise extension data."""
        user = make_db_user(email="alice@contoso.com")
        mock_dal.get_user.return_value = user
        mapping = make_user_mapping(user_id=user.id)
        mapping.department = "Sales"
        mapping.manager = "mgr-456"
        mock_dal.get_user_mapping_by_user_id.return_value = mapping

        result = get_user(
            user_id=str(user.id),
            _token=mock_token,
            provider=entra_provider,
            db_session=mock_db_session,
        )

        resource = parse_scim_user(result)
        assert resource.enterprise_extension is not None
        assert resource.enterprise_extension.department == "Sales"
        assert resource.enterprise_extension.manager is not None
        assert resource.enterprise_extension.manager.value == "mgr-456"

    def test_list_users_includes_enterprise_schema(
        self,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
        entra_provider: ScimProvider,
    ) -> None:
        user = make_db_user(email="alice@contoso.com")
        mapping = make_user_mapping(external_id="entra-ext-1", user_id=user.id)
        mock_dal.list_users.return_value = ([(user, mapping)], 1)

        result = list_users(
            filter=None,
            startIndex=1,
            count=100,
            _token=mock_token,
            provider=entra_provider,
            db_session=mock_db_session,
        )

        parsed = parse_scim_list(result)
        resource = parsed.Resources[0]
        assert isinstance(resource, ScimUserResource)
        assert SCIM_ENTERPRISE_USER_SCHEMA in resource.schemas

    def test_patch_user_deactivate_with_pascal_case_replace(
        self,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
        entra_provider: ScimProvider,
    ) -> None:
        """Entra sends ``"Replace"`` (PascalCase) instead of ``"replace"``."""
        user = make_db_user(is_active=True)
        mock_dal.get_user.return_value = user
        patch_req = ScimPatchRequest(
            Operations=[
                ScimPatchOperation(
                    op="Replace",  # type: ignore[arg-type]
                    path="active",
                    value=False,
                )
            ]
        )

        result = patch_user(
            user_id=str(user.id),
            patch_request=patch_req,
            _token=mock_token,
            provider=entra_provider,
            db_session=mock_db_session,
        )

        parse_scim_user(result)
        # Mock doesn't propagate the change, so verify via the DAL call
        mock_dal.update_user.assert_called_once()
        call_kwargs = mock_dal.update_user.call_args
        assert call_kwargs[1]["is_active"] is False

    def test_patch_user_add_external_id_with_pascal_case(
        self,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
        entra_provider: ScimProvider,
    ) -> None:
        """Entra sends ``"Add"`` (PascalCase) instead of ``"add"``."""
        user = make_db_user()
        mock_dal.get_user.return_value = user
        patch_req = ScimPatchRequest(
            Operations=[
                ScimPatchOperation(
                    op="Add",  # type: ignore[arg-type]
                    path="externalId",
                    value="entra-ext-999",
                )
            ]
        )

        result = patch_user(
            user_id=str(user.id),
            patch_request=patch_req,
            _token=mock_token,
            provider=entra_provider,
            db_session=mock_db_session,
        )

        parse_scim_user(result)
        # Verify the patched externalId was synced to the DAL
        mock_dal.sync_user_external_id.assert_called_once()
        call_args = mock_dal.sync_user_external_id.call_args
        assert call_args[0][1] == "entra-ext-999"

    def test_patch_user_enterprise_extension_in_value_dict(
        self,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
        entra_provider: ScimProvider,
    ) -> None:
        """Entra sends enterprise extension URN as key in path-less PATCH value
        dicts — enterprise data should be stored, not ignored."""
        user = make_db_user()
        mock_dal.get_user.return_value = user

        value = ScimPatchResourceValue(active=False)
        assert value.__pydantic_extra__ is not None
        value.__pydantic_extra__[
            "urn:ietf:params:scim:schemas:extension:enterprise:2.0:User"
        ] = {"department": "Engineering"}

        patch_req = ScimPatchRequest(
            Operations=[
                ScimPatchOperation(
                    op=ScimPatchOperationType.REPLACE,
                    path=None,
                    value=value,
                )
            ]
        )

        result = patch_user(
            user_id=str(user.id),
            patch_request=patch_req,
            _token=mock_token,
            provider=entra_provider,
            db_session=mock_db_session,
        )

        parse_scim_user(result)
        # Verify active=False was applied
        mock_dal.update_user.assert_called_once()
        call_kwargs = mock_dal.update_user.call_args
        assert call_kwargs[1]["is_active"] is False
        # Verify enterprise data was passed to DAL
        mock_dal.sync_user_external_id.assert_called_once()
        sync_kwargs = mock_dal.sync_user_external_id.call_args[1]
        assert sync_kwargs["fields"] == ScimMappingFields(
            department="Engineering",
            given_name="Test",
            family_name="User",
            scim_emails_json='[{"value": "test@example.com", "type": "work", "primary": true}]',
        )

    def test_patch_user_remove_external_id(
        self,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
        entra_provider: ScimProvider,
    ) -> None:
        """PATCH remove op should clear the target field."""
        user = make_db_user()
        mock_dal.get_user.return_value = user
        mapping = make_user_mapping(user_id=user.id)
        mapping.external_id = "ext-to-remove"
        mock_dal.get_user_mapping_by_user_id.return_value = mapping

        patch_req = ScimPatchRequest(
            Operations=[
                ScimPatchOperation(
                    op=ScimPatchOperationType.REMOVE,
                    path="externalId",
                )
            ]
        )

        result = patch_user(
            user_id=str(user.id),
            patch_request=patch_req,
            _token=mock_token,
            provider=entra_provider,
            db_session=mock_db_session,
        )

        parse_scim_user(result)
        # externalId should be cleared (None)
        mock_dal.sync_user_external_id.assert_called_once()
        call_args = mock_dal.sync_user_external_id.call_args
        assert call_args[0][1] is None

    def test_patch_user_emails_primary_eq_true_value(
        self,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
        entra_provider: ScimProvider,
    ) -> None:
        """PATCH with path emails[primary eq true].value should update
        the primary email entry, not userName."""
        user = make_db_user(email="old@contoso.com")
        mock_dal.get_user.return_value = user

        patch_req = ScimPatchRequest(
            Operations=[
                ScimPatchOperation(
                    op=ScimPatchOperationType.REPLACE,
                    path="emails[primary eq true].value",
                    value="new@contoso.com",
                )
            ]
        )

        result = patch_user(
            user_id=str(user.id),
            patch_request=patch_req,
            _token=mock_token,
            provider=entra_provider,
            db_session=mock_db_session,
        )

        resource = parse_scim_user(result)
        # userName should remain unchanged — emails and userName are separate
        assert resource.userName == "old@contoso.com"
        # Primary email should be updated
        primary_emails = [e for e in resource.emails if e.primary]
        assert len(primary_emails) == 1
        assert primary_emails[0].value == "new@contoso.com"

    def test_patch_user_enterprise_urn_department_path(
        self,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
        entra_provider: ScimProvider,
    ) -> None:
        """PATCH with dotted enterprise URN path should store department."""
        user = make_db_user()
        mock_dal.get_user.return_value = user

        patch_req = ScimPatchRequest(
            Operations=[
                ScimPatchOperation(
                    op=ScimPatchOperationType.REPLACE,
                    path="urn:ietf:params:scim:schemas:extension:enterprise:2.0:User:department",
                    value="Marketing",
                )
            ]
        )

        result = patch_user(
            user_id=str(user.id),
            patch_request=patch_req,
            _token=mock_token,
            provider=entra_provider,
            db_session=mock_db_session,
        )

        parse_scim_user(result)
        mock_dal.sync_user_external_id.assert_called_once()
        sync_kwargs = mock_dal.sync_user_external_id.call_args[1]
        assert sync_kwargs["fields"] == ScimMappingFields(
            department="Marketing",
            given_name="Test",
            family_name="User",
            scim_emails_json='[{"value": "test@example.com", "type": "work", "primary": true}]',
        )

    def test_replace_user_includes_enterprise_schema(
        self,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
        entra_provider: ScimProvider,
    ) -> None:
        user = make_db_user(email="old@contoso.com")
        mock_dal.get_user.return_value = user
        resource = make_scim_user(
            userName="new@contoso.com",
            name=ScimName(givenName="New", familyName="Name"),
        )

        result = replace_user(
            user_id=str(user.id),
            user_resource=resource,
            _token=mock_token,
            provider=entra_provider,
            db_session=mock_db_session,
        )

        resource = parse_scim_user(result)
        assert SCIM_ENTERPRISE_USER_SCHEMA in resource.schemas

    def test_replace_user_with_enterprise_extension(
        self,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
        entra_provider: ScimProvider,
    ) -> None:
        """PUT with enterprise extension should store the fields."""
        user = make_db_user(email="alice@contoso.com")
        mock_dal.get_user.return_value = user
        resource = make_scim_user(
            userName="alice@contoso.com",
            enterprise_extension=ScimEnterpriseExtension(
                department="HR",
                manager=ScimManagerRef(value="boss-id"),
            ),
        )

        result = replace_user(
            user_id=str(user.id),
            user_resource=resource,
            _token=mock_token,
            provider=entra_provider,
            db_session=mock_db_session,
        )

        parse_scim_user(result)
        mock_dal.sync_user_external_id.assert_called_once()
        sync_kwargs = mock_dal.sync_user_external_id.call_args[1]
        assert sync_kwargs["fields"] == ScimMappingFields(
            department="HR",
            manager="boss-id",
            given_name="Test",
            family_name="User",
        )

    def test_delete_user_returns_204(
        self,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
    ) -> None:
        user = make_db_user()
        mock_dal.get_user.return_value = user
        mock_dal.get_user_mapping_by_user_id.return_value = MagicMock(id=1)

        result = delete_user(
            user_id=str(user.id),
            _token=mock_token,
            db_session=mock_db_session,
        )

        assert isinstance(result, Response)
        assert result.status_code == 204

    def test_double_delete_returns_404(
        self,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
    ) -> None:
        """Second DELETE should return 404 — the SCIM mapping is gone."""
        user = make_db_user()
        mock_dal.get_user.return_value = user
        # No mapping — user was already deleted from SCIM's perspective
        mock_dal.get_user_mapping_by_user_id.return_value = None

        result = delete_user(
            user_id=str(user.id),
            _token=mock_token,
            db_session=mock_db_session,
        )

        assert isinstance(result, ScimJSONResponse)
        assert result.status_code == 404

    def test_name_formatted_preserved_on_create(
        self,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
        entra_provider: ScimProvider,
    ) -> None:
        """When name.formatted is provided, it should be used as personal_name."""
        mock_dal.get_user_by_email.return_value = None
        resource = make_scim_user(
            userName="alice@contoso.com",
            name=ScimName(
                givenName="Alice",
                familyName="Smith",
                formatted="Dr. Alice Smith",
            ),
        )

        with patch(
            "ee.onyx.server.scim.api._check_seat_availability", return_value=None
        ):
            result = create_user(
                user_resource=resource,
                _token=mock_token,
                provider=entra_provider,
                db_session=mock_db_session,
            )

        parse_scim_user(result, status=201)
        # The User constructor should have received the formatted name
        mock_dal.add_user.assert_called_once()
        created_user = mock_dal.add_user.call_args[0][0]
        assert created_user.personal_name == "Dr. Alice Smith"


# ---------------------------------------------------------------------------
# Group Lifecycle (Entra-specific)
# ---------------------------------------------------------------------------


class TestEntraGroupLifecycle:
    """Test group CRUD with Entra-specific behaviors."""

    def test_get_group_standard_response(
        self,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
        entra_provider: ScimProvider,
    ) -> None:
        group = make_db_group(id=10, name="Contoso Engineering")
        mock_dal.get_group.return_value = group
        uid = uuid4()
        mock_dal.get_group_members.return_value = [(uid, "alice@contoso.com")]

        result = get_group(
            group_id="10",
            _token=mock_token,
            provider=entra_provider,
            db_session=mock_db_session,
        )

        resource = parse_scim_group(result)
        assert resource.displayName == "Contoso Engineering"
        assert len(resource.members) == 1

    def test_list_groups_with_excluded_attributes_members(
        self,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
        entra_provider: ScimProvider,
    ) -> None:
        """Entra sends ?excludedAttributes=members on group list queries."""
        group = make_db_group(id=10, name="Engineering")
        uid = uuid4()
        mock_dal.list_groups.return_value = ([(group, "ext-g-1")], 1)
        mock_dal.get_group_members.return_value = [(uid, "alice@contoso.com")]

        result = list_groups(
            filter=None,
            excludedAttributes="members",
            startIndex=1,
            count=100,
            _token=mock_token,
            provider=entra_provider,
            db_session=mock_db_session,
        )

        assert isinstance(result, ScimJSONResponse)
        parsed = json.loads(result.body)
        assert parsed["totalResults"] == 1
        resource = parsed["Resources"][0]
        assert "members" not in resource
        assert resource["displayName"] == "Engineering"

    def test_get_group_with_excluded_attributes_members(
        self,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
        entra_provider: ScimProvider,
    ) -> None:
        """Entra sends ?excludedAttributes=members on single group GET."""
        group = make_db_group(id=10, name="Engineering")
        uid = uuid4()
        mock_dal.get_group.return_value = group
        mock_dal.get_group_members.return_value = [(uid, "alice@contoso.com")]

        result = get_group(
            group_id="10",
            excludedAttributes="members",
            _token=mock_token,
            provider=entra_provider,
            db_session=mock_db_session,
        )

        assert isinstance(result, ScimJSONResponse)
        parsed = json.loads(result.body)
        assert "members" not in parsed
        assert parsed["displayName"] == "Engineering"

    @patch("ee.onyx.server.scim.api.apply_group_patch")
    def test_patch_group_add_members_with_pascal_case(
        self,
        mock_apply: MagicMock,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
        entra_provider: ScimProvider,
    ) -> None:
        """Entra sends ``"Add"`` (PascalCase) for group member additions."""
        group = make_db_group(id=10)
        mock_dal.get_group.return_value = group
        mock_dal.get_group_members.return_value = []
        mock_dal.validate_member_ids.return_value = []

        uid = str(uuid4())
        patched = ScimGroupResource(
            id="10",
            displayName="Engineering",
            members=[ScimGroupMember(value=uid)],
        )
        mock_apply.return_value = (patched, [uid], [])

        patch_req = ScimPatchRequest(
            Operations=[
                ScimPatchOperation(
                    op="Add",  # type: ignore[arg-type]
                    path="members",
                    value=[ScimGroupMember(value=uid)],
                )
            ]
        )

        result = patch_group(
            group_id="10",
            patch_request=patch_req,
            _token=mock_token,
            provider=entra_provider,
            db_session=mock_db_session,
        )

        parse_scim_group(result)
        mock_dal.upsert_group_members.assert_called_once()

    @patch("ee.onyx.server.scim.api.apply_group_patch")
    def test_patch_group_remove_member_with_pascal_case(
        self,
        mock_apply: MagicMock,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
        entra_provider: ScimProvider,
    ) -> None:
        """Entra sends ``"Remove"`` (PascalCase) for group member removals."""
        group = make_db_group(id=10)
        mock_dal.get_group.return_value = group
        mock_dal.get_group_members.return_value = []

        uid = str(uuid4())
        patched = ScimGroupResource(id="10", displayName="Engineering", members=[])
        mock_apply.return_value = (patched, [], [uid])

        patch_req = ScimPatchRequest(
            Operations=[
                ScimPatchOperation(
                    op="Remove",  # type: ignore[arg-type]
                    path=f'members[value eq "{uid}"]',
                )
            ]
        )

        result = patch_group(
            group_id="10",
            patch_request=patch_req,
            _token=mock_token,
            provider=entra_provider,
            db_session=mock_db_session,
        )

        parse_scim_group(result)
        mock_dal.remove_group_members.assert_called_once()


# ---------------------------------------------------------------------------
# excludedAttributes (RFC 7644 §3.4.2.5)
# ---------------------------------------------------------------------------


class TestExcludedAttributes:
    """Test excludedAttributes query parameter on GET endpoints."""

    def test_list_groups_excludes_members(
        self,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
        entra_provider: ScimProvider,
    ) -> None:
        group = make_db_group(id=1, name="Team")
        uid = uuid4()
        mock_dal.list_groups.return_value = ([(group, None)], 1)
        mock_dal.get_group_members.return_value = [(uid, "user@example.com")]

        result = list_groups(
            filter=None,
            excludedAttributes="members",
            startIndex=1,
            count=100,
            _token=mock_token,
            provider=entra_provider,
            db_session=mock_db_session,
        )

        assert isinstance(result, ScimJSONResponse)
        parsed = json.loads(result.body)
        resource = parsed["Resources"][0]
        assert "members" not in resource
        assert "displayName" in resource

    def test_get_group_excludes_members(
        self,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
        entra_provider: ScimProvider,
    ) -> None:
        group = make_db_group(id=1, name="Team")
        uid = uuid4()
        mock_dal.get_group.return_value = group
        mock_dal.get_group_members.return_value = [(uid, "user@example.com")]

        result = get_group(
            group_id="1",
            excludedAttributes="members",
            _token=mock_token,
            provider=entra_provider,
            db_session=mock_db_session,
        )

        assert isinstance(result, ScimJSONResponse)
        parsed = json.loads(result.body)
        assert "members" not in parsed
        assert "displayName" in parsed

    def test_list_users_excludes_groups(
        self,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
        entra_provider: ScimProvider,
    ) -> None:
        user = make_db_user()
        mapping = make_user_mapping(user_id=user.id)
        mock_dal.list_users.return_value = ([(user, mapping)], 1)
        mock_dal.get_users_groups_batch.return_value = {user.id: [(1, "Engineering")]}

        result = list_users(
            filter=None,
            excludedAttributes="groups",
            startIndex=1,
            count=100,
            _token=mock_token,
            provider=entra_provider,
            db_session=mock_db_session,
        )

        assert isinstance(result, ScimJSONResponse)
        parsed = json.loads(result.body)
        resource = parsed["Resources"][0]
        assert "groups" not in resource
        assert "userName" in resource

    def test_get_user_excludes_groups(
        self,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
        entra_provider: ScimProvider,
    ) -> None:
        user = make_db_user()
        mock_dal.get_user.return_value = user
        mock_dal.get_user_groups.return_value = [(1, "Engineering")]

        result = get_user(
            user_id=str(user.id),
            excludedAttributes="groups",
            _token=mock_token,
            provider=entra_provider,
            db_session=mock_db_session,
        )

        assert isinstance(result, ScimJSONResponse)
        parsed = json.loads(result.body)
        assert "groups" not in parsed
        assert "userName" in parsed

    def test_multiple_excluded_attributes(
        self,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
        entra_provider: ScimProvider,
    ) -> None:
        group = make_db_group(id=1, name="Team")
        mock_dal.get_group.return_value = group
        mock_dal.get_group_members.return_value = []

        result = get_group(
            group_id="1",
            excludedAttributes="members,externalId",
            _token=mock_token,
            provider=entra_provider,
            db_session=mock_db_session,
        )

        assert isinstance(result, ScimJSONResponse)
        parsed = json.loads(result.body)
        assert "members" not in parsed
        assert "externalId" not in parsed
        assert "displayName" in parsed

    def test_no_excluded_attributes_returns_full_response(
        self,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
        entra_provider: ScimProvider,
    ) -> None:
        group = make_db_group(id=1, name="Team")
        uid = uuid4()
        mock_dal.get_group.return_value = group
        mock_dal.get_group_members.return_value = [(uid, "user@example.com")]

        result = get_group(
            group_id="1",
            _token=mock_token,
            provider=entra_provider,
            db_session=mock_db_session,
        )

        resource = parse_scim_group(result)
        assert len(resource.members) == 1


# ---------------------------------------------------------------------------
# Entra Connection Probe
# ---------------------------------------------------------------------------


class TestEntraConnectionProbe:
    """Entra sends a probe request during initial SCIM setup."""

    def test_filter_for_nonexistent_user_returns_empty_list(
        self,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
        entra_provider: ScimProvider,
    ) -> None:
        """Entra probes with: GET /Users?filter=userName eq "non-existent"&count=1"""
        mock_dal.list_users.return_value = ([], 0)

        result = list_users(
            filter='userName eq "non-existent@contoso.com"',
            startIndex=1,
            count=1,
            _token=mock_token,
            provider=entra_provider,
            db_session=mock_db_session,
        )

        parsed = parse_scim_list(result)
        assert parsed.totalResults == 0
        assert parsed.Resources == []
