"""Storage repair behavior at the first immutable-version boundary."""

import io
import zipfile
from typing import Never
from unittest.mock import patch

import pytest
from psycopg2 import OperationalError
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from onyx.db.models import FileContent, FileRecord, Skill, SkillVersion, User
from onyx.db.skill import delete_skill
from onyx.db.skill_version import (
    delete_unreferenced_skill_bundles,
    repair_skill_version_metadata,
    repair_version_metadata,
)
from onyx.file_store import postgres_file_store
from onyx.file_store.file_store import get_default_file_store
from onyx.file_store.models import BundleLimits
from onyx.server.features.skill import api
from onyx.skills.ingest import save_skill_bundle_bytes
from tests.external_dependency_unit.db.test_skill_version_writes import (
    bundle,
    skill_with_versions,
    upload,
    versions,
)
from tests.external_dependency_unit.db.test_skill_version_writes import (
    session as session,
)
from tests.external_dependency_unit.db.test_skill_version_writes import (
    tenant as tenant,
)
from tests.external_dependency_unit.db.test_skill_version_writes import (
    user as user,
)


def test_identical_upload_replaces_missing_large_object(
    session: Session, user: User
) -> None:
    store = postgres_file_store.PostgresBackedFileStore()
    with patch("onyx.file_store.file_store._DEFAULT_FILE_STORE", store):
        content = bundle("missing-large-object")
        created = api.create_custom_skill(upload(content), False, user, session)
        skill = session.get(Skill, created.id)
        assert skill is not None
        old_file_id = skill.bundle_file_id
        assert old_file_id is not None
        oid = session.scalar(
            select(FileContent.lobj_oid).where(FileContent.file_id == old_file_id)
        )
        assert oid is not None
        session.execute(text("SELECT lo_unlink(:oid)"), {"oid": oid})
        session.commit()
        with pytest.raises(FileNotFoundError):
            store.read_file(old_file_id, db_session=session)
        assert session.scalar(select(1)) == 1
        api.replace_current_user_skill_bundle(skill.id, upload(content), user, session)
        session.refresh(skill)
        assert skill.bundle_file_id != old_file_id
        assert skill.bundle_file_id is not None
        with store.read_file(skill.bundle_file_id) as source:
            assert source.read() == content
        store.delete_file(old_file_id)
        assert session.get(FileRecord, old_file_id) is None
        store.delete_file(skill.bundle_file_id)


@pytest.mark.parametrize("operation", ["read", "delete"])
def test_existing_large_object_errors_propagate(
    session: Session, operation: str
) -> None:
    store = postgres_file_store.PostgresBackedFileStore()
    file_id = save_skill_bundle_bytes(b"content", display_name="test", file_store=store)
    error = OperationalError("storage unavailable")

    def fail(*_args: object, **_kwargs: object) -> Never:
        raise error

    with patch.object(postgres_file_store, f"_{operation}_large_object", fail):
        with pytest.raises(OperationalError) as caught:
            if operation == "read":
                store.read_file(file_id, db_session=session)
            else:
                store.delete_file(file_id, db_session=session)
        assert caught.value is error
    assert session.scalar(select(1)) == 1
    assert session.get(FileRecord, file_id) is not None
    with store.read_file(file_id) as source:
        assert source.read() == b"content"
    store.delete_file(file_id)


def test_delete_cleans_versions_only_after_commit(session: Session, user: User) -> None:
    created = api.create_custom_skill(
        upload(bundle("delete-history")), False, user, session
    )
    api.replace_current_user_skill_bundle(
        created.id, upload(bundle("delete-history", "Second")), user, session
    )
    skill = session.get(Skill, created.id)
    assert skill is not None
    files = set(session.scalars(select(FileRecord.file_id)))
    assert len(files) == 2
    delete_unreferenced_skill_bundles(list(files), session)
    assert set(session.scalars(select(FileRecord.file_id))) == files
    pending = delete_skill(skill, session)
    assert set(pending) == files
    session.rollback()
    delete_unreferenced_skill_bundles(pending, session)
    assert set(session.scalars(select(FileRecord.file_id))) == files
    api.delete_current_user_skill(created.id, user, session)
    assert list(session.scalars(select(FileRecord.file_id))) == []


_LEGACY_SKILL_MD = b"---\nname: legacy\ndescription: Legacy bundle\n---\n"


@pytest.mark.parametrize("failure", ["stored", "file", "total", "exact"])
def test_metadata_byte_limits(session: Session, user: User, failure: str) -> None:
    created = api.create_custom_skill(
        upload(bundle("bounded-history")), False, user, session
    )
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("SKILL.md", _LEGACY_SKILL_MD)
        archive.writestr("a.txt", b"a" * 1024)
        archive.writestr("b.txt", b"b" * 1024)
    content = output.getvalue()
    total = 2048 + len(_LEGACY_SKILL_MD)
    limits = BundleLimits(
        max_stored_bytes=len(content) - (failure == "stored"),
        max_file_bytes=1024 - (failure == "file"),
        max_total_bytes=total - (failure == "total"),
    )
    store = get_default_file_store()
    version = SkillVersion(
        skill_id=created.id,
        version_number=2,
        bundle_file_id=save_skill_bundle_bytes(
            content, display_name="legacy.zip", file_store=store
        ),
    )
    session.add(version)
    session.commit()
    assert repair_version_metadata(version, store, limits=limits) == (
        failure == "exact"
    )
    assert (version.unpacked_size_bytes is not None) == (failure == "exact")
    assert (version.frontmatter is not None) == (failure == "exact")
    # Limit overflows stay retryable, so a raised limit repairs the version.
    assert version.metadata_unrepairable is False
    raised = BundleLimits(
        max_stored_bytes=len(content), max_file_bytes=1024, max_total_bytes=total
    )
    assert repair_version_metadata(version, store, limits=raised)
    assert version.unpacked_size_bytes == total
    assert version.file_count == 3
    assert version.name == "legacy"
    assert version.skill_md == _LEGACY_SKILL_MD.decode()


def test_metadata_preserves_legacy_file_count(session: Session, user: User) -> None:
    created = api.create_custom_skill(
        upload(bundle("legacy-file-count")), False, user, session
    )
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("SKILL.md", _LEGACY_SKILL_MD)
        for index in range(500):
            archive.writestr(f"wrapped/{index}.txt", b"x")
    content = output.getvalue()
    store = get_default_file_store()
    version = SkillVersion(
        skill_id=created.id,
        version_number=2,
        bundle_file_id=save_skill_bundle_bytes(
            content, display_name="legacy.zip", file_store=store
        ),
    )
    session.add(version)
    session.commit()
    total = 500 + len(_LEGACY_SKILL_MD)
    limits = BundleLimits(
        max_stored_bytes=len(content),
        max_file_bytes=len(_LEGACY_SKILL_MD),
        max_total_bytes=total,
    )
    assert repair_version_metadata(version, store, limits=limits)
    assert version.file_count == 501
    assert version.unpacked_size_bytes == total
    assert version.bundle_file_id is not None
    with store.read_file(version.bundle_file_id) as source:
        assert source.read() == content


def test_physical_history_absence_clears_link_without_payload_reads(
    session: Session, user: User
) -> None:
    store = postgres_file_store.PostgresBackedFileStore()
    with patch("onyx.file_store.file_store._DEFAULT_FILE_STORE", store):
        skill = skill_with_versions(session, user, 2)
        current, old = versions(skill, session)
        current_file = current.bundle_file_id
        old_file = old.bundle_file_id
        assert current_file is not None and old_file is not None
        for file_id in (current_file, old_file):
            oid = session.scalar(
                select(FileContent.lobj_oid).where(FileContent.file_id == file_id)
            )
            assert oid is not None
            session.execute(text("SELECT lo_unlink(:oid)"), {"oid": oid})
        session.commit()
        with patch.object(store, "read_file", wraps=store.read_file) as read:
            assert repair_skill_version_metadata(skill, session, store) == []
        read.assert_not_called()
        session.commit()
        assert old.bundle_file_id is None
        assert current.bundle_file_id == current_file
        assert skill.bundle_file_id == current_file
        assert session.get(FileRecord, old_file) is not None
        assert session.get(FileRecord, current_file) is not None
        api.replace_current_user_skill_bundle(
            skill.id, upload(bundle(skill.name, "Version 2")), user, session
        )
        session.refresh(skill)
        assert skill.bundle_file_id != current_file
        assert skill.bundle_file_id is not None
        with store.read_file(skill.bundle_file_id) as source:
            assert source.read() == bundle(skill.name, "Version 2")
        for file_id in (old_file, current_file, skill.bundle_file_id):
            store.delete_file(file_id)
