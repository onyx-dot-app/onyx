"""Failed background reads remain retryable without starving later skills."""

from typing import IO
from unittest.mock import patch

import pytest
from botocore.exceptions import ClientError
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.background.celery.tasks.skill_versions import tasks as repair_tasks
from onyx.background.celery.tasks.skill_versions.tasks import (
    PROGRESS_KEY,
    repair_skill_versions,
)
from onyx.db.models import SkillVersion, User
from onyx.db.skill_version import (
    repair_skill_version_metadata,
    skill_version_repair_batch,
)
from onyx.file_store.file_store import get_default_file_store
from onyx.key_value_store.factory import get_kv_store
from onyx.skills.ingest import ingested_skill_bundle
from tests.external_dependency_unit.db.test_skill_version_writes import (
    bundle,
    legacy_skill,
    skill_with_versions,
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


@pytest.mark.parametrize("completed", [False, True])
@pytest.mark.parametrize("blocked_count", [1, 50])
def test_access_denied_does_not_starve_later_skills(
    tenant: str, session: Session, user: User, completed: bool, blocked_count: int
) -> None:
    blocked = [
        legacy_skill(session, user, number) for number in range(1, blocked_count + 1)
    ]
    healthy = legacy_skill(session, user, blocked_count + 1)
    failed_files = {skill.bundle_file_id for skill in blocked}
    if completed:
        get_kv_store().store(PROGRESS_KEY, "completed")
    store = get_default_file_store()
    original_read = store.read_file

    def read(
        file_id: str,
        mode: str | None = None,
        use_tempfile: bool = False,
        *,
        max_bytes: int | None = None,
    ) -> IO[bytes]:
        if file_id in failed_files:
            raise ClientError({"Error": {"Code": "AccessDenied"}}, "GetObject")
        return original_read(file_id, mode, use_tempfile, max_bytes=max_bytes)

    with patch.object(store, "read_file", read):
        for _ in range(3):
            repair_skill_versions.run(tenant_id=tenant)
        session.expire_all()
        assert versions(healthy, session)[0].content_digest is not None
        assert all(skill.current_version_id is None for skill in blocked)
        pending = skill_version_repair_batch(session, None, drift_only=True)
        assert {skill.id for skill in pending} == {skill.id for skill in blocked}
        session.commit()
    for _ in range(3):
        repair_skill_versions.run(tenant_id=tenant)
    session.expire_all()
    for skill in blocked:
        assert versions(skill, session)[0].content_digest is not None
    assert skill_version_repair_batch(session, None, drift_only=True) == []


def test_missing_metadata_keeps_its_bundle_link_for_retry(
    session: Session, user: User
) -> None:
    skill = skill_with_versions(session, user, 10)
    oldest = versions(skill, session)[-1]
    old_file_id = oldest.bundle_file_id
    assert old_file_id is not None
    oldest.content_digest = oldest.unpacked_size_bytes = oldest.file_count = None
    session.commit()
    store = get_default_file_store()
    original_read = store.read_file

    def read(
        file_id: str,
        mode: str | None = None,
        use_tempfile: bool = False,
        *,
        max_bytes: int | None = None,
    ) -> IO[bytes]:
        if file_id == old_file_id:
            raise ClientError({"Error": {"Code": "AccessDenied"}}, "GetObject")
        return original_read(file_id, mode, use_tempfile, max_bytes=max_bytes)

    # Simulate an old writer's backlog without pruning on the new-version path.
    newest = versions(skill, session)[0]
    session.add(
        SkillVersion(
            skill_id=skill.id,
            version_number=11,
            bundle_file_id=newest.bundle_file_id,
            content_digest=newest.content_digest,
            unpacked_size_bytes=newest.unpacked_size_bytes,
            file_count=newest.file_count,
        )
    )
    session.commit()
    with patch.object(store, "read_file", read):
        assert repair_skill_version_metadata(skill, session, store) == []
        session.commit()
    session.refresh(oldest)
    assert oldest.bundle_file_id == old_file_id
    assert oldest.content_digest is None
    assert skill_version_repair_batch(session, None, drift_only=True) == [skill]
    assert repair_skill_version_metadata(skill, session, store) == [old_file_id]
    session.commit()
    session.refresh(oldest)
    assert oldest.bundle_file_id is None
    assert oldest.content_digest is not None
    assert skill_version_repair_batch(session, None, drift_only=True) == []
    assert len(list(session.scalars(select(SkillVersion)))) == 11


@pytest.mark.parametrize("metadata_complete", [False, True])
def test_definitively_missing_history_clears_only_historical_link(
    session: Session, user: User, metadata_complete: bool
) -> None:
    skill = skill_with_versions(session, user, 2)
    current, old = versions(skill, session)
    store = get_default_file_store()
    for version in (current, old):
        assert version.bundle_file_id is not None
        store.delete_file(version.bundle_file_id)
        if not metadata_complete:
            version.content_digest = version.unpacked_size_bytes = (
                version.file_count
            ) = None
    current_file_id = current.bundle_file_id
    session.commit()
    assert repair_skill_version_metadata(skill, session, store) == []
    session.commit()
    session.refresh(old)
    session.refresh(current)
    assert old.bundle_file_id is None
    assert current.bundle_file_id == current_file_id
    assert skill.bundle_file_id == current_file_id
    assert skill_version_repair_batch(session, None, drift_only=True) == (
        [] if metadata_complete else [skill]
    )


@pytest.mark.parametrize("completed", [False, True])
def test_cleanup_failure_does_not_freeze_repair_progress(
    tenant: str, session: Session, user: User, completed: bool
) -> None:
    first = legacy_skill(session, user, 1)
    second = legacy_skill(session, user, 2)
    if completed:
        get_kv_store().store(PROGRESS_KEY, "completed")
    calls = 0

    def failed_cleanup(_files: list[str], _session: Session) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ConnectionError("cleanup unavailable after commit")

    with patch.object(
        repair_tasks, "delete_unreferenced_skill_bundles", failed_cleanup
    ):
        repair_skill_versions.run(tenant_id=tenant)
    assert calls == 2
    session.expire_all()
    assert versions(first, session)[0].content_digest is not None
    assert versions(second, session)[0].content_digest is not None
    if not completed:
        assert get_kv_store().load(PROGRESS_KEY, refresh_cache=True) == str(second.id)
    assert skill_version_repair_batch(session, None, drift_only=True) == []


@pytest.mark.parametrize("metadata_complete", [False, True])
def test_denied_history_does_not_roll_back_legacy_current_repair(
    tenant: str, session: Session, user: User, metadata_complete: bool
) -> None:
    skill = skill_with_versions(session, user, 3)
    oldest = versions(skill, session)[-1]
    old_file_id = oldest.bundle_file_id
    assert old_file_id is not None
    if not metadata_complete:
        oldest.content_digest = oldest.unpacked_size_bytes = oldest.file_count = None
    store = get_default_file_store()
    with ingested_skill_bundle(
        bundle(skill.name, "Legacy writer"), "skill.zip", store
    ) as ingested:
        skill.bundle_file_id = ingested.bundle_file_id
        skill.bundle_sha256 = ingested.bundle_sha256
        session.commit()
    legacy_file = skill.bundle_file_id
    get_kv_store().store(PROGRESS_KEY, "completed")
    original_read = store.read_file
    original_size = store.get_file_size

    def read(
        file_id: str,
        mode: str | None = None,
        use_tempfile: bool = False,
        *,
        max_bytes: int | None = None,
    ) -> IO[bytes]:
        if file_id == old_file_id:
            raise ClientError({"Error": {"Code": "AccessDenied"}}, "GetObject")
        return original_read(file_id, mode, use_tempfile, max_bytes=max_bytes)

    def size(file_id: str, db_session: Session | None = None) -> int | None:
        if file_id == old_file_id:
            raise ClientError({"Error": {"Code": "AccessDenied"}}, "HeadObject")
        return original_size(file_id, db_session)

    with (
        patch.object(store, "read_file", read),
        patch.object(store, "get_file_size", size),
    ):
        for _ in range(3):
            repair_skill_versions.run(tenant_id=tenant)
    session.expire_all()
    assert versions(skill, session)[0].bundle_file_id == legacy_file
    assert oldest.bundle_file_id == old_file_id
    if not metadata_complete:
        assert oldest.content_digest is None
        for _ in range(3):
            repair_skill_versions.run(tenant_id=tenant)
        session.expire_all()
        assert oldest.content_digest is not None


def test_complete_history_uses_no_payload_reads_during_retries(
    tenant: str, session: Session, user: User
) -> None:
    skill = skill_with_versions(session, user, 10)
    oldest = versions(skill, session)[-1]
    old_file_id = oldest.bundle_file_id
    assert old_file_id is not None
    oldest.content_digest = oldest.unpacked_size_bytes = oldest.file_count = None
    session.commit()
    get_kv_store().store(PROGRESS_KEY, "completed")
    store = get_default_file_store()
    original_read = store.read_file
    reads: list[str] = []

    def read(
        file_id: str,
        mode: str | None = None,
        use_tempfile: bool = False,
        *,
        max_bytes: int | None = None,
    ) -> IO[bytes]:
        reads.append(file_id)
        if file_id == old_file_id:
            raise ClientError({"Error": {"Code": "AccessDenied"}}, "GetObject")
        return original_read(file_id, mode, use_tempfile, max_bytes=max_bytes)

    with patch.object(store, "read_file", read):
        for _ in range(3):
            repair_skill_versions.run(tenant_id=tenant)
    assert reads == [old_file_id] * 3
    session.expire_all()
    assert oldest.bundle_file_id == old_file_id
    assert oldest.content_digest is None
    with patch.object(store, "read_file", wraps=original_read) as recovered:
        repair_skill_versions.run(tenant_id=tenant)
    assert recovered.call_count == 1
    session.expire_all()
    assert oldest.content_digest is not None
    assert skill_version_repair_batch(session, None, drift_only=True) == []
