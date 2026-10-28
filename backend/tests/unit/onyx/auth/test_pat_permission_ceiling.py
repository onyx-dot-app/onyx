from unittest.mock import patch

import pytest
from starlette.requests import Request

from onyx.auth.pat import TokenPermissionAuthority, TokenPermissionCap
from onyx.auth.permissions import (
    IMPLIED_PERMISSIONS,
    has_permission,
    intersect_pat_permission_caps,
    materialize_pat_permission_cap,
    pat_permission_cap_is_stale,
    require_permission,
)
from onyx.auth.users import uncapped_credential_user
from onyx.db.enums import AccountType, PatType, Permission, PermissionAuthority
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.build.craft_gateway import gateway_request_flow
from onyx.tracing.flows import LLMFlow
from shared_configs.contextvars import UsageCredentialIdentity
from shared_configs.enums import UsageCredentialType


def _token_request(scopes: list[Permission] | None, cap: TokenPermissionCap) -> Request:
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


@pytest.mark.parametrize("scopes", [None, [Permission.MANAGE_CONNECTORS]])
@pytest.mark.parametrize("allow_scope", [False, True])
@pytest.mark.parametrize(
    "promotion", [Permission.FULL_ADMIN_PANEL_ACCESS, Permission.MANAGE_CONNECTORS]
)
@pytest.mark.asyncio
async def test_manager_token_cannot_gain_global_authority(
    admin: User,
    scopes: list[Permission] | None,
    allow_scope: bool,
    promotion: Permission,
) -> None:
    admin.effective_permissions = [Permission.BASIC_ACCESS.value]
    admin.is_group_manager = True
    request = _token_request(scopes, materialize_pat_permission_cap(admin, scopes))
    assert (
        await require_permission(Permission.MANAGE_CONNECTORS, allow_scope=True)(
            request, admin
        )
        is admin
    )

    admin.effective_permissions = [Permission.BASIC_ACCESS.value, promotion.value]
    assert (
        has_permission(admin, Permission.MANAGE_CONNECTORS)
        is PermissionAuthority.GLOBAL
    )
    with pytest.raises(OnyxError) as error:
        await require_permission(Permission.MANAGE_CONNECTORS, allow_scope=allow_scope)(
            request, admin
        )
    assert error.value.error_code is OnyxErrorCode.INSUFFICIENT_PERMISSIONS
    assert (
        has_permission(admin, Permission.MANAGE_CONNECTORS)
        is PermissionAuthority.GLOBAL
    )

    fresh = _token_request(scopes, materialize_pat_permission_cap(admin, scopes))
    assert (
        await require_permission(Permission.MANAGE_CONNECTORS, allow_scope=allow_scope)(
            fresh, admin
        )
        is admin
    )


def test_promotion_cannot_bypass_a_secondary_handler_scope_check(
    admin: User,
) -> None:
    admin.effective_permissions = [
        Permission.BASIC_ACCESS.value,
        Permission.MANAGE_LLMS.value,
    ]
    admin.is_group_manager = True
    request = _token_request(None, materialize_pat_permission_cap(admin, None))
    cap = request.state.token_permission_cap
    assert cap[Permission.READ_USER_GROUPS] is PermissionAuthority.GLOBAL
    assert not pat_permission_cap_is_stale(admin, cap)

    admin.effective_permissions = [
        Permission.BASIC_ACCESS.value,
        Permission.MANAGE_USER_GROUPS.value,
    ]
    assert (
        has_permission(admin, Permission.MANAGE_CONNECTORS)
        is PermissionAuthority.SCOPED
    )
    assert pat_permission_cap_is_stale(admin, cap)


@pytest.mark.parametrize(
    ("child_authority", "parent_authority", "expected"),
    [
        (
            PermissionAuthority.GLOBAL,
            PermissionAuthority.GLOBAL,
            PermissionAuthority.GLOBAL,
        ),
        (
            PermissionAuthority.GLOBAL,
            PermissionAuthority.SCOPED,
            PermissionAuthority.SCOPED,
        ),
        (
            PermissionAuthority.SCOPED,
            PermissionAuthority.GLOBAL,
            PermissionAuthority.SCOPED,
        ),
        (
            PermissionAuthority.SCOPED,
            PermissionAuthority.SCOPED,
            PermissionAuthority.SCOPED,
        ),
    ],
)
def test_child_cap_keeps_the_lower_authority(
    child_authority: TokenPermissionAuthority,
    parent_authority: TokenPermissionAuthority,
    expected: TokenPermissionAuthority,
) -> None:
    child: TokenPermissionCap = {
        Permission.MANAGE_CONNECTORS: child_authority,
        Permission.READ_CHAT: PermissionAuthority.GLOBAL,
    }
    parent: TokenPermissionCap = {Permission.MANAGE_CONNECTORS: parent_authority}
    assert intersect_pat_permission_caps(child, parent) == {
        Permission.MANAGE_CONNECTORS: expected
    }


def test_removed_manager_authority_keeps_basic_permissions(admin: User) -> None:
    admin.effective_permissions = [Permission.BASIC_ACCESS.value]
    admin.is_group_manager = True
    cap = materialize_pat_permission_cap(admin, None)
    assert cap[Permission.MANAGE_CONNECTORS] is PermissionAuthority.SCOPED
    admin.is_group_manager = False
    assert not pat_permission_cap_is_stale(admin, cap)
    assert (
        has_permission(admin, Permission.MANAGE_CONNECTORS) is PermissionAuthority.NONE
    )
    assert has_permission(admin, Permission.READ_CHAT) is PermissionAuthority.GLOBAL


@pytest.mark.parametrize(
    "scopes", [None, [Permission.BASIC_ACCESS], [Permission.FULL_ADMIN_PANEL_ACCESS]]
)
def test_new_broad_token_includes_gateway_permission(
    admin: User, scopes: list[Permission] | None
) -> None:
    cap = materialize_pat_permission_cap(admin, scopes)
    assert Permission.READ_CHAT in cap
    assert Permission.USE_LLM_GATEWAY in cap
    assert Permission.CRAFT_SANDBOX not in cap
    assert materialize_pat_permission_cap(admin, [Permission.USE_LLM_GATEWAY]) == {
        Permission.USE_LLM_GATEWAY: PermissionAuthority.GLOBAL
    }


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


@pytest.mark.parametrize(
    "scopes", [None, [Permission.BASIC_ACCESS], [Permission.FULL_ADMIN_PANEL_ACCESS]]
)
def test_gateway_uses_stored_cap_without_expanding_raw_scopes(
    admin: User, scopes: list[Permission] | None
) -> None:
    request = _token_request(scopes, {Permission.READ_CHAT: PermissionAuthority.GLOBAL})
    request.state.usage_credential = UsageCredentialIdentity(UsageCredentialType.PAT)
    assert gateway_request_flow(request, admin) is None
    request.state.token_permission_cap = {
        Permission.USE_LLM_GATEWAY: PermissionAuthority.GLOBAL
    }
    assert gateway_request_flow(request, admin) is LLMFlow.LLM_GATEWAY


def test_new_chat_token_excludes_gateway_without_a_gateway_grant(admin: User) -> None:
    assert materialize_pat_permission_cap(admin, [Permission.WRITE_CHAT]) == {
        Permission.WRITE_CHAT: PermissionAuthority.GLOBAL,
        Permission.READ_CHAT: PermissionAuthority.GLOBAL,
    }
    admin.effective_permissions = [Permission.READ_CHAT.value]
    cap = materialize_pat_permission_cap(admin, None)
    assert Permission.READ_CHAT in cap
    assert Permission.USE_LLM_GATEWAY not in cap


@pytest.mark.asyncio
async def test_full_token_does_not_gain_gateway_after_owner_grant(admin: User) -> None:
    admin.effective_permissions = [Permission.READ_CHAT.value]
    request = _token_request(None, materialize_pat_permission_cap(admin, None))
    request.state.usage_credential = UsageCredentialIdentity(UsageCredentialType.PAT)

    admin.effective_permissions = [Permission.BASIC_ACCESS.value]
    with pytest.raises(OnyxError) as error:
        await require_permission(Permission.USE_LLM_GATEWAY)(request, admin)
    assert error.value.error_code is OnyxErrorCode.INSUFFICIENT_PERMISSIONS
    assert gateway_request_flow(request, admin) is None

    request.state.token_permission_cap = materialize_pat_permission_cap(admin, None)
    assert await require_permission(Permission.USE_LLM_GATEWAY)(request, admin) is admin
    assert gateway_request_flow(request, admin) is LLMFlow.LLM_GATEWAY


def test_internal_craft_bundle_has_finite_gateway_access(admin: User) -> None:
    assert materialize_pat_permission_cap(
        admin, [Permission.CRAFT_SANDBOX], PatType.CRAFT
    ) == {
        Permission.CRAFT_SANDBOX: PermissionAuthority.GLOBAL,
        Permission.READ_SEARCH: PermissionAuthority.GLOBAL,
        Permission.GENERATE_IMAGE: PermissionAuthority.GLOBAL,
        Permission.USE_LLM_GATEWAY: PermissionAuthority.GLOBAL,
    }


@pytest.mark.parametrize("scopes", [None, [Permission.FULL_ADMIN_PANEL_ACCESS]])
@pytest.mark.asyncio
async def test_full_and_admin_tokens_use_stored_ceiling(
    admin: User, scopes: list[Permission] | None
) -> None:
    request = _token_request(scopes, {Permission.READ_CHAT: PermissionAuthority.GLOBAL})
    assert await require_permission(Permission.READ_CHAT)(request, admin) is admin
    with pytest.raises(OnyxError) as error:
        await require_permission(Permission.USE_LLM_GATEWAY)(request, admin)
    assert error.value.error_code is OnyxErrorCode.INSUFFICIENT_PERMISSIONS


@pytest.mark.asyncio
async def test_empty_stored_ceiling_denies_even_full_token(admin: User) -> None:
    request = _token_request(None, {})
    with pytest.raises(OnyxError) as error:
        await require_permission(Permission.READ_CHAT)(request, admin)
    assert error.value.error_code is OnyxErrorCode.INSUFFICIENT_PERMISSIONS


@pytest.mark.asyncio
async def test_user_revocation_still_restricts_stored_ceiling(admin: User) -> None:
    request = _token_request(
        [Permission.MANAGE_CONNECTORS],
        {Permission.MANAGE_CONNECTORS: PermissionAuthority.GLOBAL},
    )
    assert (
        await require_permission(Permission.MANAGE_CONNECTORS)(request, admin) is admin
    )
    admin.effective_permissions = [Permission.BASIC_ACCESS.value]
    with pytest.raises(OnyxError) as error:
        await require_permission(Permission.MANAGE_CONNECTORS)(request, admin)
    assert error.value.error_code is OnyxErrorCode.INSUFFICIENT_PERMISSIONS
