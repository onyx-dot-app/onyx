"""Unit tests for SCIM Group CRUD endpoints."""

from __future__ import annotations

from unittest.mock import MagicMock
from unittest.mock import patch
from uuid import uuid4

from fastapi import Response

from ee.onyx.server.scim.api import create_group
from ee.onyx.server.scim.api import delete_group
from ee.onyx.server.scim.api import get_group
from ee.onyx.server.scim.api import list_groups
from ee.onyx.server.scim.api import patch_group
from ee.onyx.server.scim.api import replace_group
from ee.onyx.server.scim.models import ScimGroupMember
from ee.onyx.server.scim.models import ScimGroupResource
from ee.onyx.server.scim.models import ScimListResponse
from ee.onyx.server.scim.models import ScimPatchOperation
from ee.onyx.server.scim.models import ScimPatchOperationType
from ee.onyx.server.scim.models import ScimPatchRequest
from ee.onyx.server.scim.patch import ScimPatchError
from tests.unit.onyx.server.scim.conftest import assert_scim_error
from tests.unit.onyx.server.scim.conftest import make_db_group
from tests.unit.onyx.server.scim.conftest import make_scim_group


class TestListGroups:
    """Tests for GET /scim/v2/Groups."""

    def test_empty_result(
        self,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
    ) -> None:
        mock_dal.list_groups.return_value = ([], 0)

        result = list_groups(
            filter=None,
            startIndex=1,
            count=100,
            _token=mock_token,
            db_session=mock_db_session,
        )

        assert isinstance(result, ScimListResponse)
        assert result.totalResults == 0
        assert result.Resources == []

    def test_unsupported_filter_returns_400(
        self,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
    ) -> None:
        mock_dal.list_groups.side_effect = ValueError(
            "Unsupported filter attribute: userName"
        )

        result = list_groups(
            filter='userName eq "x"',
            startIndex=1,
            count=100,
            _token=mock_token,
            db_session=mock_db_session,
        )

        assert_scim_error(result, 400)

    def test_returns_groups_with_members(
        self,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
    ) -> None:
        group = make_db_group(id=5, name="Engineering")
        uid = uuid4()
        mock_dal.list_groups.return_value = ([(group, "ext-g-1")], 1)
        mock_dal.get_group_members.return_value = [(uid, "alice@example.com")]

        result = list_groups(
            filter=None,
            startIndex=1,
            count=100,
            _token=mock_token,
            db_session=mock_db_session,
        )

        assert isinstance(result, ScimListResponse)
        assert result.totalResults == 1
        resource = result.Resources[0]
        assert isinstance(resource, ScimGroupResource)
        assert resource.displayName == "Engineering"
        assert resource.externalId == "ext-g-1"
        assert len(resource.members) == 1
        assert resource.members[0].display == "alice@example.com"


class TestGetGroup:
    """Tests for GET /scim/v2/Groups/{group_id}."""

    def test_returns_scim_resource(
        self,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
    ) -> None:
        group = make_db_group(id=5, name="Engineering")
        mock_dal.get_group.return_value = group
        mock_dal.get_group_members.return_value = []

        result = get_group(
            group_id="5",
            _token=mock_token,
            db_session=mock_db_session,
        )

        assert isinstance(result, ScimGroupResource)
        assert result.displayName == "Engineering"
        assert result.id == "5"

    def test_non_integer_id_returns_404(
        self,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,  # noqa: ARG002
    ) -> None:
        result = get_group(
            group_id="not-a-number",
            _token=mock_token,
            db_session=mock_db_session,
        )

        assert_scim_error(result, 404)

    def test_not_found_returns_404(
        self,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
    ) -> None:
        mock_dal.get_group.return_value = None

        result = get_group(
            group_id="999",
            _token=mock_token,
            db_session=mock_db_session,
        )

        assert_scim_error(result, 404)


class TestCreateGroup:
    """Tests for POST /scim/v2/Groups."""

    @patch("ee.onyx.server.scim.api._validate_and_parse_members")
    def test_success(
        self,
        mock_validate: MagicMock,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
    ) -> None:
        mock_dal.get_group_by_name.return_value = None
        mock_validate.return_value = ([], None)
        mock_dal.get_group_members.return_value = []

        resource = make_scim_group(displayName="New Group")

        result = create_group(
            group_resource=resource,
            _token=mock_token,
            db_session=mock_db_session,
        )

        assert isinstance(result, ScimGroupResource)
        assert result.displayName == "New Group"
        mock_dal.add_group.assert_called_once()
        mock_dal.commit.assert_called_once()

    def test_duplicate_name_returns_409(
        self,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
    ) -> None:
        mock_dal.get_group_by_name.return_value = make_db_group()
        resource = make_scim_group()

        result = create_group(
            group_resource=resource,
            _token=mock_token,
            db_session=mock_db_session,
        )

        assert_scim_error(result, 409)

    @patch("ee.onyx.server.scim.api._validate_and_parse_members")
    def test_invalid_member_returns_400(
        self,
        mock_validate: MagicMock,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
    ) -> None:
        mock_dal.get_group_by_name.return_value = None
        mock_validate.return_value = ([], "Invalid member ID: bad-uuid")

        resource = make_scim_group(members=[ScimGroupMember(value="bad-uuid")])

        result = create_group(
            group_resource=resource,
            _token=mock_token,
            db_session=mock_db_session,
        )

        assert_scim_error(result, 400)

    @patch("ee.onyx.server.scim.api._validate_and_parse_members")
    def test_nonexistent_member_returns_400(
        self,
        mock_validate: MagicMock,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
    ) -> None:
        mock_dal.get_group_by_name.return_value = None
        uid = uuid4()
        mock_validate.return_value = ([], f"Member(s) not found: {uid}")

        resource = make_scim_group(members=[ScimGroupMember(value=str(uid))])

        result = create_group(
            group_resource=resource,
            _token=mock_token,
            db_session=mock_db_session,
        )

        assert_scim_error(result, 400)

    @patch("ee.onyx.server.scim.api._validate_and_parse_members")
    def test_creates_external_id_mapping(
        self,
        mock_validate: MagicMock,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
    ) -> None:
        mock_dal.get_group_by_name.return_value = None
        mock_validate.return_value = ([], None)
        mock_dal.get_group_members.return_value = []

        resource = make_scim_group(externalId="ext-g-123")

        result = create_group(
            group_resource=resource,
            _token=mock_token,
            db_session=mock_db_session,
        )

        assert isinstance(result, ScimGroupResource)
        mock_dal.create_group_mapping.assert_called_once()


class TestReplaceGroup:
    """Tests for PUT /scim/v2/Groups/{group_id}."""

    @patch("ee.onyx.server.scim.api._validate_and_parse_members")
    def test_success(
        self,
        mock_validate: MagicMock,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
    ) -> None:
        group = make_db_group(id=5, name="Old Name")
        mock_dal.get_group.return_value = group
        mock_validate.return_value = ([], None)
        mock_dal.get_group_members.return_value = []

        resource = make_scim_group(displayName="New Name")

        result = replace_group(
            group_id="5",
            group_resource=resource,
            _token=mock_token,
            db_session=mock_db_session,
        )

        assert isinstance(result, ScimGroupResource)
        mock_dal.update_group.assert_called_once_with(group, name="New Name")
        mock_dal.replace_group_members.assert_called_once()
        mock_dal.commit.assert_called_once()

    def test_not_found_returns_404(
        self,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
    ) -> None:
        mock_dal.get_group.return_value = None

        result = replace_group(
            group_id="999",
            group_resource=make_scim_group(),
            _token=mock_token,
            db_session=mock_db_session,
        )

        assert_scim_error(result, 404)

    @patch("ee.onyx.server.scim.api._validate_and_parse_members")
    def test_invalid_member_returns_400(
        self,
        mock_validate: MagicMock,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
    ) -> None:
        group = make_db_group(id=5)
        mock_dal.get_group.return_value = group
        mock_validate.return_value = ([], "Invalid member ID: bad")

        resource = make_scim_group(members=[ScimGroupMember(value="bad")])

        result = replace_group(
            group_id="5",
            group_resource=resource,
            _token=mock_token,
            db_session=mock_db_session,
        )

        assert_scim_error(result, 400)

    @patch("ee.onyx.server.scim.api._validate_and_parse_members")
    def test_syncs_external_id(
        self,
        mock_validate: MagicMock,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
    ) -> None:
        group = make_db_group(id=5)
        mock_dal.get_group.return_value = group
        mock_validate.return_value = ([], None)
        mock_dal.get_group_members.return_value = []

        resource = make_scim_group(externalId="new-ext")

        replace_group(
            group_id="5",
            group_resource=resource,
            _token=mock_token,
            db_session=mock_db_session,
        )

        mock_dal.sync_group_external_id.assert_called_once_with(5, "new-ext")


class TestPatchGroup:
    """Tests for PATCH /scim/v2/Groups/{group_id}."""

    @patch("ee.onyx.server.scim.api.apply_group_patch")
    def test_rename(
        self,
        mock_apply: MagicMock,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
    ) -> None:
        group = make_db_group(id=5, name="Old Name")
        mock_dal.get_group.return_value = group
        mock_dal.get_group_members.return_value = []

        patched = ScimGroupResource(id="5", displayName="New Name", members=[])
        mock_apply.return_value = (patched, [], [])

        patch_req = ScimPatchRequest(
            Operations=[
                ScimPatchOperation(
                    op=ScimPatchOperationType.REPLACE,
                    path="displayName",
                    value="New Name",
                )
            ]
        )

        result = patch_group(
            group_id="5",
            patch_request=patch_req,
            _token=mock_token,
            db_session=mock_db_session,
        )

        assert isinstance(result, ScimGroupResource)
        mock_dal.update_group.assert_called_once_with(group, name="New Name")

    def test_not_found_returns_404(
        self,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
    ) -> None:
        mock_dal.get_group.return_value = None

        patch_req = ScimPatchRequest(
            Operations=[
                ScimPatchOperation(
                    op=ScimPatchOperationType.REPLACE,
                    path="displayName",
                    value="X",
                )
            ]
        )

        result = patch_group(
            group_id="999",
            patch_request=patch_req,
            _token=mock_token,
            db_session=mock_db_session,
        )

        assert_scim_error(result, 404)

    @patch("ee.onyx.server.scim.api.apply_group_patch")
    def test_patch_error_returns_error_response(
        self,
        mock_apply: MagicMock,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
    ) -> None:
        group = make_db_group(id=5)
        mock_dal.get_group.return_value = group
        mock_dal.get_group_members.return_value = []

        mock_apply.side_effect = ScimPatchError("Unsupported path", 400)

        patch_req = ScimPatchRequest(
            Operations=[
                ScimPatchOperation(
                    op=ScimPatchOperationType.REPLACE,
                    path="badPath",
                    value="x",
                )
            ]
        )

        result = patch_group(
            group_id="5",
            patch_request=patch_req,
            _token=mock_token,
            db_session=mock_db_session,
        )

        assert_scim_error(result, 400)

    @patch("ee.onyx.server.scim.api.apply_group_patch")
    def test_add_members(
        self,
        mock_apply: MagicMock,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
    ) -> None:
        group = make_db_group(id=5)
        mock_dal.get_group.return_value = group
        mock_dal.get_group_members.return_value = []
        mock_dal.validate_member_ids.return_value = []

        uid = str(uuid4())
        patched = ScimGroupResource(
            id="5",
            displayName="Engineering",
            members=[ScimGroupMember(value=uid)],
        )
        mock_apply.return_value = (patched, [uid], [])

        patch_req = ScimPatchRequest(
            Operations=[
                ScimPatchOperation(
                    op=ScimPatchOperationType.ADD,
                    path="members",
                    value=[{"value": uid}],
                )
            ]
        )

        result = patch_group(
            group_id="5",
            patch_request=patch_req,
            _token=mock_token,
            db_session=mock_db_session,
        )

        assert isinstance(result, ScimGroupResource)
        mock_dal.validate_member_ids.assert_called_once()
        mock_dal.upsert_group_members.assert_called_once()

    @patch("ee.onyx.server.scim.api.apply_group_patch")
    def test_add_nonexistent_member_returns_400(
        self,
        mock_apply: MagicMock,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
    ) -> None:
        group = make_db_group(id=5)
        mock_dal.get_group.return_value = group
        mock_dal.get_group_members.return_value = []

        uid = uuid4()
        patched = ScimGroupResource(
            id="5",
            displayName="Engineering",
            members=[ScimGroupMember(value=str(uid))],
        )
        mock_apply.return_value = (patched, [str(uid)], [])
        mock_dal.validate_member_ids.return_value = [uid]

        patch_req = ScimPatchRequest(
            Operations=[
                ScimPatchOperation(
                    op=ScimPatchOperationType.ADD,
                    path="members",
                    value=[{"value": str(uid)}],
                )
            ]
        )

        result = patch_group(
            group_id="5",
            patch_request=patch_req,
            _token=mock_token,
            db_session=mock_db_session,
        )

        assert_scim_error(result, 400)

    @patch("ee.onyx.server.scim.api.apply_group_patch")
    def test_remove_members(
        self,
        mock_apply: MagicMock,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
    ) -> None:
        group = make_db_group(id=5)
        mock_dal.get_group.return_value = group
        mock_dal.get_group_members.return_value = []

        uid = str(uuid4())
        patched = ScimGroupResource(id="5", displayName="Engineering", members=[])
        mock_apply.return_value = (patched, [], [uid])

        patch_req = ScimPatchRequest(
            Operations=[
                ScimPatchOperation(
                    op=ScimPatchOperationType.REMOVE,
                    path=f'members[value eq "{uid}"]',
                )
            ]
        )

        result = patch_group(
            group_id="5",
            patch_request=patch_req,
            _token=mock_token,
            db_session=mock_db_session,
        )

        assert isinstance(result, ScimGroupResource)
        mock_dal.remove_group_members.assert_called_once()


class TestDeleteGroup:
    """Tests for DELETE /scim/v2/Groups/{group_id}."""

    def test_success(
        self,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
    ) -> None:
        group = make_db_group(id=5)
        mock_dal.get_group.return_value = group
        mapping = MagicMock()
        mapping.id = 1
        mock_dal.get_group_mapping_by_group_id.return_value = mapping

        result = delete_group(
            group_id="5",
            _token=mock_token,
            db_session=mock_db_session,
        )

        assert isinstance(result, Response)
        assert result.status_code == 204
        mock_dal.delete_group_mapping.assert_called_once_with(1)
        mock_dal.delete_group_with_members.assert_called_once_with(group)
        mock_dal.commit.assert_called_once()

    def test_not_found_returns_404(
        self,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
    ) -> None:
        mock_dal.get_group.return_value = None

        result = delete_group(
            group_id="999",
            _token=mock_token,
            db_session=mock_db_session,
        )

        assert_scim_error(result, 404)

    def test_non_integer_id_returns_404(
        self,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,  # noqa: ARG002
    ) -> None:
        result = delete_group(
            group_id="abc",
            _token=mock_token,
            db_session=mock_db_session,
        )

        assert_scim_error(result, 404)
