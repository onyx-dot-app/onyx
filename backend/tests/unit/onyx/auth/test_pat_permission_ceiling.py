from unittest.mock import patch

import pytest
from starlette.requests import Request

from onyx.auth.permissions import (
    IMPLIED_PERMISSIONS,
    materialize_pat_permission_cap,
    require_permission,
)
from onyx.auth.users import uncapped_credential_user
from onyx.db.enums import AccountType, PatType, Permission
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.build.craft_gateway import gateway_request_flow
from onyx.tracing.flows import LLMFlow
from shared_configs.contextvars import UsageCredentialIdentity
from shared_configs.enums import UsageCredentialType


def _token_request(
    scopes: list[Permission] | None, cap: frozenset[Permission]
) -> Request:
    request = Request({"type": "http"})
    request.state.token_scopes = scopes
    request.state.token_permission_cap = cap
    return request


@pytest.fixture
def admin() -> User:
    return User(
        effective_permissions=[Permission.FULL_ADMIN_PANEL_ACCESS.value],
        account_type=AccountType.STANDARD,
        is_group_manager=False,
    )


@pytest.mark.asyncio
async def test_new_implication_does_not_expand_issued_token(admin: User) -> None:
    request = _token_request(
        [Permission.WRITE_CHAT],
        materialize_pat_permission_cap(admin, [Permission.WRITE_CHAT]),
    )
    with patch.dict(
        IMPLIED_PERMISSIONS,
        {
            Permission.WRITE_CHAT.value: {
                Permission.READ_CHAT.value,
                Permission.MANAGE_CONNECTORS.value,
            }
        },
    ):
        assert await require_permission(Permission.READ_CHAT)(request, admin) is admin
        with pytest.raises(OnyxError) as error:
            await require_permission(Permission.MANAGE_CONNECTORS)(request, admin)
        new_request = _token_request(
            [Permission.WRITE_CHAT],
            materialize_pat_permission_cap(admin, [Permission.WRITE_CHAT]),
        )
        assert (
            await require_permission(Permission.MANAGE_CONNECTORS)(new_request, admin)
            is admin
        )
    assert error.value.error_code is OnyxErrorCode.INSUFFICIENT_PERMISSIONS


@pytest.mark.asyncio
async def test_full_manager_cap_preserves_scoped_authority(admin: User) -> None:
    admin.effective_permissions = [Permission.BASIC_ACCESS.value]
    admin.is_group_manager = True
    request = _token_request(None, materialize_pat_permission_cap(admin, None))
    assert (
        await require_permission(Permission.MANAGE_CONNECTORS, allow_scope=True)(
            request, admin
        )
        is admin
    )
    with pytest.raises(OnyxError) as error:
        await require_permission(Permission.MANAGE_CONNECTORS)(request, admin)
    assert error.value.error_code is OnyxErrorCode.INSUFFICIENT_PERMISSIONS


@pytest.mark.parametrize(
    "scopes", [None, [Permission.BASIC_ACCESS], [Permission.FULL_ADMIN_PANEL_ACCESS]]
)
def test_gateway_requires_explicit_selection(
    admin: User, scopes: list[Permission] | None
) -> None:
    cap = materialize_pat_permission_cap(admin, scopes)
    assert Permission.READ_CHAT in cap
    assert Permission.USE_LLM_GATEWAY not in cap
    assert Permission.CRAFT_SANDBOX not in cap
    assert materialize_pat_permission_cap(
        admin, [Permission.USE_LLM_GATEWAY]
    ) == frozenset({Permission.USE_LLM_GATEWAY})


@pytest.mark.parametrize(
    "kind",
    [
        UsageCredentialType.PAT,
        UsageCredentialType.CRAFT_PAT,
        UsageCredentialType.OAUTH_PROVIDER,
    ],
)
@pytest.mark.asyncio
async def test_missing_token_cap_fails_closed(
    admin: User, kind: UsageCredentialType
) -> None:
    request = Request({"type": "http"})
    request.state.usage_credential = UsageCredentialIdentity(kind)
    with pytest.raises(OnyxError) as error:
        await require_permission(Permission.READ_SEARCH)(request, admin)
    assert error.value.error_code is OnyxErrorCode.INSUFFICIENT_PERMISSIONS


@pytest.mark.parametrize(
    "kind",
    [UsageCredentialType.SESSION, UsageCredentialType.JWT, UsageCredentialType.API_KEY],
)
@pytest.mark.asyncio
async def test_uncapped_callers_keep_credential_issuance(
    admin: User, kind: UsageCredentialType
) -> None:
    request = Request({"type": "http"})
    request.state.usage_credential = UsageCredentialIdentity(kind)
    assert await uncapped_credential_user(request, admin) is admin


@pytest.mark.parametrize(
    "kind",
    [
        UsageCredentialType.PAT,
        UsageCredentialType.CRAFT_PAT,
        UsageCredentialType.OAUTH_PROVIDER,
    ],
)
@pytest.mark.asyncio
async def test_capped_callers_cannot_issue_uncapped_credentials(
    admin: User, kind: UsageCredentialType
) -> None:
    request = Request({"type": "http"})
    request.state.usage_credential = UsageCredentialIdentity(kind)
    with pytest.raises(OnyxError) as error:
        await uncapped_credential_user(request, admin)
    assert error.value.error_code is OnyxErrorCode.INSUFFICIENT_PERMISSIONS


def test_external_gateway_never_expands_basic_or_admin_scopes(admin: User) -> None:
    for scope in (Permission.BASIC_ACCESS, Permission.FULL_ADMIN_PANEL_ACCESS):
        request = _token_request([scope], frozenset({Permission.USE_LLM_GATEWAY}))
        request.state.usage_credential = UsageCredentialIdentity(
            UsageCredentialType.PAT
        )
        assert gateway_request_flow(request, admin) is None
    request = _token_request(
        [Permission.USE_LLM_GATEWAY], frozenset({Permission.USE_LLM_GATEWAY})
    )
    request.state.usage_credential = UsageCredentialIdentity(UsageCredentialType.PAT)
    assert gateway_request_flow(request, admin) is LLMFlow.LLM_GATEWAY


def test_internal_craft_bundle_has_finite_gateway_access(admin: User) -> None:
    assert materialize_pat_permission_cap(
        admin, [Permission.CRAFT_SANDBOX], PatType.CRAFT
    ) == frozenset(
        {
            Permission.CRAFT_SANDBOX,
            Permission.READ_SEARCH,
            Permission.GENERATE_IMAGE,
            Permission.USE_LLM_GATEWAY,
        }
    )


@pytest.mark.parametrize("scopes", [None, [Permission.FULL_ADMIN_PANEL_ACCESS]])
@pytest.mark.asyncio
async def test_full_and_admin_tokens_use_stored_ceiling(
    admin: User, scopes: list[Permission] | None
) -> None:
    request = _token_request(scopes, frozenset({Permission.READ_CHAT}))
    assert await require_permission(Permission.READ_CHAT)(request, admin) is admin
    with pytest.raises(OnyxError) as error:
        await require_permission(Permission.USE_LLM_GATEWAY)(request, admin)
    assert error.value.error_code is OnyxErrorCode.INSUFFICIENT_PERMISSIONS


@pytest.mark.asyncio
async def test_empty_stored_ceiling_denies_even_full_token(admin: User) -> None:
    request = _token_request(None, frozenset())
    with pytest.raises(OnyxError) as error:
        await require_permission(Permission.READ_CHAT)(request, admin)
    assert error.value.error_code is OnyxErrorCode.INSUFFICIENT_PERMISSIONS


@pytest.mark.asyncio
async def test_user_revocation_still_restricts_stored_ceiling(admin: User) -> None:
    request = _token_request(
        [Permission.MANAGE_CONNECTORS], frozenset({Permission.MANAGE_CONNECTORS})
    )
    assert (
        await require_permission(Permission.MANAGE_CONNECTORS)(request, admin) is admin
    )
    admin.effective_permissions = [Permission.BASIC_ACCESS.value]
    with pytest.raises(OnyxError) as error:
        await require_permission(Permission.MANAGE_CONNECTORS)(request, admin)
    assert error.value.error_code is OnyxErrorCode.INSUFFICIENT_PERMISSIONS
