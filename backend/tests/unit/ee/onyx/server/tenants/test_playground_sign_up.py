"""The playground asks the control plane before it gives a sign-up a tenant.

The answer decides between provisioning, a refusal page and the join-or-new
choice. A control plane that cannot answer refuses: no tenant without the rules.
"""

import json
from collections.abc import Callable
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from ee.onyx.server.tenants.models import SignUpDomainState
from ee.onyx.server.tenants.provisioning import (
    PLAYGROUND_CHECK_FAILED_CODE,
    PLAYGROUND_REFUSAL_CODES,
    check_playground_sign_up,
    fetch_sign_up_domain_state,
    get_or_provision_tenant,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError

_MODULE = "ee.onyx.server.tenants.provisioning"
EMAIL = "someone@example.com"


# Kept before any patch: the tests patch `httpx.AsyncClient` on the module.
_ASYNC_CLIENT = httpx.AsyncClient


def _client_answering(
    handler: Callable[[httpx.Request], httpx.Response],
) -> Callable[..., httpx.AsyncClient]:
    """An httpx client that routes to `handler` instead of the network."""

    def factory(**kwargs: Any) -> httpx.AsyncClient:
        return _ASYNC_CLIENT(transport=httpx.MockTransport(handler), **kwargs)

    return factory


def _unreachable(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("refused", request=request)


class TestFetchSignUpDomainState:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("state", list(SignUpDomainState))
    async def test_returns_the_control_plane_answer(
        self, state: SignUpDomainState
    ) -> None:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json={"state": state.value})

        with (
            patch(f"{_MODULE}.generate_data_plane_token", return_value="token"),
            patch(f"{_MODULE}.httpx.AsyncClient", _client_answering(handler)),
        ):
            answer = await fetch_sign_up_domain_state(EMAIL)

        assert answer is state
        (request,) = seen
        assert request.url.path == "/sign-up-domain"
        assert request.headers["Authorization"] == "Bearer token"
        assert json.loads(request.content) == {"email": EMAIL}

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("handler", "error"),
        [
            (lambda _request: httpx.Response(500, text="down"), httpx.HTTPStatusError),
            (
                lambda _request: httpx.Response(200, json={"state": "something new"}),
                ValueError,
            ),
            (_unreachable, httpx.ConnectError),
        ],
        ids=["error status", "unknown state", "unreachable"],
    )
    async def test_a_failing_control_plane_raises(
        self,
        handler: Callable[[httpx.Request], httpx.Response],
        error: type[Exception],
    ) -> None:
        with (
            patch(f"{_MODULE}.generate_data_plane_token", return_value="token"),
            patch(f"{_MODULE}.httpx.AsyncClient", _client_answering(handler)),
        ):
            with pytest.raises(error):
                await fetch_sign_up_domain_state(EMAIL)


class TestCheckPlaygroundSignUp:
    @pytest.mark.asyncio
    async def test_new_passes(self) -> None:
        with patch(
            f"{_MODULE}.fetch_sign_up_domain_state",
            AsyncMock(return_value=SignUpDomainState.NEW),
        ):
            await check_playground_sign_up(EMAIL, start_new_team=False)

    @pytest.mark.asyncio
    async def test_a_control_plane_that_cannot_answer_refuses(self) -> None:
        """Even a new team: no tenant without the rules."""
        with patch(
            f"{_MODULE}.fetch_sign_up_domain_state",
            AsyncMock(side_effect=httpx.ConnectError("refused")),
        ):
            with pytest.raises(OnyxError) as exc_info:
                await check_playground_sign_up(EMAIL, start_new_team=True)

        assert exc_info.value.error_code is OnyxErrorCode.REGISTRATION_DISABLED
        assert exc_info.value.detail == PLAYGROUND_CHECK_FAILED_CODE

    @pytest.mark.asyncio
    @pytest.mark.parametrize("state", list(PLAYGROUND_REFUSAL_CODES))
    async def test_refuses_with_the_code_of_the_page(
        self, state: SignUpDomainState
    ) -> None:
        with patch(
            f"{_MODULE}.fetch_sign_up_domain_state", AsyncMock(return_value=state)
        ):
            with pytest.raises(OnyxError) as exc_info:
                await check_playground_sign_up(EMAIL, start_new_team=False)

        assert exc_info.value.error_code is OnyxErrorCode.REGISTRATION_DISABLED
        assert exc_info.value.detail == f"PLAYGROUND_{state.value.upper()}"

    @pytest.mark.asyncio
    async def test_a_new_team_passes_a_running_trial(self) -> None:
        with patch(
            f"{_MODULE}.fetch_sign_up_domain_state",
            AsyncMock(return_value=SignUpDomainState.ACTIVE_TENANT),
        ):
            await check_playground_sign_up(EMAIL, start_new_team=True)

    @pytest.mark.asyncio
    async def test_a_new_team_does_not_pass_the_limit(self) -> None:
        with patch(
            f"{_MODULE}.fetch_sign_up_domain_state",
            AsyncMock(return_value=SignUpDomainState.LIMIT_REACHED),
        ):
            with pytest.raises(OnyxError) as exc_info:
                await check_playground_sign_up(EMAIL, start_new_team=True)

        assert exc_info.value.detail == "PLAYGROUND_LIMIT_REACHED"


class TestGetOrProvisionTenant:
    """The check sits after the mapping lookup and before provisioning."""

    @staticmethod
    def _provisioning(*, playground: bool, check: AsyncMock) -> Any:
        """Patch a pool tenant into place so the call completes without a database."""
        return (
            patch(f"{_MODULE}.MULTI_TENANT", True),
            patch(f"{_MODULE}.IS_PLAYGROUND", playground),
            patch(f"{_MODULE}.DEV_MODE", True),
            patch(f"{_MODULE}.resolve_tenant_id", return_value=None),
            patch(f"{_MODULE}.check_playground_sign_up", check),
            patch(
                f"{_MODULE}.get_available_tenant", AsyncMock(return_value="tenant_pool")
            ),
            patch(f"{_MODULE}.run_alembic_migrations", MagicMock()),
            patch(f"{_MODULE}.assign_tenant_to_user", AsyncMock()),
        )

    @pytest.mark.asyncio
    async def test_cloud_never_asks(self) -> None:
        check = AsyncMock()
        with _patch_all(self._provisioning(playground=False, check=check)):
            tenant_id = await get_or_provision_tenant(email=EMAIL, start_new_team=True)

        assert tenant_id == "tenant_pool"
        check.assert_not_called()

    @pytest.mark.asyncio
    async def test_playground_asks_before_provisioning(self) -> None:
        check = AsyncMock()
        with _patch_all(self._provisioning(playground=True, check=check)):
            tenant_id = await get_or_provision_tenant(email=EMAIL, start_new_team=True)

        assert tenant_id == "tenant_pool"
        check.assert_awaited_once_with(EMAIL, True)

    @pytest.mark.asyncio
    async def test_a_refusal_reaches_the_caller_unchanged(self) -> None:
        """Not the 500 that provisioning errors turn into."""
        refusal = OnyxError(
            OnyxErrorCode.REGISTRATION_DISABLED, "PLAYGROUND_LIMIT_REACHED"
        )
        check = AsyncMock(side_effect=refusal)
        available = AsyncMock()
        with (
            _patch_all(self._provisioning(playground=True, check=check)),
            patch(f"{_MODULE}.get_available_tenant", available),
        ):
            with pytest.raises(OnyxError) as exc_info:
                await get_or_provision_tenant(email=EMAIL)

        assert exc_info.value is refusal
        available.assert_not_called()


class _patch_all:
    """Enter several `patch` objects as one context manager."""

    def __init__(self, patches: tuple[Any, ...]) -> None:
        self._patches = patches

    def __enter__(self) -> None:
        for p in self._patches:
            p.__enter__()

    def __exit__(self, *exc: Any) -> None:
        for p in reversed(self._patches):
            p.__exit__(*exc)
