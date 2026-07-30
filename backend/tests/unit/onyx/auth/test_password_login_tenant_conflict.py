"""Guards that an ambiguous workspace reaches the password login caller.

Resolution raises CONFLICT when an address has several pending invitations and
no active membership, because picking one would join a workspace the user never
accepted. That response tells them to choose. A blanket handler around the
lookup would flatten it into a generic credential failure, leaving the user with
no way to act and no signal that their account is fine.
"""

from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.security import OAuth2PasswordRequestForm

from onyx.auth.users import UserManager
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError

_AUTH_MODULE = "onyx.auth.users"


def _credentials(username: str) -> OAuth2PasswordRequestForm:
    return cast(
        OAuth2PasswordRequestForm,
        SimpleNamespace(username=username, password="unused"),
    )


def _manager() -> UserManager:
    manager = UserManager.__new__(UserManager)
    manager.password_helper = MagicMock()
    return manager


@pytest.mark.asyncio
async def test_ambiguous_membership_reaches_the_caller() -> None:
    conflict = OnyxError(OnyxErrorCode.CONFLICT, "choose a workspace")
    with (
        patch(f"{_AUTH_MODULE}.MULTI_TENANT", True),
        patch(
            f"{_AUTH_MODULE}.fetch_ee_implementation_or_noop",
            return_value=MagicMock(side_effect=conflict),
        ),
        patch(f"{_AUTH_MODULE}.emit_audit_event"),
    ):
        with pytest.raises(OnyxError) as exc_info:
            await _manager().authenticate(_credentials("user@example.com"))

    assert exc_info.value is conflict


@pytest.mark.asyncio
async def test_an_unmapped_address_is_still_a_generic_failure() -> None:
    """Anything that is not an actionable conflict must stay indistinguishable
    from a wrong password, so a caller cannot probe for known addresses."""
    with (
        patch(f"{_AUTH_MODULE}.MULTI_TENANT", True),
        patch(
            f"{_AUTH_MODULE}.fetch_ee_implementation_or_noop",
            return_value=MagicMock(side_effect=RuntimeError("no mapping")),
        ),
        patch(f"{_AUTH_MODULE}.emit_audit_event"),
        patch(f"{_AUTH_MODULE}.logger"),
    ):
        manager = _manager()
        hasher = cast(MagicMock, manager.password_helper).hash
        result = await manager.authenticate(_credentials("nobody@example.com"))

    assert result is None
    # The password is still hashed so timing does not leak whether the address
    # is known.
    hasher.assert_called_once()


@pytest.mark.asyncio
async def test_a_disabled_password_login_is_rejected_before_resolution() -> None:
    lookup = MagicMock()
    with (
        patch(f"{_AUTH_MODULE}.MULTI_TENANT", False),
        patch(f"{_AUTH_MODULE}.get_security_settings") as settings,
        patch(f"{_AUTH_MODULE}.fetch_ee_implementation_or_noop", return_value=lookup),
        patch(f"{_AUTH_MODULE}.emit_audit_event"),
    ):
        settings.return_value.password_auth_enabled = False
        with pytest.raises(Exception, match="PASSWORD_LOGIN_DISABLED"):
            await _manager().authenticate(_credentials("user@example.com"))

    lookup.assert_not_called()


@pytest.mark.asyncio
async def test_asyncmock_is_not_required_for_the_lookup() -> None:
    """The resolver is synchronous. Awaiting it would raise TypeError and be
    swallowed as a credential failure, hiding every routing error."""
    lookup = MagicMock(return_value="tenant_abc")
    with (
        patch(f"{_AUTH_MODULE}.MULTI_TENANT", True),
        patch(f"{_AUTH_MODULE}.fetch_ee_implementation_or_noop", return_value=lookup),
        patch(f"{_AUTH_MODULE}.emit_audit_event"),
        patch(
            f"{_AUTH_MODULE}.get_async_session_context_manager",
            side_effect=RuntimeError("stop after resolution"),
        ),
        patch(f"{_AUTH_MODULE}.SQLAlchemyUserDatabase", AsyncMock()),
    ):
        with pytest.raises(RuntimeError, match="stop after resolution"):
            await _manager().authenticate(_credentials("user@example.com"))

    lookup.assert_called_once_with(email="user@example.com")
