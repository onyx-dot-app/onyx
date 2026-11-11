"""Storage repair behavior at the first immutable-version boundary."""

from typing import Never
from unittest.mock import patch

import pytest
from psycopg2 import OperationalError
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from onyx.db.models import FileContent, FileRecord, Skill, User
from onyx.db.skill import delete_skill
from onyx.db.skill_version import delete_unreferenced_skill_bundles
from onyx.file_store import postgres_file_store
from onyx.server.features.skill import api
from onyx.skills.ingest import save_skill_bundle_bytes
from tests.external_dependency_unit.db.test_skill_version_writes import (
    bundle,
    upload,
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
