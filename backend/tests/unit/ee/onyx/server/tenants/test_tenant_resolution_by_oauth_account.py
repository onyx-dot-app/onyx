"""Guards the resolution order that keeps a renamed user out of a fresh tenant.

`resolve_tenant_id` must consult the IdP subject before the email, because the
subject is the only identifier that survives an address change at the provider.
If the order inverts, a renamed user resolves nowhere and `get_or_provision_tenant`
hands them a newly provisioned empty workspace instead of the one they belong to.
"""

from collections.abc import Callable
from unittest.mock import MagicMock, patch

import pytest
from fastapi_users import exceptions
from sqlalchemy.dialects import postgresql

from ee.onyx.db.user_tenant_mapping import (
    _oauth_identity_matches_mapping,
    get_superseded_tenant_id_for_oauth_account,
    get_tenant_id_for_email,
    get_tenant_id_for_oauth_account,
    resolve_tenant_id,
)
from ee.onyx.server.tenants.provisioning import get_or_provision_tenant
from onyx.db.models import UserTenantMapping
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError

_MAPPING_MODULE = "ee.onyx.db.user_tenant_mapping"
_PROVISIONING_MODULE = "ee.onyx.server.tenants.provisioning"


def test_subject_wins_over_a_stale_email() -> None:
    """The renamed-user case: the address maps nowhere but the subject still does."""
    by_email = MagicMock(side_effect=exceptions.UserNotExists())
    with (
        patch(
            f"{_MAPPING_MODULE}.get_tenant_id_for_oauth_account",
            return_value="tenant_existing",
        ),
        patch(f"{_MAPPING_MODULE}.get_tenant_id_for_email", by_email),
    ):
        tenant_id = resolve_tenant_id("new-address@example.com", "google", "sub-123")

    assert tenant_id == "tenant_existing"
    by_email.assert_not_called()


def test_falls_back_to_email_when_subject_is_unstamped() -> None:
    with (
        patch(f"{_MAPPING_MODULE}.get_tenant_id_for_oauth_account", return_value=None),
        patch(
            f"{_MAPPING_MODULE}.get_tenant_id_for_email",
            return_value="tenant_from_email",
        ),
    ):
        tenant_id = resolve_tenant_id("user@example.com", "google", "sub-123")

    assert tenant_id == "tenant_from_email"


def test_an_active_email_membership_outranks_a_superseded_subject() -> None:
    """An admin moving a member into another workspace deactivates the row their
    subject is linked to. Following that link would undo the move."""
    superseded = MagicMock()
    with (
        patch(f"{_MAPPING_MODULE}.get_tenant_id_for_oauth_account", return_value=None),
        patch(
            f"{_MAPPING_MODULE}.get_superseded_tenant_id_for_oauth_account", superseded
        ),
        patch(
            f"{_MAPPING_MODULE}.get_tenant_id_for_email",
            return_value="tenant_from_email",
        ),
    ):
        tenant_id = resolve_tenant_id("current@example.com", "google", "sub-123")

    assert tenant_id == "tenant_from_email"
    superseded.assert_not_called()


def test_a_superseded_subject_answers_when_the_address_maps_nowhere() -> None:
    """The renamed-and-reassigned case: the address now belongs to someone else,
    so only the subject still names the workspace this user belongs to."""
    with (
        patch(f"{_MAPPING_MODULE}.get_tenant_id_for_oauth_account", return_value=None),
        patch(
            f"{_MAPPING_MODULE}.get_superseded_tenant_id_for_oauth_account",
            return_value="tenant_superseded",
        ),
        patch(
            f"{_MAPPING_MODULE}.get_tenant_id_for_email",
            side_effect=exceptions.UserNotExists(),
        ),
    ):
        tenant_id = resolve_tenant_id("renamed@example.com", "google", "sub-123")

    assert tenant_id == "tenant_superseded"


def test_password_login_skips_the_subject_lookup() -> None:
    by_subject = MagicMock()
    with (
        patch(f"{_MAPPING_MODULE}.get_tenant_id_for_oauth_account", by_subject),
        patch(
            f"{_MAPPING_MODULE}.get_tenant_id_for_email",
            return_value="tenant_from_email",
        ),
    ):
        tenant_id = resolve_tenant_id("user@example.com")

    assert tenant_id == "tenant_from_email"
    by_subject.assert_not_called()


def test_returns_none_when_nothing_maps() -> None:
    with (
        patch(f"{_MAPPING_MODULE}.get_tenant_id_for_oauth_account", return_value=None),
        patch(
            f"{_MAPPING_MODULE}.get_tenant_id_for_email",
            side_effect=exceptions.UserNotExists(),
        ),
    ):
        assert resolve_tenant_id("nobody@example.com", "google", "sub-123") is None


def test_subject_resolution_checks_every_linked_provider() -> None:
    subject_filter = _oauth_identity_matches_mapping("github", "sub-456")
    sql = str(
        subject_filter.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )

    assert UserTenantMapping.__tablename__ in sql
    assert "user_tenant_mapping_oauth_account" in sql
    assert "github" in sql
    assert "sub-456" in sql


@pytest.mark.asyncio
async def test_provisioning_is_skipped_when_the_login_already_resolves() -> None:
    """A resolved tenant must short-circuit before any pool or control-plane call."""
    available = MagicMock()
    with (
        patch(f"{_PROVISIONING_MODULE}.MULTI_TENANT", True),
        patch(
            f"{_PROVISIONING_MODULE}.resolve_tenant_id",
            return_value="tenant_existing",
        ),
        patch(f"{_PROVISIONING_MODULE}.get_available_tenant", available),
    ):
        tenant_id = await get_or_provision_tenant(
            email="new-address@example.com",
            oauth_name="google",
            account_id="sub-123",
        )

    assert tenant_id == "tenant_existing"
    available.assert_not_called()


@pytest.mark.asyncio
async def test_ambiguous_mapping_never_enters_provisioning() -> None:
    available = MagicMock()
    conflict = OnyxError(OnyxErrorCode.CONFLICT, "choose a workspace")
    with (
        patch(f"{_PROVISIONING_MODULE}.MULTI_TENANT", True),
        patch(
            f"{_PROVISIONING_MODULE}.resolve_tenant_id",
            side_effect=conflict,
        ),
        patch(f"{_PROVISIONING_MODULE}.get_available_tenant", available),
    ):
        with pytest.raises(OnyxError) as exc_info:
            await get_or_provision_tenant(email="user@example.com")

    assert exc_info.value is conflict
    assert exc_info.value.error_code is OnyxErrorCode.CONFLICT
    available.assert_not_called()


def test_several_pending_email_invitations_are_ambiguous() -> None:
    session_ctx = MagicMock()
    db_session = session_ctx.return_value.__enter__.return_value
    active_miss = MagicMock()
    active_miss.scalar_one_or_none.return_value = None
    inactive_two = MagicMock()
    inactive_two.scalars.return_value.all.return_value = ["tenant_a", "tenant_b"]
    db_session.execute.side_effect = [active_miss, inactive_two]

    with (
        patch(f"{_MAPPING_MODULE}.MULTI_TENANT", True),
        patch(f"{_MAPPING_MODULE}.get_catalog_session", session_ctx),
    ):
        with pytest.raises(OnyxError) as exc_info:
            get_tenant_id_for_email("user@example.com")

    assert exc_info.value.error_code is OnyxErrorCode.CONFLICT
    db_session.query.assert_not_called()
    db_session.commit.assert_not_called()


def _catalog_session(tenant_id: str | None) -> tuple[MagicMock, MagicMock]:
    session_ctx = MagicMock()
    db_session = session_ctx.return_value.__enter__.return_value
    db_session.scalar.return_value = tenant_id
    return session_ctx, db_session


@pytest.mark.parametrize(
    "lookup, expected_predicate",
    [
        (get_tenant_id_for_oauth_account, "active IS true"),
        (get_superseded_tenant_id_for_oauth_account, "active IS false"),
    ],
)
def test_each_lookup_filters_on_its_own_membership_state(
    lookup: Callable[[str, str], str | None], expected_predicate: str
) -> None:
    """Both read one linked row, so the `active` predicate is the only thing
    separating a live membership from one that yielded its address."""
    session_ctx, db_session = _catalog_session("tenant_a")

    with (
        patch(f"{_MAPPING_MODULE}.MULTI_TENANT", True),
        patch(f"{_MAPPING_MODULE}.get_catalog_session", session_ctx),
    ):
        assert lookup("google", "sub-123") == "tenant_a"

    sql = str(
        db_session.scalar.call_args[0][0].compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert expected_predicate in sql
    db_session.commit.assert_not_called()


def test_an_unlinked_subject_maps_nowhere() -> None:
    session_ctx, _ = _catalog_session(None)

    with (
        patch(f"{_MAPPING_MODULE}.MULTI_TENANT", True),
        patch(f"{_MAPPING_MODULE}.get_catalog_session", session_ctx),
    ):
        assert get_tenant_id_for_oauth_account("google", "sub-123") is None
        assert get_superseded_tenant_id_for_oauth_account("google", "sub-1") is None
