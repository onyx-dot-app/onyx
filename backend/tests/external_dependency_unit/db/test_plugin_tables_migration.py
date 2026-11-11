"""Migration cdec9dd9ca3d adds the plugin tables and backfills one plugin for
each custom skill. The test drops the tables with the migration's downgrade,
seeds skills, then runs upgrade, downgrade and upgrade again. Everything runs
in the test transaction and rolls back."""

import datetime
import hashlib
import importlib.util
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any
from uuid import UUID, uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.orm import Session

from onyx.db.enums import SkillInstallationPolicy, SkillSharePermission
from onyx.db.models import (
    Skill,
    Skill__User,
    Skill__UserGroup,
    User,
    UserSkillPreference,
)
from tests.external_dependency_unit.craft.db_helpers import make_group, make_user

_MIGRATION_PATH = (
    Path(__file__).parents[3]
    / "alembic/versions/cdec9dd9ca3d_add_plugin_tables_and_backfill.py"
)
_ORGANIZATION_LIBRARY_ID = UUID("00000000-0000-4000-8000-00000000011b")
_T0 = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("plugin_migration", _MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


@contextmanager
def _migration_ops(db_session: Session) -> Iterator[None]:
    with Operations.context(MigrationContext.configure(db_session.connection())):
        yield


def _check_deferred_constraints(db_session: Session) -> None:
    """The test never commits, so check the deferred version pointers now."""
    db_session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    db_session.execute(text("SET CONSTRAINTS ALL DEFERRED"))


def _account_uploads_id(user_id: UUID) -> UUID:
    return UUID(hashlib.md5(f"account_uploads:{user_id}".encode()).hexdigest())


def _skill_table_shape(db_session: Session) -> tuple[list[Any], list[Any]]:
    columns = db_session.execute(
        text(
            "SELECT column_name, data_type, is_nullable, column_default "
            "FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = 'skill' "
            "ORDER BY column_name"
        )
    ).all()
    constraints = db_session.execute(
        text(
            "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid = 'skill'::regclass ORDER BY conname"
        )
    ).all()
    return list(columns), list(constraints)


def _table_exists(db_session: Session, table: str) -> bool:
    return db_session.execute(
        text("SELECT to_regclass(:table) IS NOT NULL"), {"table": table}
    ).scalar_one()


@dataclass(frozen=True)
class _Expected:
    """The plugin a custom skill must map to."""

    skill: Skill
    plugin_name: str
    marketplace_id: UUID
    published: bool


def _add_skill(
    db_session: Session,
    *,
    name: str,
    minutes: int,
    author: User | None,
    public_permission: SkillSharePermission | None = None,
    installation_policy: SkillInstallationPolicy = SkillInstallationPolicy.AVAILABLE,
) -> Skill:
    created_at = _T0 + datetime.timedelta(minutes=minutes)
    skill = Skill(
        id=uuid4(),
        name=name,
        description=f"description of {name}",
        bundle_file_id=f"bundle-{uuid4().hex[:8]}",
        bundle_sha256=uuid4().hex + uuid4().hex,
        is_valid=minutes % 2 == 0,
        author_user_id=author.id if author else None,
        public_permission=public_permission,
        installation_policy=installation_policy,
        created_at=created_at,
        updated_at=created_at + datetime.timedelta(hours=1),
    )
    db_session.add(skill)
    db_session.flush()
    return skill


def _assert_backfilled(
    db_session: Session,
    expected: list[_Expected],
    built_in: Skill,
    authors: dict[UUID, User],
    seeded_ids: list[UUID],
) -> None:
    library = db_session.execute(
        text(
            "SELECT kind, name, owner_user_id, default_installation_policy, "
            "created_at FROM plugin_marketplace WHERE id = :id"
        ),
        {"id": _ORGANIZATION_LIBRARY_ID},
    ).one()
    assert tuple(library) == (
        "organization_library",
        "Organization library",
        None,
        "AVAILABLE",
        datetime.datetime(2026, 11, 11, tzinfo=datetime.timezone.utc),
    )

    for author_id, author in authors.items():
        uploads = db_session.execute(
            text(
                "SELECT kind, name, owner_user_id, default_installation_policy, "
                "created_at FROM plugin_marketplace WHERE id = :id"
            ),
            {"id": _account_uploads_id(author_id)},
        ).one()
        oldest = min(
            e.skill.created_at for e in expected if e.skill.author_user_id == author_id
        )
        assert tuple(uploads) == (
            "account_uploads",
            "My uploads",
            author.id,
            "AVAILABLE",
            oldest,
        )

    for e in expected:
        skill = e.skill
        plugin = (
            db_session.execute(
                text("SELECT * FROM plugin WHERE id = :id"), {"id": skill.id}
            )
            .mappings()
            .one()
        )
        assert plugin["name"] == e.plugin_name, skill.name
        assert plugin["description"] == skill.description
        assert plugin["kind"] == "skill"
        assert plugin["marketplace_id"] == e.marketplace_id
        assert plugin["author_user_id"] == skill.author_user_id
        assert plugin["installation_policy"] == (
            None
            if skill.installation_policy == SkillInstallationPolicy.AVAILABLE
            else skill.installation_policy.value
        )
        assert plugin["current_version_id"] == skill.id
        assert plugin["published_version_id"] == (skill.id if e.published else None)
        assert plugin["created_at"] == skill.created_at
        assert plugin["updated_at"] == skill.updated_at

        versions = (
            db_session.execute(
                text("SELECT * FROM plugin_version WHERE plugin_id = :id"),
                {"id": skill.id},
            )
            .mappings()
            .all()
        )
        assert len(versions) == 1
        version = versions[0]
        author = authors.get(skill.author_user_id) if skill.author_user_id else None
        assert version["id"] == skill.id
        assert version["version_number"] == 1
        assert version["bundle_file_id"] == skill.bundle_file_id
        assert version["bundle_sha256"] == skill.bundle_sha256
        assert version["is_valid"] == skill.is_valid
        assert version["file_manifest"] is None
        assert version["unpacked_size_bytes"] is None
        assert version["file_count"] is None
        assert version["created_by_user_id"] == skill.author_user_id
        assert version["created_by_email"] == (author.email if author else None)
        assert version["created_at"] == skill.updated_at

        plugin_skills = db_session.execute(
            text(
                "SELECT id, path, name, skill_md, frontmatter FROM plugin_skill "
                "WHERE plugin_version_id = :id"
            ),
            {"id": skill.id},
        ).all()
        # The skill name never changes, also when the plugin name does.
        assert [tuple(row) for row in plugin_skills] == [
            (skill.id, "", skill.name, None, None)
        ]

        user_shares = {
            (row.user_id, row.permission, row.created_at)
            for row in db_session.execute(
                text(
                    "SELECT user_id, permission, created_at FROM plugin__user "
                    "WHERE plugin_id = :id"
                ),
                {"id": skill.id},
            )
        }
        assert user_shares == {
            (share.user_id, share.permission.value, skill.created_at)
            for share in db_session.query(Skill__User).filter_by(skill_id=skill.id)
        }
        group_shares = {
            tuple(row)
            for row in db_session.execute(
                text(
                    "SELECT user_group_id, permission, installation_policy, "
                    "created_at FROM plugin__user_group WHERE plugin_id = :id"
                ),
                {"id": skill.id},
            )
        }
        assert group_shares == {
            (share.user_group_id, share.permission.value, None, skill.created_at)
            for share in db_session.query(Skill__UserGroup).filter_by(skill_id=skill.id)
        }
        preferences = {
            tuple(row)
            for row in db_session.execute(
                text(
                    "SELECT user_id, enabled, enabled_at FROM user_plugin_preference "
                    "WHERE plugin_id = :id"
                ),
                {"id": skill.id},
            )
        }
        assert preferences == {
            (pref.user_id, pref.enabled, None)
            for pref in db_session.query(UserSkillPreference).filter_by(
                skill_id=skill.id
            )
        }

    for table, column in (
        ("plugin", "id"),
        ("plugin_version", "id"),
        ("plugin_skill", "id"),
        ("plugin__user", "plugin_id"),
        ("plugin__user_group", "plugin_id"),
        ("user_plugin_preference", "plugin_id"),
    ):
        assert (
            db_session.execute(
                text(f"SELECT count(*) FROM {table} WHERE {column} = :id"),
                {"id": built_in.id},
            ).scalar_one()
            == 0
        ), table

    assert db_session.execute(
        text("SELECT count(*) FROM plugin WHERE id = ANY(:ids)"),
        {"ids": seeded_ids},
    ).scalar_one() == len(expected)


def test_backfill_maps_each_custom_skill_to_one_plugin(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    migration = _load_migration()
    try:
        skill_shape = _skill_table_shape(db_session)
        with _migration_ops(db_session):
            migration.downgrade()
        assert not _table_exists(db_session, "plugin")

        tag = uuid4().hex[:8]
        deploy = f"deploy-{tag}"
        alice = make_user(db_session, email_prefix="plugin_alice")
        bob = make_user(db_session, email_prefix="plugin_bob")
        carol = make_user(db_session, email_prefix="plugin_carol")
        group = make_group(db_session)
        alice_uploads = _account_uploads_id(alice.id)
        bob_uploads = _account_uploads_id(bob.id)
        library = _ORGANIZATION_LIBRARY_ID

        shared = _add_skill(db_session, name=f"notes-{tag}", minutes=10, author=alice)
        default = _add_skill(
            db_session,
            name=f"lint-{tag}",
            minutes=11,
            author=alice,
            installation_policy=SkillInstallationPolicy.DEFAULT,
        )
        required_public = _add_skill(
            db_session,
            name=f"policy-{tag}",
            minutes=12,
            author=alice,
            public_permission=SkillSharePermission.VIEWER,
            installation_policy=SkillInstallationPolicy.REQUIRED,
        )
        # One user with two skills named deploy and one named deploy-2. The
        # deploy-2 skill is the newest and still keeps its name.
        deploy_oldest = _add_skill(db_session, name=deploy, minutes=1, author=alice)
        deploy_newer = _add_skill(db_session, name=deploy, minutes=3, author=alice)
        deploy_2 = _add_skill(db_session, name=f"{deploy}-2", minutes=4, author=alice)
        # Two public skills named deploy from two users, the newer one with
        # organization-wide edit: both go to the Organization library.
        public_deploy_bob = _add_skill(
            db_session,
            name=deploy,
            minutes=2,
            author=bob,
            public_permission=SkillSharePermission.VIEWER,
        )
        public_deploy_carol = _add_skill(
            db_session,
            name=deploy,
            minutes=5,
            author=carol,
            public_permission=SkillSharePermission.EDITOR,
        )
        authorless = _add_skill(
            db_session,
            name=f"orphan-{tag}",
            minutes=6,
            author=None,
            public_permission=SkillSharePermission.VIEWER,
        )
        # A full-length duplicate name is cut to fit the suffix.
        long_name = f"{tag}-" + "x" * (64 - len(tag) - 1)
        long_first = _add_skill(db_session, name=long_name, minutes=7, author=bob)
        long_second = _add_skill(db_session, name=long_name, minutes=8, author=bob)
        built_in = Skill(
            id=uuid4(),
            name=f"builtin-{tag}",
            description="built-in",
            built_in_skill_id=f"test-builtin-{tag}",
            public_permission=SkillSharePermission.VIEWER,
        )
        db_session.add(built_in)
        db_session.flush()

        db_session.add_all(
            [
                Skill__User(
                    skill_id=shared.id,
                    user_id=bob.id,
                    permission=SkillSharePermission.EDITOR,
                ),
                Skill__User(
                    skill_id=shared.id,
                    user_id=carol.id,
                    permission=SkillSharePermission.VIEWER,
                ),
                Skill__User(
                    skill_id=built_in.id,
                    user_id=carol.id,
                    permission=SkillSharePermission.VIEWER,
                ),
                Skill__UserGroup(
                    skill_id=shared.id,
                    user_group_id=group.id,
                    permission=SkillSharePermission.VIEWER,
                ),
                Skill__UserGroup(
                    skill_id=public_deploy_bob.id,
                    user_group_id=group.id,
                    permission=SkillSharePermission.EDITOR,
                ),
                UserSkillPreference(
                    user_id=bob.id, skill_id=shared.id, name=shared.name, enabled=True
                ),
                UserSkillPreference(
                    user_id=carol.id,
                    skill_id=default.id,
                    name=default.name,
                    enabled=False,
                ),
                UserSkillPreference(
                    user_id=carol.id,
                    skill_id=built_in.id,
                    name=built_in.name,
                    enabled=True,
                ),
            ]
        )
        db_session.flush()

        expected = [
            _Expected(shared, shared.name, alice_uploads, False),
            _Expected(default, default.name, alice_uploads, False),
            _Expected(required_public, required_public.name, library, True),
            _Expected(deploy_oldest, deploy, alice_uploads, False),
            _Expected(deploy_newer, f"{deploy}-3", alice_uploads, False),
            _Expected(deploy_2, f"{deploy}-2", alice_uploads, False),
            _Expected(public_deploy_bob, deploy, library, True),
            _Expected(public_deploy_carol, f"{deploy}-2", library, True),
            _Expected(authorless, authorless.name, library, True),
            _Expected(long_first, long_name, bob_uploads, False),
            _Expected(long_second, long_name[:62] + "-2", bob_uploads, False),
        ]
        authors = {user.id: user for user in (alice, bob, carol)}
        seeded_ids = [e.skill.id for e in expected] + [built_in.id]

        with _migration_ops(db_session):
            migration.upgrade()
        _check_deferred_constraints(db_session)
        _assert_backfilled(db_session, expected, built_in, authors, seeded_ids)
        assert _skill_table_shape(db_session) == skill_shape

        with _migration_ops(db_session):
            migration.downgrade()
        assert not _table_exists(db_session, "plugin")
        assert not _table_exists(db_session, "plugin_marketplace")
        assert _skill_table_shape(db_session) == skill_shape

        with _migration_ops(db_session):
            migration.upgrade()
        _check_deferred_constraints(db_session)
        _assert_backfilled(db_session, expected, built_in, authors, seeded_ids)

        # A second run (as a re-sync migration does) adds only skills that have
        # no plugin yet and gives a new duplicate the first free name.
        late_deploy = _add_skill(db_session, name=deploy, minutes=20, author=alice)
        with _migration_ops(db_session):
            migration.backfill_plugins_from_skills()
        _check_deferred_constraints(db_session)
        _assert_backfilled(
            db_session,
            [*expected, _Expected(late_deploy, f"{deploy}-4", alice_uploads, False)],
            built_in,
            authors,
            [*seeded_ids, late_deploy.id],
        )
    finally:
        db_session.rollback()
