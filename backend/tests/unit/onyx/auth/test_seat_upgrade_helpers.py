"""Unit tests for the seat-counted-status helpers in onyx.auth.users.

These cover the predicate that decides whether upgrading a non-web-login
user to STANDARD will add a seat (i.e. flip the user from uncounted to
counted), so the surrounding upgrade paths can short-circuit when the
upgrade is seat-neutral.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from onyx.auth.users import _upgrade_will_add_seat
from onyx.auth.users import _user_currently_counts_toward_seats
from onyx.configs.constants import ANONYMOUS_USER_EMAIL
from onyx.db.enums import AccountType


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
