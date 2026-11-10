"""History reads and restore failure paths with real PostgreSQL and FileStore."""

import io
import zipfile
from typing import Never

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.auth.users import current_user
from onyx.db.engine.sql_engine import get_session, get_session_with_current_tenant
from onyx.db.enums import GrantSource, Permission
from onyx.db.models import (
    FileRecord,
    PermissionGrant,
    Skill,
    SkillVersion,
    User,
    UserGroup,
)
from onyx.db.skill_version import VERSION_FILES_NOT_KEPT, repair_skill_version
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.file_store import get_default_file_store
from onyx.server.features.skill import api
from onyx.skills import ingest
from onyx.skills.bundle import DEFAULT_PER_FILE_MAX_BYTES, build_skill_md
from onyx.skills.ingest import save_skill_bundle_bytes
from tests.external_dependency_unit.craft.db_helpers import make_user
from tests.external_dependency_unit.db.test_skill_version_writes import bundle, upload
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


@pytest.mark.parametrize("offset", [-1, 0, 1])
@pytest.mark.parametrize("reader", ["current", "validation", "preview", "restore"])
def test_stored_read_boundaries(
    session: Session,
    user: User,
    monkeypatch: pytest.MonkeyPatch,
    reader: str,
    offset: int,
) -> None:
    from onyx.file_store.models import BundleLimits
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
        with pytest.raises(OnyxError) as error:
            read()
        assert error.value.error_code == OnyxErrorCode.PAYLOAD_TOO_LARGE
        if reader != "validation":
            assert f"{limits.max_stored_bytes}-byte read limit" in error.value.detail
    else:
        assert read() is not None
    session.rollback()
    restored = reader == "restore" and offset >= 0
    assert len(api.list_custom_skill_versions(skill.id, user, session)) == (
        2 if restored else 1
    )


def test_current_editor_rejects_expansion_before_inspection(
    session: Session,
    user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from onyx.file_store.models import BundleLimits
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
    )
    with pytest.raises(OnyxError) as error:
        api.fetch_custom_skill_for_edit(response.id, user, session)
    assert error.value.error_code == OnyxErrorCode.PAYLOAD_TOO_LARGE


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


def test_history_current_marker_includes_edit_after_authorization(
    session: Session, user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    skill = api.create_custom_skill(
        upload(bundle("history-concurrent-edit")), False, user, session
    )
    list_versions = api.list_skill_versions

    def edit_before_history_query(
        authorized: Skill, db_session: Session, *, before_version: int | None = None
    ) -> list[tuple[SkillVersion, User | None, bool]]:
        with get_session_with_current_tenant() as writer:
            writer_user = writer.get(User, user.id)
            assert writer_user is not None
            api.replace_current_user_skill_bundle(
                skill.id,
                upload(bundle(skill.name, "Concurrent edit")),
                writer_user,
                writer,
            )
        return list_versions(authorized, db_session, before_version=before_version)

    monkeypatch.setattr(api, "list_skill_versions", edit_before_history_query)
    history = api.list_custom_skill_versions(skill.id, user, session)
    assert [(version.version_number, version.is_current) for version in history] == [
        (2, True),
        (1, False),
    ]


def test_history_without_current_pointer_has_no_current_marker(
    session: Session, user: User
) -> None:
    created = api.create_custom_skill(
        upload(bundle("history-missing-pointer")), False, user, session
    )
    skill = session.get(Skill, created.id)
    assert skill is not None
    skill.current_version_id = None
    session.commit()
    history = api.list_custom_skill_versions(created.id, user, session)
    assert [(version.version_number, version.is_current) for version in history] == [
        (1, False)
    ]


def test_restore_legacy_file_count_preserves_upload_limit(
    session: Session, user: User
) -> None:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "SKILL.md",
            build_skill_md(
                name="legacy-count",
                description="Legacy",
                instructions_markdown="Original",
            ),
        )
        for number in range(500):
            archive.writestr(f"notes/{number}.txt", "legacy")
    content = output.getvalue()
    with pytest.raises(OnyxError) as caught:
        api.create_custom_skill(upload(content), False, user, session)
    assert caught.value.error_code == OnyxErrorCode.PAYLOAD_TOO_LARGE
    assert list(session.scalars(select(FileRecord.file_id))) == []
    file_id = save_skill_bundle_bytes(
        content, display_name="legacy.zip", file_store=get_default_file_store()
    )
    skill = Skill(
        name="legacy-count",
        description="Legacy",
        author_user_id=user.id,
        bundle_file_id=file_id,
        is_valid=True,
    )
    session.add(skill)
    session.commit()
    original = repair_skill_version(skill, session)
    session.commit()
    api.replace_current_user_skill_bundle(
        skill.id, upload(bundle(skill.name, "New")), user, session
    )
    restored = api.restore_custom_skill_version(skill.id, original.id, user, session)
    assert restored.instructions_markdown == "Original"
    assert len(restored.files) == 500
    history = api.list_custom_skill_versions(skill.id, user, session)
    assert [(item.version_number, item.is_current) for item in history] == [
        (3, True),
        (2, False),
        (1, False),
    ]


@pytest.mark.parametrize("damage", ["name", "path", "stored_bytes"])
def test_stored_restore_preserves_admission_safety(
    session: Session, user: User, monkeypatch: pytest.MonkeyPatch, damage: str
) -> None:
    created = api.create_custom_skill(
        upload(bundle("restore-safety")), False, user, session
    )
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "SKILL.md",
            build_skill_md(
                name="other-name" if damage == "name" else created.name,
                description="History",
                instructions_markdown="Old",
            ),
        )
        archive.writestr("../escape.txt" if damage == "path" else "note.txt", "old")
    content = output.getvalue()
    file_id = save_skill_bundle_bytes(
        content, display_name="old.zip", file_store=get_default_file_store()
    )
    historical = SkillVersion(
        skill_id=created.id, version_number=2, bundle_file_id=file_id
    )
    session.add(historical)
    session.commit()
    before_files = set(session.scalars(select(FileRecord.file_id)))
    before_history = api.list_custom_skill_versions(created.id, user, session)
    if damage == "stored_bytes":
        monkeypatch.setattr(ingest, "DEFAULT_STORED_ZIP_MAX_BYTES", len(content) - 1)
    with pytest.raises(OnyxError):
        api.restore_custom_skill_version(created.id, historical.id, user, session)
    session.rollback()
    assert set(session.scalars(select(FileRecord.file_id))) == before_files
    assert api.list_custom_skill_versions(created.id, user, session) == before_history
