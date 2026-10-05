from collections.abc import AsyncGenerator, Generator
from datetime import datetime, timedelta, timezone
from threading import Barrier
from typing import Literal
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from mcp.shared.auth import OAuthClientInformationFull
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from onyx.auth.pat import hash_pat
from onyx.db.engine.async_sql_engine import (
    get_async_session_context_manager,
    reset_sqlalchemy_async_engine,
)
from onyx.db.engine.sql_engine import (
    get_catalog_session,
    get_session_with_current_tenant,
)
from onyx.db.enums import Permission
from onyx.db.models import (
    OAuthProviderClient,
    OAuthProviderGrant,
    OAuthProviderToken,
    User,
)
from onyx.db.oauth_provider import (
    OAUTH_PROVIDER_ACCESS_LIFETIME,
    create_oauth_provider_grant__no_commit,
    get_oauth_provider_client,
    load_oauth_provider_refresh__no_commit,
    register_oauth_provider_client,
    resolve_oauth_provider_access_token,
    revoke_oauth_provider_grant__no_commit,
    revoke_oauth_provider_token__no_commit,
    rotate_oauth_provider_refresh__no_commit,
)
from onyx.oauth_provider.models import OAuthProviderTokenInfo
from onyx.utils.threadpool_concurrency import run_functions_tuples_in_parallel
from shared_configs.contextvars import (
    CURRENT_TENANT_ID_CONTEXTVAR,
    get_current_tenant_id,
)
from tests.external_dependency_unit.conftest import create_test_user, delete_test_user

pytestmark = pytest.mark.usefixtures("tenant_context")


@pytest_asyncio.fixture(scope="module", loop_scope="module", autouse=True)
async def close_storage_async_pool() -> AsyncGenerator[None, None]:
    yield
    await reset_sqlalchemy_async_engine()


_RESOURCE = "https://onyx.example.com/mcp/"
_OTHER_RESOURCE = "https://onyx.example.com/other-mcp/"


@pytest.fixture
def oauth_provider_rows(
    db_session: Session,
) -> Generator["_OAuthProviderRows", None, None]:
    rows = _OAuthProviderRows(db_session)
    try:
        yield rows
    finally:
        rows.cleanup()


class _OAuthProviderRows:
    def __init__(self, db_session: Session) -> None:
        self.db_session = db_session
        self.users: list[User] = []
        self.client_ids: list[str] = []

    def create_user(
        self,
        *,
        email_prefix: str = "oauth_provider_storage",
        permissions: list[Permission] | None = None,
        is_active: bool = True,
    ) -> User:
        user = create_test_user(
            self.db_session,
            email_prefix,
            assign_default_group=False,
        )
        user.effective_permissions = [
            permission.value
            for permission in (
                permissions
                if permissions is not None
                else [Permission.READ_SEARCH, Permission.CREATE_USER_API_KEYS]
            )
        ]
        user.is_active = is_active
        self.db_session.commit()
        self.db_session.refresh(user)
        self.users.append(user)
        return user

    def create_grant(
        self,
        *,
        user: User | None = None,
        client_id: str | None = None,
        resource: str = _RESOURCE,
        issue_refresh: bool = True,
    ) -> tuple[User, str, str | None, str]:
        grant_user = user or self.create_user()
        grant_client_id = client_id or f"oauth-provider-storage-{uuid4().hex}"
        self.client_ids.append(grant_client_id)
        token_pair = create_oauth_provider_grant__no_commit(
            self.db_session,
            user_id=grant_user.id,
            client_id=grant_client_id,
            client_name="Storage test client",
            resource=resource,
            issue_refresh=issue_refresh,
        )
        self.db_session.commit()
        assert token_pair is not None
        return (
            grant_user,
            token_pair.access_token,
            token_pair.refresh_token,
            grant_client_id,
        )

    def cleanup(self) -> None:
        self.db_session.rollback()
        if self.client_ids:
            grant_ids = list(
                self.db_session.scalars(
                    select(OAuthProviderGrant.id).where(
                        OAuthProviderGrant.client_id.in_(self.client_ids)
                    )
                )
            )
            if grant_ids:
                self.db_session.execute(
                    delete(OAuthProviderToken).where(
                        OAuthProviderToken.grant_id.in_(grant_ids)
                    )
                )
                self.db_session.execute(
                    delete(OAuthProviderGrant).where(
                        OAuthProviderGrant.id.in_(grant_ids)
                    )
                )
        if self.users:
            delete_test_user(self.db_session, *self.users)
        self.db_session.commit()


def _grant_for_access_token(
    db_session: Session, access_token: str
) -> OAuthProviderGrant:
    grant = db_session.scalar(
        select(OAuthProviderGrant)
        .join(OAuthProviderToken, OAuthProviderToken.grant_id == OAuthProviderGrant.id)
        .where(OAuthProviderToken.token_hash == hash_pat(access_token))
    )
    assert grant is not None
    return grant


def _tokens_for_grant(db_session: Session, grant_id: UUID) -> list[OAuthProviderToken]:
    return list(
        db_session.scalars(
            select(OAuthProviderToken)
            .where(OAuthProviderToken.grant_id == grant_id)
            .order_by(OAuthProviderToken.kind, OAuthProviderToken.expires_at)
        )
    )


async def _resolve_access_token(
    raw_token: str,
) -> tuple[User, OAuthProviderTokenInfo] | None:
    async with get_async_session_context_manager() as async_session:
        return await resolve_oauth_provider_access_token(
            async_session, raw_token, resource=_RESOURCE
        )


def _client_information(
    client_id: str,
    *,
    token_endpoint_auth_method: Literal[
        "none", "client_secret_post", "client_secret_basic", "private_key_jwt"
    ] = "none",
    client_secret: str | None = None,
    client_name: str | None = None,
) -> OAuthClientInformationFull:
    return OAuthClientInformationFull(
        client_id=client_id,
        client_name=client_name,
        redirect_uris=["http://127.0.0.1:6274/oauth/callback"],
        token_endpoint_auth_method=token_endpoint_auth_method,
        client_secret=client_secret,
    )


def _delete_catalog_client(client_id: str) -> None:
    with get_catalog_session() as catalog_session:
        catalog_session.execute(
            delete(OAuthProviderClient).where(
                OAuthProviderClient.client_id == client_id
            )
        )
        catalog_session.commit()


def test_create_grant_stores_only_token_hashes(
    db_session: Session, oauth_provider_rows: _OAuthProviderRows
) -> None:
    _, access_token, refresh_token, _ = oauth_provider_rows.create_grant()
    assert refresh_token is not None

    grant = _grant_for_access_token(db_session, access_token)
    token_hashes = {
        token.token_hash for token in _tokens_for_grant(db_session, grant.id)
    }

    assert access_token not in token_hashes
    assert refresh_token not in token_hashes
    assert hash_pat(access_token) in token_hashes
    assert hash_pat(refresh_token) in token_hashes


def test_access_only_grant_has_no_refresh_token(
    db_session: Session, oauth_provider_rows: _OAuthProviderRows
) -> None:
    _, access_token, refresh_token, _ = oauth_provider_rows.create_grant(
        issue_refresh=False
    )

    grant = _grant_for_access_token(db_session, access_token)
    tokens = _tokens_for_grant(db_session, grant.id)
    lifetime = grant.expires_at - grant.created_at

    assert refresh_token is None
    assert [token.kind for token in tokens] == ["access"]
    assert lifetime == OAUTH_PROVIDER_ACCESS_LIFETIME


def test_load_refresh_rejects_access_token(
    db_session: Session, oauth_provider_rows: _OAuthProviderRows
) -> None:
    _, access_token, _, client_id = oauth_provider_rows.create_grant()

    loaded = load_oauth_provider_refresh__no_commit(
        db_session, access_token, client_id=client_id, resource=_RESOURCE
    )

    assert loaded is None


@pytest.mark.asyncio(loop_scope="module")
async def test_resolve_access_token_rejects_refresh_token(
    oauth_provider_rows: _OAuthProviderRows,
) -> None:
    _, _, refresh_token, _ = oauth_provider_rows.create_grant()
    assert refresh_token is not None

    assert await _resolve_access_token(refresh_token) is None


def test_rotate_refresh_preserves_grant_expiry(
    db_session: Session, oauth_provider_rows: _OAuthProviderRows
) -> None:
    _, _, refresh_token, client_id = oauth_provider_rows.create_grant()
    assert refresh_token is not None
    grant = db_session.scalar(
        select(OAuthProviderGrant).where(OAuthProviderGrant.client_id == client_id)
    )
    assert grant is not None
    original_expires_at = grant.expires_at

    rotated = rotate_oauth_provider_refresh__no_commit(
        db_session, refresh_token, client_id=client_id, resource=_RESOURCE
    )
    db_session.commit()

    assert rotated is not None
    db_session.refresh(grant)
    assert grant.expires_at == original_expires_at
    assert rotated.refresh_token is not None
    assert rotated.refresh_token != refresh_token


def test_consumed_refresh_load_revokes_committed_family(
    db_session: Session, oauth_provider_rows: _OAuthProviderRows
) -> None:
    _, _, refresh_token, client_id = oauth_provider_rows.create_grant()
    assert refresh_token is not None
    assert (
        rotate_oauth_provider_refresh__no_commit(
            db_session, refresh_token, client_id=client_id, resource=_RESOURCE
        )
        is not None
    )
    db_session.commit()

    replay = load_oauth_provider_refresh__no_commit(
        db_session, refresh_token, client_id=client_id, resource=_RESOURCE
    )
    db_session.commit()

    grant = db_session.scalar(
        select(OAuthProviderGrant).where(OAuthProviderGrant.client_id == client_id)
    )
    assert replay is None
    assert grant is not None
    assert grant.revoked_at is not None


def test_wrong_client_refresh_replay_does_not_revoke_grant(
    db_session: Session, oauth_provider_rows: _OAuthProviderRows
) -> None:
    _, _, refresh_token, client_id = oauth_provider_rows.create_grant()
    assert refresh_token is not None
    assert (
        rotate_oauth_provider_refresh__no_commit(
            db_session, refresh_token, client_id=client_id, resource=_RESOURCE
        )
        is not None
    )
    db_session.commit()

    replay = load_oauth_provider_refresh__no_commit(
        db_session,
        refresh_token,
        client_id=f"{client_id}-wrong",
        resource=_RESOURCE,
    )
    db_session.commit()

    grant = db_session.scalar(
        select(OAuthProviderGrant).where(OAuthProviderGrant.client_id == client_id)
    )
    assert replay is None
    assert grant is not None
    assert grant.revoked_at is None


def test_wrong_resource_refresh_replay_does_not_revoke_grant(
    db_session: Session, oauth_provider_rows: _OAuthProviderRows
) -> None:
    _, _, refresh_token, client_id = oauth_provider_rows.create_grant()
    assert refresh_token is not None
    assert (
        rotate_oauth_provider_refresh__no_commit(
            db_session, refresh_token, client_id=client_id, resource=_RESOURCE
        )
        is not None
    )
    db_session.commit()

    replay = load_oauth_provider_refresh__no_commit(
        db_session, refresh_token, client_id=client_id, resource=_OTHER_RESOURCE
    )
    db_session.commit()

    grant = db_session.scalar(
        select(OAuthProviderGrant).where(OAuthProviderGrant.client_id == client_id)
    )
    assert replay is None
    assert grant is not None
    assert grant.revoked_at is None


def test_revoking_consumed_refresh_invalidates_grant(
    db_session: Session, oauth_provider_rows: _OAuthProviderRows
) -> None:
    _, _, refresh_token, client_id = oauth_provider_rows.create_grant()
    assert refresh_token is not None
    assert (
        rotate_oauth_provider_refresh__no_commit(
            db_session, refresh_token, client_id=client_id, resource=_RESOURCE
        )
        is not None
    )
    db_session.commit()

    revoke_oauth_provider_token__no_commit(
        db_session, refresh_token, client_id=client_id, resource=_RESOURCE
    )
    db_session.commit()

    grant = db_session.scalar(
        select(OAuthProviderGrant).where(OAuthProviderGrant.client_id == client_id)
    )
    assert grant is not None
    assert grant.revoked_at is not None


def test_owner_revoke_does_not_revoke_another_users_grant(
    db_session: Session, oauth_provider_rows: _OAuthProviderRows
) -> None:
    owner, _, _, owner_client_id = oauth_provider_rows.create_grant()
    other_user, _, _, other_client_id = oauth_provider_rows.create_grant()
    owner_grant = db_session.scalar(
        select(OAuthProviderGrant).where(
            OAuthProviderGrant.client_id == owner_client_id
        )
    )
    other_grant = db_session.scalar(
        select(OAuthProviderGrant).where(
            OAuthProviderGrant.client_id == other_client_id
        )
    )
    assert owner_grant is not None
    assert other_grant is not None

    revoked = revoke_oauth_provider_grant__no_commit(
        db_session, grant_id=other_grant.id, user_id=owner.id
    )
    db_session.commit()

    db_session.refresh(other_grant)
    assert revoked is False
    assert other_grant.user_id == other_user.id
    assert other_grant.revoked_at is None


@pytest.mark.asyncio(loop_scope="module")
async def test_inactive_user_access_token_does_not_resolve(
    db_session: Session, oauth_provider_rows: _OAuthProviderRows
) -> None:
    user, access_token, _, _ = oauth_provider_rows.create_grant()
    user.is_active = False
    db_session.commit()

    assert await _resolve_access_token(access_token) is None


@pytest.mark.asyncio(loop_scope="module")
async def test_revoked_grant_access_token_does_not_resolve(
    db_session: Session, oauth_provider_rows: _OAuthProviderRows
) -> None:
    _, access_token, _, client_id = oauth_provider_rows.create_grant()
    grant = db_session.scalar(
        select(OAuthProviderGrant).where(OAuthProviderGrant.client_id == client_id)
    )
    assert grant is not None
    grant.revoked_at = datetime.now(timezone.utc)
    db_session.commit()

    assert await _resolve_access_token(access_token) is None


@pytest.mark.asyncio(loop_scope="module")
async def test_expired_access_token_does_not_resolve(
    db_session: Session, oauth_provider_rows: _OAuthProviderRows
) -> None:
    _, access_token, _, _ = oauth_provider_rows.create_grant()
    token = db_session.get(OAuthProviderToken, hash_pat(access_token))
    assert token is not None
    token.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db_session.commit()

    assert await _resolve_access_token(access_token) is None


@pytest.mark.asyncio(loop_scope="module")
async def test_expired_grant_blocks_access_and_refresh(
    db_session: Session, oauth_provider_rows: _OAuthProviderRows
) -> None:
    _, access_token, refresh_token, client_id = oauth_provider_rows.create_grant()
    assert refresh_token is not None
    grant = db_session.scalar(
        select(OAuthProviderGrant).where(OAuthProviderGrant.client_id == client_id)
    )
    assert grant is not None
    grant.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db_session.commit()

    assert await _resolve_access_token(access_token) is None
    assert (
        rotate_oauth_provider_refresh__no_commit(
            db_session, refresh_token, client_id=client_id, resource=_RESOURCE
        )
        is None
    )


def test_expired_refresh_token_does_not_rotate(
    db_session: Session, oauth_provider_rows: _OAuthProviderRows
) -> None:
    _, _, refresh_token, client_id = oauth_provider_rows.create_grant()
    assert refresh_token is not None
    token = db_session.get(OAuthProviderToken, hash_pat(refresh_token))
    assert token is not None
    token.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db_session.commit()

    assert (
        rotate_oauth_provider_refresh__no_commit(
            db_session, refresh_token, client_id=client_id, resource=_RESOURCE
        )
        is None
    )


@pytest.mark.asyncio(loop_scope="module")
async def test_access_token_does_not_resolve_for_other_resource(
    oauth_provider_rows: _OAuthProviderRows,
) -> None:
    _, access_token, _, _ = oauth_provider_rows.create_grant()

    async with get_async_session_context_manager() as async_session:
        resolved = await resolve_oauth_provider_access_token(
            async_session, access_token, resource=_OTHER_RESOURCE
        )

    assert resolved is None
    assert await _resolve_access_token(access_token) is not None


@pytest.mark.asyncio(loop_scope="module")
async def test_rotated_tokens_resolve_and_rotate_again(
    db_session: Session, oauth_provider_rows: _OAuthProviderRows
) -> None:
    user, _, refresh_token, client_id = oauth_provider_rows.create_grant()
    assert refresh_token is not None
    rotated = rotate_oauth_provider_refresh__no_commit(
        db_session, refresh_token, client_id=client_id, resource=_RESOURCE
    )
    db_session.commit()
    assert rotated is not None and rotated.refresh_token is not None

    resolved = await _resolve_access_token(rotated.access_token)
    rotated_again = rotate_oauth_provider_refresh__no_commit(
        db_session, rotated.refresh_token, client_id=client_id, resource=_RESOURCE
    )
    db_session.commit()

    assert resolved is not None
    resolved_user, resolved_info = resolved
    assert resolved_user.id == user.id
    assert resolved_info.grant.id == rotated.grant_id
    assert rotated_again is not None
    assert rotated_again.grant_id == rotated.grant_id


@pytest.mark.asyncio(loop_scope="module")
async def test_old_access_token_resolves_after_normal_refresh(
    db_session: Session, oauth_provider_rows: _OAuthProviderRows
) -> None:
    user, access_token, refresh_token, client_id = oauth_provider_rows.create_grant()
    assert refresh_token is not None

    rotated = rotate_oauth_provider_refresh__no_commit(
        db_session, refresh_token, client_id=client_id, resource=_RESOURCE
    )
    db_session.commit()

    resolved = await _resolve_access_token(access_token)
    assert rotated is not None
    assert resolved is not None
    resolved_user, _ = resolved
    assert resolved_user.id == user.id


@pytest.mark.asyncio(loop_scope="module")
async def test_old_access_token_stops_resolving_after_refresh_replay(
    db_session: Session, oauth_provider_rows: _OAuthProviderRows
) -> None:
    _, access_token, refresh_token, client_id = oauth_provider_rows.create_grant()
    assert refresh_token is not None
    assert (
        rotate_oauth_provider_refresh__no_commit(
            db_session, refresh_token, client_id=client_id, resource=_RESOURCE
        )
        is not None
    )
    db_session.commit()

    replay = load_oauth_provider_refresh__no_commit(
        db_session, refresh_token, client_id=client_id, resource=_RESOURCE
    )
    db_session.commit()

    assert replay is None
    assert await _resolve_access_token(access_token) is None


@pytest.mark.asyncio(loop_scope="module")
async def test_access_token_does_not_resolve_in_other_tenant(
    oauth_provider_rows: _OAuthProviderRows,
) -> None:
    _, access_token, _, _ = oauth_provider_rows.create_grant()

    async with get_async_session_context_manager() as async_session:
        token = CURRENT_TENANT_ID_CONTEXTVAR.set("other_storage_tenant")
        try:
            resolved = await resolve_oauth_provider_access_token(
                async_session, access_token, resource=_RESOURCE
            )
        finally:
            CURRENT_TENANT_ID_CONTEXTVAR.reset(token)

    assert resolved is None
    assert await _resolve_access_token(access_token) is not None


def test_create_grant_requires_user_api_key_permission(
    db_session: Session, oauth_provider_rows: _OAuthProviderRows
) -> None:
    user = oauth_provider_rows.create_user(permissions=[Permission.READ_SEARCH])
    client_id = f"oauth-provider-storage-denied-{uuid4().hex}"
    oauth_provider_rows.client_ids.append(client_id)

    token_pair = create_oauth_provider_grant__no_commit(
        db_session,
        user_id=user.id,
        client_id=client_id,
        client_name="Storage test client",
        resource=_RESOURCE,
        issue_refresh=True,
    )
    db_session.commit()

    assert token_pair is None
    assert (
        db_session.scalar(
            select(OAuthProviderGrant).where(OAuthProviderGrant.client_id == client_id)
        )
        is None
    )


def test_catalog_client_roundtrip_uses_catalog_and_restores_tenant_context() -> None:
    client_id = f"oauth-provider-storage-client-{uuid4().hex}"
    token = CURRENT_TENANT_ID_CONTEXTVAR.set("nondefault_storage_tenant")
    try:
        try:
            register_oauth_provider_client(_client_information(client_id))
            stored = get_oauth_provider_client(client_id)
        finally:
            _delete_catalog_client(client_id)
        assert get_current_tenant_id() == "nondefault_storage_tenant"
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)

    assert stored is not None
    assert stored.client_id == client_id


def test_register_client_rejects_client_secret() -> None:
    client_id = f"oauth-provider-storage-secret-{uuid4().hex}"

    with pytest.raises(ValueError, match="Only public OAuth provider clients"):
        register_oauth_provider_client(
            _client_information(client_id, client_secret="not-supported")
        )


def test_register_client_rejects_non_none_auth_method() -> None:
    client_id = f"oauth-provider-auth-method-{uuid4().hex}"

    with pytest.raises(ValueError, match="Only public OAuth provider clients"):
        register_oauth_provider_client(
            _client_information(
                client_id,
                token_endpoint_auth_method="client_secret_post",
            )
        )


def test_register_client_rejects_overlong_name() -> None:
    client_id = f"oauth-provider-long-name-{uuid4().hex}"

    with pytest.raises(ValueError, match="client name exceeds"):
        register_oauth_provider_client(
            _client_information(client_id, client_name="x" * 257)
        )


def test_concurrent_refresh_rotation_revokes_family_after_double_use(
    db_session: Session, oauth_provider_rows: _OAuthProviderRows
) -> None:
    _, _, refresh_token, client_id = oauth_provider_rows.create_grant()
    assert refresh_token is not None
    barrier = Barrier(2, timeout=10)

    def load_then_rotate() -> bool:
        with get_session_with_current_tenant() as load_session:
            loaded = load_oauth_provider_refresh__no_commit(
                load_session,
                refresh_token,
                client_id=client_id,
                resource=_RESOURCE,
            )
            load_session.commit()
        assert loaded is not None
        with get_session_with_current_tenant() as rotate_session:
            preloaded_token = rotate_session.get(
                OAuthProviderToken, hash_pat(refresh_token)
            )
            assert preloaded_token is not None
            barrier.wait()
            rotated = rotate_oauth_provider_refresh__no_commit(
                rotate_session,
                refresh_token,
                client_id=client_id,
                resource=_RESOURCE,
            )
            rotate_session.commit()
        return rotated is not None

    raw_results = run_functions_tuples_in_parallel(
        [(load_then_rotate, ()), (load_then_rotate, ())],
        max_workers=2,
        timeout=20,
    )

    db_session.expire_all()
    grant = db_session.scalar(
        select(OAuthProviderGrant).where(OAuthProviderGrant.client_id == client_id)
    )
    assert sorted(raw_results) == [False, True]
    assert grant is not None
    assert grant.revoked_at is not None
