"""Unit tests for SCIM User CRUD endpoints."""

from __future__ import annotations

from unittest.mock import MagicMock
from unittest.mock import patch
from uuid import uuid4

from fastapi import Response
from sqlalchemy.exc import IntegrityError

from ee.onyx.server.scim.api import create_user
from ee.onyx.server.scim.api import delete_user
from ee.onyx.server.scim.api import get_user
from ee.onyx.server.scim.api import list_users
from ee.onyx.server.scim.api import patch_user
from ee.onyx.server.scim.api import replace_user
from ee.onyx.server.scim.models import ScimListResponse
from ee.onyx.server.scim.models import ScimName
from ee.onyx.server.scim.models import ScimPatchOperation
from ee.onyx.server.scim.models import ScimPatchOperationType
from ee.onyx.server.scim.models import ScimPatchRequest
from ee.onyx.server.scim.models import ScimUserResource
from ee.onyx.server.scim.patch import ScimPatchError
from tests.unit.onyx.server.scim.conftest import assert_scim_error
from tests.unit.onyx.server.scim.conftest import make_db_user
from tests.unit.onyx.server.scim.conftest import make_scim_user


class TestListUsers:
    """Tests for GET /scim/v2/Users."""

    def test_empty_result(
        self,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
    ) -> None:
        mock_dal.list_users.return_value = ([], 0)

        result = list_users(
            filter=None,
            startIndex=1,
            count=100,
            _token=mock_token,
            db_session=mock_db_session,
        )

        assert isinstance(result, ScimListResponse)
        assert result.totalResults == 0
        assert result.Resources == []

    def test_returns_users_with_scim_shape(
        self,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
    ) -> None:
        user = make_db_user(email="alice@example.com", personal_name="Alice Smith")
        mock_dal.list_users.return_value = ([(user, "ext-abc")], 1)

        result = list_users(
            filter=None,
            startIndex=1,
            count=100,
            _token=mock_token,
            db_session=mock_db_session,
        )

        assert isinstance(result, ScimListResponse)
        assert result.totalResults == 1
        assert len(result.Resources) == 1
        resource = result.Resources[0]
        assert isinstance(resource, ScimUserResource)
        assert resource.userName == "alice@example.com"
        assert resource.externalId == "ext-abc"

    def test_unsupported_filter_attribute_returns_400(
        self,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
    ) -> None:
        mock_dal.list_users.side_effect = ValueError(
            "Unsupported filter attribute: emails"
        )

        result = list_users(
            filter='emails eq "x@y.com"',
            startIndex=1,
            count=100,
            _token=mock_token,
            db_session=mock_db_session,
        )

        assert_scim_error(result, 400)

    def test_invalid_filter_syntax_returns_400(
        self,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,  # noqa: ARG002
    ) -> None:
        result = list_users(
            filter="not a valid filter",
            startIndex=1,
            count=100,
            _token=mock_token,
            db_session=mock_db_session,
        )

        assert_scim_error(result, 400)


class TestGetUser:
    """Tests for GET /scim/v2/Users/{user_id}."""

    def test_returns_scim_resource(
        self,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
    ) -> None:
        user = make_db_user(email="alice@example.com")
        mock_dal.get_user.return_value = user

        result = get_user(
            user_id=str(user.id),
            _token=mock_token,
            db_session=mock_db_session,
        )

        assert isinstance(result, ScimUserResource)
        assert result.userName == "alice@example.com"
        assert result.id == str(user.id)

    def test_invalid_uuid_returns_404(
        self,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,  # noqa: ARG002
    ) -> None:
        result = get_user(
            user_id="not-a-uuid",
            _token=mock_token,
            db_session=mock_db_session,
        )

        assert_scim_error(result, 404)

    def test_user_not_found_returns_404(
        self,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
    ) -> None:
        mock_dal.get_user.return_value = None

        result = get_user(
            user_id=str(uuid4()),
            _token=mock_token,
            db_session=mock_db_session,
        )

        assert_scim_error(result, 404)


class TestCreateUser:
    """Tests for POST /scim/v2/Users."""

    @patch("ee.onyx.server.scim.api._check_seat_availability", return_value=None)
    def test_success(
        self,
        mock_seats: MagicMock,  # noqa: ARG002
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
    ) -> None:
        mock_dal.get_user_by_email.return_value = None
        resource = make_scim_user(userName="new@example.com")

        result = create_user(
            user_resource=resource,
            _token=mock_token,
            db_session=mock_db_session,
        )

        assert isinstance(result, ScimUserResource)
        assert result.userName == "new@example.com"
        mock_dal.add_user.assert_called_once()
        mock_dal.commit.assert_called_once()

    def test_missing_external_id_returns_400(
        self,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,  # noqa: ARG002
    ) -> None:
        resource = make_scim_user(externalId=None)

        result = create_user(
            user_resource=resource,
            _token=mock_token,
            db_session=mock_db_session,
        )

        assert_scim_error(result, 400)

    @patch("ee.onyx.server.scim.api._check_seat_availability", return_value=None)
    def test_duplicate_email_returns_409(
        self,
        mock_seats: MagicMock,  # noqa: ARG002
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
    ) -> None:
        mock_dal.get_user_by_email.return_value = make_db_user()
        resource = make_scim_user()

        result = create_user(
            user_resource=resource,
            _token=mock_token,
            db_session=mock_db_session,
        )

        assert_scim_error(result, 409)

    @patch("ee.onyx.server.scim.api._check_seat_availability", return_value=None)
    def test_integrity_error_returns_409(
        self,
        mock_seats: MagicMock,  # noqa: ARG002
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
    ) -> None:
        mock_dal.get_user_by_email.return_value = None
        mock_dal.add_user.side_effect = IntegrityError("dup", {}, Exception())
        resource = make_scim_user()

        result = create_user(
            user_resource=resource,
            _token=mock_token,
            db_session=mock_db_session,
        )

        assert_scim_error(result, 409)
        mock_dal.rollback.assert_called_once()

    @patch("ee.onyx.server.scim.api._check_seat_availability")
    def test_seat_limit_returns_403(
        self,
        mock_seats: MagicMock,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,  # noqa: ARG002
    ) -> None:
        mock_seats.return_value = "Seat limit reached"
        resource = make_scim_user()

        result = create_user(
            user_resource=resource,
            _token=mock_token,
            db_session=mock_db_session,
        )

        assert_scim_error(result, 403)

    @patch("ee.onyx.server.scim.api._check_seat_availability", return_value=None)
    def test_creates_external_id_mapping(
        self,
        mock_seats: MagicMock,  # noqa: ARG002
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
    ) -> None:
        mock_dal.get_user_by_email.return_value = None
        resource = make_scim_user(externalId="ext-123")

        result = create_user(
            user_resource=resource,
            _token=mock_token,
            db_session=mock_db_session,
        )

        assert isinstance(result, ScimUserResource)
        assert result.externalId == "ext-123"
        mock_dal.create_user_mapping.assert_called_once()


class TestReplaceUser:
    """Tests for PUT /scim/v2/Users/{user_id}."""

    def test_success(
        self,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
    ) -> None:
        user = make_db_user(email="old@example.com")
        mock_dal.get_user.return_value = user
        resource = make_scim_user(
            userName="new@example.com",
            name=ScimName(givenName="New", familyName="Name"),
        )

        result = replace_user(
            user_id=str(user.id),
            user_resource=resource,
            _token=mock_token,
            db_session=mock_db_session,
        )

        assert isinstance(result, ScimUserResource)
        mock_dal.update_user.assert_called_once()
        mock_dal.commit.assert_called_once()

    def test_not_found_returns_404(
        self,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
    ) -> None:
        mock_dal.get_user.return_value = None

        result = replace_user(
            user_id=str(uuid4()),
            user_resource=make_scim_user(),
            _token=mock_token,
            db_session=mock_db_session,
        )

        assert_scim_error(result, 404)

    @patch("ee.onyx.server.scim.api._check_seat_availability")
    def test_reactivation_checks_seats(
        self,
        mock_seats: MagicMock,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
    ) -> None:
        user = make_db_user(is_active=False)
        mock_dal.get_user.return_value = user
        mock_seats.return_value = "No seats"
        resource = make_scim_user(active=True)

        result = replace_user(
            user_id=str(user.id),
            user_resource=resource,
            _token=mock_token,
            db_session=mock_db_session,
        )

        assert_scim_error(result, 403)
        mock_seats.assert_called_once()

    def test_syncs_external_id(
        self,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
    ) -> None:
        user = make_db_user()
        mock_dal.get_user.return_value = user

        resource = make_scim_user(externalId=None)

        result = replace_user(
            user_id=str(user.id),
            user_resource=resource,
            _token=mock_token,
            db_session=mock_db_session,
        )

        assert isinstance(result, ScimUserResource)
        mock_dal.sync_user_external_id.assert_called_once_with(user.id, None)


class TestPatchUser:
    """Tests for PATCH /scim/v2/Users/{user_id}."""

    def test_deactivate(
        self,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
    ) -> None:
        user = make_db_user(is_active=True)
        mock_dal.get_user.return_value = user
        patch_req = ScimPatchRequest(
            Operations=[
                ScimPatchOperation(
                    op=ScimPatchOperationType.REPLACE,
                    path="active",
                    value=False,
                )
            ]
        )

        result = patch_user(
            user_id=str(user.id),
            patch_request=patch_req,
            _token=mock_token,
            db_session=mock_db_session,
        )

        assert isinstance(result, ScimUserResource)
        mock_dal.update_user.assert_called_once()

    def test_not_found_returns_404(
        self,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
    ) -> None:
        mock_dal.get_user.return_value = None
        patch_req = ScimPatchRequest(
            Operations=[
                ScimPatchOperation(
                    op=ScimPatchOperationType.REPLACE,
                    path="active",
                    value=False,
                )
            ]
        )

        result = patch_user(
            user_id=str(uuid4()),
            patch_request=patch_req,
            _token=mock_token,
            db_session=mock_db_session,
        )

        assert_scim_error(result, 404)

    @patch("ee.onyx.server.scim.api.apply_user_patch")
    def test_patch_error_returns_error_response(
        self,
        mock_apply: MagicMock,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
    ) -> None:
        user = make_db_user()
        mock_dal.get_user.return_value = user
        mock_apply.side_effect = ScimPatchError("Bad op", 400)
        patch_req = ScimPatchRequest(
            Operations=[
                ScimPatchOperation(
                    op=ScimPatchOperationType.REMOVE,
                    path="userName",
                )
            ]
        )

        result = patch_user(
            user_id=str(user.id),
            patch_request=patch_req,
            _token=mock_token,
            db_session=mock_db_session,
        )

        assert_scim_error(result, 400)


class TestDeleteUser:
    """Tests for DELETE /scim/v2/Users/{user_id}."""

    def test_success(
        self,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
    ) -> None:
        user = make_db_user(is_active=True)
        mock_dal.get_user.return_value = user
        mapping = MagicMock()
        mapping.id = 1
        mock_dal.get_user_mapping_by_user_id.return_value = mapping

        result = delete_user(
            user_id=str(user.id),
            _token=mock_token,
            db_session=mock_db_session,
        )

        assert isinstance(result, Response)
        assert result.status_code == 204
        mock_dal.deactivate_user.assert_called_once_with(user)
        mock_dal.delete_user_mapping.assert_called_once_with(1)
        mock_dal.commit.assert_called_once()

    def test_not_found_returns_404(
        self,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
    ) -> None:
        mock_dal.get_user.return_value = None

        result = delete_user(
            user_id=str(uuid4()),
            _token=mock_token,
            db_session=mock_db_session,
        )

        assert_scim_error(result, 404)

    def test_invalid_uuid_returns_404(
        self,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,  # noqa: ARG002
    ) -> None:
        result = delete_user(
            user_id="not-a-uuid",
            _token=mock_token,
            db_session=mock_db_session,
        )

        assert_scim_error(result, 404)
