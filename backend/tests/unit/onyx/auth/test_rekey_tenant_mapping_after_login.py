"""Guards that a catalog failure cannot fail a login that already succeeded.

The provider's address is committed to the tenant database before the catalog
rekey runs on a separate connection, so a raise here would fail the login over a
row the linked subject still resolves under its old address.
"""

from unittest.mock import MagicMock, patch

import pytest

from onyx.auth.users import rekey_tenant_mapping_after_login

_AUTH_MODULE = "onyx.auth.users"
_IDENTITIES = [("google", "sub-123"), ("github", "sub-456")]


def test_a_catalog_failure_does_not_reach_the_caller() -> None:
    with (
        patch(
            f"{_AUTH_MODULE}.fetch_ee_implementation_or_noop",
            return_value=MagicMock(side_effect=RuntimeError("catalog is down")),
        ),
        patch(f"{_AUTH_MODULE}.logger") as logger,
    ):
        rekey_tenant_mapping_after_login("new@example.com", "tenant_a", _IDENTITIES)

    assert logger.warning.call_count == 1
    assert logger.warning.call_args.kwargs["exc_info"] is True


def test_the_rekey_receives_the_adopted_address_and_every_subject() -> None:
    rekey = MagicMock()
    with patch(f"{_AUTH_MODULE}.fetch_ee_implementation_or_noop", return_value=rekey):
        rekey_tenant_mapping_after_login("new@example.com", "tenant_a", _IDENTITIES)

    rekey.assert_called_once_with("new@example.com", "tenant_a", _IDENTITIES, None)


def test_the_replaced_address_is_passed_through() -> None:
    """A tenant can hold several of this user's rows, so the rekey needs the one
    the caller is moving rather than picking among them."""
    rekey = MagicMock()
    with patch(f"{_AUTH_MODULE}.fetch_ee_implementation_or_noop", return_value=rekey):
        rekey_tenant_mapping_after_login(
            "new@example.com", "tenant_a", _IDENTITIES, "old@example.com"
        )

    rekey.assert_called_once_with(
        "new@example.com", "tenant_a", _IDENTITIES, "old@example.com"
    )


def test_a_keyboard_interrupt_is_not_swallowed() -> None:
    with patch(
        f"{_AUTH_MODULE}.fetch_ee_implementation_or_noop",
        return_value=MagicMock(side_effect=KeyboardInterrupt),
    ):
        with pytest.raises(KeyboardInterrupt):
            rekey_tenant_mapping_after_login("new@example.com", "tenant_a", _IDENTITIES)
