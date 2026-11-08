"""Real PostgreSQL/FileStore syncs; only GitHub and deliberate faults are faked."""

import io
import json
import os
import subprocess
import sys
from collections.abc import Mapping
from contextlib import ExitStack, nullcontext
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
import requests
from botocore.exceptions import ClientError
from psycopg2 import OperationalError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from onyx.db.enums import SkillSharePermission
from onyx.db.models import FileContent, Marketplace, Skill, SkillVersion
from onyx.db.skill_version import delete_orphan_skill_bundles
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store import postgres_file_store
from onyx.file_store.file_store import (
    FileStore,
    S3BackedFileStore,
    get_default_file_store,
    is_missing_object,
)
from onyx.skills import sync
from onyx.skills.ingest import IngestedBundle, PreparedSkillBundle
from onyx.skills.marketplace.models import MarketplaceSyncStatus, ReconciliationResult
from onyx.skills.marketplace.read_models import CompleteMarketplace, FailedMarketplace
from tests.external_dependency_unit.craft.db_helpers import make_sandbox, make_user
from tests.external_dependency_unit.db.test_marketplace_reconciliation import (
    marketplace as marketplace,
)
from tests.external_dependency_unit.db.test_skill_version_writes import (
    bundle,
    make_old,
    stored_bundles,
)
from tests.external_dependency_unit.db.test_skill_version_writes import (
    session as session,
)
from tests.external_dependency_unit.db.test_skill_version_writes import (
    tenant as tenant,
)
from tests.unit.onyx.skills.marketplace_fixtures import CLAUDE, _archive, _catalog, _md


class GitHub:
    def __init__(self) -> None:
        self.revision = "a" * 40
        self.archive = catalog_bytes("alpha", "beta")
        self.urls: list[str] = []

    def get(self, url: str, **_kwargs: object) -> requests.Response:
        self.urls.append(url)
        response = requests.Response()
        response.status_code = 200
        if "/commits/" in url:
            content = json.dumps({"sha": self.revision}).encode()
        else:
            assert url.endswith("/tar.gz/" + self.revision)
            content = self.archive
        response.raw = io.BytesIO(content)
        return response


def catalog_bytes(*names: str, body: bytes = b"") -> bytes:
    return _archive(
        {CLAUDE: _catalog(skills=["./skills"])}
        | {f"skills/{name}/SKILL.md": _md(name) + body for name in names},
        kind="tar",
        wrapper="repo-commit/",
    )


@pytest.fixture
def github(
    monkeypatch: pytest.MonkeyPatch, session: Session, marketplace: Marketplace
) -> GitHub:
    marketplace.login_user_id = make_user(session).id
    session.commit()
    github = GitHub()
    monkeypatch.setattr("onyx.utils.github.ssrf_safe_get", github.get)
    monkeypatch.setattr(
        "onyx.skills.marketplace.provider.github_authorization_header",
        lambda *_args, **_kwargs: "Bearer test",
    )
    return github


def rows(session: Session) -> list[Skill]:
    session.expire_all()
    return list(session.scalars(select(Skill).order_by(Skill.name)))


def run(marketplace: Marketplace, tenant: str) -> ReconciliationResult:
    result = sync.sync_marketplace(marketplace.id, tenant)
    assert result is not None
    return result


def test_success_and_noop(
    session: Session,
    marketplace: Marketplace,
    tenant: str,
    github: GitHub,
) -> None:
    result = run(marketplace, tenant)
    assert result.status == "applied" and len(result.changed_skill_ids) == 2
    versions = [row.current_version_id for row in rows(session)]
    files = stored_bundles(session)
    assert len(files) == 2
    assert marketplace.last_synced_revision == github.revision
    with patch.object(
        get_default_file_store(), "read_file", side_effect=AssertionError("full read")
    ):
        assert sync.sync_marketplace(marketplace.id, tenant) is None
    assert len(github.urls) == 3  # The unchanged source needs only a commit lookup.
    github.revision = "b" * 40
    assert not run(marketplace, tenant).changed_skill_ids
    assert [row.current_version_id for row in rows(session)] == versions
    assert marketplace.last_synced_revision == github.revision
    assert stored_bundles(session) == files


@pytest.mark.parametrize("failure", ["upload", "commit", "cleanup"])
def test_failure_preserves_rows_and_revision(
    session: Session,
    marketplace: Marketplace,
    tenant: str,
    github: GitHub,
    failure: str,
) -> None:
    run(marketplace, tenant)
    original = [(row.id, row.current_version_id) for row in rows(session)]
    retained = stored_bundles(session)
    github.revision = "b" * 40
    github.archive = catalog_bytes("alpha", "beta", "gamma", body=b"\nChanged")
    save = sync.save_skill_bundle_bytes
    calls = 0

    def fail_later(
        content: bytes,
        *,
        display_name: str,
        file_store: FileStore,
        file_id: str | None = None,
    ) -> str:
        nonlocal calls
        file_id = save(
            content, display_name=display_name, file_store=file_store, file_id=file_id
        )
        calls += 1
        if calls == 2:
            raise ValueError("storage failed after saving later skill")
        return file_id

    reconcile = sync.reconcile_marketplace__no_commit

    def fail_commit(
        marketplace_id: UUID,
        read: CompleteMarketplace | FailedMarketplace,
        *,
        revision: str,
        staged: Mapping[str, IngestedBundle],
        db_session: Session,
        created_by_user_id: UUID | None = None,
        recovery_keys: frozenset[str] = frozenset(),
    ) -> ReconciliationResult:
        result = reconcile(
            marketplace_id,
            read,
            revision=revision,
            staged=staged,
            db_session=db_session,
            created_by_user_id=created_by_user_id,
            recovery_keys=recovery_keys,
        )
        skill = db_session.get(Skill, result.changed_skill_ids[-1])
        assert skill is not None
        skill.current_version_id = uuid4()  # Deferred FK fails at the outer commit.
        return result

    with (
        patch.object(sync, "reconcile_marketplace__no_commit", side_effect=fail_commit)
        if failure == "commit"
        else patch.object(sync, "save_skill_bundle_bytes", side_effect=fail_later)
    ):
        with (
            patch.object(
                get_default_file_store(), "delete_file", side_effect=OSError("offline")
            )
            if failure == "cleanup"
            else nullcontext()
        ):
            with pytest.raises((ValueError, IntegrityError)):
                run(marketplace, tenant)
    assert [(row.id, row.current_version_id) for row in rows(session)] == original
    assert marketplace.last_synced_revision == "a" * 40
    assert len(list(session.scalars(select(SkillVersion)))) == 2
    if failure in {"cleanup", "commit"}:
        leftovers = stored_bundles(session) - retained
        assert len(leftovers) == (3 if failure == "commit" else 2)
        assert delete_orphan_skill_bundles() == 0
        make_old(leftovers, session)
        assert delete_orphan_skill_bundles() == len(leftovers)
    assert stored_bundles(session) == retained
    result = run(marketplace, tenant)
    assert len(result.changed_skill_ids) == 3
    assert {row.id for row in rows(session)}.issuperset({item[0] for item in original})
    assert marketplace.last_synced_revision == github.revision


@pytest.mark.parametrize(
    "damage", ["missing", "missing_object", "corrupt", "different", "pruned"]
)
@pytest.mark.parametrize("same_revision", [False, True])
def test_equal_content_recovery(
    session: Session,
    marketplace: Marketplace,
    tenant: str,
    github: GitHub,
    damage: str,
    same_revision: bool,
) -> None:
    run(marketplace, tenant)
    skill, healthy = rows(session)
    old_version = skill.current_version_id
    healthy_version = healthy.current_version_id
    old_file = skill.bundle_file_id
    assert old_file is not None
    store = get_default_file_store()
    if damage == "missing":
        store.delete_file(old_file)
    elif damage == "missing_object":
        if isinstance(store, postgres_file_store.PostgresBackedFileStore):
            content = session.get(FileContent, old_file)
            assert content is not None
            assert session.scalar(select(func.lo_unlink(content.lobj_oid))) == 1
            session.commit()
        else:
            assert isinstance(store, S3BackedFileStore)
            record = store.read_file_record(old_file)
            for client in (store._get_s3_client(), store._get_legacy_s3_client()):
                if client is not None:
                    client.delete_object(
                        Bucket=record.bucket_name, Key=record.object_key
                    )
        for use_tempfile, max_bytes in [(False, None), (True, None), (False, 4096)]:
            with pytest.raises((FileNotFoundError, ClientError)) as missing:
                store.read_file(
                    old_file,
                    db_session=session,
                    use_tempfile=use_tempfile,
                    max_bytes=max_bytes,
                )
            if isinstance(missing.value, ClientError):
                assert is_missing_object(missing.value)
            assert session.scalar(select(1)) == 1
    elif damage == "pruned":
        assert skill.current_version is not None
        skill.current_version.bundle_file_id = None
        session.commit()
    else:
        record = store.read_file_record(old_file)
        corrupt = (
            b"not a ZIP"
            if damage == "corrupt"
            else bundle("alpha", "Changed in storage")
        )
        store.save_file(
            io.BytesIO(corrupt),
            record.display_name,
            record.file_origin,
            record.file_type,
            file_id=old_file,
        )
    if same_revision and damage in {"corrupt", "different"}:
        assert sync.sync_marketplace(marketplace.id, tenant) is None
        assert rows(session)[0].current_version_id == old_version
        # Content corruption is checked when the source next changes.
        github.revision = "b" * 40
    if not same_revision:
        github.revision = "b" * 40
    result = run(marketplace, tenant)
    assert result.changed_skill_ids == [skill.id]
    skill, healthy = rows(session)
    assert skill.current_version_id != old_version
    assert healthy.current_version_id == healthy_version
    assert skill.bundle_file_id != old_file
    assert skill.bundle_file_id not in result.cleanup_file_ids
    assert skill.current_version is not None
    assert skill.bundle_file_id is not None
    with store.read_file(skill.bundle_file_id) as source:
        assert source.read().startswith(b"PK")
    assert len(list(session.scalars(select(SkillVersion)))) == 3
    assert marketplace.last_synced_revision == github.revision
    assert sync.sync_marketplace(marketplace.id, tenant) is None

    if damage == "missing_object":
        store.delete_file(old_file)
        session.expire_all()
        assert session.get(FileContent, old_file) is None


@pytest.mark.parametrize("limit_error", [False, True])
def test_blocked_ingestion_preserves_key_and_other_imports(
    session: Session,
    marketplace: Marketplace,
    tenant: str,
    github: GitHub,
    limit_error: bool,
) -> None:
    github.archive = catalog_bytes("alpha")
    run(marketplace, tenant)
    original = rows(session)[0].current_version_id
    github.revision = "b" * 40
    github.archive = catalog_bytes("alpha", "beta", "pptx", body=b"\nChanged")
    prepare = sync.prepare_skill_bundle

    def invalid_alpha(
        content: bytes, filename: str | None, *, expected_name: str | None = None
    ) -> PreparedSkillBundle:
        if expected_name == "alpha":
            if limit_error:
                raise OnyxError(OnyxErrorCode.PAYLOAD_TOO_LARGE, "invalid import")
            raise ValueError("invalid import")
        return prepare(content, filename, expected_name=expected_name)

    with patch.object(sync, "prepare_skill_bundle", side_effect=invalid_alpha):
        result = run(marketplace, tenant)
    assert len(result.changed_skill_ids) == 1
    assert result.blocked_entries["tools/alpha"] == "invalid import"
    assert "reserved" in result.blocked_entries["tools/pptx"]
    alpha, beta = rows(session)
    assert alpha.current_version_id == original and alpha.retired_at is None
    assert beta.name == "beta"
    assert marketplace.last_synced_revision == github.revision
    assert marketplace.blocked_entries == result.blocked_entries
    assert len(stored_bundles(session)) == 2


def test_retention_and_post_commit_cleanup_failure(
    session: Session,
    marketplace: Marketplace,
    tenant: str,
    github: GitHub,
) -> None:
    for number in range(11):
        github.revision = f"{number:040x}"
        github.archive = catalog_bytes("alpha", body=f"\n{number}".encode())
        with patch.object(
            get_default_file_store(), "delete_file", side_effect=OSError("offline")
        ):
            result = run(marketplace, tenant)
        assert result.status == "applied"
    history = list(
        session.scalars(select(SkillVersion).order_by(SkillVersion.version_number))
    )
    assert len(history) == 11 and history[0].bundle_file_id is None
    assert len(result.cleanup_file_ids) == 1
    assert len(stored_bundles(session)) == 11
    make_old(stored_bundles(session), session)
    assert delete_orphan_skill_bundles() == 1
    assert stored_bundles(session) == {v.bundle_file_id for v in history[1:]}


def test_unused_stage_is_removed_after_noop_reconciliation(
    session: Session,
    marketplace: Marketplace,
    tenant: str,
    github: GitHub,
) -> None:
    run(marketplace, tenant)
    original = stored_bundles(session)
    github.revision = "b" * 40
    fetch = sync.fetch_marketplace_sync_state

    def miss_snapshot(
        marketplace_id: UUID, db_session: Session
    ) -> tuple[Marketplace, dict[str, SkillVersion | None]]:
        marketplace, _current = fetch(marketplace_id, db_session)
        return marketplace, {}

    # A preflight snapshot can miss content that is already current at apply time.
    with patch.object(sync, "fetch_marketplace_sync_state", side_effect=miss_snapshot):
        result = run(marketplace, tenant)
    assert not result.changed_skill_ids and len(result.cleanup_file_ids) == 2
    assert stored_bundles(session) == original


def test_crash_before_commit_then_retry(
    session: Session,
    marketplace: Marketplace,
    tenant: str,
    github: GitHub,
    tmp_path: Path,
) -> None:
    run(marketplace, tenant)
    retained = stored_bundles(session)
    github.revision = "b" * 40
    github.archive = catalog_bytes("alpha", "beta", body=b"\nChanged")
    archive = tmp_path / "archive.tar.gz"
    archive.write_bytes(github.archive)
    worker = """
import os, sys
from pathlib import Path
from unittest.mock import patch
from onyx.db.engine.sql_engine import SqlEngine
from onyx.skills import sync
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR
from tests.external_dependency_unit.db.test_marketplace_sync import GitHub
from uuid import UUID
SqlEngine.init_engine(pool_size=2, max_overflow=0)
CURRENT_TENANT_ID_CONTEXTVAR.set(sys.argv[1])
github = GitHub()
github.revision = "b" * 40
github.archive = Path(sys.argv[3]).read_bytes()
reconcile = sync.reconcile_marketplace__no_commit
def crash(*args, **kwargs):
    reconcile(*args, **kwargs)
    os._exit(17)
with patch("onyx.utils.github.ssrf_safe_get", github.get), patch(
    "onyx.skills.marketplace.provider.github_authorization_header", return_value="Bearer test"
), patch.object(sync, "reconcile_marketplace__no_commit", crash):
    sync.sync_marketplace(UUID(sys.argv[2]), sys.argv[1])
"""
    child = subprocess.run(
        [sys.executable, "-c", worker, tenant, str(marketplace.id), str(archive)],
        cwd=Path(__file__).resolve().parents[3],
        env=os.environ.copy(),
        capture_output=True,
        timeout=60,
    )
    assert child.returncode == 17, child.stderr.decode()
    assert len(list(session.scalars(select(SkillVersion)))) == 2
    session.refresh(marketplace)
    assert marketplace.last_synced_revision == "a" * 40
    orphaned = stored_bundles(session) - retained
    assert len(orphaned) == 2
    marketplace.sync_lease_expires_at = session.execute(
        select(func.clock_timestamp())
    ).scalar_one() - timedelta(seconds=1)
    session.commit()
    assert len(run(marketplace, tenant).changed_skill_ids) == 2
    assert orphaned.issubset(stored_bundles(session))
    assert delete_orphan_skill_bundles() == 0
    make_old(orphaned, session)
    assert delete_orphan_skill_bundles() == 2
    assert len(stored_bundles(session)) == 4


@pytest.mark.parametrize("source", ["failed", "needs_confirmation"])
def test_source_guards_keep_rows_and_clean_stages(
    session: Session,
    marketplace: Marketplace,
    tenant: str,
    github: GitHub,
    source: str,
) -> None:
    github.archive = catalog_bytes(*(f"skill-{index}" for index in range(7)))
    run(marketplace, tenant)
    original = [(row.id, row.current_version_id) for row in rows(session)]
    files = stored_bundles(session)
    github.revision = "b" * 40
    github.archive = (
        b"broken archive" if source == "failed" else catalog_bytes("replacement")
    )
    result = run(marketplace, tenant)
    assert result.status == source
    session.refresh(marketplace)
    assert marketplace.sync_status == source and marketplace.last_error
    assert [(row.id, row.current_version_id) for row in rows(session)] == original
    assert all(row.retired_at is None for row in rows(session))
    assert marketplace.last_synced_revision == "a" * 40
    assert stored_bundles(session) == files
    assert len(result.cleanup_file_ids) == (1 if source == "needs_confirmation" else 0)


def test_transient_current_read_failure_stops_before_fetch(
    session: Session,
    marketplace: Marketplace,
    tenant: str,
    github: GitHub,
) -> None:
    run(marketplace, tenant)
    files = stored_bundles(session)
    with (
        patch.object(get_default_file_store(), "get_file_size", return_value=None),
        patch.object(
            get_default_file_store(), "read_file", side_effect=OSError("offline")
        ),
    ):
        with pytest.raises(OSError, match="offline"):
            run(marketplace, tenant)
    assert len(github.urls) == 2
    assert stored_bundles(session) == files


def test_commit_acknowledgement_failure_keeps_referenced_uploads(
    session: Session,
    marketplace: Marketplace,
    tenant: str,
    github: GitHub,
) -> None:
    commit = Session.commit

    def lost_ack(transaction: Session) -> None:
        commit(transaction)
        # Upload commits have no versions yet. The content commit has both.
        with Session(transaction.get_bind()) as observer:
            if observer.scalar(select(SkillVersion.id).limit(1)) is not None:
                raise OSError("commit acknowledgement lost")

    with (
        patch.object(Session, "commit", lost_ack),
        patch.object(sync, "_cleanup", wraps=sync._cleanup) as cleanup,
    ):
        with pytest.raises(OSError, match="acknowledgement"):
            run(marketplace, tenant)
        cleanup.assert_not_called()
    assert len(rows(session)) == 2
    assert marketplace.last_synced_revision == github.revision
    assert stored_bundles(session) == {row.bundle_file_id for row in rows(session)}
    assert sync.sync_marketplace(marketplace.id, tenant) is None


@pytest.mark.parametrize("operation", ["read", "delete"])
def test_existing_blob_errors_are_not_treated_as_missing(
    session: Session,
    marketplace: Marketplace,
    tenant: str,
    github: GitHub,
    operation: str,
) -> None:
    run(marketplace, tenant)
    store = get_default_file_store()
    files = stored_bundles(session)
    file_id = next(iter(files))
    with ExitStack() as faults:
        error: OperationalError | ClientError
        if isinstance(store, postgres_file_store.PostgresBackedFileStore):
            error = OperationalError("storage unavailable")
            faults.enter_context(
                patch.object(
                    postgres_file_store,
                    f"_{operation}_large_object",
                    side_effect=error,
                )
            )
        else:
            assert isinstance(store, S3BackedFileStore)
            method = "get_object" if operation == "read" else "delete_object"
            error = ClientError(
                {
                    "Error": {
                        "Code": "ServiceUnavailable",
                        "Message": "storage unavailable",
                    }
                },
                method,
            )
            for client in (store._get_s3_client(), store._get_legacy_s3_client()):
                if client is not None:
                    faults.enter_context(
                        patch.object(client, method, side_effect=error)
                    )
        with pytest.raises(type(error), match="storage unavailable") as raised:
            if operation == "read":
                store.read_file(file_id)
            else:
                store.delete_file(file_id)
        assert raised.value is error
    assert stored_bundles(session) == files
    with store.read_file(file_id) as content:
        assert content.read().startswith(b"PK")
    assert marketplace.last_synced_revision == github.revision


@pytest.mark.parametrize("blocked", ["skill", "plugin"])
def test_unrepairable_bundle_does_not_repeat_archive_download(
    session: Session,
    marketplace: Marketplace,
    tenant: str,
    github: GitHub,
    blocked: str,
) -> None:
    run(marketplace, tenant)
    skill = rows(session)[0]
    assert skill.bundle_file_id is not None
    get_default_file_store().delete_file(skill.bundle_file_id)
    github.archive = _archive(
        {CLAUDE: _catalog(skills=["./skills"])}
        | {"skills/alpha/SKILL.md": b"invalid", "skills/beta/SKILL.md": _md("beta")}
        | ({"agents/agent.md": b"unsupported"} if blocked == "plugin" else {}),
        kind="tar",
        wrapper="repo-commit/",
    )
    assert sync.sync_marketplace(marketplace.id, tenant) is None
    assert len(github.urls) == 4
    session.refresh(marketplace)
    assert marketplace.blocked_entries
    for _ in range(2):
        assert sync.sync_marketplace(marketplace.id, tenant) is None
    assert len(github.urls) == 6
    github.revision = "b" * 40
    github.archive = catalog_bytes("alpha", "beta")
    assert run(marketplace, tenant).changed_skill_ids == [skill.id]


def test_push_observes_committed_creation_and_retirement(
    session: Session, marketplace: Marketplace, tenant: str, github: GitHub
) -> None:
    user = make_user(session)
    make_sandbox(session, user)
    marketplace.public_permission = SkillSharePermission.VIEWER
    session.commit()

    def pushed(recipients: set[UUID], push_session: Session) -> None:
        assert recipients == {user.id}
        assert not push_session.in_transaction()
        with sync.get_session_with_current_tenant() as observer:
            stored = list(observer.scalars(select(Skill)))
            assert len(stored) == 2
            assert sum(row.retired_at is not None for row in stored) == retired

    retired = 0
    with patch.object(sync, "push_skills_for_users", side_effect=pushed) as push:
        run(marketplace, tenant)
        push.assert_called_once()
        github.revision = "b" * 40
        github.archive = catalog_bytes("alpha")
        retired = 1
        run(marketplace, tenant)
        assert push.call_count == 2


@pytest.mark.parametrize("stop", [False, True])
def test_publication_and_completion_survive_post_commit_failure(
    session: Session,
    marketplace: Marketplace,
    tenant: str,
    github: GitHub,
    stop: bool,
) -> None:
    user = make_user(session)
    make_sandbox(session, user)
    marketplace.public_permission = SkillSharePermission.VIEWER
    session.commit()

    def fail_push(_recipients: set[UUID], _push_session: Session) -> None:
        with sync.get_session_with_current_tenant() as observer:
            published = observer.get(Marketplace, marketplace.id)
            assert published is not None
            assert published.last_synced_revision == github.revision
            assert published.sync_status == MarketplaceSyncStatus.APPLIED
            assert published.sync_owner is None
        if stop:
            raise SystemExit("worker stopped after publication")
        raise RuntimeError("push unavailable")

    with patch.object(sync, "push_skills_for_users", side_effect=fail_push):
        if stop:
            with pytest.raises(SystemExit, match="worker stopped"):
                run(marketplace, tenant)
        else:
            assert run(marketplace, tenant).status == "applied"
    session.refresh(marketplace)
    assert marketplace.sync_status == MarketplaceSyncStatus.APPLIED
    assert marketplace.last_error is None and marketplace.sync_owner is None
    assert not marketplace.sync_requested
    assert len(rows(session)) == 2
    count = len(github.urls)
    assert sync.sync_marketplace(marketplace.id, tenant, request_work=False) is None
    assert len(github.urls) == count
