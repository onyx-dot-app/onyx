"""History reads and restore failure paths with real PostgreSQL and FileStore."""

from typing import Never

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import select, update
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
from onyx.db.resource_version import VERSION_FILES_NOT_KEPT
from onyx.db.skill_version import PreparedSkillVersionWrite, delete_orphan_skill_bundles
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.file_store import get_default_file_store
from onyx.server.features.skill import api
from onyx.skills.bundle import DEFAULT_PER_FILE_MAX_BYTES, compute_bundle_sha256
from onyx.skills.ingest import IngestedBundle, save_skill_bundle_bytes
from tests.external_dependency_unit.craft.db_helpers import make_user
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


def test_history_current_marker_includes_edit_after_authorization(
    session: Session, user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    skill = api.create_custom_skill(
        upload(bundle("history-concurrent-edit")),
        False,
        user,
        session,
        http_request=Request({"type": "http"}),
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
                http_request=Request({"type": "http"}),
            )
        return list_versions(authorized, db_session, before_version=before_version)

    monkeypatch.setattr(api, "list_skill_versions", edit_before_history_query)
    history = api.list_custom_skill_versions(
        skill.id,
        user,
        session,
        http_request=Request({"type": "http"}),
    )
    assert [(version.version_number, version.is_current) for version in history] == [
        (2, True),
        (1, False),
    ]


def test_history_without_current_pointer_has_no_current_marker(
    session: Session, user: User
) -> None:
    created = api.create_custom_skill(
        upload(bundle("history-missing-pointer")),
        False,
        user,
        session,
        http_request=Request({"type": "http"}),
    )
    skill = session.get(Skill, created.id)
    assert skill is not None
    skill.current_version_id = None
    session.commit()
    history = api.list_custom_skill_versions(
        created.id,
        user,
        session,
        http_request=Request({"type": "http"}),
    )
    assert [(version.version_number, version.is_current) for version in history] == [
        (1, False)
    ]


@pytest.mark.parametrize("damage", ["pruned", "missing", "oversized", "corrupt"])
def test_unreadable_history_refuses_preview_and_restore(
    session: Session, user: User, damage: str
) -> None:
    skill = api.create_custom_skill(
        upload(bundle("history-damage")),
        False,
        user,
        session,
        http_request=Request({"type": "http"}),
    )
    original_id = api.list_custom_skill_versions(
        skill.id,
        user,
        session,
        http_request=Request({"type": "http"}),
    )[0].id
    api.replace_current_user_skill_bundle(
        skill.id,
        upload(bundle(skill.name, "Current instructions")),
        user,
        session,
        http_request=Request({"type": "http"}),
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
    before_history = api.list_custom_skill_versions(
        skill.id,
        user,
        session,
        http_request=Request({"type": "http"}),
    )
    for operation in (
        api.preview_custom_skill_version,
        api.restore_custom_skill_version,
    ):
        with pytest.raises(OnyxError) as error:
            operation(
                skill.id,
                original_id,
                user,
                session,
                http_request=Request({"type": "http"}),
            )
        if damage == "oversized":
            assert error.value.error_code == OnyxErrorCode.PAYLOAD_TOO_LARGE
        elif damage != "corrupt":
            assert error.value.detail == VERSION_FILES_NOT_KEPT
        session.rollback()
    assert (
        api.list_custom_skill_versions(
            skill.id,
            user,
            session,
            http_request=Request({"type": "http"}),
        )
        == before_history
    )
    assert set(session.scalars(select(FileRecord.file_id))) == before_files
    assert (
        api.fetch_custom_skill_for_edit(
            skill.id,
            user,
            session,
            http_request=Request({"type": "http"}),
        ).instructions_markdown
        == "Current instructions"
    )


def test_restore_rechecks_historical_bundle_after_storage(
    session: Session, user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    skill = api.create_custom_skill(
        upload(bundle("restore-pruned-source")),
        False,
        user,
        session,
        http_request=Request({"type": "http"}),
    )
    original = api.list_custom_skill_versions(
        skill.id, user, session, http_request=Request({"type": "http"})
    )[0]
    api.replace_current_user_skill_bundle(
        skill.id,
        upload(bundle(skill.name, "Current instructions")),
        user,
        session,
        http_request=Request({"type": "http"}),
    )
    before_files = set(session.scalars(select(FileRecord.file_id)))
    prepare = api.prepare_skill_version_write

    def prune_after_preparation(
        source: Skill, ingested: IngestedBundle, db_session: Session
    ) -> PreparedSkillVersionWrite:
        prepared = prepare(source, ingested, db_session)
        with get_session_with_current_tenant() as writer:
            writer.execute(
                update(SkillVersion)
                .where(SkillVersion.id == original.id)
                .values(bundle_file_id=None)
            )
            writer.commit()
        return prepared

    with monkeypatch.context() as patch:
        patch.setattr(api, "prepare_skill_version_write", prune_after_preparation)
        with pytest.raises(OnyxError, match="Version files changed") as caught:
            api.restore_custom_skill_version(
                skill.id,
                original.id,
                user,
                session,
                http_request=Request({"type": "http"}),
            )
    assert caught.value.error_code == OnyxErrorCode.CONFLICT
    assert (
        len(
            api.list_custom_skill_versions(
                skill.id, user, session, http_request=Request({"type": "http"})
            )
        )
        == 2
    )
    assert set(session.scalars(select(FileRecord.file_id))) == before_files
    assert (
        api.fetch_custom_skill_for_edit(
            skill.id, user, session, http_request=Request({"type": "http"})
        ).instructions_markdown
        == "Current instructions"
    )


@pytest.mark.parametrize("committed", [False, True])
def test_failed_restore_commit_defers_cleanup(
    session: Session, user: User, monkeypatch: pytest.MonkeyPatch, committed: bool
) -> None:
    skill = api.create_custom_skill(
        upload(bundle("restore-rollback")),
        False,
        user,
        session,
        http_request=Request({"type": "http"}),
    )
    original = api.list_custom_skill_versions(
        skill.id,
        user,
        session,
        http_request=Request({"type": "http"}),
    )[0]
    api.replace_current_user_skill_bundle(
        skill.id,
        upload(bundle(skill.name, "Current instructions")),
        user,
        session,
        http_request=Request({"type": "http"}),
    )
    before_history = api.list_custom_skill_versions(
        skill.id,
        user,
        session,
        http_request=Request({"type": "http"}),
    )
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
            api.restore_custom_skill_version(
                skill.id,
                original.id,
                user,
                session,
                http_request=Request({"type": "http"}),
            )
    history = api.list_custom_skill_versions(
        skill.id,
        user,
        session,
        http_request=Request({"type": "http"}),
    )
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
        skill.id,
        user,
        session,
        http_request=Request({"type": "http"}),
    ).instructions_markdown == (
        "First instructions" if committed else "Current instructions"
    )
    assert (
        api.preview_custom_skill_version(
            skill.id,
            original.id,
            user,
            session,
            http_request=Request({"type": "http"}),
        ).instructions_markdown
        == "First instructions"
    )


def test_history_without_creator_and_builtin_refusal(
    session: Session, user: User
) -> None:
    skill = api.create_custom_skill(
        upload(bundle("unknown-creator")),
        False,
        user,
        session,
        http_request=Request({"type": "http"}),
    )
    version = session.get(
        SkillVersion,
        api.list_custom_skill_versions(
            skill.id,
            user,
            session,
            http_request=Request({"type": "http"}),
        )[0].id,
    )
    assert version is not None
    version.created_by_user_id = None
    builtin = Skill(name="pdf", description="Built in", built_in_skill_id="pdf")
    session.add(builtin)
    session.commit()
    assert (
        api.list_custom_skill_versions(
            skill.id,
            user,
            session,
            http_request=Request({"type": "http"}),
        )[0].created_by
        is None
    )
    assert (
        api.preview_custom_skill_version(
            skill.id,
            version.id,
            user,
            session,
            http_request=Request({"type": "http"}),
        ).name
        == skill.name
    )
    with pytest.raises(OnyxError, match="Skill not found"):
        api.list_custom_skill_versions(
            builtin.id,
            user,
            session,
            http_request=Request({"type": "http"}),
        )


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
        upload(bundle("bounded-reader")),
        False,
        user,
        session,
        http_request=Request({"type": "http"}),
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
            return api.preview_custom_skill_version(
                skill.id,
                version.id,
                user,
                session,
                http_request=Request({"type": "http"}),
            )
        return api.restore_custom_skill_version(
            skill.id,
            version.id,
            user,
            session,
            http_request=Request({"type": "http"}),
        )

    if offset < 0:
        with pytest.raises(FileSizeLimitExceeded):
            read()
    else:
        assert read() is not None
    session.rollback()
    assert (
        len(
            api.list_custom_skill_versions(
                skill.id,
                user,
                session,
                http_request=Request({"type": "http"}),
            )
        )
        == 1
    )


def test_current_editor_rejects_expansion_before_inspection(
    session: Session,
    user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from onyx.file_store.models import BundleLimits, FileSizeLimitExceeded
    from onyx.skills import content

    response = api.create_custom_skill(
        upload(bundle("bounded-editor")),
        False,
        user,
        session,
        http_request=Request({"type": "http"}),
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
        api.fetch_custom_skill_for_edit(
            response.id,
            user,
            session,
            http_request=Request({"type": "http"}),
        )


def test_legacy_current_and_preview_keep_stored_allowances(
    session: Session,
    user: User,
) -> None:
    import io
    import zipfile

    from onyx.skills.validation import load_stored_custom_skill_bundle

    response = api.create_custom_skill(
        upload(bundle("legacy-reader")),
        False,
        user,
        session,
        http_request=Request({"type": "http"}),
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
    assert (
        len(
            api.fetch_custom_skill_for_edit(
                skill.id,
                user,
                session,
                http_request=Request({"type": "http"}),
            ).files
        )
        == 501
    )
    assert (
        len(
            api.preview_custom_skill_version(
                skill.id,
                version.id,
                user,
                session,
                http_request=Request({"type": "http"}),
            ).files
        )
        == 501
    )


@pytest.mark.parametrize("wrapped", [False, True])
def test_legacy_large_central_directory_stays_readable(
    session: Session, user: User, wrapped: bool
) -> None:
    import io
    import struct
    import zipfile

    from onyx.db.skill_version import repair_skill_version_metadata
    from onyx.skills.validation import validate_stored_custom_skill
    from onyx.utils.bundle import compute_bundle_metadata

    response = api.create_custom_skill(
        upload(bundle("legacy-directory")),
        False,
        user,
        session,
        http_request=Request({"type": "http"}),
    )
    skill = session.get(Skill, response.id)
    assert skill is not None and skill.current_version is not None
    version = skill.current_version
    with zipfile.ZipFile(io.BytesIO(bundle(skill.name))) as original:
        skill_md = original.read("SKILL.md")
    # Fewer than 100 files, but long extra fields, comments and folders make
    # the central directory larger than 4 MiB.
    prefix = f"{skill.name}/" if wrapped else ""
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(zipfile.ZipInfo(f"{prefix}SKILL.md"), skill_md)
        for index in range(90):
            info = zipfile.ZipInfo(f"{prefix}refs/{index}.md")
            info.extra = struct.pack("<HH", 0xCAFE, 50_000) + bytes(50_000)
            info.comment = b"c" * 1000
            archive.writestr(info, b"x")
        for index in range(10_000):
            archive.writestr(zipfile.ZipInfo(f"{prefix}folders/{index}/"), b"")
    content = output.getvalue()
    directory_size = int.from_bytes(content[-10:-6], "little")
    assert directory_size > 4 * 1024 * 1024
    store = get_default_file_store()
    version.bundle_file_id = save_skill_bundle_bytes(
        content, display_name="legacy.zip", file_store=store
    )
    skill.bundle_file_id = version.bundle_file_id
    skill.is_valid = None
    version.bundle_sha256 = compute_bundle_sha256(content)
    skill.bundle_sha256 = version.bundle_sha256
    version.content_digest = None
    version.unpacked_size_bytes = None
    version.file_count = None
    version.is_valid = None
    session.commit()

    if not wrapped:
        # The editor reads root SKILL.md, so it has never opened wrapped bundles.
        editable = api.fetch_custom_skill_for_edit(
            skill.id, user, session, http_request=Request({"type": "http"})
        )
        assert len(editable.files) == 90
    preview = api.preview_custom_skill_version(
        skill.id, version.id, user, session, http_request=Request({"type": "http"})
    )
    assert [file.path for file in preview.files][:2] == ["refs/0.md", "refs/1.md"]
    assert len(preview.files) == 90
    validation = validate_stored_custom_skill(skill, store)
    assert validation.is_valid is True and validation.normalized_bundle is not None
    if not wrapped:
        assert validation.normalized_bundle == content

    repair_skill_version_metadata(skill, session, store)
    session.commit()
    session.refresh(version)
    metadata = compute_bundle_metadata(content)
    assert version.content_digest == metadata.content_digest
    assert (version.file_count, version.unpacked_size_bytes) == (91, 90 + len(skill_md))


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
        http_request=Request({"type": "http"}),
    )
    other = api.create_custom_skill(
        upload(bundle("other-history")),
        False,
        user,
        session,
        http_request=Request({"type": "http"}),
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
