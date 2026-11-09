"""Real PostgreSQL ownership races; GitHub and transport dispatch are controlled."""

from collections.abc import Callable, Generator, Mapping
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import timedelta
from threading import BoundedSemaphore, Event
from unittest.mock import Mock, patch
from uuid import UUID

import pytest
import requests
from psycopg2.errors import LockNotAvailable
from sqlalchemy import func, text, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from onyx.background.celery.tasks.marketplace_sync import tasks
from onyx.db import marketplace_sync as ownership
from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.enums import ExternalAppType
from onyx.db.models import ExternalApp, Marketplace
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.file_store import FileStore
from onyx.skills import sync
from onyx.skills.github_auth import github_authorization_header
from onyx.skills.ingest import IngestedBundle
from onyx.skills.marketplace.models import MarketplaceSyncStatus, ReconciliationResult
from onyx.skills.marketplace.read_models import CompleteMarketplace, FailedMarketplace
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR
from tests.external_dependency_unit.craft.db_helpers import make_user
from tests.external_dependency_unit.db.test_marketplace_reconciliation import (
    marketplace as marketplace,
)
from tests.external_dependency_unit.db.test_marketplace_sync import (
    GitHub,
    catalog_bytes,
    rows,
)
from tests.external_dependency_unit.db.test_marketplace_sync import github as github
from tests.external_dependency_unit.db.test_skill_version_writes import (
    session as session,
)
from tests.external_dependency_unit.db.test_skill_version_writes import tenant as tenant

other_tenant = tenant


@pytest.fixture
def broker(monkeypatch: pytest.MonkeyPatch) -> Generator[Mock, None, None]:
    monkeypatch.setattr(tasks, "DISABLE_VECTOR_DB", False)
    with patch("onyx.background.celery.versioned_apps.client.app.send_task") as send:
        yield send


def expire(session: Session, marketplace_id: UUID) -> None:
    session.execute(
        update(Marketplace)
        .where(Marketplace.id == marketplace_id)
        .values(
            sync_lease_expires_at=func.clock_timestamp() - timedelta(seconds=1),
            sync_dispatch_after=None,
            sync_retry_after=None,
        )
    )
    session.commit()


def run_task(marketplace_id: UUID, tenant: str) -> None:
    tasks.sync_marketplace_task.run(
        marketplace_id=str(marketplace_id), tenant_id=tenant
    )


def test_publication_finishes_when_lease_expires_under_its_row_lock(
    session: Session,
    marketplace: Marketplace,
    tenant: str,
    github: GitHub,
    broker: Mock,
) -> None:
    identifier = marketplace.id
    reconcile = sync.reconcile_marketplace__no_commit

    def rival_claim() -> None:
        with get_session_with_tenant(tenant_id=tenant) as other:
            other.execute(text("SET LOCAL lock_timeout = '100ms'"))
            with pytest.raises(OperationalError) as failure:
                ownership.claim_marketplace_sync(identifier, other)
            assert isinstance(failure.value.orig, LockNotAvailable)

    def reconcile_after_expiry(
        marketplace_id: UUID,
        read: CompleteMarketplace | FailedMarketplace,
        *,
        revision: str,
        staged: Mapping[str, IngestedBundle],
        db_session: Session,
        created_by_user_id: UUID | None = None,
        recovery_keys: frozenset[str] = frozenset(),
    ) -> ReconciliationResult:
        db_session.execute(
            update(Marketplace)
            .where(Marketplace.id == marketplace_id)
            .values(sync_lease_expires_at=func.clock_timestamp() - timedelta(seconds=1))
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(rival_claim).result(5)
        return reconcile(
            marketplace_id,
            read,
            revision=revision,
            staged=staged,
            db_session=db_session,
            created_by_user_id=created_by_user_id,
            recovery_keys=recovery_keys,
        )

    tasks.enqueue_marketplace_sync(identifier, tenant_id=tenant)
    with patch.object(sync, "reconcile_marketplace__no_commit", reconcile_after_expiry):
        run_task(identifier, tenant)
    session.refresh(marketplace)
    assert marketplace.sync_status == MarketplaceSyncStatus.APPLIED
    assert marketplace.last_synced_revision == github.revision
    assert marketplace.sync_owner is None
    assert marketplace.sync_attempts == 1
    assert {row.name for row in rows(session)} == {"alpha", "beta"}
    assert broker.call_count == 1


def test_second_commit_during_run(
    session: Session,
    marketplace: Marketplace,
    tenant: str,
    github: GitHub,
    broker: Mock,
) -> None:
    identifier = marketplace.id
    tasks.enqueue_marketplace_sync(identifier, tenant_id=tenant)
    entered, release = Event(), Event()
    get = github.get

    def blocked_get(url: str, **kwargs: object) -> requests.Response:
        response = get(url, **kwargs)
        if "/tar.gz/" in url and not entered.is_set():
            entered.set()
            assert release.wait(10)
        return response

    with (
        patch("onyx.utils.github.ssrf_safe_get", blocked_get),
        ThreadPoolExecutor() as pool,
    ):
        first = pool.submit(run_task, identifier, tenant)
        try:
            assert entered.wait(10)
            github.revision = "b" * 40
            github.archive = catalog_bytes("alpha", "beta", "gamma")
            tasks.enqueue_marketplace_sync(identifier, tenant_id=tenant)
            pool.submit(run_task, identifier, tenant).result(10)  # duplicate delivery
            assert broker.call_count == 1
        finally:
            release.set()
        first.result(10)
    session.refresh(marketplace)
    assert marketplace.last_synced_revision == "b" * 40
    assert not marketplace.sync_requested and marketplace.sync_owner is None
    assert len([url for url in github.urls if "/tar.gz/" in url]) == 2


def test_request_at_final_release(
    session: Session,
    marketplace: Marketplace,
    tenant: str,
    github: GitHub,
    broker: Mock,
) -> None:
    identifier = marketplace.id
    tasks.enqueue_marketplace_sync(identifier, tenant_id=tenant)
    released, resume = Event(), Event()
    perform = sync._sync_marketplace

    def pause_after_release(
        identifier: UUID, tenant_id: str, owner: UUID, heartbeat: sync.LeaseHeartbeat
    ) -> tuple[ReconciliationResult | None, bool]:
        result = perform(identifier, tenant_id, owner, heartbeat)
        released.set()
        assert resume.wait(10)
        return result

    with (
        patch.object(sync, "_sync_marketplace", pause_after_release),
        ThreadPoolExecutor() as pool,
    ):
        worker = pool.submit(run_task, identifier, tenant)
        try:
            assert released.wait(10)
            github.revision = "b" * 40
            tasks.enqueue_marketplace_sync(identifier, tenant_id=tenant)
        finally:
            resume.set()
        worker.result(10)
    assert broker.call_count == 2
    run_task(identifier, tenant)
    session.refresh(marketplace)
    assert marketplace.last_synced_revision == "b" * 40
    assert not marketplace.sync_requested


def test_expired_worker_cannot_publish_or_clear_new_owner(
    session: Session,
    marketplace: Marketplace,
    tenant: str,
    github: GitHub,
    broker: Mock,
) -> None:
    identifier = marketplace.id
    tasks.enqueue_marketplace_sync(identifier, tenant_id=tenant)
    staged, resume = Event(), Event()
    save = sync.save_skill_bundle_bytes

    def pause_after_upload(
        content: bytes,
        *,
        display_name: str,
        file_store: FileStore,
        file_id: str | None = None,
    ) -> str:
        value = save(
            content, display_name=display_name, file_store=file_store, file_id=file_id
        )
        if not staged.is_set():
            staged.set()
            assert resume.wait(10)
        return value

    with (
        patch.object(sync, "save_skill_bundle_bytes", pause_after_upload),
        ThreadPoolExecutor() as pool,
    ):
        old = pool.submit(run_task, identifier, tenant)
        try:
            assert staged.wait(10)
            session.refresh(marketplace)
            old_owner = marketplace.sync_owner
            expire(session, identifier)
            with get_session_with_tenant(tenant_id=tenant) as other:
                ownership.request_marketplace_sync(identifier, other)
                new_owner = ownership.claim_marketplace_sync(identifier, other)
                assert new_owner is not None and new_owner != old_owner
                assert old_owner is not None
                assert not ownership.renew_marketplace_sync(
                    identifier, old_owner, other
                )
                ownership.request_marketplace_sync(identifier, other)
            resume.set()
            old.result(10)
            session.refresh(marketplace)
            assert marketplace.last_synced_revision is None
            assert marketplace.sync_owner == new_owner and marketplace.sync_requested
            assert marketplace.last_error == ownership.SYNC_INTERRUPTED
        finally:
            resume.set()
    expire(session, identifier)
    github.revision = "b" * 40
    run_task(identifier, tenant)
    session.refresh(marketplace)
    assert marketplace.last_synced_revision == "b" * 40
    assert broker.call_count == 1


@pytest.mark.parametrize("failure", ["dispatch", "expired_queue", "crash", "exception"])
def test_recovery_preserves_requested_work(
    session: Session,
    marketplace: Marketplace,
    tenant: str,
    github: GitHub,
    broker: Mock,
    failure: str,
) -> None:
    identifier = marketplace.id
    if failure == "dispatch":
        broker.side_effect = RuntimeError("private transport body")
    tasks.enqueue_marketplace_sync(identifier, tenant_id=tenant)
    broker.side_effect = None
    if failure == "crash":
        with get_session_with_tenant(tenant_id=tenant) as other:
            assert ownership.claim_marketplace_sync(identifier, other)
    if failure == "exception":
        with patch.object(
            sync,
            "save_skill_bundle_bytes",
            side_effect=OnyxError(OnyxErrorCode.SERVICE_UNAVAILABLE, "secret body"),
        ):
            run_task(identifier, tenant)
        session.refresh(marketplace)
        assert marketplace.last_error == ownership.SYNC_FAILED
        assert marketplace.sync_requested
    expire(session, identifier)
    tasks.recover_marketplace_syncs.run(tenant_id=tenant)
    if failure == "crash":
        expire(session, identifier)
        tasks.recover_marketplace_syncs.run(tenant_id=tenant)
    assert broker.call_count == 2
    run_task(identifier, tenant)
    session.refresh(marketplace)
    assert marketplace.last_synced_revision == github.revision
    assert marketplace.last_error is None and not marketplace.sync_requested
    tasks.recover_marketplace_syncs.run(tenant_id=tenant)
    assert broker.call_count == 2  # Recovery never polls an idle source.


def test_bounded_repeat_yields_durably(
    session: Session,
    marketplace: Marketplace,
    tenant: str,
    github: GitHub,
    broker: Mock,
) -> None:
    identifier = marketplace.id
    tasks.enqueue_marketplace_sync(identifier, tenant_id=tenant)
    get = github.get

    def another_request(url: str, **kwargs: object) -> requests.Response:
        response = get(url, **kwargs)
        if "/commits/" in url:
            with get_session_with_tenant(tenant_id=tenant) as other:
                ownership.request_marketplace_sync(identifier, other)
        return response

    with patch("onyx.utils.github.ssrf_safe_get", side_effect=another_request):
        run_task(identifier, tenant)
        assert len(github.urls) == 3
    session.refresh(marketplace)
    assert marketplace.sync_requested and marketplace.sync_owner is None
    tasks.recover_marketplace_syncs.run(tenant_id=tenant)
    assert broker.call_count == 2
    run_task(identifier, tenant)
    session.refresh(marketplace)
    assert not marketplace.sync_requested


def test_explicit_tenant_isolation(
    session: Session,
    marketplace: Marketplace,
    tenant: str,
    other_tenant: str,
    github: GitHub,
    broker: Mock,
) -> None:
    identifier = marketplace.id
    with get_session_with_tenant(tenant_id=other_tenant) as other:
        other.add(
            Marketplace(
                id=identifier,
                name="Other",
                provider=marketplace.provider,
                provider_config=marketplace.provider_config,
            )
        )
        other.commit()
    tasks.enqueue_marketplace_sync(identifier, tenant_id=tenant)
    with ThreadPoolExecutor() as pool:
        pool.submit(run_task, identifier, tenant).result(10)
    session.refresh(marketplace)
    assert marketplace.last_synced_revision == github.revision
    with get_session_with_tenant(tenant_id=other_tenant) as other:
        row = other.get(Marketplace, identifier)
        assert row is not None and row.last_synced_revision is None
        assert not row.sync_requested and row.sync_owner is None
    assert CURRENT_TENANT_ID_CONTEXTVAR.get() == other_tenant
    kwargs = broker.call_args.kwargs
    assert kwargs["kwargs"]["tenant_id"] == tenant and kwargs["expires"] > 0


@pytest.mark.parametrize("login", ["missing", "inactive", "disconnected"])
def test_unavailable_login_and_unchanged_error_clear(
    session: Session,
    marketplace: Marketplace,
    tenant: str,
    github: GitHub,
    broker: Mock,
    login: str,
) -> None:
    identifier = marketplace.id
    tasks.enqueue_marketplace_sync(identifier, tenant_id=tenant)
    run_task(identifier, tenant)
    revision = github.revision
    urls = len(github.urls)
    if login == "missing":
        marketplace.login_user_id = None
        session.commit()
    if login != "missing":
        user = make_user(session)
        user.is_active = login != "inactive"
        session.add(ExternalApp(name="GitHub", app_type=ExternalAppType.GITHUB))
        marketplace.login_user_id = user.id
        session.commit()
    with patch(
        "onyx.skills.marketplace.provider.github_authorization_header",
        github_authorization_header,
    ):
        tasks.enqueue_marketplace_sync(identifier, tenant_id=tenant)
        run_task(identifier, tenant)
    session.refresh(marketplace)
    assert marketplace.sync_status == MarketplaceSyncStatus.FAILED
    assert "login" in (marketplace.last_error or "")
    assert len(github.urls) == urls and marketplace.last_synced_revision == revision
    assert not marketplace.sync_requested
    marketplace.login_user_id = make_user(session).id
    session.commit()
    tasks.enqueue_marketplace_sync(identifier, tenant_id=tenant)
    run_task(identifier, tenant)
    session.refresh(marketplace)
    assert marketplace.last_error is None
    assert marketplace.sync_status == MarketplaceSyncStatus.APPLIED
    assert broker.call_count == 3


def test_lite_dispatch_is_bounded_and_off_poller(
    session: Session,
    marketplace: Marketplace,
    tenant: str,
    github: GitHub,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tasks, "DISABLE_VECTOR_DB", True)
    entered, release = Event(), Event()
    original = tasks.sync_marketplace

    def blocked(
        identifier: UUID, tenant_id: str, *, request_work: bool = True
    ) -> ReconciliationResult | None:
        entered.set()
        assert release.wait(10)
        return original(identifier, tenant_id, request_work=request_work)

    futures: list[Future[None]] = []
    start = tasks.start_thread_future

    def capture(operation: Callable[[], None], *, name: str) -> Future[None]:
        future = start(operation, name=name)
        futures.append(future)
        return future

    with (
        patch.object(tasks, "sync_marketplace", blocked),
        patch.object(tasks, "start_thread_future", capture),
    ):
        try:
            tasks.enqueue_marketplace_sync(marketplace.id, tenant_id=tenant)
            assert entered.wait(10)  # Enqueue returned while I/O is still blocked.
        finally:
            release.set()
        for future in futures:
            future.result(10)
    session.refresh(marketplace)
    assert marketplace.last_synced_revision == github.revision
    slots = BoundedSemaphore(4)
    monkeypatch.setattr(tasks, "_LITE_SLOTS", slots)
    for _ in range(4):
        assert slots.acquire(blocking=False)
    try:
        tasks.enqueue_marketplace_sync(marketplace.id, tenant_id=tenant)
        session.refresh(marketplace)
        assert marketplace.sync_requested and len(futures) == 1
    finally:
        for _ in range(4):
            slots.release()


def test_recovery_wiring() -> None:
    from onyx.background import periodic_poller
    from onyx.background.celery.apps.heavy import celery_app as heavy
    from onyx.background.celery.apps.primary import celery_app as primary
    from onyx.background.celery.tasks.beat_schedule import (
        CLOUD_BEAT_MULTIPLIER_DEFAULT,
        beat_task_templates,
        get_cloud_tasks_to_schedule,
    )
    from onyx.configs.constants import OnyxCeleryQueues, OnyxCeleryTask

    for app in (heavy, primary):
        app.loader.import_default_modules()
        assert OnyxCeleryTask.SYNC_MARKETPLACE in app.tasks
        assert OnyxCeleryTask.RECOVER_MARKETPLACE_SYNCS in app.tasks
    template = next(
        t
        for t in beat_task_templates
        if t["task"] == OnyxCeleryTask.RECOVER_MARKETPLACE_SYNCS
    )
    cloud = next(
        t
        for t in get_cloud_tasks_to_schedule(CLOUD_BEAT_MULTIPLIER_DEFAULT)
        if t.get("kwargs", {}).get("task_name")
        == OnyxCeleryTask.RECOVER_MARKETPLACE_SYNCS
    )
    assert cloud["kwargs"]["work_gated"] is True
    assert cloud["kwargs"].get("skip_gated", True) is True
    assert cloud["kwargs"]["expires"] >= cloud["schedule"].total_seconds()
    assert template["options"]["queue"] == OnyxCeleryQueues.PRIMARY
    with (
        patch("onyx.background.task_utils.drain_processing_loop"),
        patch("onyx.background.task_utils.drain_delete_loop"),
        patch("onyx.background.task_utils.drain_project_sync_loop"),
        patch.object(tasks.recover_marketplace_syncs, "run") as recover,
    ):
        periodic_poller._run_drain_loops("public")
        recover.assert_called_once_with(tenant_id="public")
