from collections.abc import Sequence
from uuid import UUID

from mcp.shared.auth import OAuthClientInformationFull
from sqlalchemy import or_, select, tuple_
from sqlalchemy.orm import Session

from onyx.auth.oauth_provider import parse_oauth_provider_token
from onyx.db import oauth_provider as _oauth_provider
from onyx.db.engine.sql_engine import get_catalog_session
from onyx.db.models import (
    OAuthProviderGrant,
    OAuthProviderToken,
    User,
    UserTenantMapping,
    UserTenantMappingOAuthAccount,
)
from onyx.mcp_oauth.models import MCPOAuthOwner
from shared_configs.configs import MULTI_TENANT, POSTGRES_DEFAULT_SCHEMA
from shared_configs.contextvars import get_current_tenant_id

MCP_OAUTH_ACCESS_LIFETIME = _oauth_provider.OAUTH_PROVIDER_ACCESS_LIFETIME
MCP_OAUTH_GRANT_LIFETIME = _oauth_provider.OAUTH_PROVIDER_GRANT_LIFETIME
MCP_OAUTH_STORAGE_ERRORS = _oauth_provider.OAUTH_PROVIDER_STORAGE_ERRORS


def mcp_oauth_tenant_has_members(tenant_id: str) -> bool:
    if not MULTI_TENANT:
        return tenant_id == POSTGRES_DEFAULT_SCHEMA
    if tenant_id == POSTGRES_DEFAULT_SCHEMA:
        return False
    with get_catalog_session() as session:
        return (
            session.scalar(
                select(UserTenantMapping.tenant_id)
                .where(
                    UserTenantMapping.tenant_id == tenant_id,
                    UserTenantMapping.active.is_(True),
                )
                .limit(1)
            )
            is not None
        )


def mcp_oauth_owner_is_member(
    tenant_id: str, email: str, identities: Sequence[tuple[str, str]]
) -> bool:
    if not MULTI_TENANT:
        return tenant_id == POSTGRES_DEFAULT_SCHEMA
    subject_membership = (
        select(UserTenantMappingOAuthAccount.oauth_name)
        .where(
            UserTenantMappingOAuthAccount.tenant_id == UserTenantMapping.tenant_id,
            UserTenantMappingOAuthAccount.email == UserTenantMapping.email,
            tuple_(
                UserTenantMappingOAuthAccount.oauth_name,
                UserTenantMappingOAuthAccount.account_id,
            ).in_(identities),
        )
        .exists()
    )
    with get_catalog_session() as session:
        return (
            session.scalar(
                select(UserTenantMapping.tenant_id)
                .where(
                    UserTenantMapping.tenant_id == tenant_id,
                    UserTenantMapping.active.is_(True),
                    or_(UserTenantMapping.email == email.lower(), subject_membership),
                )
                .limit(1)
            )
            is not None
        )


def mcp_oauth_owner_snapshot(user: User) -> MCPOAuthOwner:
    return MCPOAuthOwner(
        user_id=user.id,
        email=user.email,
        oauth_identities=tuple(
            (account.oauth_name, account.account_id) for account in user.oauth_accounts
        ),
    )


def get_mcp_oauth_owner(session: Session, user_id: UUID) -> MCPOAuthOwner | None:
    user = session.get(User, user_id, populate_existing=True)
    if user is None or not user.is_active:
        return None
    return mcp_oauth_owner_snapshot(user)


def get_mcp_oauth_token_owner(
    session: Session,
    raw_token: str,
    *,
    client_id: str,
    resource: str,
) -> MCPOAuthOwner | None:
    parsed = parse_oauth_provider_token(raw_token)
    if parsed is None or parsed.tenant_id != get_current_tenant_id():
        return None
    user = (
        session.scalars(
            select(User)
            .join(OAuthProviderGrant, OAuthProviderGrant.user_id == User.id)
            .join(
                OAuthProviderToken, OAuthProviderToken.grant_id == OAuthProviderGrant.id
            )
            .where(
                OAuthProviderToken.token_hash == parsed.token_hash,
                OAuthProviderToken.kind == parsed.kind.value,
                OAuthProviderGrant.client_id == client_id,
                OAuthProviderGrant.resource == resource,
                User.__table__.c.is_active.is_(True),
            )
        )
        .unique()
        .one_or_none()
    )
    if user is None:
        return None
    return mcp_oauth_owner_snapshot(user)


def register_mcp_oauth_client(client: OAuthClientInformationFull) -> None:
    _oauth_provider.register_oauth_provider_client(client)


def get_mcp_oauth_client(client_id: str) -> OAuthClientInformationFull | None:
    return _oauth_provider.get_oauth_provider_client(client_id)


create_mcp_oauth_grant__no_commit = (
    _oauth_provider.create_oauth_provider_grant__no_commit
)
load_mcp_oauth_refresh__no_commit = (
    _oauth_provider.load_oauth_provider_refresh__no_commit
)
rotate_mcp_oauth_refresh__no_commit = (
    _oauth_provider.rotate_oauth_provider_refresh__no_commit
)
resolve_mcp_oauth_access_token = _oauth_provider.resolve_oauth_provider_access_token
revoke_mcp_oauth_token__no_commit = (
    _oauth_provider.revoke_oauth_provider_token__no_commit
)
list_mcp_oauth_grants = _oauth_provider.list_oauth_provider_grants
revoke_mcp_oauth_grant__no_commit = (
    _oauth_provider.revoke_oauth_provider_grant__no_commit
)
