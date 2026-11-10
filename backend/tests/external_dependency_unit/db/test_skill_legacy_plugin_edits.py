"""Saved plugin markers survive edits; new uploads cannot introduce them."""

import io
import zipfile

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.models import FileRecord, Skill, SkillVersion, User
from onyx.db.skill import create_skill_from_ingested_bundle
from onyx.file_store.file_store import get_default_file_store
from onyx.skills.bundle import compute_bundle_sha256
from onyx.skills.content import read_custom_skill_bundle_bytes
from onyx.skills.ingest import (
    IngestedBundle,
    prepare_skill_bundle,
    save_skill_bundle_bytes,
)
from onyx.utils.bundle import compute_bundle_metadata
from tests.external_dependency_unit.db.skill_api_client import client_for
from tests.external_dependency_unit.db.test_skill_plugin_upload import (
    GUIDANCE,
    MANIFESTS,
    SKILL_MD,
    archive,
)
from tests.external_dependency_unit.db.test_skill_version_writes import (
    session as session,
)
from tests.external_dependency_unit.db.test_skill_version_writes import tenant as tenant
from tests.external_dependency_unit.db.test_skill_version_writes import user as user


def legacy_skill(session: Session, user: User, manifest: str) -> Skill:
    # Store the exact normalized bytes and metadata accepted before upload retirement.
    prepared = prepare_skill_bundle(
        archive({"SKILL.md": SKILL_MD, manifest: b"legacy manifest"}), "legacy.zip"
    )
    file_id = save_skill_bundle_bytes(
        prepared.content, display_name="legacy.zip", file_store=get_default_file_store()
    )
    skill = create_skill_from_ingested_bundle(
        IngestedBundle(
            prepared.canonical_name,
            file_id,
            prepared.bundle_sha256,
            prepared.description,
            prepared.metadata,
        ),
        user.id,
        session,
    )
    session.commit()
    return skill


@pytest.mark.parametrize("manifest", MANIFESTS)
@pytest.mark.parametrize(
    "operation",
    ["description", "instructions_markdown", "restore", "files", "reference"],
)
def test_saved_plugin_bundle_can_be_edited_and_restored(
    session: Session, user: User, manifest: str, operation: str
) -> None:
    skill = legacy_skill(session, user, manifest)
    original_id = skill.current_version_id
    base = f"/skills/custom/{skill.id}"
    with client_for(user, session) as client:
        if operation == "restore":
            replaced = client.put(
                base + "/bundle",
                files={"bundle": ("clean.zip", archive({"SKILL.md": SKILL_MD}))},
            )
            assert replaced.status_code == 200, replaced.text
            result = client.post(base + f"/versions/{original_id}/restore")
        elif operation in ("files", "reference"):
            path = "notes.txt" if operation == "files" else f"references/{manifest}"
            result = client.post(
                base + "/files", files={"upload": (path, b"support file")}
            )
            assert result.status_code == 200, result.text
            result = client.delete(base + "/files", params={"path": path})
        else:
            result = client.patch(base, json={operation: "Edited legacy content"})
        assert result.status_code == 200, result.text
        if operation in ("description", "instructions_markdown"):
            detail = client.get(base + "/edit")
            assert detail.status_code == 200, detail.text
            assert detail.json()[operation] == "Edited legacy content"
    session.refresh(skill)
    assert skill.current_version_id != original_id
    saved = read_custom_skill_bundle_bytes(skill)
    with zipfile.ZipFile(io.BytesIO(saved)) as bundle:
        assert bundle.read(manifest) == b"legacy manifest"
        assert set(bundle.namelist()) == {"SKILL.md", manifest}
    version = session.get(SkillVersion, skill.current_version_id)
    assert version is not None
    assert version.bundle_sha256 == compute_bundle_sha256(saved)
    metadata = compute_bundle_metadata(saved)
    assert version.content_digest == metadata.content_digest
    assert version.file_count == metadata.file_count
    assert version.unpacked_size_bytes == metadata.unpacked_size_bytes


@pytest.mark.parametrize("manifest", MANIFESTS)
@pytest.mark.parametrize(
    "operation",
    ["upload", "replace", "file", "files_zip", "bundle_files", "wrapped_bundle"],
)
def test_new_plugin_content_is_refused_even_on_legacy_skill(
    session: Session, user: User, manifest: str, operation: str
) -> None:
    skill = legacy_skill(session, user, manifest)
    original_id = skill.current_version_id
    before_files = set(session.scalars(select(FileRecord.file_id)))
    base = f"/skills/custom/{skill.id}"
    data = archive({"SKILL.md": SKILL_MD, manifest: b"new manifest"})
    with client_for(user, session) as client:
        if operation == "upload":
            result = client.post(
                "/skills/custom", files={"bundle": ("plugin.zip", data)}
            )
        elif operation == "replace":
            result = client.put(
                base + "/bundle", files={"bundle": ("plugin.zip", data)}
            )
        else:
            filename, content = {
                "file": (manifest, b"new manifest"),
                "files_zip": ("plugin.zip", archive({manifest: b"new manifest"})),
                "bundle_files": ("plugin.zip", data),
                "wrapped_bundle": (
                    "plugin.zip",
                    archive(
                        {"SKILL.md": SKILL_MD, manifest: b"new manifest"},
                        "upload-guidance/",
                    ),
                ),
            }[operation]
            result = client.post(base + "/files", files={"upload": (filename, content)})
        assert result.status_code == 400, result.text
        assert result.json()["detail"] == GUIDANCE
    session.refresh(skill)
    assert skill.current_version_id == original_id
    assert len(list(session.scalars(select(SkillVersion)))) == 1
    assert set(session.scalars(select(FileRecord.file_id))) == before_files
