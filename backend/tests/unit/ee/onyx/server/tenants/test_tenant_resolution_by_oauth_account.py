"""Guards the resolution order that keeps a renamed user out of a fresh tenant.

`resolve_tenant_id` must consult the IdP subject before the email, because the
subject is the only identifier that survives an address change at the provider.
If the order inverts, a renamed user resolves nowhere and `get_or_provision_tenant`
hands them a newly provisioned empty workspace instead of the one they belong to.
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi_users import exceptions

from ee.onyx.server.tenants.provisioning import get_or_provision_tenant
from ee.onyx.server.tenants.user_mapping import resolve_tenant_id

_MAPPING_MODULE = "ee.onyx.server.tenants.user_mapping"
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
