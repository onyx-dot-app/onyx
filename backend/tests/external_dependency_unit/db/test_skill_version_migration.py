"""Version migration and ORM constraints against isolated PostgreSQL schemas."""

from collections.abc import Generator
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import Script, ScriptDirectory
from sqlalchemy import delete, func, inspect, select, text, update
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema

from onyx.db.enums import SkillSharePermission
from onyx.db.models import Base, Skill, SkillVersion


@pytest.fixture
def revision() -> Script:
    scripts = ScriptDirectory(str(Path(__file__).resolve().parents[3] / "alembic"))
    revision = scripts.get_revision("6476b236ec97")
    assert revision is not None
    return revision


@pytest.fixture
def connection(isolated_engine: Engine) -> Generator[Connection, None, None]:
    schema = f"skill_versions_{uuid4().hex}"
    with isolated_engine.connect() as connection:
        try:
            connection.execute(CreateSchema(schema))
            connection.execute(
                text("SELECT set_config('search_path', :schema, false)"),
                {"schema": schema},
            )
            connection.execute(text('CREATE TABLE "user" (id uuid PRIMARY KEY)'))
            connection.execute(
                text("""
                    CREATE TABLE skill (
                        id uuid PRIMARY KEY,
                        name varchar(64) NOT NULL,
                        description text NOT NULL,
                        built_in_skill_id varchar,
                        bundle_file_id varchar,
                        bundle_sha256 varchar(64),
                        is_valid boolean,
                        author_user_id uuid REFERENCES "user"(id) ON DELETE SET NULL,
                        public_permission varchar,
                        installation_policy varchar NOT NULL DEFAULT 'AVAILABLE',
                        created_at timestamptz NOT NULL DEFAULT now(),
                        updated_at timestamptz NOT NULL DEFAULT now(),
                        CONSTRAINT ck_skill_definition_source CHECK (
                            (built_in_skill_id IS NULL) <> (bundle_file_id IS NULL)),
                        CONSTRAINT ck_private_skill_has_owner CHECK (
                            built_in_skill_id IS NOT NULL OR public_permission IS NOT NULL
                            OR author_user_id IS NOT NULL)
                    )
                """)
            )
            connection.commit()
            yield connection
        finally:
            connection.rollback()
            connection.execute(DropSchema(schema, cascade=True, if_exists=True))
            connection.execute(text("RESET search_path"))
            connection.commit()


def test_backfill_round_trip(connection: Connection, revision: Script) -> None:
    author = UUID(int=1)
    created_at = datetime(2026, 1, 2, tzinfo=timezone.utc)
    connection.execute(text('INSERT INTO "user" VALUES (:id)'), {"id": author})
    # Include each lazy-validity state and an authorless public custom skill.
    connection.execute(
        text("""
            INSERT INTO skill (
                id, name, description, built_in_skill_id, bundle_file_id,
                bundle_sha256, is_valid, author_user_id, public_permission, created_at
            ) VALUES (
                :id, :name, 'description', :built_in, :file, :hash, :valid,
                :author, :permission, :created_at
            )
        """),
        [
            {
                "id": UUID(int=2),
                "name": "private",
                "built_in": None,
                "file": "private.zip",
                "hash": "a" * 64,
                "valid": True,
                "author": author,
                "permission": None,
                "created_at": created_at,
            },
            {
                "id": UUID(int=3),
                "name": "public",
                "built_in": None,
                "file": "public.zip",
                "hash": None,
                "valid": None,
                "author": None,
                "permission": "VIEWER",
                "created_at": created_at,
            },
            {
                "id": UUID(int=4),
                "name": "invalid",
                "built_in": None,
                "file": "invalid.zip",
                "hash": "b" * 64,
                "valid": False,
                "author": author,
                "permission": None,
                "created_at": created_at,
            },
            {
                "id": UUID(int=5),
                "name": "builtin",
                "built_in": "builtin",
                "file": None,
                "hash": None,
                "valid": True,
                "author": None,
                "permission": None,
                "created_at": created_at,
            },
        ],
    )
    before = connection.execute(text("SELECT * FROM skill ORDER BY id")).all()
    connection.commit()
    with Operations.context(MigrationContext.configure(connection)):
        revision.module.upgrade()
        connection.commit()
        versions = connection.execute(
            select(SkillVersion).order_by(SkillVersion.id)
        ).all()
        assert len(versions) == 3
        for row, original in zip(versions, before[:3], strict=True):
            assert row.id == row.skill_id == original.id
            assert row.version_number == 1
            assert row.bundle_file_id == original.bundle_file_id
            assert row.bundle_sha256 == original.bundle_sha256
            assert row.is_valid == original.is_valid
            assert row.created_by_user_id == original.author_user_id
            assert row.created_at == original.created_at
            assert row.unpacked_size_bytes is row.file_count is None
            assert row.metadata_unrepairable is False
            assert row.name is row.frontmatter is None
        assert connection.execute(
            select(Skill.id, Skill.current_version_id).order_by(Skill.id)
        ).all() == [(UUID(int=i), UUID(int=i)) for i in (2, 3, 4)] + [
            (UUID(int=5), None)
        ]
        revision.module.downgrade()
        connection.commit()
        assert "skill_version" not in inspect(connection).get_table_names()
        assert (
            connection.execute(text("SELECT * FROM skill ORDER BY id")).all() == before
        )
        revision.module.upgrade()
        connection.commit()
        assert (
            connection.execute(select(SkillVersion).order_by(SkillVersion.id)).all()
            == versions
        )


@pytest.mark.parametrize("schema_source", ["migration", "orm"])
def test_version_constraints(
    connection: Connection, revision: Script, schema_source: str
) -> None:
    if schema_source == "migration":
        with Operations.context(MigrationContext.configure(connection)):
            revision.module.upgrade()
    else:
        connection.execute(text("DROP TABLE skill"))
        Base.metadata.create_all(
            connection,
            tables=[Base.metadata.tables[name] for name in ("skill", "skill_version")],
        )
    creator = uuid4()
    connection.execute(text('INSERT INTO "user" VALUES (:id)'), {"id": creator})
    connection.commit()

    skill_id, version_id, other_id = uuid4(), uuid4(), uuid4()
    with Session(connection) as session:
        # Flush the skill with its preallocated pointer before inserting the version.
        session.add(
            Skill(
                id=skill_id,
                name="cyclic",
                description="cyclic",
                bundle_file_id="first.zip",
                current_version_id=version_id,
                public_permission=SkillSharePermission.VIEWER,
            )
        )
        session.flush()
        session.add(
            SkillVersion(
                id=version_id,
                skill_id=skill_id,
                version_number=1,
                bundle_file_id="first.zip",
                created_by_user_id=creator,
            )
        )
        session.commit()
        assert (
            session.scalar(select(Skill.current_version_id).where(Skill.id == skill_id))
            == version_id
        )

        # Old writers can still create a custom skill without a pointer during rollout.
        session.add(
            Skill(
                id=other_id,
                name="other",
                description="other",
                bundle_file_id="other.zip",
                public_permission=SkillSharePermission.VIEWER,
            )
        )
        session.commit()
        for bad_pointer in (version_id, uuid4()):
            session.execute(
                update(Skill)
                .where(Skill.id == other_id)
                .values(current_version_id=bad_pointer)
            )
            with pytest.raises(IntegrityError, match="fk_skill_current_version"):
                session.commit()
            session.rollback()

        session.add(SkillVersion(skill_id=skill_id, version_number=1))
        with pytest.raises(IntegrityError, match="uq_skill_version_number"):
            session.commit()
        session.rollback()

        # The same number is allowed for another skill; a pruned bundle is nullable.
        session.add(SkillVersion(skill_id=other_id, version_number=1))
        session.commit()
        session.execute(text('DELETE FROM "user" WHERE id = :id'), {"id": creator})
        session.commit()
        assert (
            session.scalar(
                select(SkillVersion.created_by_user_id).where(
                    SkillVersion.id == version_id
                )
            )
            is None
        )

        # The current version cannot disappear while the owning skill remains.
        session.execute(delete(SkillVersion).where(SkillVersion.id == version_id))
        with pytest.raises(IntegrityError, match="fk_skill_current_version"):
            session.commit()
        session.rollback()

        session.execute(delete(Skill).where(Skill.id == skill_id))
        session.commit()
        assert (
            session.scalar(
                select(func.count())
                .select_from(SkillVersion)
                .where(SkillVersion.skill_id == skill_id)
            )
            == 0
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(SkillVersion)
                .where(SkillVersion.skill_id == other_id)
            )
            == 1
        )
