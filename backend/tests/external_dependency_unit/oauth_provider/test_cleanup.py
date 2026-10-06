from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, Table, event, func, select, text, update
from sqlalchemy.orm import Session

from onyx.background.celery.tasks.oauth_provider import tasks
from onyx.db import oauth_provider
from onyx.db.models import OAuthProviderClient, OAuthProviderGrant, OAuthProviderToken
from onyx.db.oauth_provider import (
    delete_expired_oauth_provider_grants__no_commit,
    delete_idle_oauth_provider_clients__no_commit,
    get_oauth_provider_client,
)

_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
_RESOURCE = "https://onyx.example.com/mcp/"


@pytest.fixture
def oauth_cleanup_engine(migration_database: Engine) -> Engine:
    with migration_database.begin() as connection:
        connection.execute(text('CREATE TABLE public."user" (id UUID PRIMARY KEY)'))
        for table in (
            OAuthProviderClient.__table__,
            OAuthProviderGrant.__table__,
            OAuthProviderToken.__table__,
        ):
            assert isinstance(table, Table)
            table.create(connection)
    return migration_database


@pytest.fixture
def catalog_session(
    oauth_cleanup_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> Generator[None, None, None]:
    @contextmanager
    def get_test_catalog_session() -> Generator[Session, None, None]:
        with Session(oauth_cleanup_engine) as session:
            yield session

    monkeypatch.setattr(oauth_provider, "get_catalog_session", get_test_catalog_session)
    yield


def _token_hash() -> str:
    return f"{uuid4().hex}{uuid4().hex}"


def _insert_user(session: Session) -> UUID:
    user_id = uuid4()
    session.execute(
        text('INSERT INTO public."user" (id) VALUES (:user_id)'),
        {"user_id": user_id},
    )
    return user_id


def _add_grant(
    session: Session,
    *,
    expires_at: datetime,
    client_id: str | None = None,
) -> OAuthProviderGrant:
    grant = OAuthProviderGrant(
        user_id=_insert_user(session),
        client_id=client_id or f"cleanup-client-{uuid4().hex}",
        client_name="Cleanup test client",
        resource=_RESOURCE,
        scopes=["read:search"],
        created_at=expires_at - timedelta(days=1),
        expires_at=expires_at,
    )
    session.add(grant)
    session.flush()
    return grant


def _add_token(
    session: Session,
    grant: OAuthProviderGrant,
    *,
    expires_at: datetime,
    kind: str = "access",
    consumed_at: datetime | None = None,
) -> str:
    token_hash = _token_hash()
    session.add(
        OAuthProviderToken(
            token_hash=token_hash,
            grant_id=grant.id,
            kind=kind,
            expires_at=expires_at,
            consumed_at=consumed_at,
        )
    )
    session.flush()
    return token_hash


def _add_client(
    session: Session, *, last_used_at: datetime, client_id: str | None = None
) -> str:
    stored_client_id = client_id or f"cleanup-client-{uuid4().hex}"
    session.add(
        OAuthProviderClient(
            client_id=stored_client_id,
            client_metadata={
                "client_id": stored_client_id,
                "redirect_uris": ["http://127.0.0.1:6274/oauth/callback"],
                "token_endpoint_auth_method": "none",
            },
            created_at=last_used_at,
            last_used_at=last_used_at,
        )
    )
    session.flush()
    return stored_client_id


def test_expired_grant_cleanup_cascades_to_tokens(
    oauth_cleanup_engine: Engine,
) -> None:
    with Session(oauth_cleanup_engine) as session:
        expired = _add_grant(session, expires_at=_NOW - timedelta(seconds=1))
        _add_token(session, expired, expires_at=_NOW - timedelta(minutes=15))
        _add_token(
            session,
            expired,
            kind="refresh",
            expires_at=expired.expires_at,
            consumed_at=_NOW - timedelta(days=1),
        )
        live = _add_grant(session, expires_at=_NOW + timedelta(days=1))
        live_access = _add_token(session, live, expires_at=_NOW + timedelta(minutes=5))
        consumed_refresh = _add_token(
            session,
            live,
            kind="refresh",
            expires_at=live.expires_at,
            consumed_at=_NOW - timedelta(hours=1),
        )
        session.commit()

        assert delete_expired_oauth_provider_grants__no_commit(session, now=_NOW) == 1
        session.commit()

        assert set(session.scalars(select(OAuthProviderGrant.id))) == {live.id}
        assert set(session.scalars(select(OAuthProviderToken.token_hash))) == {
            live_access,
            consumed_refresh,
        }


def test_idle_client_cleanup_keeps_recent_clients(
    oauth_cleanup_engine: Engine,
) -> None:
    with Session(oauth_cleanup_engine) as session:
        stale_id = _add_client(session, last_used_at=_NOW - timedelta(days=91))
        recent_id = _add_client(session, last_used_at=_NOW - timedelta(days=89))
        session.commit()

        assert delete_idle_oauth_provider_clients__no_commit(session, now=_NOW) == 1
        session.commit()

        assert session.get(OAuthProviderClient, stale_id) is None
        assert session.get(OAuthProviderClient, recent_id) is not None


def test_tasks_commit_cleanup_and_repeat_safely(
    oauth_cleanup_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    @contextmanager
    def cleanup_session() -> Generator[Session, None, None]:
        with Session(oauth_cleanup_engine) as session:
            yield session

    monkeypatch.setattr(tasks, "get_session_with_current_tenant", cleanup_session)
    monkeypatch.setattr(tasks, "get_catalog_session", cleanup_session)
    with Session(oauth_cleanup_engine) as setup:
        expired = datetime.now(timezone.utc) - timedelta(days=91)
        grant = _add_grant(setup, expires_at=expired)
        _add_token(setup, grant, expires_at=expired)
        _add_client(setup, last_used_at=expired)
        setup.commit()

    for _ in range(2):
        tasks.cleanup_oauth_provider_grants.run(tenant_id="public")
        tasks.cleanup_oauth_provider_clients.run()

    with Session(oauth_cleanup_engine) as session:
        for model in (OAuthProviderToken, OAuthProviderGrant, OAuthProviderClient):
            assert session.scalar(select(func.count()).select_from(model)) == 0


@pytest.mark.usefixtures("catalog_session")
def test_client_lookup_rereads_when_activity_update_loses_to_another_lookup(
    oauth_cleanup_engine: Engine,
) -> None:
    client_id = "activity-race-client"
    stale_at = datetime.now(timezone.utc) - timedelta(days=1)
    with Session(oauth_cleanup_engine) as session:
        _add_client(session, last_used_at=stale_at, client_id=client_id)
        session.commit()

    did_update = False

    def update_before_lookup_update(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        nonlocal did_update
        if did_update or not statement.startswith(
            "UPDATE public.oauth_provider_client"
        ):
            return
        did_update = True
        with oauth_cleanup_engine.begin() as connection:
            connection.execute(
                update(OAuthProviderClient)
                .where(OAuthProviderClient.client_id == client_id)
                .values(last_used_at=datetime.now(timezone.utc))
            )

    event.listen(
        oauth_cleanup_engine, "before_cursor_execute", update_before_lookup_update
    )
    try:
        client = get_oauth_provider_client(client_id)
    finally:
        event.remove(
            oauth_cleanup_engine, "before_cursor_execute", update_before_lookup_update
        )

    assert client is not None
    assert client.client_id == client_id


@pytest.mark.usefixtures("catalog_session")
def test_client_lookup_returns_none_when_activity_update_loses_to_cleanup(
    oauth_cleanup_engine: Engine,
) -> None:
    client_id = "deleted-race-client"
    stale_at = datetime.now(timezone.utc) - timedelta(days=1)
    with Session(oauth_cleanup_engine) as session:
        _add_client(session, last_used_at=stale_at, client_id=client_id)
        session.commit()

    did_delete = False

    def delete_before_lookup_update(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        nonlocal did_delete
        if did_delete or not statement.startswith(
            "UPDATE public.oauth_provider_client"
        ):
            return
        did_delete = True
        with oauth_cleanup_engine.begin() as connection:
            connection.execute(
                text(
                    "DELETE FROM public.oauth_provider_client WHERE client_id = :client_id"
                ),
                {"client_id": client_id},
            )

    event.listen(
        oauth_cleanup_engine, "before_cursor_execute", delete_before_lookup_update
    )
    try:
        assert get_oauth_provider_client(client_id) is None
    finally:
        event.remove(
            oauth_cleanup_engine, "before_cursor_execute", delete_before_lookup_update
        )
