"""Plugin ZIP guidance through the upload API with real PostgreSQL and FileStore."""

import io
import zipfile

import pytest
from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.models import FileRecord, Skill, SkillVersion, User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.file_store import get_default_file_store
from onyx.server.features.skill import api
from onyx.skills.bundle import build_skill_md
from onyx.skills.ingest import save_skill_bundle_bytes
from onyx.skills.metadata import parse_skill_document
from onyx.skills.validation import load_stored_custom_skill_bundle
from tests.external_dependency_unit.db.test_skill_version_writes import (
    session as session,
)
from tests.external_dependency_unit.db.test_skill_version_writes import tenant as tenant
from tests.external_dependency_unit.db.test_skill_version_writes import upload
from tests.external_dependency_unit.db.test_skill_version_writes import user as user

MANIFESTS = (".claude-plugin/plugin.json", ".codex-plugin/plugin.json", "plugin.json")
GUIDANCE = "This is a plugin. Plugin upload is not supported yet."
SKILL_MD = build_skill_md(
    name="upload-guidance",
    description="Upload guidance test",
    instructions_markdown="Follow these instructions.",
).encode()


def archive(files: dict[str, bytes], wrapper: str = "") -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as bundle:
        for path, data in files.items():
            bundle.writestr(wrapper + path, data)
        bundle.writestr("__MACOSX/._upload-guidance", b"metadata")
    return output.getvalue()


@pytest.mark.parametrize("manifest", MANIFESTS)
@pytest.mark.parametrize("wrapper", ["", "upload-guidance/"])
@pytest.mark.parametrize("with_skill", [False, True])
@pytest.mark.parametrize("content", [b'{"name":"example"}', b"invalid JSON"])
@pytest.mark.parametrize("operation", ["preview", "upload"])
def test_plugin_preview_and_upload_refused(
    session: Session,
    user: User,
    manifest: str,
    wrapper: str,
    with_skill: bool,
    content: bytes,
    operation: str,
) -> None:
    files = {manifest: content}
    if with_skill:
        files["SKILL.md"] = SKILL_MD
    data = archive(files, wrapper)
    before_files = set(session.scalars(select(FileRecord.file_id)))
    with pytest.raises(OnyxError) as error:
        if operation == "preview":
            api.inspect_custom_skill_bundle_upload(upload(data), user)
        else:
            api.create_custom_skill(
                upload(data),
                False,
                user,
                session,
                http_request=Request({"type": "http"}),
            )
    assert error.value.error_code == OnyxErrorCode.INVALID_INPUT
    assert error.value.detail == GUIDANCE
    assert list(session.scalars(select(Skill))) == []
    assert list(session.scalars(select(SkillVersion))) == []
    assert set(session.scalars(select(FileRecord.file_id))) == before_files


@pytest.mark.parametrize("wrapper", ["", "upload-guidance/"])
@pytest.mark.parametrize(
    "extra",
    [
        {},
        {f"references/{path}": b"{}" for path in MANIFESTS},
        {f"examples/{path}": b"invalid JSON" for path in MANIFESTS},
        {"__MACOSX/.claude-plugin/plugin.json": b"{}", "._plugin.json": b"{}"},
    ],
)
def test_skill_preview_and_upload_accept_support_files(
    session: Session, user: User, wrapper: str, extra: dict[str, bytes]
) -> None:
    data = archive({"SKILL.md": SKILL_MD, **extra}, wrapper)
    preview = api.inspect_custom_skill_bundle_upload(upload(data), user)
    assert preview.name == "upload-guidance"
    skill = api.create_custom_skill(
        upload(data), False, user, session, http_request=Request({"type": "http"})
    )
    assert skill.name == preview.name
    saved = api.fetch_custom_skill_for_edit(
        skill.id, user, session, http_request=Request({"type": "http"})
    )
    assert saved.instructions_markdown == preview.instructions_markdown
    assert saved.files == preview.files


def test_batch_upload_rejects_plugin_without_partial_skill_import(
    session: Session, user: User
) -> None:
    result = api.create_custom_skills_batch(
        [
            upload(archive({"SKILL.md": SKILL_MD}), "skill.zip"),
            upload(
                archive({"SKILL.md": SKILL_MD, ".claude-plugin/plugin.json": b"{}"}),
                "plugin.zip",
            ),
        ],
        False,
        None,
        user,
        session,
        http_request=Request({"type": "http"}),
    )
    assert len(result.imported) == 1
    assert len(result.not_imported) == 1
    assert result.not_imported[0].reason == GUIDANCE
    assert len(list(session.scalars(select(Skill)))) == 1
    assert len(list(session.scalars(select(SkillVersion)))) == 1
    assert len(list(session.scalars(select(FileRecord)))) == 1


@pytest.mark.parametrize(
    "files",
    [
        {"outer/inner/.claude-plugin/plugin.json": b"{}"},
        {"package/.codex-plugin/plugin.json": b"{}", "README.md": b"outside"},
        {"__MACOSX/.claude-plugin/plugin.json": b"{}"},
        {".claude-plugin/plugin.json/": b""},
    ],
)
def test_preview_does_not_infer_plugin_from_non_package_markers(
    user: User, files: dict[str, bytes]
) -> None:
    with pytest.raises(OnyxError) as error:
        api.inspect_custom_skill_bundle_upload(upload(archive(files)), user)
    assert error.value.error_code == OnyxErrorCode.INVALID_INPUT
    assert error.value.detail == (
        "SKILL.md missing at bundle root or directly inside one top-level directory"
    )


@pytest.mark.parametrize("manifest", MANIFESTS)
def test_legacy_stored_plugin_marker_remains_readable(
    session: Session, user: User, manifest: str
) -> None:
    skill = api.create_custom_skill(
        upload(archive({"SKILL.md": SKILL_MD})),
        False,
        user,
        session,
        http_request=Request({"type": "http"}),
    )
    row = session.get(Skill, skill.id)
    assert row is not None and row.current_version_id is not None
    version = session.get(SkillVersion, row.current_version_id)
    assert version is not None and version.bundle_file_id is not None
    # Model a bundle stored before plugin upload detection existed.
    store = get_default_file_store()
    save_skill_bundle_bytes(
        archive({"SKILL.md": SKILL_MD, manifest: b"invalid JSON"}),
        display_name="legacy.zip",
        file_store=store,
        file_id=version.bundle_file_id,
    )
    loaded = load_stored_custom_skill_bundle(version.bundle_file_id, store)
    with zipfile.ZipFile(io.BytesIO(loaded.content)) as stored:
        assert parse_skill_document(stored.read("SKILL.md")).metadata.name == skill.name
    preview = api.preview_custom_skill_version(
        skill.id,
        version.id,
        user,
        session,
        http_request=Request({"type": "http"}),
    )
    assert preview.name == "upload-guidance"
    assert [file.path for file in preview.files] == [manifest]

    edited = api.patch_current_user_skill(
        skill.id,
        api.SkillPatchRequest(description="Edited saved Skill"),
        user,
        session,
        http_request=Request({"type": "http"}),
    )
    assert edited.description == "Edited saved Skill"
