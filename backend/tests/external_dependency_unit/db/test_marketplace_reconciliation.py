"""Reconcile real reader results against PostgreSQL constraints without bundle I/O."""

import io
import sys
import time
import zipfile
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from queue import Queue
from threading import Barrier
from types import FrameType
from uuid import UUID, uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema

from onyx.db.marketplace import reconcile_marketplace__no_commit
from onyx.db.models import Base, Marketplace, Skill
from onyx.db.resource_version import write_resource_version
from onyx.db.skill_version import SkillVersionAdapter
from onyx.skills.bundle import compute_bundle_sha256
from onyx.skills.ingest import IngestedBundle
from onyx.skills.marketplace.models import (
    GitHubMarketplaceConfig,
    MarketplaceProvider,
    ReconciliationResult,
)
from onyx.skills.marketplace.read_models import (
    CompleteMarketplace,
    FailedMarketplace,
    ReadySkill,
)
from onyx.skills.marketplace.reader import read_marketplace_archive
from onyx.skills.metadata import parse_skill_document
from onyx.utils.bundle import compute_bundle_metadata
from tests.external_dependency_unit.craft.db_helpers import make_skill, make_user
from tests.unit.onyx.skills.marketplace_fixtures import CLAUDE, _archive, _catalog, _md


@pytest.fixture
def session(isolated_engine: Engine) -> Generator[Session, None, None]:
    schema = f"reconcile_{uuid4().hex}"
    tables = {
        Base.metadata.tables[name]
        for name in (
            "skill",
            "skill_version",
            "marketplace",
            "marketplace__user_group",
            "skill__user",
            "skill__user_group",
            "sandbox",
            "external_app__skill",
            "user__user_group",
            "user_skill_preference",
            "oauth_account",
            "user__pinned_persona",
        )
    }
    while (
        dependencies := {
            fk.column.table for table in tables for fk in table.foreign_keys
        }
        - tables
    ):
        tables |= dependencies
    with isolated_engine.connect() as connection:
        connection.execute(CreateSchema(schema))
        connection.execute(
            text("SELECT set_config('search_path', :schema, false)"), {"schema": schema}
        )
        Base.metadata.create_all(connection, tables=list(tables))
        connection.commit()
        try:
            with Session(connection) as session:
                yield session
        finally:
            connection.rollback()
            connection.execute(DropSchema(schema, cascade=True))
            connection.commit()


@pytest.fixture
def marketplace(session: Session) -> Marketplace:
    marketplace = Marketplace(
        name="Test catalog",
        provider=MarketplaceProvider.GITHUB,
        provider_config=GitHubMarketplaceConfig(owner="acme", repo="tools", ref="main"),
    )
    session.add(marketplace)
    session.commit()
    return marketplace


def catalog(
    *names: str, folder: str = "skills", body: bytes = b""
) -> CompleteMarketplace:
    files = {CLAUDE: _catalog(skills=[f"./{folder}"])}
    files.update({f"{folder}/{name}/SKILL.md": _md(name) + body for name in names})
    result = read_marketplace_archive(_archive(files))
    assert isinstance(result, CompleteMarketplace)
    return result


def stage(read: CompleteMarketplace) -> dict[str, IngestedBundle]:
    staged = {}
    for entry in read.entries:
        if isinstance(entry, ReadySkill):
            with zipfile.ZipFile(io.BytesIO(entry.bundle_bytes)) as archive:
                document = parse_skill_document(archive.read("SKILL.md"))
            staged[entry.entry_key] = IngestedBundle(
                canonical_name=document.metadata.name,
                bundle_file_id=str(uuid4()),
                bundle_sha256=compute_bundle_sha256(entry.bundle_bytes),
                description=document.metadata.description,
                metadata=compute_bundle_metadata(entry.bundle_bytes),
            )
    return staged


def apply(
    session: Session,
    marketplace: Marketplace,
    read: CompleteMarketplace | FailedMarketplace,
    *,
    revision: str = "revision-1",
    staged: dict[str, IngestedBundle] | None = None,
) -> ReconciliationResult:
    def forbid_io(frame: FrameType, event: str, _arg: object) -> None:
        if event == "call":
            path = frame.f_code.co_filename
            assert not (
                "/onyx/file_store/" in path and not path.endswith("/models.py")
            ), f"Storage call: {path}"
            assert not any(
                part in path
                for part in (
                    "/onyx/skills/marketplace/provider.py",
                    "/requests/",
                    "/httpx/",
                    "/urllib/",
                    "/socket.py",
                )
            ), f"Reconciliation attempted I/O: {path}"

    bundles = (
        staged
        if staged is not None
        else stage(read)
        if isinstance(read, CompleteMarketplace)
        else {}
    )
    previous = sys.getprofile()
    sys.setprofile(forbid_io)
    try:
        return reconcile_marketplace__no_commit(
            marketplace.id,
            read,
            revision=revision,
            staged=bundles,
            db_session=session,
            created_by_user_id=marketplace.login_user_id,
        )
    finally:
        sys.setprofile(previous)


def skills(session: Session, marketplace: Marketplace) -> list[Skill]:
    session.expire_all()
    return list(
        session.scalars(
            select(Skill)
            .where(Skill.marketplace_id == marketplace.id)
            .order_by(Skill.created_at, Skill.id)
        )
    )


def test_create_update_move_and_unchanged(
    session: Session, marketplace: Marketplace
) -> None:
    creator = make_user(session)
    marketplace.login_user_id = creator.id
    session.commit()
    first = apply(session, marketplace, catalog("hello"))
    session.commit()
    skill = skills(session, marketplace)[0]
    original_id = skill.id
    original_version = skill.current_version_id
    assert first.changed_skill_ids == [original_id]
    assert (skill.name, skill.description, skill.marketplace_path) == (
        "hello",
        "A test skill",
        "skills/hello",
    )
    assert skill.author_user_id is None and skill.public_permission is None
    assert skill.follows_marketplace_access
    assert skill.current_version is not None
    assert skill.current_version.created_by_user_id == creator.id
    assert skill.current_version.marketplace_revision == "revision-1"
    moved = apply(session, marketplace, catalog("hello", folder="moved"), staged={})
    session.commit()
    assert moved.changed_skill_ids == [original_id]
    assert skill.marketplace_path == "moved/hello"
    assert skill.current_version_id == original_version
    read = catalog("hello", folder="moved")
    staged = stage(read)
    unchanged = apply(session, marketplace, read, staged=staged)
    assert not unchanged.changed_skill_ids
    assert unchanged.cleanup_file_ids == {
        bundle.bundle_file_id for bundle in staged.values()
    }
    changed_read = catalog("hello", folder="moved", body=b"\nNew instructions")
    changed = apply(session, marketplace, changed_read, revision="revision-2")
    session.commit()
    history = list(session.scalars(SkillVersionAdapter(skill).versions()))
    assert len(history) == 2 and skill.id == original_id
    assert changed.changed_skill_ids == [original_id]
    assert (
        history[0].marketplace_revision
        == marketplace.last_synced_revision
        == "revision-2"
    )
    assert skill.current_version_id == history[0].id != original_version
    assert (skill.bundle_file_id, skill.bundle_sha256, skill.is_valid) == (
        history[0].bundle_file_id,
        history[0].bundle_sha256,
        True,
    )
    assert history[0].file_count == 1 and history[0].unpacked_size_bytes is not None


def test_rename_retire_and_reappearance(
    session: Session, marketplace: Marketplace
) -> None:
    apply(session, marketplace, catalog("old"))
    session.commit()
    old = skills(session, marketplace)[0]
    old_version = old.current_version_id
    result = apply(session, marketplace, catalog("new"))
    session.commit()
    assert result.retired_skill_ids == [old.id]
    retirement = old.retired_at
    assert retirement is not None and old.name == "old"
    result = apply(session, marketplace, catalog("old", "new"))
    session.commit()
    rows = skills(session, marketplace)
    assert len(rows) == 3
    assert old.retired_at == retirement and old.current_version_id == old_version
    assert len(result.changed_skill_ids) == 1 and result.changed_skill_ids[0] != old.id
    assert (
        len([row for row in rows if row.name == "old" and row.retired_at is None]) == 1
    )


@pytest.mark.parametrize("unsupported", [False, True])
def test_blocked_preserves_existing_and_reason(
    session: Session, marketplace: Marketplace, unsupported: bool
) -> None:
    apply(session, marketplace, catalog("hello"))
    session.commit()
    skill = skills(session, marketplace)[0]
    version_id = skill.current_version_id
    files = {
        CLAUDE: _catalog(skills=["./moved"]),
        "moved/hello/SKILL.md": b"bad",
        "moved/new/SKILL.md": b"bad",
    }
    if unsupported:
        files["commands/run.md"] = b"Use the command"
    read = read_marketplace_archive(_archive(files))
    assert isinstance(read, CompleteMarketplace)
    result = apply(session, marketplace, read)
    session.commit()
    assert result.changed_skill_ids == ([] if unsupported else [skill.id])
    assert not result.retired_skill_ids
    assert skill.marketplace_path == ("skills/hello" if unsupported else "moved/hello")
    assert len(skills(session, marketplace)) == 1
    assert skill.current_version_id == version_id and skill.retired_at is None
    assert marketplace.blocked_entries == result.blocked_entries
    assert ("tools" if unsupported else "tools/hello") in result.blocked_entries
    apply(session, marketplace, catalog("hello"), staged={})
    session.commit()
    assert marketplace.blocked_entries == {}


def test_failed_read_changes_nothing(
    session: Session, marketplace: Marketplace
) -> None:
    apply(session, marketplace, catalog("hello"))
    marketplace.last_error = "prior error"
    marketplace.blocked_entries = {"prior": "reason"}
    session.commit()
    before = (marketplace.last_synced_revision, marketplace.last_synced_at)
    read = read_marketplace_archive(b"truncated archive")
    assert isinstance(read, FailedMarketplace)
    result = apply(session, marketplace, read, revision="failed")
    session.commit()
    assert result.status == "failed"
    assert marketplace.last_error == "prior error" and marketplace.blocked_entries == {
        "prior": "reason"
    }
    assert before == (marketplace.last_synced_revision, marketplace.last_synced_at)
    assert skills(session, marketplace)[0].retired_at is None


@pytest.mark.parametrize(
    ("total", "removed", "stopped"),
    [(6, 5, False), (12, 6, False), (11, 6, True), (6, 6, True)],
)
def test_mass_retirement_boundary(
    session: Session, marketplace: Marketplace, total: int, removed: int, stopped: bool
) -> None:
    names = [f"skill-{i}" for i in range(total)]
    apply(session, marketplace, catalog(*names))
    session.commit()
    before = marketplace.last_synced_at
    read = catalog(*names[removed:], "added", body=b"changed")
    staged = stage(read)
    result = apply(session, marketplace, read, revision="force-push", staged=staged)
    session.commit()
    rows = skills(session, marketplace)
    if stopped:
        assert result.status == "needs_confirmation"
        assert marketplace.last_error == "needs confirmation"
        assert (
            marketplace.last_synced_revision == "revision-1"
            and marketplace.last_synced_at == before
        )
        assert not any(row.retired_at for row in rows) and len(rows) == total
        assert all(
            row.current_version is not None and row.current_version.version_number == 1
            for row in rows
        )
        assert result.cleanup_file_ids == {
            bundle.bundle_file_id for bundle in staged.values()
        }
    else:
        assert result.status == "applied" and len(result.retired_skill_ids) == removed
        assert len([row for row in rows if row.retired_at is not None]) == removed
        assert marketplace.last_synced_revision == "force-push"


@pytest.mark.parametrize(
    ("personal", "same_library", "retired"),
    [
        (False, True, False),
        (False, False, False),
        (True, True, False),
        (True, False, False),
        (False, True, True),
        (True, True, True),
    ],
)
def test_library_name_collision(
    session: Session,
    marketplace: Marketplace,
    personal: bool,
    same_library: bool,
    retired: bool,
) -> None:
    owner = make_user(session)
    other = make_user(session)
    marketplace.owner_user_id = owner.id if personal else None
    conflict_owner = owner.id if personal else None
    if not same_library:
        conflict_owner = other.id
    existing = make_skill(
        session,
        name="hello",
        author_user_id=conflict_owner,
        is_public=conflict_owner is None,
    )
    if retired:
        existing.retired_at = datetime.now(timezone.utc)
    session.commit()
    result = apply(session, marketplace, catalog("hello"))
    session.commit()
    blocked = same_library and not retired
    assert result.blocked_entries == ({"tools/hello": "name taken"} if blocked else {})
    assert len(skills(session, marketplace)) == (0 if blocked else 1)
    assert existing.name == "hello"


def test_new_entries_with_same_name_and_another_marketplace(
    session: Session, marketplace: Marketplace
) -> None:
    read = catalog("hello")
    entry = read.entries[0]
    read = CompleteMarketplace(
        entries=[entry, entry.model_copy(update={"entry_key": "second/hello"})]
    )
    result = apply(session, marketplace, read)
    assert result.blocked_entries == {"second/hello": "name taken"}
    other = Marketplace(
        name="Other",
        provider=marketplace.provider,
        provider_config=marketplace.provider_config,
    )
    session.add(other)
    session.commit()
    result = apply(session, other, catalog("hello"))
    session.commit()
    assert result.blocked_entries == {"tools/hello": "name taken"}
    assert not skills(session, other)


def test_missing_stage_rolls_back_all_changes(
    session: Session, marketplace: Marketplace
) -> None:
    apply(session, marketplace, catalog("gone", "updated"))
    session.commit()
    before = {row.id: row.current_version_id for row in skills(session, marketplace)}
    read = catalog("updated", "new", body=b"changed")
    staged = stage(read)
    staged.pop("tools/new")
    with pytest.raises(ValueError, match="needs a staged bundle"):
        apply(session, marketplace, read, revision="bad", staged=staged)
    session.commit()
    rows = skills(session, marketplace)
    assert {row.id: row.current_version_id for row in rows} == before
    assert not any(row.retired_at for row in rows)
    assert marketplace.last_synced_revision == "revision-1"


def test_outer_rollback_and_deferred_commit_failure(
    session: Session, marketplace: Marketplace
) -> None:
    apply(session, marketplace, catalog("hello"))
    session.rollback()
    assert not skills(session, marketplace) and marketplace.last_synced_revision is None
    apply(session, marketplace, catalog("hello"))
    skill = skills(session, marketplace)[0]
    skill.current_version_id = uuid4()
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()
    assert not skills(session, marketplace) and marketplace.last_synced_revision is None


def test_staged_identity_validation(session: Session, marketplace: Marketplace) -> None:
    read = catalog("hello")
    staged = stage(read)
    staged["tools/hello"] = staged["tools/hello"]._replace(canonical_name="wrong")
    with pytest.raises(ValueError, match="does not match"):
        apply(session, marketplace, read, staged=staged)
    assert not skills(session, marketplace)
    staged = stage(catalog("hello", body=b"different"))
    with pytest.raises(ValueError, match="does not match"):
        apply(session, marketplace, read, staged=staged)
    assert not skills(session, marketplace)


def test_retention_and_cleanup_are_transactional(
    session: Session, marketplace: Marketplace
) -> None:
    first_file: str | None = None
    for index in range(11):
        result = apply(session, marketplace, catalog("hello", body=str(index).encode()))
        if index == 0:
            first_file = skills(session, marketplace)[0].bundle_file_id
        session.commit()
    skill = skills(session, marketplace)[0]
    history = list(session.scalars(SkillVersionAdapter(skill).versions()))
    assert (
        len(history) == 11 and sum(v.bundle_file_id is not None for v in history) == 10
    )
    assert result.cleanup_file_ids == {first_file}
    assert history[-1].bundle_file_id is None
    next_pruned_file = history[-2].bundle_file_id
    result = apply(session, marketplace, catalog("hello", body=b"rollback"))
    assert result.cleanup_file_ids == {next_pruned_file}
    session.rollback()
    assert len(list(session.scalars(SkillVersionAdapter(skill).versions()))) == 11
    assert history[-2].bundle_file_id is not None


def test_reconciliation_migration_round_trip(
    session: Session, marketplace: Marketplace
) -> None:
    scripts = ScriptDirectory(str(Path(__file__).resolve().parents[3] / "alembic"))
    revision = scripts.get_revision("3833433b1585")
    assert revision is not None
    with Operations.context(MigrationContext.configure(session.connection())):
        revision.module.downgrade()
        revision.module.upgrade()
    session.commit()
    session.refresh(marketplace)
    assert marketplace.blocked_entries == {}
    apply(session, marketplace, catalog("hello"))
    session.commit()
    assert skills(session, marketplace)[0].marketplace_path == "skills/hello"


@pytest.mark.parametrize("same_marketplace", [False, True])
def test_concurrent_syncs_serialize_library_names(
    session: Session,
    marketplace: Marketplace,
    isolated_engine: Engine,
    same_marketplace: bool,
) -> None:
    schema = session.scalar(text("SELECT current_schema()"))
    other = Marketplace(
        name="Second",
        provider=marketplace.provider,
        provider_config=marketplace.provider_config,
    )
    session.add(other)
    session.flush()
    ids = [marketplace.id, marketplace.id if same_marketplace else other.id]
    session.commit()
    barrier = Barrier(2)
    read = catalog("hello")

    def sync(marketplace_id: UUID) -> ReconciliationResult:
        with Session(isolated_engine) as worker:
            worker.execute(
                text("SELECT set_config('search_path', :schema, true)"),
                {"schema": schema},
            )
            row = worker.get(Marketplace, marketplace_id)
            assert row is not None
            barrier.wait(timeout=10)
            result = apply(worker, row, read)
            worker.commit()
            return result

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(sync, ids))
    assert sum(len(result.changed_skill_ids) for result in results) == 1
    assert sum(len(result.blocked_entries) for result in results) == (
        0 if same_marketplace else 1
    )
    assert len(list(session.scalars(select(Skill)))) == 1


def test_name_cannot_change_under_existing_key(
    session: Session, marketplace: Marketplace
) -> None:
    apply(session, marketplace, catalog("hello"))
    session.commit()
    skill = skills(session, marketplace)[0]
    entry = (
        catalog("changed").entries[0].model_copy(update={"entry_key": "tools/hello"})
    )
    with pytest.raises(ValueError, match="name cannot change"):
        apply(session, marketplace, CompleteMarketplace(entries=[entry]))
    session.commit()
    assert skills(session, marketplace)[0].name == skill.name == "hello"


def test_waiting_sync_reads_committed_version(
    session: Session, marketplace: Marketplace, isolated_engine: Engine
) -> None:
    apply(session, marketplace, catalog("hello"))
    session.commit()
    skill = skills(session, marketplace)[0]
    schema = session.scalar(text("SELECT current_schema()"))
    marketplace_id = marketplace.id
    read = catalog("hello", body=b"concurrent edit")
    staged = stage(read)
    bundle = staged["tools/hello"]
    write_resource_version(
        SkillVersionAdapter(skill),
        bundle_file_id=bundle.bundle_file_id,
        bundle_sha256=bundle.bundle_sha256,
        metadata=bundle.metadata,
        is_valid=True,
        created_by_user_id=None,
        db_session=session,
    )
    waiting: Queue[int] = Queue()

    def sync() -> ReconciliationResult:
        with Session(isolated_engine) as worker:
            worker.execute(
                text("SELECT set_config('search_path', :schema, true)"),
                {"schema": schema},
            )
            worker.execute(text("SET LOCAL statement_timeout = '10s'"))
            row = worker.get(Marketplace, marketplace_id)
            assert row is not None
            pid = worker.scalar(select(func.pg_backend_pid()))
            assert isinstance(pid, int)
            waiting.put(pid)
            result = apply(worker, row, read, staged=staged)
            worker.commit()
            return result

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(sync)
        try:
            pid = waiting.get(timeout=5)
            with isolated_engine.connect() as observer:
                deadline = time.monotonic() + 5
                while not observer.scalar(
                    select(func.cardinality(func.pg_blocking_pids(pid)))
                ):
                    assert time.monotonic() < deadline
                    time.sleep(0.01)
            session.commit()
        finally:
            session.rollback()
        result = future.result(timeout=15)
    assert not result.changed_skill_ids
    assert len(list(session.scalars(SkillVersionAdapter(skill).versions()))) == 2
