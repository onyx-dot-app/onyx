"""V7 reconciles legacy rows without reading or inventing bundle files."""

from pathlib import Path
from uuid import UUID

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, select, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError, IntegrityError

from onyx.configs.constants import FileOrigin
from onyx.db.models import Skill
from onyx.db.skill_version import _unused_skill_bundles
from tests.external_dependency_unit.db.test_skill_version_migration import (
    connection as connection,
)


def test_cutover_round_trip(connection: Connection) -> None:
    scripts = ScriptDirectory(str(Path(__file__).resolve().parents[3] / "alembic"))
    v1 = scripts.get_revision("6476b236ec97")
    v7 = scripts.get_revision("ef73786dc783")
    assert v1 is not None and v7 is not None
    # Three validity states, private/public custom rows, and a built-in.
    connection.execute(text('INSERT INTO "user" VALUES (:id)'), {"id": UUID(int=99)})
    connection.execute(
        text("""
            INSERT INTO skill (id, name, description, bundle_file_id, bundle_sha256,
                               is_valid, public_permission, author_user_id,
                               built_in_skill_id, created_at, updated_at)
            VALUES (:id, :name, 'old', :file, :hash, :valid, :public, :owner,
                    :builtin, '2026-01-01', '2026-01-02')
        """),
        [
            {
                "id": UUID(int=n),
                "name": f"skill-{n}",
                "file": f"file-{n}" if n < 6 else None,
                "hash": "a" * 64 if n < 6 else None,
                "valid": [True, False, None][n % 3],
                "public": "VIEWER" if n % 2 else None,
                "owner": UUID(int=99) if n % 2 == 0 else None,
                "builtin": "builtin" if n == 6 else None,
            }
            for n in range(1, 7)
        ],
    )
    with Operations.context(MigrationContext.configure(connection)):
        v1.module.upgrade()
        # Old writer changes a bundle, changes only validity, and inserts without a pointer.
        connection.execute(
            text(
                "UPDATE skill SET bundle_file_id = 'new-file', bundle_sha256 = NULL WHERE name = 'skill-1'"
            )
        )
        connection.execute(
            text("UPDATE skill SET is_valid = NULL WHERE name = 'skill-3'")
        )
        connection.execute(
            text("UPDATE skill SET current_version_id = NULL WHERE name = 'skill-2'")
        )
        connection.execute(
            text("DELETE FROM skill_version WHERE skill_id = :id"), {"id": UUID(int=2)}
        )
        # A pruned history row and an absent blob keep their honest references.
        connection.execute(
            text("UPDATE skill_version SET bundle_file_id = NULL WHERE skill_id = :id"),
            {"id": UUID(int=4)},
        )
        connection.execute(
            text("UPDATE skill SET current_version_id = NULL WHERE name = 'skill-5'")
        )
        before = connection.execute(
            text("SELECT * FROM skill_version ORDER BY skill_id, version_number")
        ).all()
        connection.execute(
            text(
                "CREATE TABLE file_record (file_id text PRIMARY KEY, file_origin text)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO file_record VALUES ('new-file', :origin), ('orphan', :origin)"
            ),
            {"origin": FileOrigin.SKILL_BUNDLE.name},
        )
        # A new worker must retain old-writer references before migration runs.
        assert list(connection.scalars(_unused_skill_bundles())) == ["orphan"]
        connection.commit()
        v7.module.upgrade()
        connection.commit()
        assert list(connection.scalars(_unused_skill_bundles())) == ["orphan"]
        after = connection.execute(
            text("SELECT * FROM skill_version ORDER BY skill_id, version_number")
        ).all()
        assert len(after) == 8
        # Existing rows stay, apart from lazy validity on the matching current bundle.
        for old in before:
            new = next(row for row in after if row.id == old.id)
            assert new.bundle_file_id == old.bundle_file_id
            assert new.bundle_sha256 == old.bundle_sha256
            assert new.created_at == old.created_at
            assert new.version_number == old.version_number
        current = connection.execute(
            text("""
            SELECT s.name, v.* FROM skill s LEFT JOIN skill_version v
            ON v.id = s.current_version_id ORDER BY s.id
        """)
        ).all()
        assert current[0].bundle_file_id == "new-file"
        assert current[0].bundle_sha256 is None
        assert current[0].version_number == 2
        assert current[1].version_number == 1
        assert current[2].is_valid is None and current[2].version_number == 1
        assert current[3].bundle_file_id == "file-4"
        assert current[4].version_number == 2
        assert current[5].id is None
        assert all(row.created_by_user_id is None for row in after if row not in before)
        columns = {col["name"] for col in inspect(connection).get_columns("skill")}
        assert {"bundle_file_id", "bundle_sha256", "is_valid"} <= columns
        assert (
            connection.execute(
                text("SELECT bundle_file_id, bundle_sha256, is_valid FROM skill")
            ).all()
            == [(None, None, None)] * 6
        )
        # Old bundle and validity writers must fail without changing current content.
        for assignment in (
            "bundle_file_id = 'old-file'",
            "bundle_sha256 = 'old-hash'",
            "is_valid = false",
        ):
            with pytest.raises(IntegrityError, match="ck_skill_legacy_fields_retired"):
                with connection.begin_nested():
                    connection.execute(
                        text(f"UPDATE skill SET {assignment} WHERE name = 'skill-1'")
                    )
        assert (
            connection.execute(
                text("SELECT current_version_id FROM skill WHERE name = 'skill-1'")
            ).scalar_one()
            == current[0].id
        )
        # Both sides of the new XOR are immediate; the same-skill FK stays deferred.
        for sql in (
            "UPDATE skill SET current_version_id = NULL WHERE name = 'skill-1'",
            "UPDATE skill SET current_version_id = id WHERE name = 'skill-6'",
        ):
            with pytest.raises(IntegrityError, match="ck_skill_definition_source"):
                with connection.begin_nested():
                    connection.execute(text(sql))
        fk = next(
            fk
            for fk in inspect(connection).get_foreign_keys("skill")
            if fk["name"] == "fk_skill_current_version"
        )
        assert fk["options"] == {"deferrable": True, "initially": "DEFERRED"}
        # Downgrade restores current data into the cleared legacy fields.
        connection.execute(
            text(
                "UPDATE skill_version SET bundle_file_id = 'v7-file', bundle_sha256 = 'v7-hash', is_valid = false WHERE id = :id"
            ),
            {"id": current[0].id},
        )
        v7.module.downgrade()
        connection.commit()
        assert connection.execute(
            text(
                "SELECT bundle_file_id, bundle_sha256, is_valid FROM skill WHERE name = 'skill-1'"
            )
        ).one() == ("v7-file", "v7-hash", False)
        v7.module.upgrade()
        connection.commit()
        round_trip = connection.execute(
            text("SELECT id, version_number FROM skill_version ORDER BY id")
        ).all()
        assert round_trip == sorted((row.id, row.version_number) for row in after)
        # Missing current links cannot be represented by the old constraint.
        connection.execute(
            text("UPDATE skill_version SET bundle_file_id = NULL WHERE id = :id"),
            {"id": current[0].id},
        )
        connection.commit()
        with pytest.raises(
            DBAPIError,
            match="Cannot downgrade skills without current bundle references",
        ):
            with connection.begin_nested():
                v7.module.downgrade()
        assert "current_version_id" in next(
            c["sqltext"]
            for c in inspect(connection).get_check_constraints("skill")
            if c["name"] == "ck_skill_definition_source"
        )


def test_skill_orm_does_not_select_legacy_columns() -> None:
    legacy = {"bundle_file_id", "bundle_sha256", "is_valid"}
    assert legacy <= set(Skill.__table__.columns.keys())
    assert not legacy.intersection(inspect(Skill).attrs.keys())
    sql = str(select(Skill))
    assert all(f"skill.{column}" not in sql for column in legacy)
    assert "LEFT OUTER JOIN skill_version" in sql
