"""Guards that /enterprise-settings/refresh-token only touches its caller.

Nothing verifies the posted userinfo, so the subject in it decides which OAuth
link `oauth_callback` resolves and rewrites. Unless the route binds that subject
to the authenticated user first, any caller can name someone else's subject and
have that person's stored tokens replaced.
"""

import uuid
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from ee.onyx.server.enterprise_settings.api import (
    RefreshTokenData,
    refresh_access_token,
)
from onyx.db.models import OAuthAccount, User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError

_API = "ee.onyx.server.enterprise_settings.api"


@pytest.fixture
def subject_owner() -> Generator[MagicMock, None, None]:
    """The user, if any, that the posted subject is already linked to."""
    with patch(f"{_API}.get_user_by_oauth_account", return_value=None) as lookup:
        yield lookup


def _user(email: str, *, subjects: list[str]) -> User:
    return User(
        id=uuid.uuid4(),
        email=email,
        hashed_password="unused",
        oauth_accounts=[
            OAuthAccount(
                id=uuid.uuid4(),
                oauth_name="custom",
                access_token="stale",
                account_id=subject,
                account_email=email,
            )
            for subject in subjects
        ],
    )


def _body(subject: str, email: str) -> RefreshTokenData:
    return RefreshTokenData(
        access_token="new-access",
        refresh_token="new-refresh",
        session={"exp": 1_800_000_000_000},
        userinfo={"userId": subject, "email": email},
    )


async def _refresh(body: RefreshTokenData, user: User) -> Any:
    user_manager = MagicMock()
    user_manager.oauth_callback = AsyncMock()
    await refresh_access_token(
        body,
        user=user,
        user_manager=user_manager,
        db_session=cast(Session, MagicMock()),
    )
    return user_manager.oauth_callback


async def _expect_rejected(body: RefreshTokenData, user: User) -> None:
    user_manager = MagicMock()
    user_manager.oauth_callback = AsyncMock()

    with pytest.raises(OnyxError) as raised:
        await refresh_access_token(
            body,
            user=user,
            user_manager=user_manager,
            db_session=cast(Session, MagicMock()),
        )

    assert raised.value.error_code is OnyxErrorCode.INSUFFICIENT_PERMISSIONS
    # Raising is not enough: the link must be untouched on the way out.
    user_manager.oauth_callback.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_subject_linked_to_another_user_is_rejected(
    subject_owner: MagicMock,
) -> None:
    subject_owner.return_value = _user(
        "victim@example.com", subjects=["victim-subject"]
    )
    caller = _user("caller@example.com", subjects=[])

    await _expect_rejected(
        _body("victim-subject", "caller@example.com"),
        caller,
    )


@pytest.mark.asyncio
async def test_another_address_cannot_claim_an_unlinked_subject(
    subject_owner: MagicMock,  # noqa: ARG001
) -> None:
    caller = _user("caller@example.com", subjects=[])

    await _expect_rejected(_body("free-subject", "someone.else@example.com"), caller)


@pytest.mark.asyncio
async def test_a_first_link_is_allowed_for_the_callers_own_address(
    subject_owner: MagicMock,  # noqa: ARG001
) -> None:
    caller = _user("caller@example.com", subjects=[])

    oauth_callback = await _refresh(
        _body("free-subject", " Caller@Example.com "), caller
    )

    assert oauth_callback.await_args.kwargs["account_id"] == "free-subject"


@contextmanager
def _multi_tenant(
    resolves_to: str | None = None, raises: OnyxError | None = None
) -> Generator[None, None, None]:
    """Multi-tenant, with the subject resolving where the callback would send it.

    `oauth_callback` picks its tenant through `get_or_provision_tenant`, which
    calls `resolve_tenant_id`, so that is what the gate has to agree with.
    """
    with (
        patch(f"{_API}.MULTI_TENANT", True),
        patch(f"{_API}.get_current_tenant_id", return_value="tenant_here"),
        patch(
            f"{_API}.resolve_tenant_id",
            side_effect=raises,
            return_value=resolves_to,
        ),
    ):
        yield


@pytest.mark.asyncio
async def test_a_subject_resolving_to_another_tenant_is_rejected(
    subject_owner: MagicMock,  # noqa: ARG001
) -> None:
    caller = _user("caller@example.com", subjects=[])

    with _multi_tenant(resolves_to="tenant_elsewhere"):
        await _expect_rejected(_body("free-subject", "caller@example.com"), caller)


@pytest.mark.asyncio
async def test_a_linked_subject_resolving_elsewhere_is_rejected(
    subject_owner: MagicMock,  # noqa: ARG001
) -> None:
    """Holding the link locally says nothing about where the catalog now points,
    so the tenant check has to apply on this branch too."""
    caller = _user("caller@example.com", subjects=["caller-subject"])

    with _multi_tenant(resolves_to="tenant_elsewhere"):
        await _expect_rejected(_body("caller-subject", "caller@example.com"), caller)


@pytest.mark.asyncio
async def test_an_ambiguous_address_is_rejected(
    subject_owner: MagicMock,  # noqa: ARG001
) -> None:
    caller = _user("caller@example.com", subjects=[])

    with _multi_tenant(
        raises=OnyxError(OnyxErrorCode.INVALID_INPUT, "several workspaces")
    ):
        await _expect_rejected(_body("free-subject", "caller@example.com"), caller)


@pytest.mark.asyncio
async def test_a_subject_that_maps_nowhere_is_allowed(
    subject_owner: MagicMock,  # noqa: ARG001
) -> None:
    caller = _user("caller@example.com", subjects=[])

    with _multi_tenant(resolves_to=None):
        oauth_callback = await _refresh(
            _body("free-subject", "caller@example.com"), caller
        )

    assert oauth_callback.await_args.kwargs["account_id"] == "free-subject"


@pytest.mark.asyncio
async def test_a_subject_resolving_to_this_tenant_is_allowed(
    subject_owner: MagicMock,  # noqa: ARG001
) -> None:
    caller = _user("caller@example.com", subjects=["caller-subject"])

    with _multi_tenant(resolves_to="tenant_here"):
        oauth_callback = await _refresh(
            _body("caller-subject", "caller@example.com"), caller
        )

    assert oauth_callback.await_args.kwargs["account_id"] == "caller-subject"


@pytest.mark.asyncio
async def test_the_callers_own_subject_refreshes_after_an_idp_rename(
    subject_owner: MagicMock,  # noqa: ARG001
) -> None:
    caller = _user("old@example.com", subjects=["caller-subject"])

    oauth_callback = await _refresh(
        _body("caller-subject", "renamed@example.com"), caller
    )

    kwargs = oauth_callback.await_args.kwargs
    assert kwargs["account_id"] == "caller-subject"
    assert kwargs["access_token"] == "new-access"
    # The stored address is used, so an unverified body cannot rename the account.
    assert kwargs["account_email"] == "old@example.com"
