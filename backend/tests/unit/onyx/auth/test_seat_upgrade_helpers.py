"""Unit tests for the seat-counted-status helpers in onyx.auth.users.

These cover the predicate that decides whether upgrading a non-web-login
user to STANDARD will add a seat (i.e. flip the user from uncounted to
counted), so the surrounding upgrade paths can short-circuit when the
upgrade is seat-neutral.

``_user_currently_counts_toward_seats`` is a thin delegator to the
canonical EE predicate ``ee/onyx/db/license.py:user_counts_toward_seats``;
the autouse fixture below wires the EE function in via a patched
``fetch_ee_implementation_or_noop`` so these tests are deterministic on
both EE and CE builds.
"""

from __future__ import annotations

from typing import Any
from typing import Iterator
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from ee.onyx.db.license import user_counts_toward_seats as _canonical
from onyx.auth.users import _upgrade_will_add_seat
from onyx.auth.users import _user_currently_counts_toward_seats
from onyx.configs.constants import ANONYMOUS_USER_EMAIL
from onyx.db.enums import AccountType


@pytest.fixture(autouse=True)
def _patch_canonical_predicate() -> Iterator[None]:
    """Wire ``_user_currently_counts_toward_seats`` to the EE predicate.

    On CE builds ``fetch_ee_implementation_or_noop`` returns a no-op that
    yields the supplied default (``False``); these tests want to validate
    the actual seat-counting logic, so we patch the lookup to return the
    canonical EE function regardless of build mode.
    """

    def fake_fetch(_module: str, name: str, _default: Any) -> Any:
        if name == "user_counts_toward_seats":
            return _canonical
        return _default

    with patch(
        "onyx.auth.users.fetch_ee_implementation_or_noop", side_effect=fake_fetch
    ):
        yield


def _user(
    *,
    is_active: bool = True,
    role: object = "BASIC",
    email: str = "u@test.com",
    account_type: object = AccountType.STANDARD,
) -> MagicMock:
    user = MagicMock()
    user.is_active = is_active
    user.role = role
    user.email = email
    user.account_type = account_type
    return user


class TestUserCurrentlyCountsTowardSeats:
    def test_active_standard_user_counts(self) -> None:
        from onyx.auth.schemas import UserRole

        assert _user_currently_counts_toward_seats(
            _user(role=UserRole.BASIC, account_type=AccountType.STANDARD)
        )

    def test_active_bot_user_counts(self) -> None:
        from onyx.auth.schemas import UserRole

        # BOT account_type is included in the seat count by design.
        assert _user_currently_counts_toward_seats(
            _user(role=UserRole.SLACK_USER, account_type=AccountType.BOT)
        )

    def test_inactive_user_does_not_count(self) -> None:
        from onyx.auth.schemas import UserRole

        assert not _user_currently_counts_toward_seats(
            _user(is_active=False, role=UserRole.BASIC)
        )

    def test_ext_perm_user_does_not_count(self) -> None:
        from onyx.auth.schemas import UserRole

        assert not _user_currently_counts_toward_seats(
            _user(role=UserRole.EXT_PERM_USER, account_type=AccountType.EXT_PERM_USER)
        )

    def test_service_account_does_not_count(self) -> None:
        from onyx.auth.schemas import UserRole

        assert not _user_currently_counts_toward_seats(
            _user(role=UserRole.BASIC, account_type=AccountType.SERVICE_ACCOUNT)
        )

    def test_anonymous_user_does_not_count(self) -> None:
        from onyx.auth.schemas import UserRole

        assert not _user_currently_counts_toward_seats(
            _user(role=UserRole.BASIC, email=ANONYMOUS_USER_EMAIL)
        )


class TestUpgradeWillAddSeat:
    def test_ext_perm_to_standard_active_adds_seat(self) -> None:
        from onyx.auth.schemas import UserRole

        before = _user(
            is_active=True,
            role=UserRole.EXT_PERM_USER,
            account_type=AccountType.EXT_PERM_USER,
        )
        assert _upgrade_will_add_seat(before, will_become_active=True)

    def test_service_account_to_standard_active_adds_seat(self) -> None:
        from onyx.auth.schemas import UserRole

        before = _user(
            is_active=True,
            role=UserRole.BASIC,
            account_type=AccountType.SERVICE_ACCOUNT,
        )
        assert _upgrade_will_add_seat(before, will_become_active=True)

    def test_inactive_to_active_standard_adds_seat(self) -> None:
        from onyx.auth.schemas import UserRole

        before = _user(
            is_active=False,
            role=UserRole.BASIC,
            account_type=AccountType.STANDARD,
        )
        assert _upgrade_will_add_seat(before, will_become_active=True)

    def test_inactive_remaining_inactive_does_not_add_seat(self) -> None:
        from onyx.auth.schemas import UserRole

        before = _user(
            is_active=False,
            role=UserRole.EXT_PERM_USER,
            account_type=AccountType.EXT_PERM_USER,
        )
        assert not _upgrade_will_add_seat(before, will_become_active=False)

    def test_bot_to_standard_does_not_add_seat(self) -> None:
        # BOT counts already; upgrade keeps it counted.
        from onyx.auth.schemas import UserRole

        before = _user(
            is_active=True,
            role=UserRole.SLACK_USER,
            account_type=AccountType.BOT,
        )
        assert not _upgrade_will_add_seat(before, will_become_active=True)

    def test_already_standard_active_does_not_add_seat(self) -> None:
        from onyx.auth.schemas import UserRole

        before = _user(
            is_active=True,
            role=UserRole.BASIC,
            account_type=AccountType.STANDARD,
        )
        assert not _upgrade_will_add_seat(before, will_become_active=True)

    def test_anonymous_email_never_adds_seat(self) -> None:
        from onyx.auth.schemas import UserRole

        before = _user(
            is_active=False,
            role=UserRole.BASIC,
            email=ANONYMOUS_USER_EMAIL,
            account_type=AccountType.EXT_PERM_USER,
        )
        assert not _upgrade_will_add_seat(before, will_become_active=True)

    def test_multi_tenant_upgrade_is_seat_neutral(self) -> None:
        """Cloud counts UserTenantMapping rows, not User attributes —
        an EXT_PERM_USER upgrade leaves the mapping count unchanged, so
        ``_upgrade_will_add_seat`` must return ``False`` to avoid
        over-billing the tenant on every promotion."""
        from onyx.auth.schemas import UserRole

        before = _user(
            is_active=True,
            role=UserRole.EXT_PERM_USER,
            account_type=AccountType.EXT_PERM_USER,
        )
        with patch("onyx.auth.users.MULTI_TENANT", True):
            assert not _upgrade_will_add_seat(before, will_become_active=True)


class TestCEDelegationFallback:
    """When the EE predicate is unavailable (CE build / noop fetch),
    ``_user_currently_counts_toward_seats`` returns the seat-conservative
    default ``False``."""

    def test_ce_returns_false(self) -> None:
        # Simulate CE: noop returns the default supplied by users.py (False).
        with patch(
            "onyx.auth.users.fetch_ee_implementation_or_noop",
            side_effect=lambda _m, _n, default: lambda *_a, **_kw: default,
        ):
            assert (
                _user_currently_counts_toward_seats(
                    _user(account_type=AccountType.STANDARD)
                )
                is False
            )
