"""Bounded recovery against PostgreSQL with controlled upstream and elapsed time."""

from unittest.mock import Mock, patch

import pytest
import requests
from sqlalchemy import func
from sqlalchemy.orm import Session

from onyx.background import periodic_poller
from onyx.background.celery.tasks.marketplace_sync import tasks
from onyx.db import marketplace_sync as ownership
from onyx.db.models import Marketplace
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.skills import sync
from onyx.skills.marketplace.models import (
    MARKETPLACE_LOGIN_ERROR,
    MarketplaceSyncStatus,
)
from tests.external_dependency_unit.db.test_marketplace_sync import GitHub
from tests.external_dependency_unit.db.test_marketplace_sync_tasks import (
    broker as broker,
)
from tests.external_dependency_unit.db.test_marketplace_sync_tasks import (
    expire,
    run_task,
)
from tests.external_dependency_unit.db.test_marketplace_sync_tasks import (
    github as github,
)
from tests.external_dependency_unit.db.test_marketplace_sync_tasks import (
    marketplace as marketplace,
)
from tests.external_dependency_unit.db.test_marketplace_sync_tasks import (
    session as session,
)
from tests.external_dependency_unit.db.test_marketplace_sync_tasks import (
    tenant as tenant,
)


@pytest.mark.parametrize(
    "code", [OnyxErrorCode.NOT_FOUND, OnyxErrorCode.UNAUTHENTICATED]
)
def test_permanent_error_waits_for_explicit_retry(
    session: Session,
    marketplace: Marketplace,
    tenant: str,
    github: GitHub,
    broker: Mock,
    code: OnyxErrorCode,
) -> None:
    tasks.enqueue_marketplace_sync(marketplace.id, tenant_id=tenant)
    with patch.object(sync, "_sync_marketplace", side_effect=OnyxError(code)) as fetch:
        run_task(marketplace.id, tenant)
        for _ in range(5):
            expire(session, marketplace.id)
            tasks.recover_marketplace_syncs.run(tenant_id=tenant)
            run_task(marketplace.id, tenant)
        assert fetch.call_count == 1
    session.refresh(marketplace)
    assert marketplace.sync_status == MarketplaceSyncStatus.FAILED
    assert not marketplace.sync_requested and broker.call_count == 1
    tasks.enqueue_marketplace_sync(marketplace.id, tenant_id=tenant)
    run_task(marketplace.id, tenant)
    session.refresh(marketplace)
    assert marketplace.last_synced_revision == github.revision


@pytest.mark.usefixtures("github")
def test_temporary_failures_back_off_then_stop(
    session: Session,
    marketplace: Marketplace,
    tenant: str,
    broker: Mock,
) -> None:
    tasks.enqueue_marketplace_sync(marketplace.id, tenant_id=tenant)
    with patch.object(
        sync, "_sync_marketplace", side_effect=OnyxError(OnyxErrorCode.GATEWAY_TIMEOUT)
    ) as fetch:
        for attempt in range(1, ownership.MAX_ATTEMPTS + 1):
            run_task(marketplace.id, tenant)
            session.refresh(marketplace)
            assert marketplace.sync_attempts == attempt
            if attempt < ownership.MAX_ATTEMPTS:
                now = session.query(func.clock_timestamp()).scalar()
                assert now is not None and marketplace.sync_retry_after is not None
                remaining = (marketplace.sync_retry_after - now).total_seconds()
                assert (
                    60 * 2 ** (attempt - 1) - 5 < remaining <= 60 * 2 ** (attempt - 1)
                )
            tasks.recover_marketplace_syncs.run(tenant_id=tenant)
            run_task(marketplace.id, tenant)  # A duplicate cannot bypass backoff.
            assert fetch.call_count == attempt
            expire(session, marketplace.id)
            tasks.recover_marketplace_syncs.run(tenant_id=tenant)
        assert broker.call_count == ownership.MAX_ATTEMPTS
    session.refresh(marketplace)
    assert marketplace.sync_status == MarketplaceSyncStatus.FAILED
    assert not marketplace.sync_requested and marketplace.sync_owner is None


def test_explicit_request_bypasses_backoff(
    session: Session,
    marketplace: Marketplace,
    tenant: str,
    github: GitHub,
    broker: Mock,
) -> None:
    tasks.enqueue_marketplace_sync(marketplace.id, tenant_id=tenant)
    with patch.object(
        sync, "_sync_marketplace", side_effect=OnyxError(OnyxErrorCode.BAD_GATEWAY)
    ):
        run_task(marketplace.id, tenant)
    tasks.enqueue_marketplace_sync(marketplace.id, tenant_id=tenant)
    assert broker.call_count == 2
    run_task(marketplace.id, tenant)
    session.refresh(marketplace)
    assert marketplace.sync_attempts == 1 and marketplace.last_error is None
    assert marketplace.last_synced_revision == github.revision


@pytest.mark.parametrize("changed", [True, False])
def test_deleted_login_error_survives_running_sync(
    session: Session,
    marketplace: Marketplace,
    tenant: str,
    github: GitHub,
    broker: Mock,
    changed: bool,
) -> None:
    sync.sync_marketplace(marketplace.id, tenant)
    if changed:
        github.revision = "b" * 40
    get = github.get

    def delete_login(url: str, **kwargs: object) -> requests.Response:
        marketplace.login_user_id = None
        marketplace.last_error = MARKETPLACE_LOGIN_ERROR
        session.commit()
        return get(url, **kwargs)

    tasks.enqueue_marketplace_sync(marketplace.id, tenant_id=tenant)
    with patch("onyx.utils.github.ssrf_safe_get", delete_login):
        run_task(marketplace.id, tenant)
    session.refresh(marketplace)
    assert marketplace.sync_status == MarketplaceSyncStatus.FAILED
    assert marketplace.last_error == MARKETPLACE_LOGIN_ERROR
    assert marketplace.last_synced_revision == "a" * 40
    assert not marketplace.sync_requested
    assert broker.call_count == 1


def test_heartbeat_silence_does_not_undo_committed_success(
    session: Session,
    marketplace: Marketplace,
    tenant: str,
    github: GitHub,
    broker: Mock,
) -> None:
    tasks.enqueue_marketplace_sync(marketplace.id, tenant_id=tenant)
    with patch.object(sync.LeaseHeartbeat, "is_lost", return_value=True):
        run_task(marketplace.id, tenant)
    session.refresh(marketplace)
    assert marketplace.sync_status == MarketplaceSyncStatus.APPLIED
    assert marketplace.last_synced_revision == github.revision
    assert marketplace.sync_owner is None
    assert broker.call_args.kwargs["expires"] >= 15 * 60


def test_lite_recovery_failure_does_not_skip_file_drains() -> None:
    with (
        patch.object(
            tasks.recover_marketplace_syncs,
            "run",
            side_effect=RuntimeError("DB unavailable"),
        ),
        patch("onyx.background.task_utils.drain_processing_loop") as process,
        patch("onyx.background.task_utils.drain_delete_loop") as delete,
        patch("onyx.background.task_utils.drain_project_sync_loop") as projects,
    ):
        periodic_poller._run_drain_loops("public")
    for drain in (process, delete, projects):
        drain.assert_called_once_with("public")


@pytest.mark.usefixtures("github", "broker")
def test_activity_marks_only_requested_or_recovering_work(
    session: Session,
    marketplace: Marketplace,
    tenant: str,
) -> None:
    with (
        patch.object(tasks, "maybe_mark_tenant_active") as dispatch_mark,
        patch.object(sync, "maybe_mark_tenant_active") as worker_mark,
    ):
        tasks.recover_marketplace_syncs.run(tenant_id=tenant)
        dispatch_mark.assert_not_called()
        tasks.enqueue_marketplace_sync(marketplace.id, tenant_id=tenant)
        dispatch_mark.assert_called_with(tenant, caller="marketplace_sync")
        worker_mark.assert_not_called()
        dispatch_mark.reset_mock()
        with patch.object(
            sync, "_sync_marketplace", side_effect=OnyxError(OnyxErrorCode.BAD_GATEWAY)
        ):
            run_task(marketplace.id, tenant)
        assert worker_mark.call_count == 2  # Claim and committed retry scheduling.
        worker_mark.assert_called_with(tenant, caller="marketplace_sync")
        session.refresh(marketplace)
        assert marketplace.sync_requested and marketplace.sync_retry_after is not None
        expire(session, marketplace.id)
        tasks.recover_marketplace_syncs.run(tenant_id=tenant)
        dispatch_mark.assert_called_once_with(tenant, caller="marketplace_sync")
        run_task(marketplace.id, tenant)
        dispatch_mark.reset_mock()
        worker_mark.reset_mock()
        tasks.recover_marketplace_syncs.run(tenant_id=tenant)
        run_task(marketplace.id, tenant)
        dispatch_mark.assert_not_called()
        worker_mark.assert_not_called()


@pytest.mark.usefixtures("github")
def test_reaping_marks_tenant_without_sending_before_backoff(
    session: Session,
    marketplace: Marketplace,
    tenant: str,
    broker: Mock,
) -> None:
    tasks.enqueue_marketplace_sync(marketplace.id, tenant_id=tenant)
    assert ownership.claim_marketplace_sync(marketplace.id, session) is not None
    session.refresh(marketplace)
    assert marketplace.sync_dispatch_after is None
    expire(session, marketplace.id)
    with patch.object(tasks, "maybe_mark_tenant_active") as mark:
        tasks.recover_marketplace_syncs.run(tenant_id=tenant)
        mark.assert_called_once_with(tenant, caller="marketplace_sync")
    session.refresh(marketplace)
    assert marketplace.sync_requested and marketplace.sync_retry_after is not None
    assert broker.call_count == 1
