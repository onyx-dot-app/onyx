"""Unit tests for SCIM User CRUD endpoints."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

from fastapi import Response
from sqlalchemy.exc import IntegrityError

from ee.onyx.db.license import seat_lock_id_for_tenant
from ee.onyx.server.scim.api import (
    _check_seat_availability,
    _scim_name_to_str,
    create_user,
    delete_user,
    get_user,
    list_users,
    patch_user,
    replace_user,
)
from ee.onyx.server.scim.models import (
    ScimMappingFields,
    ScimName,
    ScimPatchOperation,
    ScimPatchOperationType,
    ScimPatchRequest,
    ScimUserResource,
)
from ee.onyx.server.scim.patch import ScimPatchError
from ee.onyx.server.scim.providers.base import ScimProvider
from onyx.db.enums import AccountType, Permission
from tests.unit.onyx.server.scim.conftest import (
    assert_scim_error,
    make_db_user,
    make_scim_user,
    make_user_mapping,
    parse_scim_list,
    parse_scim_user,
)


class TestListUsers:
    """Tests for GET /scim/v2/Users."""

    def test_empty_result(
        self,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
        provider: ScimProvider,
    ) -> None:
        mock_dal.list_users.return_value = ([], 0)

        result = list_users(
            filter=None,
            startIndex=1,
            count=100,
            _token=mock_token,
            provider=provider,
            db_session=mock_db_session,
        )

        parsed = parse_scim_list(result)
        assert parsed.totalResults == 0
        assert parsed.Resources == []

    def test_returns_users_with_scim_shape(
        self,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
        provider: ScimProvider,
    ) -> None:
        user = make_db_user(email="alice@example.com", personal_name="Alice Smith")
        mapping = make_user_mapping(
            external_id="ext-abc", user_id=user.id, scim_username="Alice@example.com"
        )
        mock_dal.list_users.return_value = ([(user, mapping)], 1)

        result = list_users(
            filter=None,
            startIndex=1,
            count=100,
            _token=mock_token,
            provider=provider,
            db_session=mock_db_session,
        )

        parsed = parse_scim_list(result)
        assert parsed.totalResults == 1
        assert len(parsed.Resources) == 1
        resource = parsed.Resources[0]
        assert isinstance(resource, ScimUserResource)
        assert resource.userName == "Alice@example.com"
        assert resource.externalId == "ext-abc"

    def test_unsupported_filter_attribute_returns_400(
        self,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
        provider: ScimProvider,
    ) -> None:
        mock_dal.list_users.side_effect = ValueError(
            "Unsupported filter attribute: emails"
        )

        result = list_users(
            filter='emails eq "x@y.com"',
            startIndex=1,
            count=100,
            _token=mock_token,
            provider=provider,
            db_session=mock_db_session,
        )

        assert_scim_error(result, 400)

    def test_invalid_filter_syntax_returns_400(
        self,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,  # noqa: ARG002
        provider: ScimProvider,
    ) -> None:
        result = list_users(
            filter="not a valid filter",
            startIndex=1,
            count=100,
            _token=mock_token,
            provider=provider,
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
        provider: ScimProvider,
    ) -> None:
        user = make_db_user(email="alice@example.com")
        mock_dal.get_user.return_value = user

        result = get_user(
            user_id=str(user.id),
            _token=mock_token,
            provider=provider,
            db_session=mock_db_session,
        )

        resource = parse_scim_user(result)
        assert resource.userName == "alice@example.com"
        assert resource.id == str(user.id)

    def test_invalid_uuid_returns_404(
        self,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,  # noqa: ARG002
        provider: ScimProvider,
    ) -> None:
        result = get_user(
            user_id="not-a-uuid",
            _token=mock_token,
            provider=provider,
            db_session=mock_db_session,
        )

        assert_scim_error(result, 404)

    def test_user_not_found_returns_404(
        self,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
        provider: ScimProvider,
    ) -> None:
        mock_dal.get_user.return_value = None

        result = get_user(
            user_id=str(uuid4()),
            _token=mock_token,
            provider=provider,
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
        provider: ScimProvider,
    ) -> None:
        mock_dal.get_user_by_email.return_value = None
        resource = make_scim_user(userName="new@example.com")

        result = create_user(
            user_resource=resource,
            _token=mock_token,
            provider=provider,
            db_session=mock_db_session,
        )

        resource = parse_scim_user(result, status=201)
        assert resource.userName == "new@example.com"
        mock_dal.add_user.assert_called_once()
        mock_dal.commit.assert_called_once()

    @patch("ee.onyx.server.scim.api._check_seat_availability", return_value=None)
    def test_missing_external_id_still_creates_mapping(
        self,
        mock_seats: MagicMock,  # noqa: ARG002
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
        provider: ScimProvider,
    ) -> None:
        """Mapping is always created to mark user as SCIM-managed."""
        mock_dal.get_user_by_email.return_value = None
        resource = make_scim_user(externalId=None)

        result = create_user(
            user_resource=resource,
            _token=mock_token,
            provider=provider,
            db_session=mock_db_session,
        )

        parsed = parse_scim_user(result, status=201)
        assert parsed.userName is not None
        mock_dal.add_user.assert_called_once()
        mock_dal.create_user_mapping.assert_called_once()
        mock_dal.commit.assert_called_once()

    @patch("ee.onyx.server.scim.api._check_seat_availability", return_value=None)
    def test_duplicate_scim_managed_email_returns_409(
        self,
        mock_seats: MagicMock,  # noqa: ARG002
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
        provider: ScimProvider,
    ) -> None:
        """409 only when the existing user already has a SCIM mapping."""
        existing = make_db_user()
        mock_dal.get_user_by_email.return_value = existing
        mock_dal.get_user_mapping_by_user_id.return_value = make_user_mapping(
            user_id=existing.id
        )
        resource = make_scim_user()

        result = create_user(
            user_resource=resource,
            _token=mock_token,
            provider=provider,
            db_session=mock_db_session,
        )

        assert_scim_error(result, 409)

    @patch("ee.onyx.server.scim.api._check_seat_availability", return_value=None)
    def test_existing_user_without_mapping_gets_linked(
        self,
        mock_seats: MagicMock,  # noqa: ARG002
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
        provider: ScimProvider,
    ) -> None:
        """Pre-existing user without SCIM mapping gets adopted (linked)."""
        existing = make_db_user(email="admin@example.com", personal_name=None)
        mock_dal.get_user_by_email.return_value = existing
        mock_dal.get_user_mapping_by_user_id.return_value = None
        resource = make_scim_user(userName="admin@example.com", externalId="ext-admin")

        result = create_user(
            user_resource=resource,
            _token=mock_token,
            provider=provider,
            db_session=mock_db_session,
        )

        parsed = parse_scim_user(result, status=201)
        assert parsed.userName == "admin@example.com"
        # Should NOT create a new user — reuse existing
        mock_dal.add_user.assert_not_called()
        # Already a real (BASIC) user — synced but NOT re-roled
        mock_dal.update_user.assert_called_once_with(
            existing,
            is_active=True,
            account_type=None,
            personal_name="Test User",
        )
        # Should create a SCIM mapping for the existing user
        mock_dal.create_user_mapping.assert_called_once()
        mock_dal.commit.assert_called_once()

    @patch("ee.onyx.server.scim.api.assign_user_to_default_groups__no_commit")
    @patch("ee.onyx.server.scim.api._check_seat_availability", return_value=None)
    def test_adopting_shadow_ext_perm_user_promotes_to_standard(
        self,
        mock_seats: MagicMock,
        mock_assign: MagicMock,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
        provider: ScimProvider,
    ) -> None:
        """A pre-existing EXT_PERM_USER shadow gets promoted to BASIC/STANDARD,
        seat-checked, and added to the Basic default group even though the
        user is already active.
        """
        existing = make_db_user(
            email="champion@example.com",
            personal_name=None,
            account_type=AccountType.EXT_PERM_USER,
            is_active=True,
        )
        mock_dal.get_user_by_email.return_value = existing
        mock_dal.get_user_mapping_by_user_id.return_value = None
        resource = make_scim_user(
            userName="champion@example.com", externalId="ext-champ"
        )

        result = create_user(
            user_resource=resource,
            _token=mock_token,
            provider=provider,
            db_session=mock_db_session,
        )

        parse_scim_user(result, status=201)
        mock_dal.add_user.assert_not_called()
        # Promotion consumes a seat -> seat check runs despite already-active user
        mock_seats.assert_called_once()
        mock_dal.update_user.assert_called_once_with(
            existing,
            is_active=True,
            account_type=AccountType.STANDARD,
            personal_name="Test User",
        )
        # Promoted shadow user must land in the Basic default group
        mock_assign.assert_called_once()
        mock_dal.create_user_mapping.assert_called_once()
        mock_dal.commit.assert_called_once()

    @patch("ee.onyx.server.scim.api._check_seat_availability")
    def test_adopting_shadow_ext_perm_user_respects_seat_limit(
        self,
        mock_seats: MagicMock,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
        provider: ScimProvider,
    ) -> None:
        """Promoting a shadow user that would exceed the seat cap returns 403."""
        mock_seats.return_value = "Seat limit reached"
        existing = make_db_user(
            email="champion@example.com",
            account_type=AccountType.EXT_PERM_USER,
            is_active=True,
        )
        mock_dal.get_user_by_email.return_value = existing
        mock_dal.get_user_mapping_by_user_id.return_value = None
        resource = make_scim_user(userName="champion@example.com")

        result = create_user(
            user_resource=resource,
            _token=mock_token,
            provider=provider,
            db_session=mock_db_session,
        )

        assert_scim_error(result, 403)
        mock_dal.update_user.assert_not_called()

    @patch(
        "ee.onyx.server.scim.api.assign_user_to_default_groups__no_commit",
        side_effect=RuntimeError("Default group 'Basic' not found"),
    )
    @patch("ee.onyx.server.scim.api._check_seat_availability", return_value=None)
    def test_promotion_default_group_failure_returns_500(
        self,
        mock_seats: MagicMock,  # noqa: ARG002
        mock_assign: MagicMock,  # noqa: ARG002
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
        provider: ScimProvider,
    ) -> None:
        """If default-group assignment raises during promotion, roll back and
        return a structured SCIM 500 instead of leaking a raw 500."""
        existing = make_db_user(
            email="champion@example.com",
            account_type=AccountType.EXT_PERM_USER,
            is_active=True,
        )
        mock_dal.get_user_by_email.return_value = existing
        mock_dal.get_user_mapping_by_user_id.return_value = None

        result = create_user(
            user_resource=make_scim_user(userName="champion@example.com"),
            _token=mock_token,
            provider=provider,
            db_session=mock_db_session,
        )

        assert_scim_error(result, 500)
        mock_dal.rollback.assert_called_once()
        mock_dal.create_user_mapping.assert_not_called()

    @patch("ee.onyx.server.scim.api._check_seat_availability", return_value=None)
    def test_integrity_error_returns_409(
        self,
        mock_seats: MagicMock,  # noqa: ARG002
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
        provider: ScimProvider,
    ) -> None:
        mock_dal.get_user_by_email.return_value = None
        mock_dal.add_user.side_effect = IntegrityError("dup", {}, Exception())
        resource = make_scim_user()

        result = create_user(
            user_resource=resource,
            _token=mock_token,
            provider=provider,
            db_session=mock_db_session,
        )

        assert_scim_error(result, 409)
        mock_dal.rollback.assert_called_once()

    @patch("ee.onyx.server.scim.api.is_unique_violation", return_value=True)
    @patch("ee.onyx.server.scim.api.assign_user_to_default_groups__no_commit")
    @patch("ee.onyx.server.scim.api._check_seat_availability", return_value=None)
    def test_assign_default_groups_email_integrity_error_returns_409(
        self,
        mock_seats: MagicMock,  # noqa: ARG002
        mock_assign: MagicMock,
        mock_is_unique: MagicMock,  # noqa: ARG002
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
        provider: ScimProvider,
    ) -> None:
        """A concurrent duplicate create can surface as an ix_user_email
        IntegrityError during default-group assignment (deferred autoflush)
        rather than at ``add_user``. It must return a clean 409, not a 500."""
        mock_dal.get_user_by_email.return_value = None
        mock_assign.side_effect = IntegrityError("dup", {}, Exception())

        result = create_user(
            user_resource=make_scim_user(),
            _token=mock_token,
            provider=provider,
            db_session=mock_db_session,
        )

        assert_scim_error(result, 409)
        mock_dal.rollback.assert_called_once()
        mock_dal.commit.assert_not_called()

    @patch("ee.onyx.server.scim.api.is_unique_violation", return_value=False)
    @patch("ee.onyx.server.scim.api.assign_user_to_default_groups__no_commit")
    @patch("ee.onyx.server.scim.api._check_seat_availability", return_value=None)
    def test_assign_default_groups_other_integrity_error_returns_500(
        self,
        mock_seats: MagicMock,  # noqa: ARG002
        mock_assign: MagicMock,
        mock_is_unique: MagicMock,  # noqa: ARG002
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
        provider: ScimProvider,
    ) -> None:
        """An integrity error NOT from the ix_user_email unique constraint (e.g.
        a FK/other-constraint fault) must stay a structured 500 so real backend
        faults aren't masked as a benign 409 'already exists'."""
        mock_dal.get_user_by_email.return_value = None
        mock_assign.side_effect = IntegrityError("fk", {}, Exception())

        result = create_user(
            user_resource=make_scim_user(),
            _token=mock_token,
            provider=provider,
            db_session=mock_db_session,
        )

        assert_scim_error(result, 500)
        mock_dal.rollback.assert_called_once()
        mock_dal.commit.assert_not_called()

    @patch("ee.onyx.server.scim.api._check_seat_availability")
    def test_seat_limit_returns_403(
        self,
        mock_seats: MagicMock,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,  # noqa: ARG002
        provider: ScimProvider,
    ) -> None:
        mock_seats.return_value = "Seat limit reached"
        resource = make_scim_user()

        result = create_user(
            user_resource=resource,
            _token=mock_token,
            provider=provider,
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
        provider: ScimProvider,
    ) -> None:
        mock_dal.get_user_by_email.return_value = None
        resource = make_scim_user(externalId="ext-123")

        result = create_user(
            user_resource=resource,
            _token=mock_token,
            provider=provider,
            db_session=mock_db_session,
        )

        resource = parse_scim_user(result, status=201)
        assert resource.externalId == "ext-123"
        mock_dal.create_user_mapping.assert_called_once()


class TestReplaceUser:
    """Tests for PUT /scim/v2/Users/{user_id}."""

    def test_success(
        self,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
        provider: ScimProvider,
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
            provider=provider,
            db_session=mock_db_session,
        )

        parse_scim_user(result)
        mock_dal.update_user.assert_called_once()
        mock_dal.commit.assert_called_once()

    def test_not_found_returns_404(
        self,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
        provider: ScimProvider,
    ) -> None:
        mock_dal.get_user.return_value = None

        result = replace_user(
            user_id=str(uuid4()),
            user_resource=make_scim_user(),
            _token=mock_token,
            provider=provider,
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
        provider: ScimProvider,
    ) -> None:
        user = make_db_user(is_active=False)
        mock_dal.get_user.return_value = user
        mock_seats.return_value = "No seats"
        resource = make_scim_user(active=True)

        result = replace_user(
            user_id=str(user.id),
            user_resource=resource,
            _token=mock_token,
            provider=provider,
            db_session=mock_db_session,
        )

        assert_scim_error(result, 403)
        mock_seats.assert_called_once()

    @patch("ee.onyx.server.scim.api.assign_user_to_default_groups__no_commit")
    @patch("ee.onyx.server.scim.api._check_seat_availability", return_value=None)
    def test_promotes_already_active_shadow_user(
        self,
        mock_seats: MagicMock,
        mock_assign: MagicMock,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
        provider: ScimProvider,
    ) -> None:
        """An already-active EXT_PERM_USER re-synced via PUT is promoted to
        STANDARD, seat-checked, and added to the Basic default group."""
        user = make_db_user(account_type=AccountType.EXT_PERM_USER, is_active=True)
        mock_dal.get_user.return_value = user
        resource = make_scim_user(active=True)

        result = replace_user(
            user_id=str(user.id),
            user_resource=resource,
            _token=mock_token,
            provider=provider,
            db_session=mock_db_session,
        )

        parse_scim_user(result)
        # Promotion consumes a seat even though the user was already active
        mock_seats.assert_called_once()
        _, kwargs = mock_dal.update_user.call_args
        assert kwargs["account_type"] == AccountType.STANDARD
        mock_assign.assert_called_once()

    @patch("ee.onyx.server.scim.api._check_seat_availability")
    def test_promotion_respects_seat_limit(
        self,
        mock_seats: MagicMock,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
        provider: ScimProvider,
    ) -> None:
        """Promoting an already-active shadow user past the cap returns 403."""
        mock_seats.return_value = "No seats"
        user = make_db_user(account_type=AccountType.EXT_PERM_USER, is_active=True)
        mock_dal.get_user.return_value = user

        result = replace_user(
            user_id=str(user.id),
            user_resource=make_scim_user(active=True),
            _token=mock_token,
            provider=provider,
            db_session=mock_db_session,
        )

        assert_scim_error(result, 403)
        mock_seats.assert_called_once()

    def test_syncs_external_id(
        self,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
        provider: ScimProvider,
    ) -> None:
        user = make_db_user()
        mock_dal.get_user.return_value = user

        resource = make_scim_user(externalId=None)

        result = replace_user(
            user_id=str(user.id),
            user_resource=resource,
            _token=mock_token,
            provider=provider,
            db_session=mock_db_session,
        )

        parse_scim_user(result)
        mock_dal.sync_user_external_id.assert_called_once_with(
            user.id,
            None,
            scim_username="test@example.com",
            fields=ScimMappingFields(
                given_name="Test",
                family_name="User",
            ),
        )


class TestPatchUser:
    """Tests for PATCH /scim/v2/Users/{user_id}."""

    def test_deactivate(
        self,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
        provider: ScimProvider,
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
            provider=provider,
            db_session=mock_db_session,
        )

        parse_scim_user(result)
        mock_dal.update_user.assert_called_once()

    @patch("ee.onyx.server.scim.api.assign_user_to_default_groups__no_commit")
    @patch("ee.onyx.server.scim.api._check_seat_availability", return_value=None)
    def test_promotes_already_active_shadow_user(
        self,
        mock_seats: MagicMock,
        mock_assign: MagicMock,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
        provider: ScimProvider,
    ) -> None:
        """PATCH on an already-active EXT_PERM_USER promotes it to STANDARD,
        seat-checks the promotion, and assigns the Basic default group."""
        user = make_db_user(account_type=AccountType.EXT_PERM_USER, is_active=True)
        mock_dal.get_user.return_value = user
        patch_req = ScimPatchRequest(
            Operations=[
                ScimPatchOperation(
                    op=ScimPatchOperationType.REPLACE,
                    path="active",
                    value=True,
                )
            ]
        )

        result = patch_user(
            user_id=str(user.id),
            patch_request=patch_req,
            _token=mock_token,
            provider=provider,
            db_session=mock_db_session,
        )

        parse_scim_user(result)
        mock_seats.assert_called_once()
        _, kwargs = mock_dal.update_user.call_args
        assert kwargs["account_type"] == AccountType.STANDARD
        mock_assign.assert_called_once()

    def test_not_found_returns_404(
        self,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
        provider: ScimProvider,
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
            provider=provider,
            db_session=mock_db_session,
        )

        assert_scim_error(result, 404)

    def test_patch_displayname_persists(
        self,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
        provider: ScimProvider,
    ) -> None:
        """PATCH displayName should update personal_name in the DB."""
        user = make_db_user(personal_name="Old Name")
        mock_dal.get_user.return_value = user
        patch_req = ScimPatchRequest(
            Operations=[
                ScimPatchOperation(
                    op=ScimPatchOperationType.REPLACE,
                    path="displayName",
                    value="New Display Name",
                )
            ]
        )

        result = patch_user(
            user_id=str(user.id),
            patch_request=patch_req,
            _token=mock_token,
            provider=provider,
            db_session=mock_db_session,
        )

        parse_scim_user(result)
        # Verify the update_user call received the new display name
        call_kwargs = mock_dal.update_user.call_args
        assert call_kwargs[1]["personal_name"] == "New Display Name"

    @patch("ee.onyx.server.scim.api.apply_user_patch")
    def test_patch_error_returns_error_response(
        self,
        mock_apply: MagicMock,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
        provider: ScimProvider,
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
            provider=provider,
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


class TestScimNameToStr:
    """Tests for _scim_name_to_str helper."""

    def test_prefers_formatted_over_components(self) -> None:
        """When client provides formatted, use it — the client knows what it wants."""
        name = ScimName(
            givenName="Jane", familyName="Smith", formatted="Dr. Jane Smith"
        )
        assert _scim_name_to_str(name) == "Dr. Jane Smith"

    def test_given_name_only(self) -> None:
        name = ScimName(givenName="Jane")
        assert _scim_name_to_str(name) == "Jane"

    def test_family_name_only(self) -> None:
        name = ScimName(familyName="Smith")
        assert _scim_name_to_str(name) == "Smith"

    def test_falls_back_to_formatted(self) -> None:
        name = ScimName(formatted="Display Name")
        assert _scim_name_to_str(name) == "Display Name"

    def test_none_returns_none(self) -> None:
        assert _scim_name_to_str(None) is None

    def test_empty_name_returns_none(self) -> None:
        name = ScimName()
        assert _scim_name_to_str(name) is None


class TestEmailCasePreservation:
    """Tests verifying email case is preserved through SCIM endpoints."""

    @patch("ee.onyx.server.scim.api._check_seat_availability", return_value=None)
    def test_create_preserves_username_case(
        self,
        mock_seats: MagicMock,  # noqa: ARG002
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
        provider: ScimProvider,
    ) -> None:
        """POST /Users with mixed-case userName returns the original case."""
        mock_dal.get_user_by_email.return_value = None
        resource = make_scim_user(userName="Alice@Example.COM")

        result = create_user(
            user_resource=resource,
            _token=mock_token,
            provider=provider,
            db_session=mock_db_session,
        )

        resource = parse_scim_user(result, status=201)
        assert resource.userName == "Alice@Example.COM"
        assert resource.emails[0].value == "Alice@Example.COM"

    def test_get_preserves_username_case(
        self,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
        provider: ScimProvider,
    ) -> None:
        """GET /Users/{id} returns the original-case userName from mapping."""
        user = make_db_user(email="alice@example.com")
        mock_dal.get_user.return_value = user
        mapping = make_user_mapping(
            external_id="ext-1",
            user_id=user.id,
            scim_username="Alice@Example.COM",
        )
        mock_dal.get_user_mapping_by_user_id.return_value = mapping

        result = get_user(
            user_id=str(user.id),
            _token=mock_token,
            provider=provider,
            db_session=mock_db_session,
        )

        resource = parse_scim_user(result)
        assert resource.userName == "Alice@Example.COM"
        assert resource.emails[0].value == "Alice@Example.COM"


class TestSeatLock:
    """Tests for the advisory lock in _check_seat_availability."""

    @patch("ee.onyx.server.scim.api.get_current_tenant_id", return_value="tenant_abc")
    @patch("ee.onyx.server.scim.api.check_seat_availability")
    @patch("ee.onyx.server.scim.api.acquire_seat_lock")
    def test_acquires_advisory_lock_before_checking(
        self,
        mock_acquire: MagicMock,
        mock_check: MagicMock,
        _mock_tenant: MagicMock,
        mock_dal: MagicMock,
    ) -> None:
        """The advisory lock must be acquired before the seat check runs."""
        call_order: list[str] = []

        mock_acquire.side_effect = lambda *_a, **_kw: call_order.append("lock")
        mock_result = MagicMock()
        mock_result.available = True
        mock_check.side_effect = lambda *_a, **_kw: (
            call_order.append("check") or mock_result
        )

        _check_seat_availability(mock_dal)

        assert call_order == ["lock", "check"]

    def test_seat_lock_id_is_stable_and_tenant_scoped(self) -> None:
        """Lock id must be deterministic and differ across tenants."""
        assert seat_lock_id_for_tenant("t1") == seat_lock_id_for_tenant("t1")
        assert seat_lock_id_for_tenant("t1") != seat_lock_id_for_tenant("t2")


# Entra ID's soft-delete rename: 32-hex objectId prefixed to the original UPN.
_TOMBSTONE_HEX = "283405f5083e4780b861a7d42f2522c2"


def _rename_patch(username: str, active: bool | None = None) -> ScimPatchRequest:
    value: dict[str, object] = {"userName": username}
    if active is not None:
        value["active"] = active
    return ScimPatchRequest(
        Operations=[ScimPatchOperation(op=ScimPatchOperationType.REPLACE, value=value)]
    )


class TestEntraTombstoneRename:
    """Entra syncs a soft-deleted user's objectId-prefixed UPN as userName.
    The email must survive; only the mapping records what the IdP sent."""

    def test_put_tombstone_keeps_email(
        self,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
        provider: ScimProvider,
    ) -> None:
        user = make_db_user(email="ralf@mane.com", is_active=True)
        mock_dal.get_user.return_value = user
        tombstone = f"{_TOMBSTONE_HEX}ralf@mane.com"

        result = replace_user(
            user_id=str(user.id),
            user_resource=make_scim_user(userName=tombstone, active=False),
            _token=mock_token,
            provider=provider,
            db_session=mock_db_session,
        )

        resource = parse_scim_user(result)
        assert resource.userName == tombstone
        _, kwargs = mock_dal.update_user.call_args
        assert kwargs["email"] is None
        assert kwargs["is_active"] is False
        assert (
            mock_dal.sync_user_external_id.call_args.kwargs["scim_username"]
            == tombstone
        )

    def test_patch_tombstone_keeps_email(
        self,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
        provider: ScimProvider,
    ) -> None:
        user = make_db_user(email="ralf@mane.com", is_active=True)
        mock_dal.get_user.return_value = user
        tombstone = f"{_TOMBSTONE_HEX}ralf@mane.com"

        result = patch_user(
            user_id=str(user.id),
            patch_request=_rename_patch(tombstone, active=False),
            _token=mock_token,
            provider=provider,
            db_session=mock_db_session,
        )

        parse_scim_user(result)
        _, kwargs = mock_dal.update_user.call_args
        assert kwargs["email"] is None
        assert kwargs["is_active"] is False

    def test_put_tombstone_of_admin_deprovision_not_blocked(
        self,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
        provider: ScimProvider,
    ) -> None:
        """Deprovisioning an admin must not trip the privileged-rename guard."""
        user = make_db_user(
            email="admin@mane.com",
            is_active=True,
            effective_permissions=[Permission.FULL_ADMIN_PANEL_ACCESS.value],
        )
        mock_dal.get_user.return_value = user
        tombstone = f"{_TOMBSTONE_HEX}admin@mane.com"

        result = replace_user(
            user_id=str(user.id),
            user_resource=make_scim_user(userName=tombstone, active=False),
            _token=mock_token,
            provider=provider,
            db_session=mock_db_session,
        )

        parse_scim_user(result)
        _, kwargs = mock_dal.update_user.call_args
        assert kwargs["email"] is None

    def test_put_hex_prefix_of_other_address_is_real_rename(
        self,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
        provider: ScimProvider,
    ) -> None:
        """A hex prefix only counts as a tombstone of the CURRENT email."""
        user = make_db_user(email="ralf@mane.com", is_active=True)
        mock_dal.get_user.return_value = user
        renamed = f"{_TOMBSTONE_HEX}other@mane.com"

        result = replace_user(
            user_id=str(user.id),
            user_resource=make_scim_user(userName=renamed, active=True),
            _token=mock_token,
            provider=provider,
            db_session=mock_db_session,
        )

        parse_scim_user(result)
        _, kwargs = mock_dal.update_user.call_args
        assert kwargs["email"] == renamed


class TestRenameCollisionAdoption:
    """A rename onto an address that an unmanaged account already owns adopts
    that account (mirror of the POST adoption path) instead of failing."""

    def _stale_and_clean(
        self, mock_dal: MagicMock, **stale_kwargs: object
    ) -> tuple[MagicMock, MagicMock, MagicMock]:
        stale = make_db_user(
            email=f"{_TOMBSTONE_HEX}ralf@mane.com", is_active=False, **stale_kwargs
        )
        clean = make_db_user(email="ralf@mane.com", is_active=True)
        stale_mapping = make_user_mapping(user_id=stale.id)
        mock_dal.get_user.return_value = stale
        mock_dal.get_user_by_email.return_value = clean
        mock_dal.get_user_mapping_by_user_id.side_effect = lambda uid: (
            stale_mapping if uid == stale.id else None
        )
        return stale, clean, stale_mapping

    def test_put_adopts_unmanaged_account(
        self,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
        provider: ScimProvider,
    ) -> None:
        stale, clean, stale_mapping = self._stale_and_clean(mock_dal)

        result = replace_user(
            user_id=str(stale.id),
            user_resource=make_scim_user(userName="ralf@mane.com", active=True),
            _token=mock_token,
            provider=provider,
            db_session=mock_db_session,
        )

        resource = parse_scim_user(result)
        assert resource.id == str(clean.id)
        mock_dal.reassign_user_mapping.assert_called_once_with(stale_mapping, clean.id)
        mock_dal.deactivate_user.assert_called_once_with(stale)
        args, kwargs = mock_dal.update_user.call_args
        assert args[0] is clean
        assert kwargs["email"] is None

    def test_patch_adopts_unmanaged_account(
        self,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
        provider: ScimProvider,
    ) -> None:
        stale, clean, stale_mapping = self._stale_and_clean(mock_dal)

        result = patch_user(
            user_id=str(stale.id),
            patch_request=_rename_patch("ralf@mane.com", active=True),
            _token=mock_token,
            provider=provider,
            db_session=mock_db_session,
        )

        resource = parse_scim_user(result)
        assert resource.id == str(clean.id)
        mock_dal.reassign_user_mapping.assert_called_once_with(stale_mapping, clean.id)
        mock_dal.deactivate_user.assert_called_once_with(stale)

    def test_patch_username_in_any_key_casing_still_resolves(
        self,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
        provider: ScimProvider,
    ) -> None:
        """Path-less values carry userName under any casing (extra='allow')."""
        stale, clean, stale_mapping = self._stale_and_clean(mock_dal)
        patch_req = ScimPatchRequest(
            Operations=[
                ScimPatchOperation(
                    op=ScimPatchOperationType.REPLACE,
                    value={"UserName": "ralf@mane.com", "active": True},
                )
            ]
        )

        result = patch_user(
            user_id=str(stale.id),
            patch_request=patch_req,
            _token=mock_token,
            provider=provider,
            db_session=mock_db_session,
        )

        resource = parse_scim_user(result)
        assert resource.id == str(clean.id)
        mock_dal.reassign_user_mapping.assert_called_once_with(stale_mapping, clean.id)

    def test_patch_without_username_op_never_resolves_a_rename(
        self,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
        provider: ScimProvider,
    ) -> None:
        """A PATCH that does not touch userName must not act on a stored
        scim_username that has drifted from the email (no adoption, no 409)."""
        user = make_db_user(email="current@mane.com", is_active=True)
        drifted_owner = make_db_user(email="drifted@mane.com", is_active=True)
        mapping = make_user_mapping(user_id=user.id, scim_username="drifted@mane.com")
        mock_dal.get_user.return_value = user
        mock_dal.get_user_by_email.return_value = drifted_owner
        mock_dal.get_user_mapping_by_user_id.side_effect = lambda uid: (
            mapping if uid == user.id else None
        )
        patch_req = ScimPatchRequest(
            Operations=[
                ScimPatchOperation(
                    op=ScimPatchOperationType.REPLACE, path="active", value=False
                )
            ]
        )

        result = patch_user(
            user_id=str(user.id),
            patch_request=patch_req,
            _token=mock_token,
            provider=provider,
            db_session=mock_db_session,
        )

        parse_scim_user(result)
        mock_dal.reassign_user_mapping.assert_not_called()
        mock_dal.deactivate_user.assert_not_called()
        args, kwargs = mock_dal.update_user.call_args
        assert args[0] is user
        assert kwargs["email"] is None
        assert kwargs["is_active"] is False

    def test_put_adoption_allowed_for_admin_source(
        self,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
        provider: ScimProvider,
    ) -> None:
        """Adoption is not a rename of the privileged account — allow it."""
        stale, clean, _ = self._stale_and_clean(
            mock_dal,
            effective_permissions=[Permission.FULL_ADMIN_PANEL_ACCESS.value],
        )

        result = replace_user(
            user_id=str(stale.id),
            user_resource=make_scim_user(userName="ralf@mane.com", active=True),
            _token=mock_token,
            provider=provider,
            db_session=mock_db_session,
        )

        resource = parse_scim_user(result)
        assert resource.id == str(clean.id)
        mock_dal.deactivate_user.assert_called_once_with(stale)

    @patch("ee.onyx.server.scim.api._check_seat_availability")
    def test_put_adoption_swap_is_seat_neutral(
        self,
        mock_seats: MagicMock,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
        provider: ScimProvider,
    ) -> None:
        """Deactivating the active source frees the seat the adopted inactive
        target needs, so a tenant at capacity must not 403."""
        mock_seats.return_value = "No seats"
        stale = make_db_user(email="old@mane.com", is_active=True)
        clean = make_db_user(email="ralf@mane.com", is_active=False)
        stale_mapping = make_user_mapping(user_id=stale.id)
        mock_dal.get_user.return_value = stale
        mock_dal.get_user_by_email.return_value = clean
        mock_dal.get_user_mapping_by_user_id.side_effect = lambda uid: (
            stale_mapping if uid == stale.id else None
        )

        result = replace_user(
            user_id=str(stale.id),
            user_resource=make_scim_user(userName="ralf@mane.com", active=True),
            _token=mock_token,
            provider=provider,
            db_session=mock_db_session,
        )

        resource = parse_scim_user(result)
        assert resource.id == str(clean.id)
        mock_seats.assert_not_called()

    @patch("ee.onyx.server.scim.api._check_seat_availability")
    def test_put_adoption_of_ext_perm_source_still_checks_seats(
        self,
        mock_seats: MagicMock,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
        provider: ScimProvider,
    ) -> None:
        """An active EXT_PERM source holds no seat, so its deactivation frees
        none and reactivating the adopted target must still be checked."""
        mock_seats.return_value = "No seats"
        stale = make_db_user(
            email="old@mane.com",
            is_active=True,
            account_type=AccountType.EXT_PERM_USER,
        )
        clean = make_db_user(email="ralf@mane.com", is_active=False)
        mock_dal.get_user.return_value = stale
        mock_dal.get_user_by_email.return_value = clean
        mock_dal.get_user_mapping_by_user_id.return_value = None

        result = replace_user(
            user_id=str(stale.id),
            user_resource=make_scim_user(userName="ralf@mane.com", active=True),
            _token=mock_token,
            provider=provider,
            db_session=mock_db_session,
        )

        assert_scim_error(result, 403)
        mock_seats.assert_called_once()

    def test_put_rename_onto_mapped_bot_returns_409(
        self,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
        provider: ScimProvider,
    ) -> None:
        """A mapped collision is a conflict no matter the account type."""
        user = make_db_user(email="old@mane.com")
        bot = make_db_user(email="bot@mane.com", account_type=AccountType.BOT)
        mock_dal.get_user.return_value = user
        mock_dal.get_user_by_email.return_value = bot
        mock_dal.get_user_mapping_by_user_id.side_effect = lambda uid: (
            make_user_mapping(user_id=uid) if uid == bot.id else None
        )

        result = replace_user(
            user_id=str(user.id),
            user_resource=make_scim_user(userName="bot@mane.com", active=True),
            _token=mock_token,
            provider=provider,
            db_session=mock_db_session,
        )

        assert_scim_error(result, 409)

    def test_put_rename_onto_bot_account_is_not_adopted(
        self,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
        provider: ScimProvider,
    ) -> None:
        """System accounts must never come under IdP control via adoption."""
        user = make_db_user(email="old@mane.com", is_active=True)
        bot = make_db_user(email="bot@mane.com", account_type=AccountType.BOT)
        mock_dal.get_user.return_value = user
        mock_dal.get_user_by_email.return_value = bot

        result = replace_user(
            user_id=str(user.id),
            user_resource=make_scim_user(userName="bot@mane.com", active=True),
            _token=mock_token,
            provider=provider,
            db_session=mock_db_session,
        )

        parse_scim_user(result)
        mock_dal.reassign_user_mapping.assert_not_called()
        mock_dal.deactivate_user.assert_not_called()
        args, _ = mock_dal.update_user.call_args
        assert args[0] is user

    def test_put_rename_onto_ext_perm_shadow_stays_a_rename(
        self,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
        provider: ScimProvider,
    ) -> None:
        """EXT_PERM shadows are merged by email reconciliation, not adopted."""
        user = make_db_user(email="old@mane.com", is_active=True)
        shadow = make_db_user(
            email="ralf@mane.com", account_type=AccountType.EXT_PERM_USER
        )
        mock_dal.get_user.return_value = user
        mock_dal.get_user_by_email.return_value = shadow

        result = replace_user(
            user_id=str(user.id),
            user_resource=make_scim_user(userName="ralf@mane.com", active=True),
            _token=mock_token,
            provider=provider,
            db_session=mock_db_session,
        )

        parse_scim_user(result)
        mock_dal.reassign_user_mapping.assert_not_called()
        mock_dal.deactivate_user.assert_not_called()
        args, kwargs = mock_dal.update_user.call_args
        assert args[0] is user
        assert kwargs["email"] == "ralf@mane.com"

    def test_put_rename_onto_scim_managed_account_returns_409(
        self,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
        provider: ScimProvider,
    ) -> None:
        user = make_db_user(email="old@mane.com")
        other = make_db_user(email="taken@mane.com")
        mock_dal.get_user.return_value = user
        mock_dal.get_user_by_email.return_value = other
        mock_dal.get_user_mapping_by_user_id.side_effect = lambda uid: (
            make_user_mapping(user_id=uid) if uid == other.id else None
        )

        result = replace_user(
            user_id=str(user.id),
            user_resource=make_scim_user(userName="taken@mane.com", active=True),
            _token=mock_token,
            provider=provider,
            db_session=mock_db_session,
        )

        assert_scim_error(result, 409)


class TestPrivilegedRename:
    """A SCIM token must not move an admin or group-manager account onto a
    different address — the address could then be claimed via first login."""

    def test_put_admin_rename_returns_403(
        self,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
        provider: ScimProvider,
    ) -> None:
        user = make_db_user(
            email="admin@mane.com",
            effective_permissions=[Permission.FULL_ADMIN_PANEL_ACCESS.value],
        )
        mock_dal.get_user.return_value = user

        result = replace_user(
            user_id=str(user.id),
            user_resource=make_scim_user(userName="moved@mane.com", active=True),
            _token=mock_token,
            provider=provider,
            db_session=mock_db_session,
        )

        assert_scim_error(result, 403)
        mock_dal.update_user.assert_not_called()

    def test_patch_group_manager_rename_returns_403(
        self,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
        provider: ScimProvider,
    ) -> None:
        user = make_db_user(email="manager@mane.com", is_group_manager=True)
        mock_dal.get_user.return_value = user

        result = patch_user(
            user_id=str(user.id),
            patch_request=_rename_patch("moved@mane.com"),
            _token=mock_token,
            provider=provider,
            db_session=mock_db_session,
        )

        assert_scim_error(result, 403)
        mock_dal.update_user.assert_not_called()

    def test_put_admin_without_rename_is_allowed(
        self,
        mock_db_session: MagicMock,
        mock_token: MagicMock,
        mock_dal: MagicMock,
        provider: ScimProvider,
    ) -> None:
        user = make_db_user(
            email="admin@mane.com",
            is_active=True,
            effective_permissions=[Permission.FULL_ADMIN_PANEL_ACCESS.value],
        )
        mock_dal.get_user.return_value = user

        result = replace_user(
            user_id=str(user.id),
            user_resource=make_scim_user(userName="admin@mane.com", active=False),
            _token=mock_token,
            provider=provider,
            db_session=mock_db_session,
        )

        parse_scim_user(result)
        _, kwargs = mock_dal.update_user.call_args
        assert kwargs["is_active"] is False
