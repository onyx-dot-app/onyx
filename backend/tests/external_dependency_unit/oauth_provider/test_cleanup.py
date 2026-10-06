from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, Table, event, func, select, text, update
from sqlalchemy.orm import Session

from onyx.auth.oauth_provider import (
    OAuthProviderTokenKind,
    generate_oauth_provider_token,
)
from onyx.auth.pat import hash_pat
from onyx.background.celery.tasks.oauth_provider import tasks
from onyx.db import oauth_provider
from onyx.db.models import OAuthProviderClient, OAuthProviderGrant, OAuthProviderToken
from onyx.db.oauth_provider import (
    cleanup_oauth_provider_clients__no_commit,
    cleanup_oauth_provider_grants__no_commit,
    cleanup_oauth_provider_tokens__no_commit,
    get_oauth_provider_client,
    load_oauth_provider_refresh__no_commit,
)
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
_RESOURCE = "https://onyx.example.com/mcp/"


def test_task_skips_real_unmigrated_database(
    migration_database: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    @contextmanager
    def unmigrated_session() -> Generator[Session, None, None]:
        with Session(migration_database) as session:
            yield session

    monkeypatch.setattr(tasks, "get_session_with_current_tenant", unmigrated_session)
    monkeypatch.setattr(tasks, "get_catalog_session", unmigrated_session)
    assert tasks._run_cleanup(catalog=False) == 0
    assert tasks._run_cleanup(catalog=True) == 0


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


def _token_count(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(OAuthProviderToken)) or 0


def _grant_count(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(OAuthProviderGrant)) or 0


def _client_count(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(OAuthProviderClient)) or 0


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


def test_token_cleanup_uses_one_minute_grace(
    oauth_cleanup_engine: Engine,
) -> None:
    with Session(oauth_cleanup_engine) as session:
        grant = _add_grant(session, expires_at=_NOW + timedelta(days=1))
        old_hash = _add_token(session, grant, expires_at=_NOW - timedelta(seconds=60))
        recent_hash = _add_token(
            session, grant, expires_at=_NOW - timedelta(seconds=59)
        )
        future_hash = _add_token(session, grant, expires_at=_NOW + timedelta(seconds=1))

        assert cleanup_oauth_provider_tokens__no_commit(session, now=_NOW) == 1
        session.commit()

        remaining = set(session.scalars(select(OAuthProviderToken.token_hash)))
    assert remaining == {recent_hash, future_hash}
    assert old_hash not in remaining


def test_consumed_refresh_hash_remains_until_token_expiry(
    oauth_cleanup_engine: Engine,
) -> None:
    with Session(oauth_cleanup_engine) as session:
        grant = _add_grant(session, expires_at=_NOW + timedelta(days=1))
        consumed_hash = _add_token(
            session,
            grant,
            kind="refresh",
            expires_at=grant.expires_at,
            consumed_at=_NOW - timedelta(hours=1),
        )

        assert cleanup_oauth_provider_tokens__no_commit(session, now=_NOW) == 0
        session.commit()

        assert session.get(OAuthProviderToken, consumed_hash) is not None

        assert (
            cleanup_oauth_provider_tokens__no_commit(
                session, now=grant.expires_at + timedelta(minutes=1)
            )
            == 1
        )
        session.commit()
        assert session.get(OAuthProviderToken, consumed_hash) is None


def test_token_cleanup_respects_batch_size(
    oauth_cleanup_engine: Engine,
) -> None:
    with Session(oauth_cleanup_engine) as session:
        grant = _add_grant(session, expires_at=_NOW + timedelta(days=1))
        for _ in range(3):
            _add_token(session, grant, expires_at=_NOW - timedelta(minutes=2))

        assert (
            cleanup_oauth_provider_tokens__no_commit(session, now=_NOW, batch_size=2)
            == 2
        )
        session.commit()

        assert _token_count(session) == 1


def test_cleanup_retains_refresh_replay_detection(oauth_cleanup_engine: Engine) -> None:
    now = datetime.now(timezone.utc)
    context_token = CURRENT_TENANT_ID_CONTEXTVAR.set(POSTGRES_DEFAULT_SCHEMA)
    try:
        raw_token = generate_oauth_provider_token(
            POSTGRES_DEFAULT_SCHEMA, OAuthProviderTokenKind.REFRESH
        )
        with Session(oauth_cleanup_engine) as session:
            grant = _add_grant(session, expires_at=now + timedelta(days=1))
            session.add(
                OAuthProviderToken(
                    token_hash=hash_pat(raw_token),
                    grant_id=grant.id,
                    kind="refresh",
                    expires_at=grant.expires_at,
                    consumed_at=now - timedelta(minutes=1),
                )
            )
            session.commit()
            assert cleanup_oauth_provider_tokens__no_commit(session, now=now) == 0
            assert cleanup_oauth_provider_grants__no_commit(session, now=now) == 0
            session.commit()
            assert (
                load_oauth_provider_refresh__no_commit(
                    session, raw_token, client_id=grant.client_id, resource=_RESOURCE
                )
                is None
            )
            session.commit()
            assert grant.revoked_at is not None
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(context_token)


def test_grants_are_removed_only_after_tokens(
    oauth_cleanup_engine: Engine,
) -> None:
    with Session(oauth_cleanup_engine) as session:
        grant = _add_grant(session, expires_at=_NOW - timedelta(minutes=2))
        _add_token(session, grant, expires_at=_NOW - timedelta(minutes=2))
        _add_token(
            session,
            grant,
            kind="refresh",
            expires_at=_NOW - timedelta(minutes=2),
            consumed_at=_NOW - timedelta(hours=1),
        )

        assert cleanup_oauth_provider_grants__no_commit(session, now=_NOW) == 0
        assert cleanup_oauth_provider_tokens__no_commit(session, now=_NOW) == 2
        assert cleanup_oauth_provider_grants__no_commit(session, now=_NOW) == 1
        session.commit()

        assert _token_count(session) == 0
        assert _grant_count(session) == 0


def test_expired_grant_with_live_token_is_preserved(
    oauth_cleanup_engine: Engine,
) -> None:
    with Session(oauth_cleanup_engine) as session:
        grant = _add_grant(session, expires_at=_NOW - timedelta(minutes=2))
        _add_token(session, grant, expires_at=_NOW + timedelta(minutes=1))
        assert cleanup_oauth_provider_tokens__no_commit(session, now=_NOW) == 0
        assert cleanup_oauth_provider_grants__no_commit(session, now=_NOW) == 0
        session.commit()
        assert _grant_count(session) == 1


def test_grant_cleanup_respects_grace_and_batch_size(
    oauth_cleanup_engine: Engine,
) -> None:
    with Session(oauth_cleanup_engine) as session:
        for offset in (timedelta(minutes=2), timedelta(minutes=3)):
            _add_grant(session, expires_at=_NOW - offset)
        recent = _add_grant(session, expires_at=_NOW - timedelta(seconds=59))
        recent_id = recent.id

        assert (
            cleanup_oauth_provider_grants__no_commit(session, now=_NOW, batch_size=1)
            == 1
        )
        session.commit()

        remaining_ids = set(session.scalars(select(OAuthProviderGrant.id)))
    assert len(remaining_ids) == 2
    assert recent_id in remaining_ids


def test_cleanup_skips_locked_tokens(
    oauth_cleanup_engine: Engine,
) -> None:
    with Session(oauth_cleanup_engine) as setup:
        grant = _add_grant(setup, expires_at=_NOW + timedelta(days=1))
        locked_hash = _add_token(setup, grant, expires_at=_NOW - timedelta(minutes=2))
        unlocked_hash = _add_token(setup, grant, expires_at=_NOW - timedelta(minutes=2))
        setup.commit()

    with Session(oauth_cleanup_engine) as locker:
        assert locker.scalar(
            select(OAuthProviderToken)
            .where(OAuthProviderToken.token_hash == locked_hash)
            .with_for_update()
        )
        with Session(oauth_cleanup_engine) as cleaner:
            assert cleanup_oauth_provider_tokens__no_commit(cleaner, now=_NOW) == 1
            cleaner.commit()
        assert locker.get(OAuthProviderToken, locked_hash) is not None
        locker.commit()

    with Session(oauth_cleanup_engine) as session:
        assert session.get(OAuthProviderToken, unlocked_hash) is None
        assert cleanup_oauth_provider_tokens__no_commit(session, now=_NOW) == 1
        session.commit()
        assert _token_count(session) == 0


def test_cleanup_skips_locked_grants(oauth_cleanup_engine: Engine) -> None:
    with Session(oauth_cleanup_engine) as setup:
        locked = _add_grant(setup, expires_at=_NOW - timedelta(minutes=2)).id
        unlocked = _add_grant(setup, expires_at=_NOW - timedelta(minutes=2)).id
        setup.commit()
    with Session(oauth_cleanup_engine) as locker:
        assert (
            locker.scalar(
                select(OAuthProviderGrant)
                .where(OAuthProviderGrant.id == locked)
                .with_for_update()
            )
            is not None
        )
        with Session(oauth_cleanup_engine) as cleaner:
            assert cleanup_oauth_provider_grants__no_commit(cleaner, now=_NOW) == 1
            cleaner.commit()
        assert locker.get(OAuthProviderGrant, locked) is not None
        assert locker.get(OAuthProviderGrant, unlocked) is None
        locker.rollback()
    with Session(oauth_cleanup_engine) as cleaner:
        assert cleanup_oauth_provider_grants__no_commit(cleaner, now=_NOW) == 1
        cleaner.commit()


def test_statement_timeout_is_applied_in_each_helper_transaction(
    oauth_cleanup_engine: Engine,
) -> None:
    with Session(oauth_cleanup_engine) as session:
        grant = _add_grant(session, expires_at=_NOW - timedelta(minutes=2))
        _add_token(session, grant, expires_at=_NOW - timedelta(minutes=2))
        assert cleanup_oauth_provider_tokens__no_commit(session, now=_NOW) == 1
        assert session.scalar(text("SHOW statement_timeout")) == "10s"
        session.commit()

    with Session(oauth_cleanup_engine) as session:
        _add_client(session, last_used_at=_NOW - timedelta(days=91))
        assert cleanup_oauth_provider_clients__no_commit(session, now=_NOW) == 1
        assert session.scalar(text("SHOW statement_timeout")) == "10s"
        session.commit()

    with Session(oauth_cleanup_engine) as session:
        assert cleanup_oauth_provider_grants__no_commit(session, now=_NOW) == 1
        assert session.scalar(text("SHOW statement_timeout")) == "10s"
        session.commit()


@pytest.mark.parametrize("kind", ["tokens", "grants", "clients"])
@pytest.mark.parametrize("batch_size", [-1, 0, 3])
def test_cleanup_bounds_batch_size(
    oauth_cleanup_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
    kind: Literal["tokens", "grants", "clients"],
    batch_size: int,
) -> None:
    monkeypatch.setattr(oauth_provider, "OAUTH_PROVIDER_CLEANUP_BATCH_SIZE", 2)
    operations = {
        "tokens": cleanup_oauth_provider_tokens__no_commit,
        "grants": cleanup_oauth_provider_grants__no_commit,
        "clients": cleanup_oauth_provider_clients__no_commit,
    }
    with Session(oauth_cleanup_engine) as session:
        for _ in range(3):
            if kind == "clients":
                _add_client(session, last_used_at=_NOW - timedelta(days=91))
            else:
                grant = _add_grant(session, expires_at=_NOW - timedelta(minutes=2))
                if kind == "tokens":
                    _add_token(session, grant, expires_at=_NOW - timedelta(minutes=2))
        assert operations[kind](session, now=_NOW, batch_size=batch_size) == (
            2 if batch_size > 0 else 0
        )


def test_cleanup_does_not_commit_for_its_caller(oauth_cleanup_engine: Engine) -> None:
    with Session(oauth_cleanup_engine) as setup:
        grant = _add_grant(setup, expires_at=_NOW - timedelta(minutes=2))
        _add_token(setup, grant, expires_at=_NOW - timedelta(minutes=2))
        _add_client(setup, last_used_at=_NOW - timedelta(days=91))
        setup.commit()
    with Session(oauth_cleanup_engine) as session:
        assert cleanup_oauth_provider_tokens__no_commit(session, now=_NOW) == 1
        assert cleanup_oauth_provider_grants__no_commit(session, now=_NOW) == 1
        assert cleanup_oauth_provider_clients__no_commit(session, now=_NOW) == 1
        session.rollback()
        assert _token_count(session) == 1
        assert _grant_count(session) == 1
        assert _client_count(session) == 1


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
    assert tasks.cleanup_oauth_provider_records.run(tenant_id="public") == 2
    assert tasks.cleanup_oauth_provider_clients.run() == 1
    assert tasks.cleanup_oauth_provider_records.run(tenant_id="public") == 0
    assert tasks.cleanup_oauth_provider_clients.run() == 0
    with Session(oauth_cleanup_engine) as session:
        assert (
            _token_count(session)
            == _grant_count(session)
            == _client_count(session)
            == 0
        )


def test_catalog_cleanup_preserves_recent_clients_and_is_idempotent(
    oauth_cleanup_engine: Engine,
) -> None:
    with Session(oauth_cleanup_engine) as session:
        stale_id = _add_client(
            session, last_used_at=_NOW - timedelta(days=91), client_id="stale-client"
        )
        recent_id = _add_client(
            session, last_used_at=_NOW - timedelta(days=89), client_id="recent-client"
        )

        assert cleanup_oauth_provider_clients__no_commit(session, now=_NOW) == 1
        assert cleanup_oauth_provider_clients__no_commit(session, now=_NOW) == 0
        session.commit()

        assert session.get(OAuthProviderClient, stale_id) is None
        assert session.get(OAuthProviderClient, recent_id) is not None


def test_catalog_cleanup_respects_batch_size_and_skips_locked_clients(
    oauth_cleanup_engine: Engine,
) -> None:
    with Session(oauth_cleanup_engine) as setup:
        locked_id = _add_client(
            setup, last_used_at=_NOW - timedelta(days=91), client_id="locked-client"
        )
        first_id = _add_client(
            setup, last_used_at=_NOW - timedelta(days=92), client_id="first-client"
        )
        second_id = _add_client(
            setup, last_used_at=_NOW - timedelta(days=93), client_id="second-client"
        )
        setup.commit()

    with Session(oauth_cleanup_engine) as locker:
        assert locker.scalar(
            select(OAuthProviderClient)
            .where(OAuthProviderClient.client_id == locked_id)
            .with_for_update()
        )
        with Session(oauth_cleanup_engine) as cleaner:
            assert (
                cleanup_oauth_provider_clients__no_commit(
                    cleaner, now=_NOW, batch_size=1
                )
                == 1
            )
            cleaner.commit()
        locker.commit()

    with Session(oauth_cleanup_engine) as session:
        assert _client_count(session) == 2
        assert session.get(OAuthProviderClient, first_id) is not None
        assert session.get(OAuthProviderClient, second_id) is None
        assert cleanup_oauth_provider_clients__no_commit(session, now=_NOW) == 2
        session.commit()
        assert _client_count(session) == 0


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
