"""Migration 88184258ae59 re-syncs the plugin rows from the skill rows that
old code changed after the plugin tables were backfilled. The test backfills
with the first migration, changes the skill rows the way old code does, runs
the re-sync twice and compares. Everything rolls back with the test."""

import datetime
import hashlib
import importlib.util
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType
from typing import Any
from uuid import UUID, uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from onyx.db.enums import SkillInstallationPolicy, SkillSharePermission
from onyx.db.models import (
    Skill,
    Skill__User,
    Skill__UserGroup,
    User,
    UserSkillPreference,
)
from onyx.db.skill import replace_skill_bundle
from onyx.skills.ingest import IngestedBundle
from onyx.skills.models import (
    PluginFileEntry,
    PluginSkillContent,
    PluginVersionContent,
)
from tests.external_dependency_unit.craft.db_helpers import make_group, make_user

_VERSIONS = Path(__file__).parents[3] / "alembic/versions"
_ORGANIZATION_LIBRARY_ID = UUID("00000000-0000-4000-8000-00000000011b")
_T0 = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)


def _load(filename: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(filename, _VERSIONS / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@contextmanager
def _migration_ops(db_session: Session) -> Iterator[None]:
    with Operations.context(MigrationContext.configure(db_session.connection())):
        yield


@pytest.fixture
def migration_session(isolated_engine: Engine) -> Iterator[Session]:
    """Migration code runs on a connection outside the app pool. The session
    never commits, so its rows roll back when it closes."""
    with Session(isolated_engine) as session:
        yield session


def _user_uploads_id(user_id: UUID) -> UUID:
    return UUID(hashlib.md5(f"user_uploads:{user_id}".encode()).hexdigest())


def _resync_version_id(plugin_id: UUID, bundle_file_id: str) -> UUID:
    return UUID(hashlib.md5(f"{plugin_id}{bundle_file_id}".encode()).hexdigest())


def _add_skill(
    db_session: Session,
    *,
    name: str,
    minutes: int,
    author: User | None,
    public: bool = False,
    is_valid: bool | None = True,
) -> Skill:
    created_at = _T0 + datetime.timedelta(minutes=minutes)
    skill = Skill(
        id=uuid4(),
        name=name,
        description=f"description of {name}",
        bundle_file_id=f"bundle-{uuid4().hex[:8]}",
        bundle_sha256=uuid4().hex + uuid4().hex,
        is_valid=is_valid,
        author_user_id=author.id if author else None,
        public_permission=SkillSharePermission.VIEWER if public else None,
        created_at=created_at,
        updated_at=created_at + datetime.timedelta(hours=1),
    )
    db_session.add(skill)
    db_session.flush()
    return skill


def _plugin_rows(db_session: Session, skill_ids: list[UUID]) -> dict[str, Any]:
    params = {"ids": skill_ids}
    return {
        "plugins": db_session.execute(
            text(
                "SELECT id, name, description, marketplace_id, author_user_id, "
                "installation_policy, current_version_id, published_version_id "
                "FROM plugin WHERE id = ANY(:ids) ORDER BY id"
            ),
            params,
        ).all(),
        "versions": db_session.execute(
            text(
                "SELECT id, plugin_id, version_number, bundle_file_id, "
                "bundle_sha256, is_valid, file_manifest, created_by_user_id, "
                "created_at FROM plugin_version WHERE plugin_id = ANY(:ids) "
                "ORDER BY plugin_id, version_number"
            ),
            params,
        ).all(),
        "skills": db_session.execute(
            text(
                "SELECT ps.id, ps.plugin_version_id, ps.path, ps.frontmatter "
                "FROM plugin_skill ps JOIN plugin_version v "
                "ON v.id = ps.plugin_version_id WHERE v.plugin_id = ANY(:ids) "
                "ORDER BY ps.id"
            ),
            params,
        ).all(),
        "user_shares": db_session.execute(
            text(
                "SELECT plugin_id, user_id, permission FROM plugin__user "
                "WHERE plugin_id = ANY(:ids) ORDER BY plugin_id, user_id"
            ),
            params,
        ).all(),
        "group_shares": db_session.execute(
            text(
                "SELECT plugin_id, user_group_id, permission FROM plugin__user_group "
                "WHERE plugin_id = ANY(:ids) ORDER BY plugin_id, user_group_id"
            ),
            params,
        ).all(),
        "preferences": db_session.execute(
            text(
                "SELECT plugin_id, user_id, enabled FROM user_plugin_preference "
                "WHERE plugin_id = ANY(:ids) ORDER BY plugin_id, user_id"
            ),
            params,
        ).all(),
    }


def _plugin(db_session: Session, skill_id: UUID) -> Any:
    return db_session.execute(
        text(
            "SELECT name, description, marketplace_id, author_user_id, "
            "installation_policy, current_version_id, published_version_id "
            "FROM plugin WHERE id = :id"
        ),
        {"id": skill_id},
    ).one_or_none()


def _content(name: str, bundle_file_id: str) -> PluginVersionContent:
    return PluginVersionContent(
        bundle_file_id=bundle_file_id,
        bundle_sha256="a" * 64,
        is_valid=True,
        file_manifest=[PluginFileEntry(path="SKILL.md", size=10, sha256="b" * 64)],
        unpacked_size_bytes=10,
        file_count=1,
        skills=[
            PluginSkillContent(
                path="",
                skill_md="---\n",
                frontmatter={"name": name, "description": "written by new code"},
            )
        ],
    )


def test_resync_matches_plugin_rows_to_skill_rows(
    migration_session: Session,
) -> None:
    backfill = _load("cdec9dd9ca3d_add_plugin_tables_and_backfill.py")
    resync = _load("88184258ae59_resync_plugin_tables_from_skills_after_.py")
    owner = make_user(migration_session)
    new_owner = make_user(migration_session)
    viewer = make_user(migration_session)
    editor = make_user(migration_session)
    group = make_group(migration_session)
    other_group = make_group(migration_session)
    tag = uuid4().hex[:6]

    # State when the plugin tables were backfilled.
    kept = _add_skill(migration_session, name=f"kept-{tag}", minutes=0, author=owner)
    gone = _add_skill(migration_session, name=f"gone-{tag}", minutes=1, author=owner)
    edited = _add_skill(
        migration_session, name=f"edited-{tag}", minutes=2, author=owner, public=True
    )
    shared = _add_skill(
        migration_session, name=f"shared-{tag}", minutes=3, author=owner
    )
    published = _add_skill(
        migration_session, name=f"pub-{tag}", minutes=4, author=owner
    )
    unpublished = _add_skill(
        migration_session, name=f"unpub-{tag}", minutes=5, author=owner, public=True
    )
    clash = _add_skill(migration_session, name=f"unpub-{tag}", minutes=6, author=owner)
    moved = _add_skill(migration_session, name=f"moved-{tag}", minutes=7, author=owner)
    new_code = _add_skill(
        migration_session, name=f"newcode-{tag}", minutes=8, author=owner
    )
    classified = _add_skill(
        migration_session,
        name=f"classified-{tag}",
        minutes=10,
        author=owner,
        is_valid=None,
    )
    migration_session.add_all(
        [
            Skill__User(
                skill_id=shared.id,
                user_id=viewer.id,
                permission=SkillSharePermission.VIEWER,
            ),
            Skill__User(
                skill_id=shared.id,
                user_id=editor.id,
                permission=SkillSharePermission.VIEWER,
            ),
            Skill__UserGroup(
                skill_id=shared.id,
                user_group_id=group.id,
                permission=SkillSharePermission.VIEWER,
            ),
            UserSkillPreference(
                user_id=viewer.id, skill_id=shared.id, name=shared.name, enabled=True
            ),
        ]
    )
    migration_session.flush()
    with _migration_ops(migration_session):
        backfill.backfill_plugins_from_skills()

    # unpublished starts in the Organization library, clash in "My uploads".
    assert _plugin(migration_session, clash.id).name == clash.name

    # New code adds a version with a file list. The re-sync must keep it.
    replace_skill_bundle(
        skill=new_code,
        ingested=IngestedBundle(
            canonical_name=new_code.name,
            bundle_file_id=f"bundle-new-{tag}",
            bundle_sha256="a" * 64,
            description="written by new code",
            content=_content(new_code.name, f"bundle-new-{tag}"),
        ),
        base_version_id=None,
        user=owner,
        skip_if_unchanged=False,
        db_session=migration_session,
    )

    # Old code then changes only the skill rows.
    fresh = _add_skill(migration_session, name=f"fresh-{tag}", minutes=9, author=owner)
    migration_session.delete(gone)
    classified.is_valid = False
    edited.bundle_file_id = f"bundle-edited-{tag}"
    edited.bundle_sha256 = "c" * 64
    edited.description = "edited by old code"
    edited.updated_at = _T0 + datetime.timedelta(days=3)
    migration_session.execute(
        text("DELETE FROM skill__user WHERE skill_id = :s AND user_id = :u"),
        {"s": shared.id, "u": viewer.id},
    )
    migration_session.execute(
        text(
            "UPDATE skill__user SET permission = 'EDITOR' "
            "WHERE skill_id = :s AND user_id = :u"
        ),
        {"s": shared.id, "u": editor.id},
    )
    migration_session.execute(
        text("DELETE FROM skill__user_group WHERE skill_id = :s"), {"s": shared.id}
    )
    migration_session.add(
        Skill__UserGroup(
            skill_id=shared.id,
            user_group_id=other_group.id,
            permission=SkillSharePermission.EDITOR,
        )
    )
    migration_session.execute(
        text(
            "UPDATE user_skill_preference SET enabled = false "
            "WHERE skill_id = :s AND user_id = :u"
        ),
        {"s": shared.id, "u": viewer.id},
    )
    migration_session.add(
        UserSkillPreference(
            user_id=editor.id, skill_id=shared.id, name=shared.name, enabled=True
        )
    )
    published.public_permission = SkillSharePermission.VIEWER
    published.installation_policy = SkillInstallationPolicy.DEFAULT
    unpublished.public_permission = None
    moved.author_user_id = new_owner.id
    migration_session.flush()

    with _migration_ops(migration_session):
        resync.upgrade()
    migration_session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    migration_session.execute(text("SET CONSTRAINTS ALL DEFERRED"))

    # A skill old code made gets a plugin; a deleted skill loses its plugin.
    fresh_plugin = _plugin(migration_session, fresh.id)
    assert fresh_plugin is not None
    assert fresh_plugin.current_version_id == fresh.id
    assert fresh_plugin.marketplace_id == _user_uploads_id(owner.id)
    assert _plugin(migration_session, gone.id) is None

    # A changed bundle gets a new version, published in the library.
    edited_plugin = _plugin(migration_session, edited.id)
    new_version_id = _resync_version_id(edited.id, f"bundle-edited-{tag}")
    assert edited_plugin.current_version_id == new_version_id
    assert edited_plugin.published_version_id == new_version_id
    assert edited_plugin.description == "edited by old code"
    version = migration_session.execute(
        text(
            "SELECT version_number, bundle_file_id, bundle_sha256, file_manifest, "
            "created_at FROM plugin_version WHERE id = :id"
        ),
        {"id": new_version_id},
    ).one()
    assert tuple(version) == (
        2,
        f"bundle-edited-{tag}",
        "c" * 64,
        None,
        edited.updated_at,
    )
    assert migration_session.execute(
        text("SELECT frontmatter FROM plugin_skill WHERE plugin_version_id = :id"),
        {"id": new_version_id},
    ).scalar_one() == {"name": edited.name, "description": edited.description}

    # A version from new code stays current: its bundle is the skill bundle.
    new_code_plugin = _plugin(migration_session, new_code.id)
    assert new_code_plugin.description == "written by new code"
    assert (
        migration_session.execute(
            text("SELECT count(*) FROM plugin_version WHERE plugin_id = :id"),
            {"id": new_code.id},
        ).scalar_one()
        == 2
    )

    # Shares and choices equal the skill rows.
    rows = _plugin_rows(migration_session, [shared.id])
    assert [(r.user_id, r.permission) for r in rows["user_shares"]] == [
        (editor.id, "EDITOR")
    ]
    assert [(r.user_group_id, r.permission) for r in rows["group_shares"]] == [
        (other_group.id, "EDITOR")
    ]
    assert sorted((r.user_id, r.enabled) for r in rows["preferences"]) == sorted(
        [(viewer.id, False), (editor.id, True)]
    )

    # Published state follows public_permission; a clash takes a free name.
    published_plugin = _plugin(migration_session, published.id)
    assert published_plugin.marketplace_id == _ORGANIZATION_LIBRARY_ID
    assert published_plugin.published_version_id == published.id
    assert published_plugin.installation_policy == "DEFAULT"
    unpublished_plugin = _plugin(migration_session, unpublished.id)
    assert unpublished_plugin.marketplace_id == _user_uploads_id(owner.id)
    assert unpublished_plugin.published_version_id is None
    assert unpublished_plugin.name == f"{unpublished.name}-2"
    moved_plugin = _plugin(migration_session, moved.id)
    assert moved_plugin.author_user_id == new_owner.id
    assert moved_plugin.marketplace_id == _user_uploads_id(new_owner.id)
    assert moved_plugin.name == moved.name
    kept_plugin = _plugin(migration_session, kept.id)
    assert kept_plugin.current_version_id == kept.id

    # A classification of the same bundle reaches its version.
    assert (
        migration_session.execute(
            text("SELECT is_valid FROM plugin_version WHERE id = :id"),
            {"id": classified.id},
        ).scalar_one()
        is False
    )

    # A second run changes nothing.
    ids = [
        kept.id,
        edited.id,
        shared.id,
        published.id,
        unpublished.id,
        clash.id,
        moved.id,
        new_code.id,
        fresh.id,
        classified.id,
    ]
    before = _plugin_rows(migration_session, ids)
    with _migration_ops(migration_session):
        resync.upgrade()
    assert _plugin_rows(migration_session, ids) == before
