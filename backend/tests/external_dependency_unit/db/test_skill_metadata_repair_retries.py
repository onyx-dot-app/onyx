"""Failed background reads remain retryable without starving later skills."""

import io
import zipfile
from time import monotonic
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
from onyx.db import skill_version as skill_version_module
from onyx.db.models import SkillVersion, User
from onyx.db.skill_version import (
    repair_skill_version_metadata,
    skill_version_repair_batch,
)
from onyx.file_store.file_store import get_default_file_store
from onyx.key_value_store.factory import get_kv_store
from onyx.skills.bundle import STORED_BUNDLE_LIMITS
from onyx.skills.ingest import ingested_skill_bundle, save_skill_bundle_bytes
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
        assert versions(healthy, session)[0].unpacked_size_bytes is not None
        assert all(skill.current_version_id is None for skill in blocked)
        pending = skill_version_repair_batch(session, None, drift_only=True)
        assert {skill.id for skill in pending} == {skill.id for skill in blocked}
        session.commit()
    for _ in range(3):
        repair_skill_versions.run(tenant_id=tenant)
    session.expire_all()
    for skill in blocked:
        assert versions(skill, session)[0].unpacked_size_bytes is not None
    assert skill_version_repair_batch(session, None, drift_only=True) == []


def test_missing_metadata_keeps_its_bundle_link_for_retry(
    session: Session, user: User
) -> None:
    skill = skill_with_versions(session, user, 10)
    oldest = versions(skill, session)[-1]
    old_file_id = oldest.bundle_file_id
    assert old_file_id is not None
    oldest.unpacked_size_bytes = oldest.file_count = None
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
    assert oldest.unpacked_size_bytes is None
    assert skill_version_repair_batch(session, None, drift_only=True) == [skill]
    assert repair_skill_version_metadata(skill, session, store) == [old_file_id]
    session.commit()
    session.refresh(oldest)
    assert oldest.bundle_file_id is None
    assert oldest.unpacked_size_bytes is not None
    assert skill_version_repair_batch(session, None, drift_only=True) == []
    assert len(list(session.scalars(select(SkillVersion)))) == 11


def test_deadline_resumes_with_older_versions(session: Session, user: User) -> None:
    skill = skill_with_versions(session, user, 4)
    history = versions(skill, session)
    for version in history:
        version.unpacked_size_bytes = version.file_count = None
    session.commit()
    store = get_default_file_store()
    original_read = store.read_file
    # The newest historical version always fails, as an over-limit bundle does.
    blocked_file_id = history[1].bundle_file_id

    def read(
        file_id: str,
        mode: str | None = None,
        use_tempfile: bool = False,
        *,
        max_bytes: int | None = None,
    ) -> IO[bytes]:
        if file_id == blocked_file_id:
            raise ClientError({"Error": {"Code": "SlowDown"}}, "GetObject")
        return original_read(file_id, mode, use_tempfile, max_bytes=max_bytes)

    def repaired() -> list[bool]:
        for version in history:
            session.refresh(version)
        return [version.unpacked_size_bytes is not None for version in history]

    with patch.object(store, "read_file", read):
        # Each pass passes the deadline after one historical version.
        for _ in range(2):
            repair_skill_version_metadata(skill, session, store, deadline=monotonic())
            session.commit()
        assert repaired() == [True, False, True, False]
        assert skill_version_repair_batch(session, None, drift_only=True) == [skill]

        repair_skill_version_metadata(skill, session, store, deadline=monotonic())
        session.commit()
        assert repaired() == [True, False, True, True]

    repair_skill_version_metadata(skill, session, store)
    session.commit()
    assert all(repaired())
    assert skill_version_repair_batch(session, None, drift_only=True) == []


def test_corrupt_history_is_unrepairable_and_prunable(
    session: Session, user: User
) -> None:
    skill = skill_with_versions(session, user, 10)
    oldest = versions(skill, session)[-1]
    store = get_default_file_store()
    corrupt_file_id = save_skill_bundle_bytes(
        b"not a zip", display_name="corrupt.zip", file_store=store
    )
    assert oldest.bundle_file_id is not None
    store.delete_file(oldest.bundle_file_id)
    oldest.bundle_file_id = corrupt_file_id
    oldest.unpacked_size_bytes = oldest.file_count = None
    session.commit()
    assert skill_version_repair_batch(session, None, drift_only=True) == [skill]

    assert repair_skill_version_metadata(skill, session, store) == []
    session.commit()
    session.refresh(oldest)
    assert oldest.metadata_unrepairable
    assert oldest.bundle_file_id == corrupt_file_id
    assert skill_version_repair_batch(session, None, drift_only=True) == []

    newest = versions(skill, session)[0]
    session.add(
        SkillVersion(
            skill_id=skill.id,
            version_number=11,
            bundle_file_id=newest.bundle_file_id,
            unpacked_size_bytes=newest.unpacked_size_bytes,
            file_count=newest.file_count,
        )
    )
    session.commit()
    assert repair_skill_version_metadata(skill, session, store) == [corrupt_file_id]
    session.commit()
    session.refresh(oldest)
    assert oldest.bundle_file_id is None


def test_repair_backfills_skill_md_columns(session: Session, user: User) -> None:
    skill = skill_with_versions(session, user, 3)
    history = versions(skill, session)
    expected = [(v.name, v.frontmatter, v.skill_md) for v in history]
    assert all(skill_md is not None for _, _, skill_md in expected)
    for version in history:
        version.name = version.frontmatter = version.skill_md = None
    session.commit()
    assert skill_version_repair_batch(session, None, drift_only=True) == [skill]

    repair_skill_version_metadata(skill, session, get_default_file_store())
    session.commit()
    for version in history:
        session.refresh(version)
    assert [(v.name, v.frontmatter, v.skill_md) for v in history] == expected
    assert skill_version_repair_batch(session, None, drift_only=True) == []


_NAN_SKILL_MD = "---\nname: odd\ndescription: d\nscore: .nan\n---\nBody"
_DATED_SKILL_MD = "---\nname: dated\ndescription: d\ncreated: 2025-01-01\n---\n"


@pytest.mark.parametrize(
    "files,skill_md,frontmatter,unrepairable",
    [
        ({"README.md": b"No root SKILL.md"}, None, None, True),
        ({"SKILL.md": b"No frontmatter"}, "No frontmatter", None, True),
        ({"SKILL.md": _NAN_SKILL_MD.encode()}, _NAN_SKILL_MD, None, True),
        (
            {"SKILL.md": b"---\nname: nul\ndescription: d\n---\nBody\x00"},
            None,
            {"name": "nul", "description": "d"},
            True,
        ),
        (
            {"SKILL.md": _DATED_SKILL_MD.encode()},
            _DATED_SKILL_MD,
            {"name": "dated", "description": "d", "created": "2025-01-01"},
            False,
        ),
    ],
)
def test_repair_stores_what_postgres_accepts_of_skill_md(
    session: Session,
    user: User,
    files: dict[str, bytes],
    skill_md: str | None,
    frontmatter: dict[str, str] | None,
    unrepairable: bool,
) -> None:
    skill = skill_with_versions(session, user, 2)
    oldest = versions(skill, session)[-1]
    store = get_default_file_store()
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for path, content in files.items():
            archive.writestr(path, content)
    oldest.bundle_file_id = save_skill_bundle_bytes(
        output.getvalue(), display_name="odd-skill-md.zip", file_store=store
    )
    oldest.unpacked_size_bytes = oldest.file_count = None
    oldest.name = oldest.frontmatter = oldest.skill_md = None
    session.commit()
    assert skill_version_repair_batch(session, None, drift_only=True) == [skill]

    repair_skill_version_metadata(skill, session, store)
    session.commit()
    session.refresh(oldest)
    assert oldest.metadata_unrepairable is unrepairable
    assert oldest.file_count == len(files)
    assert oldest.skill_md == skill_md
    assert oldest.frontmatter == frontmatter
    assert skill_version_repair_batch(session, None, drift_only=True) == []


def test_history_over_limits_stays_retryable_until_limits_rise(
    session: Session, user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    skill = skill_with_versions(session, user, 10)
    oldest = versions(skill, session)[-1]
    oldest_file_id = oldest.bundle_file_id
    oldest.unpacked_size_bytes = oldest.file_count = None
    newest = versions(skill, session)[0]
    session.add(
        SkillVersion(
            skill_id=skill.id,
            version_number=11,
            bundle_file_id=newest.bundle_file_id,
            unpacked_size_bytes=newest.unpacked_size_bytes,
            file_count=newest.file_count,
        )
    )
    session.commit()
    store = get_default_file_store()
    monkeypatch.setattr(
        skill_version_module,
        "STORED_BUNDLE_LIMITS",
        STORED_BUNDLE_LIMITS.model_copy(update={"max_total_bytes": 1}),
    )

    assert repair_skill_version_metadata(skill, session, store) == []
    session.commit()
    session.refresh(oldest)
    assert oldest.unpacked_size_bytes is None
    assert not oldest.metadata_unrepairable
    assert oldest.bundle_file_id == oldest_file_id
    assert skill_version_repair_batch(session, None, drift_only=True) == [skill]

    monkeypatch.setattr(
        skill_version_module, "STORED_BUNDLE_LIMITS", STORED_BUNDLE_LIMITS
    )
    assert repair_skill_version_metadata(skill, session, store) == [oldest_file_id]
    session.commit()
    session.refresh(oldest)
    assert oldest.unpacked_size_bytes is not None
    assert skill_version_repair_batch(session, None, drift_only=True) == []


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
            version.unpacked_size_bytes = version.file_count = None
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
    assert versions(first, session)[0].unpacked_size_bytes is not None
    assert versions(second, session)[0].unpacked_size_bytes is not None
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
        oldest.unpacked_size_bytes = oldest.file_count = None
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
        assert oldest.unpacked_size_bytes is None
        for _ in range(3):
            repair_skill_versions.run(tenant_id=tenant)
        session.expire_all()
        assert oldest.unpacked_size_bytes is not None


def test_complete_history_uses_no_payload_reads_during_retries(
    tenant: str, session: Session, user: User
) -> None:
    skill = skill_with_versions(session, user, 10)
    oldest = versions(skill, session)[-1]
    old_file_id = oldest.bundle_file_id
    assert old_file_id is not None
    oldest.unpacked_size_bytes = oldest.file_count = None
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
    assert oldest.unpacked_size_bytes is None
    with patch.object(store, "read_file", wraps=original_read) as recovered:
        repair_skill_versions.run(tenant_id=tenant)
    assert recovered.call_count == 1
    session.expire_all()
    assert oldest.unpacked_size_bytes is not None
    assert skill_version_repair_batch(session, None, drift_only=True) == []


def test_failed_current_read_keeps_history_repair(session: Session, user: User) -> None:
    skill = skill_with_versions(session, user, 3)
    current, _, oldest = versions(skill, session)
    current_file_id = current.bundle_file_id
    assert current_file_id is not None
    for version in (current, oldest):
        version.unpacked_size_bytes = version.file_count = None
    session.commit()
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
        if file_id == current_file_id:
            raise ClientError({"Error": {"Code": "AccessDenied"}}, "GetObject")
        return original_read(file_id, mode, use_tempfile, max_bytes=max_bytes)

    with patch.object(store, "read_file", read):
        repair_skill_version_metadata(skill, session, store)
    session.commit()

    assert reads.count(current_file_id) == 1
    session.expire_all()
    assert current.unpacked_size_bytes is None
    assert oldest.unpacked_size_bytes is not None
