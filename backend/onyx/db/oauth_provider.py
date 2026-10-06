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

from onyx.auth.oauth_provider import (
    OAuthProviderTokenKind,
    generate_oauth_provider_token,
    parse_oauth_provider_token,
)
from onyx.auth.pat import hash_pat
from onyx.auth.permissions import has_global_permission
from onyx.db.engine.shard_registry import ShardConfigurationError
from onyx.db.engine.shard_routing import ShardLookupError
from onyx.db.engine.sql_engine import get_catalog_session
from onyx.db.enums import AccountType, Permission
from onyx.db.models import (
    OAuthProviderClient,
    OAuthProviderGrant,
    OAuthProviderToken,
    User,
    UserTenantMapping,
    UserTenantMappingOAuthAccount,
)
from onyx.oauth_provider.models import (
    OAuthProviderGrantInfo,
    OAuthProviderOwner,
    OAuthProviderTokenInfo,
    OAuthProviderTokenPair,
)
from shared_configs.configs import MULTI_TENANT, POSTGRES_DEFAULT_SCHEMA
from shared_configs.contextvars import get_current_tenant_id

OAUTH_PROVIDER_ACCESS_LIFETIME = timedelta(minutes=15)
OAUTH_PROVIDER_GRANT_LIFETIME = timedelta(days=30)
OAUTH_PROVIDER_STORAGE_ERRORS = (
    SQLAlchemyError,
    ShardConfigurationError,
    ShardLookupError,
)


def register_oauth_provider_client(client: OAuthClientInformationFull) -> None:
    if (
        not client.client_id
        or len(client.client_id) > 64
        or client.token_endpoint_auth_method != "none"
        or client.client_secret is not None
    ):
        raise ValueError("Only public OAuth provider clients can be registered")
    if client.client_name is not None and len(client.client_name) > 256:
        raise ValueError("OAuth provider client name exceeds 256 characters")
    with get_catalog_session() as session:
        session.add(
            OAuthProviderClient(
                client_id=client.client_id,
                client_metadata=client.model_dump(mode="json", exclude_none=True),
            )
        )
        session.commit()


def get_oauth_provider_client(client_id: str) -> OAuthClientInformationFull | None:
    if len(client_id) > 64:
        return None
    with get_catalog_session() as session:
        stored = session.get(OAuthProviderClient, client_id)
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
                update(OAuthProviderClient)
                .where(
                    OAuthProviderClient.client_id == client_id,
                    OAuthProviderClient.last_used_at == stored.last_used_at,
                )
                .values(last_used_at=now)
            )
            session.commit()
            if not cast(CursorResult[Any], result).rowcount:
                stored = session.get(
                    OAuthProviderClient, client_id, populate_existing=True
                )
                if stored is None:
                    return None
        return client


def _issue_tokens(
    session: Session, grant: OAuthProviderGrant, *, issue_refresh: bool, now: datetime
) -> OAuthProviderTokenPair:
    access_token = generate_oauth_provider_token(
        get_current_tenant_id(), OAuthProviderTokenKind.ACCESS
    )
    expires_at = min(now + OAUTH_PROVIDER_ACCESS_LIFETIME, grant.expires_at)
    session.add(
        OAuthProviderToken(
            token_hash=hash_pat(access_token),
            grant_id=grant.id,
            kind="access",
            expires_at=expires_at,
        )
    )
    refresh_token: str | None = None
    if issue_refresh:
        refresh_token = generate_oauth_provider_token(
            get_current_tenant_id(), OAuthProviderTokenKind.REFRESH
        )
        session.add(
            OAuthProviderToken(
                token_hash=hash_pat(refresh_token),
                grant_id=grant.id,
                kind="refresh",
                expires_at=grant.expires_at,
            )
        )
    session.flush()
    return OAuthProviderTokenPair(
        grant_id=grant.id,
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=expires_at,
        scopes=tuple(grant.scopes),
    )


def create_oauth_provider_grant__no_commit(
    session: Session,
    *,
    user_id: UUID,
    client_id: str,
    client_name: str,
    resource: str,
    issue_refresh: bool,
) -> OAuthProviderTokenPair | None:
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
    grant = OAuthProviderGrant(
        user_id=user_id,
        client_id=client_id,
        client_name=client_name,
        resource=resource,
        scopes=[Permission.READ_SEARCH.value],
        created_at=now,
        expires_at=now
        + (
            OAUTH_PROVIDER_GRANT_LIFETIME
            if issue_refresh
            else OAUTH_PROVIDER_ACCESS_LIFETIME
        ),
    )
    session.add(grant)
    session.flush()
    return _issue_tokens(session, grant, issue_refresh=issue_refresh, now=now)


def _lock_token_grant(
    session: Session, raw_token: str, *, resource: str, client_id: str
) -> tuple[OAuthProviderGrant, OAuthProviderToken] | None:
    parsed = parse_oauth_provider_token(raw_token)
    if parsed is None or parsed.tenant_id != get_current_tenant_id():
        return None
    grant_id = session.scalar(
        select(OAuthProviderToken.grant_id).where(
            OAuthProviderToken.token_hash == parsed.token_hash,
            OAuthProviderToken.kind == parsed.kind.value,
        )
    )
    if grant_id is None:
        return None
    grant = session.scalar(
        select(OAuthProviderGrant)
        .where(
            OAuthProviderGrant.id == grant_id,
            OAuthProviderGrant.client_id == client_id,
            OAuthProviderGrant.resource == resource,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if grant is None:
        return None
    # Reread after acquiring the grant lock: a concurrent rotation may have
    # consumed the token while this transaction waited for that lock.
    token = session.get(OAuthProviderToken, parsed.token_hash, populate_existing=True)
    if token is None:
        return None
    return grant, token


def load_oauth_provider_refresh__no_commit(
    session: Session, raw_token: str, *, client_id: str, resource: str
) -> OAuthProviderTokenInfo | None:
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
    return OAuthProviderTokenInfo(
        grant=OAuthProviderGrantInfo.model_validate(grant),
        kind=OAuthProviderTokenKind.REFRESH,
        expires_at=token.expires_at,
    )


def rotate_oauth_provider_refresh__no_commit(
    session: Session, raw_token: str, *, client_id: str, resource: str
) -> OAuthProviderTokenPair | None:
    info = load_oauth_provider_refresh__no_commit(
        session, raw_token, client_id=client_id, resource=resource
    )
    if info is None:
        return None
    token = session.get(OAuthProviderToken, hash_pat(raw_token))
    grant = session.get(OAuthProviderGrant, info.grant.id)
    if token is None or grant is None:
        return None
    now = datetime.now(timezone.utc)
    token.consumed_at = now
    return _issue_tokens(session, grant, issue_refresh=True, now=now)


async def resolve_oauth_provider_access_token(
    session: AsyncSession, raw_token: str, *, resource: str
) -> tuple[User, OAuthProviderTokenInfo] | None:
    parsed = parse_oauth_provider_token(raw_token)
    if (
        parsed is None
        or parsed.kind != OAuthProviderTokenKind.ACCESS
        or parsed.tenant_id != get_current_tenant_id()
    ):
        return None
    now = datetime.now(timezone.utc)
    row = (
        (
            await session.execute(
                select(User, OAuthProviderGrant, OAuthProviderToken)
                .join(OAuthProviderGrant, OAuthProviderGrant.user_id == User.id)
                .join(
                    OAuthProviderToken,
                    OAuthProviderToken.grant_id == OAuthProviderGrant.id,
                )
                .where(
                    OAuthProviderToken.token_hash == parsed.token_hash,
                    OAuthProviderToken.kind == "access",
                    OAuthProviderToken.expires_at > now,
                    OAuthProviderGrant.expires_at > now,
                    OAuthProviderGrant.revoked_at.is_(None),
                    OAuthProviderGrant.resource == resource,
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
    return user, OAuthProviderTokenInfo(
        grant=OAuthProviderGrantInfo.model_validate(grant),
        kind=OAuthProviderTokenKind.ACCESS,
        expires_at=token.expires_at,
    )


def revoke_oauth_provider_token__no_commit(
    session: Session, raw_token: str, *, client_id: str, resource: str
) -> None:
    locked = _lock_token_grant(
        session, raw_token, client_id=client_id, resource=resource
    )
    if locked is not None:
        grant, _ = locked
        if grant.revoked_at is None:
            grant.revoked_at = datetime.now(timezone.utc)


def list_oauth_provider_grants(
    session: Session, user_id: UUID
) -> list[OAuthProviderGrantInfo]:
    grants = session.scalars(
        select(OAuthProviderGrant)
        .where(
            OAuthProviderGrant.user_id == user_id,
            OAuthProviderGrant.revoked_at.is_(None),
            OAuthProviderGrant.expires_at > datetime.now(timezone.utc),
        )
        .order_by(OAuthProviderGrant.created_at.desc())
    )
    return [OAuthProviderGrantInfo.model_validate(grant) for grant in grants]


def revoke_oauth_provider_grant__no_commit(
    session: Session, *, grant_id: UUID, user_id: UUID
) -> bool:
    grant = session.scalar(
        select(OAuthProviderGrant)
        .where(OAuthProviderGrant.id == grant_id, OAuthProviderGrant.user_id == user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if grant is None:
        return False
    if grant.revoked_at is None:
        grant.revoked_at = datetime.now(timezone.utc)
    return True


def oauth_provider_tenant_has_members(tenant_id: str) -> bool:
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


def oauth_provider_owner_is_member(
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


def oauth_provider_owner_snapshot(user: User) -> OAuthProviderOwner:
    return OAuthProviderOwner(
        user_id=user.id,
        email=user.email,
        oauth_identities=tuple(
            (account.oauth_name, account.account_id) for account in user.oauth_accounts
        ),
    )


def get_oauth_provider_owner(
    session: Session, user_id: UUID
) -> OAuthProviderOwner | None:
    user = session.get(User, user_id, populate_existing=True)
    if user is None or not user.is_active:
        return None
    return oauth_provider_owner_snapshot(user)


def get_oauth_provider_token_owner(
    session: Session,
    raw_token: str,
    *,
    client_id: str,
    resource: str,
) -> OAuthProviderOwner | None:
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
    return oauth_provider_owner_snapshot(user)
