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
