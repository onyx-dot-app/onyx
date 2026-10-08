"""ENG-4235: skill-table restore must not decrypt pre-existing rows.

``restore_skill_tables`` restores the committed skill/external-app tables
after each Craft ext-dep test. On a shared dev DB (e.g. a kind cluster),
``external_app``/``external_app_user_credential`` rows were encrypted with a
different ``ENCRYPTION_KEY_SECRET`` than the local environment has, so
decrypting them raises ``UnicodeDecodeError``. The previous ``merge``-based
restore forced SQLAlchemy's dirty-check to decrypt every loaded row's
credential column during teardown of an otherwise-passing test.

These tests run the real ORM models over SQLite and seed rows with raw
"foreign" encrypted bytes that no local key can decode, then assert the
restore round-trips them verbatim without decrypting.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import DefaultClause, create_engine, event, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.sql.schema import Table

from onyx.db.models import (
    ExternalApp,
    ExternalApp__Skill,
    ExternalAppUserCredential,
    GatedActionPolicy,
    GatedApp,
    OAuthAccount,
    Skill,
    Skill__User,
    Skill__UserGroup,
    User,
    _release_inserted_user_email,
    _release_updated_user_email,
)
from tests.common.craft.skill_table_isolation import (
    restore_skill_tables,
    snapshot_skill_tables,
)

# gzip-like magic byte (0x8b, as seen in the ENG-4235 traceback) that no
# local key can decode on an MIT build.
FOREIGN_BYTES = b"\x8bforeign-encrypted-not-decodable\x00\x01"

_ISOLATION_TABLES: list[Table] = [
    User.__table__,
    OAuthAccount.__table__,
    Skill.__table__,
    ExternalApp.__table__,
    ExternalApp__Skill.__table__,
    ExternalAppUserCredential.__table__,
    GatedApp.__table__,
    GatedActionPolicy.__table__,
    Skill__User.__table__,
    Skill__UserGroup.__table__,
]  # ty: ignore[invalid-assignment] — __table__ is typed FromClause, values are Table


def _make_session() -> tuple[Any, Session]:
    """SQLite session over the real ORM models, made renderable.

    Postgres-only column types, server-default SQL, the ``num_nonnulls()``
    check constraint, and User's array-op listeners have no SQLite
    equivalent, so they are swapped for portable stand-ins. Column type
    swaps on the shared table objects only affect this module's session.
    """
    from sqlalchemy import JSON

    for tbl in _ISOLATION_TABLES:
        for col in tbl.columns:
            if isinstance(col.type, postgresql.ARRAY):
                col.type = JSON()
            elif isinstance(col.type, postgresql.JSONB):
                col.type = JSON()
            elif isinstance(col.type, postgresql.UUID):
                col.type = _SQLiteUuid()
            if col.server_default is not None and col.name in (
                "created_at",
                "updated_at",
                "time_created",
                "time_updated",
            ):
                col.server_default = DefaultClause(text("CURRENT_TIMESTAMP"))
            else:
                col.server_default = None
    gated_app_tbl = GatedApp.__table__
    gated_app_tbl.constraints = {  # ty: ignore[unresolved-attribute]
        c
        for c in gated_app_tbl.constraints  # ty: ignore[unresolved-attribute]
        if getattr(c, "name", None)  # ods: ignore[getattr] — Constraint.name optional
        != "ck_gated_app_single_target"
    }
    # User's before_insert/before_update listeners issue Postgres-only array
    # ops (``array_remove``, ``@>``) that SQLite can't run.
    for evt, fn in (
        ("before_insert", _release_inserted_user_email),
        ("before_update", _release_updated_user_email),
    ):
        try:
            event.remove(User, evt, fn)
        except Exception:  # noqa: S110 — listener may already be removed
            pass

    from onyx.db.models import Base

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine, tables=_ISOLATION_TABLES)
    maker = sessionmaker(bind=engine, expire_on_commit=False)
    return engine, maker()


class _SQLiteUuid(postgresql.UUID):  # type: ignore[type-arg,misc]
    def get_col_spec(self) -> str:
        return "CHAR(32)"


def _seed_foreign_encrypted_row(session: Session) -> ExternalApp:
    """Insert an ``ExternalApp`` row whose encrypted column holds raw bytes
    written with a different key — via raw SQL so the ORM's encrypt-on-write
    never runs. Also seeds its dependent user-credential row the same way."""
    user = User(
        id=uuid4(),
        email=f"foreign_{uuid4().hex[:6]}@example.com",
        hashed_password="x",
        is_active=True,
        is_superuser=False,
        is_verified=True,
    )
    session.add(user)
    skill = Skill(
        id=uuid4(),
        name=f"foreign-skill-{uuid4().hex[:6]}",
        description="d",
        bundle_file_id=f"bundle-{uuid4().hex[:8]}",
        bundle_sha256="0" * 64,
    )
    session.add(skill)
    session.flush()
    app = ExternalApp(
        name=skill.name,
        app_type="CUSTOM",
        enabled=True,
        upstream_url_patterns=[],
        auth_template={},
        organization_credentials={},
        associated_skills=[skill],
    )
    session.add(app)
    session.flush()
    cred = ExternalAppUserCredential(
        external_app_id=app.id,
        user_id=user.id,
        user_credentials={},
    )
    session.add(cred)
    session.flush()
    # Overwrite the blobs directly — bytes no local key can decode.
    session.execute(
        text("UPDATE external_app SET organization_credentials = :b WHERE id = :id"),
        {"b": FOREIGN_BYTES, "id": app.id},
    )
    session.execute(
        text(
            "UPDATE external_app_user_credential SET user_credentials = :b"
            " WHERE external_app_id = :id"
        ),
        {"b": FOREIGN_BYTES, "id": app.id},
    )
    session.commit()
    return app


def _raw_creds(session: Session, table: str, app_id: int, col: str) -> bytes:
    return session.execute(
        text(
            f"SELECT {col} FROM {table} WHERE {'id' if table == 'external_app' else 'external_app_id'} = :id"
        ),
        {"id": app_id},
    ).scalar_one()


def _old_merge_restore(
    session: Session, snapshot: dict[type[Any], list[dict[str, Any]]]
) -> None:
    """The pre-fix implementation, inlined for the failure assertion."""
    from tests.common.craft.skill_table_isolation import _SKILL_ISOLATION_MODELS

    for model in reversed(_SKILL_ISOLATION_MODELS):
        for row in session.execute(select(model)).scalars().all():
            session.delete(row)
        session.flush()
    for model in _SKILL_ISOLATION_MODELS:
        for row in snapshot[model]:
            session.merge(model(**row))
        session.flush()
    session.commit()


def test_old_merge_restore_fails_on_foreign_bytes() -> None:
    _, session = _make_session()
    app = _seed_foreign_encrypted_row(session)
    # Expire so the snapshot re-reads the foreign bytes from the DB, as a
    # fresh fixture session would.
    session.expire_all()
    snapshot = snapshot_skill_tables(session)
    seeded = next(row for row in snapshot[ExternalApp] if row["id"] == app.id)
    assert seeded["organization_credentials"]._encrypted_bytes == FOREIGN_BYTES  # noqa: SLF001

    with pytest.raises(Exception, match=r"can't decode byte 0x8b"):
        # The old restore decrypts the foreign bytes during flush.
        _old_merge_restore(session, snapshot)


def test_new_restore_survives_foreign_bytes_and_restores_verbatim() -> None:
    _, session = _make_session()
    app = _seed_foreign_encrypted_row(session)
    session.expire_all()
    snapshot = snapshot_skill_tables(session)

    # --- the "test" runs: create a row, mutate the baseline, delete a row ---
    skill = Skill(
        id=uuid4(),
        name=f"created-{uuid4().hex[:6]}",
        description="d",
        bundle_file_id=f"bundle-{uuid4().hex[:8]}",
        bundle_sha256="0" * 64,
    )
    session.add(skill)
    created = ExternalApp(
        name=skill.name,
        app_type="CUSTOM",
        enabled=True,
        upstream_url_patterns=[],
        auth_template={},
        organization_credentials={"k": "v"},
        associated_skills=[skill],
    )
    session.add(created)
    session.flush()
    created_id = created.id
    session.execute(
        text("UPDATE external_app SET enabled = 0 WHERE id = :id"), {"id": app.id}
    )
    session.execute(
        text("DELETE FROM external_app_user_credential WHERE external_app_id = :id"),
        {"id": app.id},
    )
    session.commit()

    # --- teardown: restore must not raise ---
    restore_skill_tables(session, snapshot)

    # Foreign-encrypted baselines restored verbatim (bytes untouched).
    assert (
        _raw_creds(session, "external_app", app.id, "organization_credentials")
        == FOREIGN_BYTES
    )
    assert (
        _raw_creds(session, "external_app_user_credential", app.id, "user_credentials")
        == FOREIGN_BYTES
    )
    # Mutated baseline column reverted.
    enabled = session.execute(
        text("SELECT enabled FROM external_app WHERE id = :id"), {"id": app.id}
    ).scalar_one()
    assert bool(enabled) is True
    # Row created during the test removed.
    assert (
        session.execute(
            text("SELECT 1 FROM external_app WHERE id = :id"), {"id": created_id}
        ).first()
        is None
    )
    # Deleted user-credential baseline row re-inserted.
    assert (
        session.execute(
            text(
                "SELECT 1 FROM external_app_user_credential WHERE external_app_id = :id"
            ),
            {"id": app.id},
        ).first()
        is not None
    )

    # A second restore is idempotent.
    restore_skill_tables(session, snapshot)
    assert (
        _raw_creds(session, "external_app", app.id, "organization_credentials")
        == FOREIGN_BYTES
    )


def test_new_restore_reinserts_deleted_baseline_row() -> None:
    _, session = _make_session()
    app = _seed_foreign_encrypted_row(session)
    session.expire_all()
    snapshot = snapshot_skill_tables(session)
    # The "test" deletes the baseline row.
    session.execute(text("DELETE FROM external_app WHERE id = :id"), {"id": app.id})
    session.commit()
    restore_skill_tables(session, snapshot)
    assert (
        _raw_creds(session, "external_app", app.id, "organization_credentials")
        == FOREIGN_BYTES
    )