"""``UserManager.magic_link_login``: the tenant step decides first, and a race
on the first insert, and an expired SSO session. The plain user cases run against a real database in
``tests/external_dependency_unit/auth/test_magic_link.py``."""

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import IntegrityError

from onyx.auth.magic_link import MAGIC_LINK_USE_SSO_CODE
from onyx.auth.users import UserManager
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError

_MODULE = "onyx.auth.users"
EMAIL = "someone@example.com"


@pytest.fixture
def provision() -> Iterator[AsyncMock]:
    """The tenant step, and the tenant session that must never open."""
    provision = AsyncMock()

    def ee(_module: str, attribute: str, *_args: Any) -> Any:
        if attribute == "get_or_provision_tenant":
            return provision
        return MagicMock()

    with (
        patch(f"{_MODULE}.fetch_ee_implementation_or_noop", side_effect=ee),
        patch.object(UserManager, "_tenant_session_with_bound_user_db") as session,
    ):
        yield provision
        session.assert_not_called()


@pytest.mark.asyncio
async def test_a_playground_refusal_stops_before_any_user_work(
    provision: AsyncMock,
) -> None:
    provision.side_effect = OnyxError(
        OnyxErrorCode.REGISTRATION_DISABLED, "PLAYGROUND_EMAIL_USED"
    )

    with pytest.raises(OnyxError) as excinfo:
        await UserManager(MagicMock()).magic_link_login(
            EMAIL, None, start_new_team=True, referral_source="ads"
        )

    assert excinfo.value.detail == "PLAYGROUND_EMAIL_USED"
    provision.assert_awaited_once_with(
        email=EMAIL, referral_source="ads", request=None, start_new_team=True
    )


@pytest.mark.asyncio
async def test_no_tenant_is_an_error_not_a_login_failure(
    provision: AsyncMock,
) -> None:
    provision.return_value = ""

    with pytest.raises(RuntimeError, match="no tenant"):
        await UserManager(MagicMock()).magic_link_login(EMAIL, None)


class _TenantWork:
    """The tenant session and user table, for the cases that reach them."""

    def __init__(self) -> None:
        self.session = MagicMock()
        self.session.rollback = AsyncMock()
        self.user_db = MagicMock()
        self.user_db.get_by_email = AsyncMock()
        self.insert = AsyncMock()
        self.promote = AsyncMock()
        self.seed = AsyncMock()
        self.on_after_register = AsyncMock()
        self.get_settings = MagicMock()
        self.manager = UserManager(self.user_db)


@pytest.fixture
def tenant_work() -> Iterator[_TenantWork]:
    work = _TenantWork()

    @asynccontextmanager
    async def session(_self: UserManager, _tenant_id: str) -> AsyncIterator[Any]:
        yield work.session

    def ee(_module: str, attribute: str, *_args: Any) -> Any:
        if attribute == "get_or_provision_tenant":
            return AsyncMock(return_value="public")
        return MagicMock()

    settings = MagicMock()
    settings.valid_email_domains = ()
    with (
        patch(f"{_MODULE}.fetch_ee_implementation_or_noop", side_effect=ee),
        patch.object(UserManager, "_tenant_session_with_bound_user_db", session),
        patch.object(UserManager, "_insert_web_user", work.insert),
        patch.object(UserManager, "_promote_placeholder_to_web_login", work.promote),
        patch.object(UserManager, "on_after_register", work.on_after_register),
        patch(f"{_MODULE}.seed_pinned_personas_from_featured", work.seed),
        patch(
            f"{_MODULE}.get_security_settings", return_value=settings
        ) as get_settings,
        patch(f"{_MODULE}.verify_email_in_whitelist"),
        patch(f"{_MODULE}.verify_email_domain"),
        patch(f"{_MODULE}.remove_user_from_invited_users_after_login"),
    ):
        work.get_settings = get_settings
        yield work


def _row(*, web_login: bool = True, verified: bool = True) -> MagicMock:
    row = MagicMock()
    row.oidc_expiry = None
    row.account_type.is_web_login.return_value = web_login
    row.is_verified = verified
    return row


def _lose_the_insert_to(tenant_work: _TenantWork, winner: MagicMock) -> None:
    """The lookup saw no account; another request inserted first."""
    tenant_work.user_db.get_by_email.side_effect = [None, winner]
    tenant_work.insert.side_effect = IntegrityError(
        "INSERT INTO user", {}, Exception("duplicate key")
    )


@pytest.mark.asyncio
async def test_two_links_redeemed_at_once_sign_in_to_one_account(
    tenant_work: _TenantWork,
) -> None:
    winner = _row()
    _lose_the_insert_to(tenant_work, winner)

    user = await tenant_work.manager.magic_link_login(EMAIL, None)

    assert user is winner
    tenant_work.session.rollback.assert_awaited_once()
    # The new-account steps are the inserting request's job.
    tenant_work.seed.assert_not_awaited()
    tenant_work.on_after_register.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_racing_unverified_sign_up_is_verified(
    tenant_work: _TenantWork,
) -> None:
    """A password sign-up inserted an unverified row first."""
    winner = _row(verified=False)
    verified = _row()
    _lose_the_insert_to(tenant_work, winner)
    tenant_work.user_db.update = AsyncMock(return_value=verified)

    user = await tenant_work.manager.magic_link_login(EMAIL, None)

    assert user is verified
    tenant_work.user_db.update.assert_awaited_once_with(winner, {"is_verified": True})


@pytest.mark.asyncio
async def test_a_racing_placeholder_is_promoted(tenant_work: _TenantWork) -> None:
    """A permission sync inserted a placeholder row first."""
    winner = _row(web_login=False)
    promoted = _row()
    _lose_the_insert_to(tenant_work, winner)
    tenant_work.promote.return_value = promoted

    user = await tenant_work.manager.magic_link_login(EMAIL, None)

    assert user is promoted
    tenant_work.promote.assert_awaited_once_with(
        tenant_work.session, winner, is_verified=True
    )


@pytest.mark.asyncio
async def test_a_racing_row_with_an_expired_sso_session_is_sent_to_sso(
    tenant_work: _TenantWork,
) -> None:
    winner = _row()
    winner.oidc_expiry = datetime.now(timezone.utc) - timedelta(hours=1)
    _lose_the_insert_to(tenant_work, winner)

    with pytest.raises(OnyxError) as excinfo:
        await tenant_work.manager.magic_link_login(EMAIL, None)

    assert excinfo.value.detail == MAGIC_LINK_USE_SSO_CODE


@pytest.mark.asyncio
async def test_an_integrity_error_with_no_row_is_raised(
    tenant_work: _TenantWork,
) -> None:
    tenant_work.user_db.get_by_email.side_effect = [None, None]
    tenant_work.insert.side_effect = IntegrityError(
        "INSERT INTO user", {}, Exception("some other constraint")
    )

    with pytest.raises(IntegrityError):
        await tenant_work.manager.magic_link_login(EMAIL, None)


@pytest.mark.asyncio
async def test_an_expired_sso_session_is_sent_to_sso(
    tenant_work: _TenantWork,
) -> None:
    existing = MagicMock()
    existing.oidc_expiry = datetime.now(timezone.utc) - timedelta(hours=1)
    tenant_work.user_db.get_by_email.return_value = existing

    with pytest.raises(OnyxError) as excinfo:
        await tenant_work.manager.magic_link_login(EMAIL, None)

    assert excinfo.value.detail == MAGIC_LINK_USE_SSO_CODE


@pytest.mark.asyncio
async def test_a_live_sso_session_signs_in(tenant_work: _TenantWork) -> None:
    existing = MagicMock()
    existing.oidc_expiry = datetime.now(timezone.utc) + timedelta(hours=1)
    existing.account_type.is_web_login.return_value = True
    existing.is_verified = True
    tenant_work.user_db.get_by_email.return_value = existing

    assert await tenant_work.manager.magic_link_login(EMAIL, None) is existing


@pytest.mark.asyncio
async def test_the_allowlist_is_read_strictly(tenant_work: _TenantWork) -> None:
    tenant_work.user_db.get_by_email.return_value = _row()

    await tenant_work.manager.magic_link_login(EMAIL, None)

    # A failed read must not fall back to the env list, which usually allows
    # every domain.
    tenant_work.get_settings.assert_called_once_with(allow_fallback=False)


@pytest.mark.asyncio
async def test_an_unreadable_allowlist_asks_for_a_new_link(
    tenant_work: _TenantWork,
) -> None:
    tenant_work.get_settings.side_effect = RuntimeError("db down")

    with pytest.raises(OnyxError) as excinfo:
        await tenant_work.manager.magic_link_login(EMAIL, None)

    assert excinfo.value.error_code is OnyxErrorCode.SERVICE_UNAVAILABLE
    # The link is used up by now, so only a new one can work.
    assert "new link" in excinfo.value.detail
    tenant_work.user_db.get_by_email.assert_not_awaited()
    tenant_work.insert.assert_not_awaited()
