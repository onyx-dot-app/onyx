"""History reads and restore failure paths with real PostgreSQL and FileStore."""

from typing import Never

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.models import FileRecord, Skill, SkillVersion, User
from onyx.db.resource_version import VERSION_FILES_NOT_KEPT
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.file_store import get_default_file_store
from onyx.server.features.skill import api
from onyx.skills.bundle import DEFAULT_PER_FILE_MAX_BYTES
from onyx.skills.ingest import save_skill_bundle_bytes
from tests.external_dependency_unit.db.test_skill_version_writes import bundle, upload
from tests.external_dependency_unit.db.test_skill_version_writes import (
    session as session,
)
from tests.external_dependency_unit.db.test_skill_version_writes import tenant as tenant
from tests.external_dependency_unit.db.test_skill_version_writes import user as user


@pytest.mark.parametrize("damage", ["pruned", "missing", "oversized"])
def test_unreadable_history_refuses_preview_and_restore(
    session: Session, user: User, damage: str
) -> None:
    skill = api.create_custom_skill(
        upload(bundle("history-damage")), False, user, session
    )
    original_id = api.list_custom_skill_versions(skill.id, user, session)[0].id
    api.replace_current_user_skill_bundle(
        skill.id, upload(bundle(skill.name, "Current instructions")), user, session
    )
    original = session.get(SkillVersion, original_id)
    assert original is not None and original.bundle_file_id is not None
    store = get_default_file_store()
    if damage == "pruned":
        original.bundle_file_id = None
    elif damage == "missing":
        store.delete_file(original.bundle_file_id)
    else:
        original.bundle_file_id = save_skill_bundle_bytes(
            bundle(skill.name, "x" * (DEFAULT_PER_FILE_MAX_BYTES + 1)),
            display_name="oversized.zip",
            file_store=store,
        )
    session.commit()
    before_files = set(session.scalars(select(FileRecord.file_id)))
    before_history = api.list_custom_skill_versions(skill.id, user, session)
    for operation in (
        api.preview_custom_skill_version,
        api.restore_custom_skill_version,
    ):
        with pytest.raises(OnyxError) as error:
            operation(skill.id, original_id, user, session)
        if damage == "oversized":
            assert error.value.error_code == OnyxErrorCode.PAYLOAD_TOO_LARGE
        else:
            assert error.value.detail == VERSION_FILES_NOT_KEPT
        session.rollback()
    assert api.list_custom_skill_versions(skill.id, user, session) == before_history
    assert set(session.scalars(select(FileRecord.file_id))) == before_files
    assert (
        api.fetch_custom_skill_for_edit(skill.id, user, session).instructions_markdown
        == "Current instructions"
    )


def test_failed_restore_commit_cleans_only_staged_blob(
    session: Session, user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    skill = api.create_custom_skill(
        upload(bundle("restore-rollback")), False, user, session
    )
    original = api.list_custom_skill_versions(skill.id, user, session)[0]
    api.replace_current_user_skill_bundle(
        skill.id, upload(bundle(skill.name, "Current instructions")), user, session
    )
    before_history = api.list_custom_skill_versions(skill.id, user, session)
    before_files = set(session.scalars(select(FileRecord.file_id)))

    def fail_commit() -> Never:
        session.rollback()
        raise RuntimeError("commit rejected")

    with monkeypatch.context() as patch:
        patch.setattr(session, "commit", fail_commit)
        with pytest.raises(RuntimeError, match="commit rejected"):
            api.restore_custom_skill_version(skill.id, original.id, user, session)
    assert api.list_custom_skill_versions(skill.id, user, session) == before_history
    assert set(session.scalars(select(FileRecord.file_id))) == before_files
    assert (
        api.preview_custom_skill_version(
            skill.id, original.id, user, session
        ).instructions_markdown
        == "First instructions"
    )


def test_history_without_creator_and_builtin_refusal(
    session: Session, user: User
) -> None:
    skill = api.create_custom_skill(
        upload(bundle("unknown-creator")), False, user, session
    )
    version = session.get(
        SkillVersion, api.list_custom_skill_versions(skill.id, user, session)[0].id
    )
    assert version is not None
    version.created_by_user_id = None
    builtin = Skill(name="pdf", description="Built in", built_in_skill_id="pdf")
    session.add(builtin)
    session.commit()
    assert api.list_custom_skill_versions(skill.id, user, session)[0].created_by is None
    assert (
        api.preview_custom_skill_version(skill.id, version.id, user, session).name
        == skill.name
    )
    with pytest.raises(OnyxError, match="Skill not found"):
        api.list_custom_skill_versions(builtin.id, user, session)
