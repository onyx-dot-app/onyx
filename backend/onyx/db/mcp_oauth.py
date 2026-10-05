from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from typing import Any, cast
from uuid import UUID

from mcp.shared.auth import OAuthClientInformationFull
from sqlalchemy import or_, select, tuple_, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from onyx.auth.mcp_oauth import (
    MCPOAuthTokenKind,
    generate_mcp_oauth_token,
    hash_mcp_oauth_token,
    parse_mcp_oauth_token,
)
from onyx.auth.permissions import has_global_permission
from onyx.db.engine.shard_registry import ShardConfigurationError
from onyx.db.engine.shard_routing import ShardLookupError
from onyx.db.engine.sql_engine import get_catalog_session
from onyx.db.enums import AccountType, Permission
from onyx.db.models import (
    MCPOAuthClient,
    MCPOAuthGrant,
    MCPOAuthToken,
    User,
    UserTenantMapping,
    UserTenantMappingOAuthAccount,
)
from onyx.mcp_oauth.models import (
    MCPOAuthGrantInfo,
    MCPOAuthTokenInfo,
    MCPOAuthTokenPair,
)
from shared_configs.configs import MULTI_TENANT, POSTGRES_DEFAULT_SCHEMA
from shared_configs.contextvars import get_current_tenant_id

MCP_OAUTH_ACCESS_LIFETIME = timedelta(minutes=15)
MCP_OAUTH_GRANT_LIFETIME = timedelta(days=30)
MCP_OAUTH_STORAGE_ERRORS = (SQLAlchemyError, ShardConfigurationError, ShardLookupError)


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


def register_mcp_oauth_client(client: OAuthClientInformationFull) -> None:
    if (
        not client.client_id
        or len(client.client_id) > 64
        or client.token_endpoint_auth_method != "none"
        or client.client_secret is not None
    ):
        raise ValueError("Only public MCP OAuth clients can be registered")
    with get_catalog_session() as session:
        session.add(
            MCPOAuthClient(
                client_id=client.client_id,
                client_metadata=client.model_dump(mode="json", exclude_none=True),
            )
        )
        session.commit()


def get_mcp_oauth_client(client_id: str) -> OAuthClientInformationFull | None:
    if len(client_id) > 64:
        return None
    with get_catalog_session() as session:
        stored = session.get(MCPOAuthClient, client_id)
        if stored is None:
            return None
        client = OAuthClientInformationFull.model_validate(stored.client_metadata)
        if (
            client.client_id != client_id
            or client.token_endpoint_auth_method != "none"
            or client.client_secret is not None
        ):
            return None
        now = datetime.now(timezone.utc)
        if now - stored.last_used_at >= timedelta(minutes=5):
            result = session.execute(
                update(MCPOAuthClient)
                .where(
                    MCPOAuthClient.client_id == client_id,
                    MCPOAuthClient.last_used_at == stored.last_used_at,
                )
                .values(last_used_at=now)
            )
            session.commit()
            if not cast(CursorResult[Any], result).rowcount:
                stored = session.get(MCPOAuthClient, client_id, populate_existing=True)
                if stored is None:
                    return None
        return client


def _issue_tokens(
    session: Session, grant: MCPOAuthGrant, *, issue_refresh: bool, now: datetime
) -> MCPOAuthTokenPair:
    access_token = generate_mcp_oauth_token(
        get_current_tenant_id(), MCPOAuthTokenKind.ACCESS
    )
    expires_at = min(now + MCP_OAUTH_ACCESS_LIFETIME, grant.expires_at)
    session.add(
        MCPOAuthToken(
            token_hash=hash_mcp_oauth_token(access_token),
            grant_id=grant.id,
            kind="access",
            expires_at=expires_at,
        )
    )
    refresh_token: str | None = None
    if issue_refresh:
        refresh_token = generate_mcp_oauth_token(
            get_current_tenant_id(), MCPOAuthTokenKind.REFRESH
        )
        session.add(
            MCPOAuthToken(
                token_hash=hash_mcp_oauth_token(refresh_token),
                grant_id=grant.id,
                kind="refresh",
                expires_at=grant.expires_at,
            )
        )
    session.flush()
    return MCPOAuthTokenPair(
        grant_id=grant.id,
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=expires_at,
        scopes=tuple(grant.scopes),
    )


def create_mcp_oauth_grant__no_commit(
    session: Session,
    *,
    user_id: UUID,
    client_id: str,
    client_name: str,
    resource: str,
    issue_refresh: bool,
) -> MCPOAuthTokenPair | None:
    user = session.get(User, user_id, populate_existing=True)
    if (
        user is None
        or not user.is_active
        or user.account_type != AccountType.STANDARD
        or not has_global_permission(user, Permission.READ_SEARCH)
        or not has_global_permission(user, Permission.CREATE_USER_API_KEYS)
    ):
        return None
    now = datetime.now(timezone.utc)
    grant = MCPOAuthGrant(
        user_id=user_id,
        client_id=client_id,
        client_name=client_name,
        resource=resource,
        scopes=[Permission.READ_SEARCH.value],
        created_at=now,
        expires_at=now
        + (MCP_OAUTH_GRANT_LIFETIME if issue_refresh else MCP_OAUTH_ACCESS_LIFETIME),
    )
    session.add(grant)
    session.flush()
    return _issue_tokens(session, grant, issue_refresh=issue_refresh, now=now)


def _lock_token_grant(
    session: Session, raw_token: str, *, resource: str, client_id: str
) -> tuple[MCPOAuthGrant, MCPOAuthToken] | None:
    parsed = parse_mcp_oauth_token(raw_token)
    if parsed is None or parsed.tenant_id != get_current_tenant_id():
        return None
    grant_id = session.scalar(
        select(MCPOAuthToken.grant_id).where(
            MCPOAuthToken.token_hash == parsed.token_hash,
            MCPOAuthToken.kind == parsed.kind.value,
        )
    )
    if grant_id is None:
        return None
    grant = session.scalar(
        select(MCPOAuthGrant)
        .where(
            MCPOAuthGrant.id == grant_id,
            MCPOAuthGrant.client_id == client_id,
            MCPOAuthGrant.resource == resource,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if grant is None:
        return None
    # Reread after acquiring the grant lock: a concurrent rotation may have
    # consumed the token while this transaction waited for that lock.
    token = session.get(MCPOAuthToken, parsed.token_hash, populate_existing=True)
    if token is None:
        return None
    return grant, token


def load_mcp_oauth_refresh__no_commit(
    session: Session, raw_token: str, *, client_id: str, resource: str
) -> MCPOAuthTokenInfo | None:
    locked = _lock_token_grant(
        session, raw_token, client_id=client_id, resource=resource
    )
    if locked is None:
        return None
    grant, token = locked
    now = datetime.now(timezone.utc)
    if (
        token.kind != "refresh"
        or grant.revoked_at is not None
        or grant.expires_at <= now
        or token.expires_at <= now
    ):
        return None
    if token.consumed_at is not None:
        grant.revoked_at = now
        session.flush()
        return None
    user = session.get(User, grant.user_id, populate_existing=True)
    if user is None or not user.is_active or user.account_type != AccountType.STANDARD:
        return None
    return MCPOAuthTokenInfo(
        grant=MCPOAuthGrantInfo.model_validate(grant),
        kind=MCPOAuthTokenKind.REFRESH,
        expires_at=token.expires_at,
    )


def rotate_mcp_oauth_refresh__no_commit(
    session: Session, raw_token: str, *, client_id: str, resource: str
) -> MCPOAuthTokenPair | None:
    info = load_mcp_oauth_refresh__no_commit(
        session, raw_token, client_id=client_id, resource=resource
    )
    if info is None:
        return None
    token = session.get(MCPOAuthToken, hash_mcp_oauth_token(raw_token))
    grant = session.get(MCPOAuthGrant, info.grant.id)
    if token is None or grant is None:
        return None
    now = datetime.now(timezone.utc)
    token.consumed_at = now
    return _issue_tokens(session, grant, issue_refresh=True, now=now)


async def resolve_mcp_oauth_access_token(
    session: AsyncSession, raw_token: str, *, resource: str
) -> tuple[User, MCPOAuthTokenInfo] | None:
    parsed = parse_mcp_oauth_token(raw_token)
    if (
        parsed is None
        or parsed.kind != MCPOAuthTokenKind.ACCESS
        or parsed.tenant_id != get_current_tenant_id()
    ):
        return None
    now = datetime.now(timezone.utc)
    row = (
        (
            await session.execute(
                select(User, MCPOAuthGrant, MCPOAuthToken)
                .join(MCPOAuthGrant, MCPOAuthGrant.user_id == User.id)
                .join(MCPOAuthToken, MCPOAuthToken.grant_id == MCPOAuthGrant.id)
                .where(
                    MCPOAuthToken.token_hash == parsed.token_hash,
                    MCPOAuthToken.kind == "access",
                    MCPOAuthToken.expires_at > now,
                    MCPOAuthGrant.expires_at > now,
                    MCPOAuthGrant.revoked_at.is_(None),
                    MCPOAuthGrant.resource == resource,
                    User.__table__.c.is_active.is_(True),
                    User.account_type == AccountType.STANDARD,
                )
            )
        )
        .unique()
        .one_or_none()
    )
    if row is None:
        return None
    user, grant, token = row
    return user, MCPOAuthTokenInfo(
        grant=MCPOAuthGrantInfo.model_validate(grant),
        kind=MCPOAuthTokenKind.ACCESS,
        expires_at=token.expires_at,
    )


def revoke_mcp_oauth_token__no_commit(
    session: Session, raw_token: str, *, client_id: str, resource: str
) -> None:
    locked = _lock_token_grant(
        session, raw_token, client_id=client_id, resource=resource
    )
    if locked is not None:
        grant, _ = locked
        if grant.revoked_at is None:
            grant.revoked_at = datetime.now(timezone.utc)


def list_mcp_oauth_grants(session: Session, user_id: UUID) -> list[MCPOAuthGrantInfo]:
    grants = session.scalars(
        select(MCPOAuthGrant)
        .where(
            MCPOAuthGrant.user_id == user_id,
            MCPOAuthGrant.revoked_at.is_(None),
            MCPOAuthGrant.expires_at > datetime.now(timezone.utc),
        )
        .order_by(MCPOAuthGrant.created_at.desc())
    )
    return [MCPOAuthGrantInfo.model_validate(grant) for grant in grants]


def revoke_mcp_oauth_grant__no_commit(
    session: Session, *, grant_id: UUID, user_id: UUID
) -> bool:
    grant = session.scalar(
        select(MCPOAuthGrant)
        .where(MCPOAuthGrant.id == grant_id, MCPOAuthGrant.user_id == user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if grant is None:
        return False
    if grant.revoked_at is None:
        grant.revoked_at = datetime.now(timezone.utc)
    return True
