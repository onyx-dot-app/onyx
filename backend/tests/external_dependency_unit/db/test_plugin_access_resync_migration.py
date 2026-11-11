"""Migration 4ea385d01d75 re-syncs the plugin rows from the skill rows that old
code changed after plugin versions were written (88184258ae59), but before
access writes went to the plugin tables. Everything rolls back with the test."""

from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from onyx.db.enums import SkillInstallationPolicy, SkillSharePermission
from onyx.db.models import Skill__User, Skill__UserGroup, UserSkillPreference
from onyx.db.skill import replace_skill_bundle
from onyx.skills.ingest import IngestedBundle
from tests.external_dependency_unit.craft.db_helpers import make_group, make_user
from tests.external_dependency_unit.db.test_plugin_resync_migration import (
    _add_skill,
    _content,
    _load,
    _migration_ops,
    _plugin,
    _plugin_rows,
)
from tests.utils.plugin_access import (
    ORGANIZATION_LIBRARY_ID,
    account_uploads_id,
    plugin_access_mismatches,
)


def _version_count(db_session: Session, plugin_id: UUID) -> Any:
    return db_session.execute(
        text("SELECT count(*) FROM plugin_version WHERE plugin_id = :id"),
        {"id": plugin_id},
    ).scalar_one()


def test_access_resync_matches_plugin_rows_to_skill_rows(db_session: Session) -> None:
    backfill = _load("cdec9dd9ca3d_add_plugin_tables_and_backfill.py")
    version_resync = _load("88184258ae59_resync_plugin_tables_from_skills_after_.py")
    access_resync = _load("4ea385d01d75_resync_plugin_tables_from_skills_after_.py")
    owner = make_user(db_session)
    new_owner = make_user(db_session)
    viewer = make_user(db_session)
    group = make_group(db_session)
    tag = uuid4().hex[:6]

    # State when plugin versions were first written.
    shared = _add_skill(db_session, name=f"shared-{tag}", minutes=0, author=owner)
    published = _add_skill(db_session, name=f"pub-{tag}", minutes=1, author=owner)
    unpublished = _add_skill(
        db_session, name=f"unpub-{tag}", minutes=2, author=owner, public=True
    )
    clash = _add_skill(db_session, name=f"unpub-{tag}", minutes=3, author=owner)
    moved = _add_skill(db_session, name=f"moved-{tag}", minutes=4, author=owner)
    gone = _add_skill(db_session, name=f"gone-{tag}", minutes=5, author=owner)
    edited = _add_skill(db_session, name=f"edited-{tag}", minutes=6, author=owner)
    db_session.flush()
    with _migration_ops(db_session):
        backfill.backfill_plugins_from_skills()
        version_resync.upgrade()

    # Code with plugin versions adds a version. The re-sync keeps it.
    replace_skill_bundle(
        skill=edited,
        ingested=IngestedBundle(
            canonical_name=edited.name,
            bundle_file_id=f"bundle-new-{tag}",
            bundle_sha256="a" * 64,
            description="written by new code",
            content=_content(edited.name, f"bundle-new-{tag}"),
        ),
        base_version_id=None,
        user=owner,
        skip_if_unchanged=False,
        db_session=db_session,
    )

    # Code without access writes then changes only the skill rows: shares,
    # choices, publish, unpublish, an install setting, a transfer, a new skill
    # from an old pod and a delete.
    db_session.add_all(
        [
            Skill__User(
                skill_id=shared.id,
                user_id=viewer.id,
                permission=SkillSharePermission.EDITOR,
            ),
            Skill__UserGroup(
                skill_id=shared.id,
                user_group_id=group.id,
                permission=SkillSharePermission.VIEWER,
            ),
            UserSkillPreference(
                user_id=viewer.id, skill_id=shared.id, name=shared.name, enabled=False
            ),
        ]
    )
    published.public_permission = SkillSharePermission.VIEWER
    published.installation_policy = SkillInstallationPolicy.REQUIRED
    unpublished.public_permission = None
    moved.author_user_id = new_owner.id
    fresh = _add_skill(db_session, name=f"fresh-{tag}", minutes=7, author=owner)
    db_session.execute(
        text("DELETE FROM skill WHERE id = :id"),
        {"id": gone.id},
    )
    db_session.expunge(gone)
    db_session.flush()
    ids = [
        shared.id,
        published.id,
        unpublished.id,
        clash.id,
        moved.id,
        edited.id,
        fresh.id,
    ]
    assert plugin_access_mismatches(db_session, ids) != []

    with _migration_ops(db_session):
        access_resync.upgrade()
    db_session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    db_session.execute(text("SET CONSTRAINTS ALL DEFERRED"))

    assert plugin_access_mismatches(db_session, ids) == []
    assert _plugin(db_session, gone.id) is None
    assert _plugin(db_session, published.id).marketplace_id == ORGANIZATION_LIBRARY_ID
    # The unpublished plugin goes back to "My uploads", where clash has its name.
    assert _plugin(db_session, unpublished.id).name == f"{unpublished.name}-2"
    assert _plugin(db_session, moved.id).marketplace_id == account_uploads_id(
        new_owner.id
    )
    assert _version_count(db_session, edited.id) == 2

    # A second run changes nothing.
    before = _plugin_rows(db_session, ids)
    with _migration_ops(db_session):
        access_resync.upgrade()
    assert _plugin_rows(db_session, ids) == before
