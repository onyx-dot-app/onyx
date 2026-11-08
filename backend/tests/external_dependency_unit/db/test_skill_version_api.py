"""History reads and restore failure paths with real PostgreSQL and FileStore."""

from typing import Never

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.auth.users import current_user
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import GrantSource, Permission
from onyx.db.models import (
    FileRecord,
    PermissionGrant,
    Skill,
    SkillVersion,
    User,
    UserGroup,
)
from onyx.db.resource_version import VERSION_FILES_NOT_KEPT
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.file_store import get_default_file_store
from onyx.server.features.skill import api
from onyx.skills.bundle import DEFAULT_PER_FILE_MAX_BYTES
from onyx.skills.ingest import save_skill_bundle_bytes
from tests.external_dependency_unit.craft.db_helpers import make_user
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


def test_history_pages_keep_older_rows_stable_during_new_writes(
    session: Session,
) -> None:
    basic = UserGroup(name="Basic", is_default=True)
    session.add(basic)
    session.flush()
    session.add(
        PermissionGrant(
            group_id=basic.id,
            permission=Permission.BASIC_ACCESS,
            grant_source=GrantSource.SYSTEM,
        )
    )
    session.flush()
    user = make_user(session, standard_account=True)
    skill = api.create_custom_skill(
        upload(bundle("paged-history")),
        False,
        user,
        session,
    )
    other = api.create_custom_skill(
        upload(bundle("other-history")),
        False,
        user,
        session,
    )
    rows = [
        SkillVersion(
            skill_id=skill.id,
            version_number=number,
            created_by_user_id=user.id,
        )
        for number in range(2, 106)
    ]
    session.add_all(rows)
    session.add(SkillVersion(skill_id=other.id, version_number=200))
    session.commit()
    app = FastAPI()
    app.include_router(api.user_router)
    app.dependency_overrides[current_user] = lambda: user
    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app) as client:
        path = f"/skills/custom/{skill.id}/versions"
        first = client.get(path)
        assert first.status_code == 200, first.text
        assert [row["version_number"] for row in first.json()] == list(
            range(105, 55, -1)
        )
        assert first.json()[0]["created_by"]["id"] == str(user.id)
        assert first.json()[0]["has_bundle"] is False
        session.add(SkillVersion(skill_id=skill.id, version_number=106))
        session.commit()
        second = client.get(path, params={"before_version": 56})
        assert second.status_code == 200, second.text
        assert [row["version_number"] for row in second.json()] == list(
            range(55, 5, -1)
        )
        last = client.get(path, params={"before_version": 6})
        assert last.status_code == 200, last.text
        assert [row["version_number"] for row in last.json()] == [5, 4, 3, 2, 1]
        assert client.get(path, params={"before_version": 1}).json() == []
        assert client.get(path).json()[0]["version_number"] == 106
        for invalid in (0, -1, "not-a-number"):
            assert (
                client.get(path, params={"before_version": invalid}).status_code == 422
            )
