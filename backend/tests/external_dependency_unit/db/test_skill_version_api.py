"""History reads and restore failure paths with real PostgreSQL and FileStore."""

from typing import Never

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.models import FileRecord, Skill, SkillVersion, User
from onyx.db.resource_version import VERSION_FILES_NOT_KEPT
from onyx.db.skill_version import delete_orphan_skill_bundles
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.file_store import get_default_file_store
from onyx.server.features.skill import api
from onyx.skills.bundle import DEFAULT_PER_FILE_MAX_BYTES
from onyx.skills.ingest import save_skill_bundle_bytes
from tests.external_dependency_unit.db.test_skill_version_writes import (
    bundle,
    make_old,
    upload,
)
from tests.external_dependency_unit.db.test_skill_version_writes import (
    session as session,
)
from tests.external_dependency_unit.db.test_skill_version_writes import tenant as tenant
from tests.external_dependency_unit.db.test_skill_version_writes import user as user


@pytest.mark.parametrize("damage", ["pruned", "missing", "oversized", "corrupt"])
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
            (
                b"not a ZIP"
                if damage == "corrupt"
                else bundle(skill.name, "x" * (DEFAULT_PER_FILE_MAX_BYTES + 1))
            ),
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
        elif damage != "corrupt":
            assert error.value.detail == VERSION_FILES_NOT_KEPT
        session.rollback()
    assert api.list_custom_skill_versions(skill.id, user, session) == before_history
    assert set(session.scalars(select(FileRecord.file_id))) == before_files
    assert (
        api.fetch_custom_skill_for_edit(skill.id, user, session).instructions_markdown
        == "Current instructions"
    )


@pytest.mark.parametrize("committed", [False, True])
def test_failed_restore_commit_defers_cleanup(
    session: Session, user: User, monkeypatch: pytest.MonkeyPatch, committed: bool
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
    commit = session.commit

    def fail_commit() -> Never:
        if committed:
            commit()
        else:
            session.rollback()
        raise RuntimeError("commit rejected")

    with monkeypatch.context() as patch:
        patch.setattr(session, "commit", fail_commit)
        with pytest.raises(RuntimeError, match="commit rejected"):
            api.restore_custom_skill_version(skill.id, original.id, user, session)
    history = api.list_custom_skill_versions(skill.id, user, session)
    assert len(history) == len(before_history) + int(committed)
    if not committed:
        assert history == before_history
    after_files = set(session.scalars(select(FileRecord.file_id)))
    assert before_files <= after_files
    staged = after_files - before_files
    assert len(staged) == 1
    assert delete_orphan_skill_bundles() == 0
    make_old(staged, session)
    assert delete_orphan_skill_bundles() == (0 if committed else 1)
    assert set(session.scalars(select(FileRecord.file_id))) == (
        after_files if committed else before_files
    )
    assert api.fetch_custom_skill_for_edit(
        skill.id, user, session
    ).instructions_markdown == (
        "First instructions" if committed else "Current instructions"
    )
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


@pytest.mark.parametrize("offset", [-1, 0, 1])
@pytest.mark.parametrize("reader", ["current", "validation", "preview", "restore"])
def test_stored_read_boundaries(
    session: Session,
    user: User,
    monkeypatch: pytest.MonkeyPatch,
    reader: str,
    offset: int,
) -> None:
    from onyx.file_store.models import BundleLimits, FileSizeLimitExceeded
    from onyx.skills import content, validation

    response = api.create_custom_skill(
        upload(bundle("bounded-reader")), False, user, session
    )
    skill = session.get(Skill, response.id)
    assert skill is not None and skill.current_version is not None
    version = skill.current_version
    assert version.bundle_file_id is not None
    bundle_file_id = version.bundle_file_id
    store = get_default_file_store()
    with store.read_file(bundle_file_id) as source:
        stored = source.read()
    limits = BundleLimits(
        max_stored_bytes=len(stored) + offset,
        max_file_bytes=10000,
        max_total_bytes=10000,
    )
    for module in (api, content, validation):
        monkeypatch.setattr(module, "STORED_BUNDLE_LIMITS", limits, raising=False)

    def read() -> object:
        if reader == "current":
            return content.read_custom_skill_bundle_instructions(skill, store)
        if reader == "validation":
            return validation.load_stored_custom_skill_bundle(bundle_file_id, store)
        if reader == "preview":
            return api.preview_custom_skill_version(skill.id, version.id, user, session)
        return api.restore_custom_skill_version(skill.id, version.id, user, session)

    if offset < 0:
        with pytest.raises(FileSizeLimitExceeded):
            read()
    else:
        assert read() is not None
    session.rollback()
    assert len(api.list_custom_skill_versions(skill.id, user, session)) == 1


def test_current_editor_rejects_expansion_before_inspection(
    session: Session,
    user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from onyx.file_store.models import BundleLimits, FileSizeLimitExceeded
    from onyx.skills import content

    response = api.create_custom_skill(
        upload(bundle("bounded-editor")), False, user, session
    )
    monkeypatch.setattr(
        content,
        "STORED_BUNDLE_LIMITS",
        BundleLimits(
            max_stored_bytes=10000,
            max_file_bytes=1,
            max_total_bytes=10000,
        ),
        raising=False,
    )
    with pytest.raises(FileSizeLimitExceeded):
        api.fetch_custom_skill_for_edit(response.id, user, session)


def test_legacy_current_and_preview_keep_stored_allowances(
    session: Session,
    user: User,
) -> None:
    import io
    import zipfile

    from onyx.skills.validation import load_stored_custom_skill_bundle

    response = api.create_custom_skill(
        upload(bundle("legacy-reader")), False, user, session
    )
    skill = session.get(Skill, response.id)
    assert skill is not None and skill.current_version is not None
    version = skill.current_version
    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(bundle(skill.name))) as original:
        skill_md = original.read("SKILL.md")
    with zipfile.ZipFile(output, "w", zipfile.ZIP_STORED) as archive:
        archive.writestr("SKILL.md", skill_md)
        for index in range(501):
            archive.writestr(f"file-{index}", b"x" * (55 * 1024))
    assert len(output.getvalue()) > 25 * 1024 * 1024
    store = get_default_file_store()
    version.bundle_file_id = save_skill_bundle_bytes(
        output.getvalue(),
        display_name="legacy.zip",
        file_store=store,
    )
    session.commit()
    assert version.bundle_file_id is not None
    assert (
        load_stored_custom_skill_bundle(version.bundle_file_id, store).content
        == output.getvalue()
    )
    assert len(api.fetch_custom_skill_for_edit(skill.id, user, session).files) == 501
    assert (
        len(api.preview_custom_skill_version(skill.id, version.id, user, session).files)
        == 501
    )
