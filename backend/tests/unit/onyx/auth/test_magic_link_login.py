"""``UserManager.magic_link_login`` before any user work: the tenant step
decides first. The user cases run against a real database in
``tests/external_dependency_unit/auth/test_magic_link.py``."""

from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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
