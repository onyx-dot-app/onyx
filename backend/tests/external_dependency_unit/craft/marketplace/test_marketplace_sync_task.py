from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from onyx.background.celery.tasks.marketplace_sync.tasks import sync_marketplace_task
from onyx.background.celery.versioned_apps.client import app as celery_app
from onyx.cache.factory import get_cache_backend
from onyx.cache.interface import CacheLock
from onyx.configs.constants import OnyxCeleryTask
from onyx.db.models import User
from onyx.server.features.skill import marketplace_api as api
from onyx.skills.marketplace import sync
from onyx.skills.marketplace.models import MarketplaceSyncResult
from tests.external_dependency_unit.craft.fake_github import FakeGitHub
from tests.external_dependency_unit.craft.marketplace.helpers import (
    OWNER,
    REPO,
    Connections,
    existing_files,
    make_marketplace,
    plugin_files,
    reload,
    synced_plugins,
)


def test_busy_lock_sets_the_mark_and_the_holder_syncs_again(
    db_session: Session,
    users: tuple[User, User, User],
    fake_github: FakeGitHub,
    connections: Connections,  # noqa: ARG001
    marketplace_ids: list[Any],
) -> None:
    owner = users[0]
    fake_github.push(OWNER, REPO, plugin_files("alpha"))
    marketplace = make_marketplace(
        db_session, marketplace_ids, login=owner, owner=owner
    )

    lock = get_cache_backend().lock(f"marketplace_sync:{marketplace.id}", timeout=60)
    assert lock.acquire(blocking=False)
    try:
        sync.run_marketplace_sync(marketplace.id)
    finally:
        lock.release()
    assert reload(db_session, marketplace).sync_requested_at is not None
    assert synced_plugins(db_session, marketplace.id) == {}

    real_sync = sync.sync_marketplace
    runs = 0

    def sync_with_push_during_first_run(
        marketplace_id: Any, lock: CacheLock | None = None
    ) -> MarketplaceSyncResult:
        nonlocal runs
        runs += 1
        result = real_sync(marketplace_id, lock)
        if runs == 1:
            fake_github.push(OWNER, REPO, plugin_files("alpha", "beta"))
            sync.run_marketplace_sync(marketplace_id)
        return result

    with patch.object(sync, "sync_marketplace", sync_with_push_during_first_run):
        task_kwargs = {"marketplace_id": str(marketplace.id), "tenant_id": "public"}
        sync_marketplace_task.run(**task_kwargs)
    assert runs == 2
    assert set(synced_plugins(db_session, marketplace.id)) == {"alpha", "beta"}
    assert reload(db_session, marketplace).sync_requested_at is None


def test_request_stays_live_while_the_sync_runs(
    db_session: Session,
    users: tuple[User, User, User],
    fake_github: FakeGitHub,
    connections: Connections,  # noqa: ARG001
    marketplace_ids: list[Any],
) -> None:
    owner = users[0]
    fake_github.push(OWNER, REPO, plugin_files("alpha"))
    marketplace = make_marketplace(
        db_session, marketplace_ids, login=owner, owner=owner
    )
    marketplace.sync_requested_at = datetime.now(timezone.utc)
    db_session.commit()

    real_sync = sync.sync_marketplace
    live_during_run: list[bool] = []

    def recording_sync(
        marketplace_id: Any, lock: CacheLock | None = None
    ) -> MarketplaceSyncResult:
        live_during_run.append(
            sync.sync_request_is_live(reload(db_session, marketplace).sync_requested_at)
        )
        return real_sync(marketplace_id, lock)

    with patch.object(sync, "sync_marketplace", recording_sync):
        sync.run_marketplace_sync(marketplace.id)
    assert live_during_run == [True]
    assert reload(db_session, marketplace).sync_requested_at is None


def test_sync_that_lost_its_lock_writes_nothing(
    db_session: Session,
    users: tuple[User, User, User],
    fake_github: FakeGitHub,
    connections: Connections,  # noqa: ARG001
    marketplace_ids: list[Any],
    staged_file_ids: list[str],
) -> None:
    owner = users[0]
    fake_github.push(OWNER, REPO, plugin_files("alpha"))
    marketplace = make_marketplace(
        db_session, marketplace_ids, login=owner, owner=owner
    )
    expired = get_cache_backend().lock(f"marketplace_sync:{marketplace.id}", timeout=60)

    sync.sync_marketplace(marketplace.id, expired)

    assert synced_plugins(db_session, marketplace.id) == {}
    assert reload(db_session, marketplace).last_synced_at is None
    assert staged_file_ids
    assert existing_files(db_session, staged_file_ids) == set()


def test_deleted_marketplace_ends_the_task(
    db_session: Session,
    users: tuple[User, User, User],
    fake_github: FakeGitHub,  # noqa: ARG001
    connections: Connections,  # noqa: ARG001
    marketplace_ids: list[Any],
) -> None:
    owner = users[0]
    marketplace = make_marketplace(
        db_session, marketplace_ids, login=owner, owner=owner
    )
    marketplace_id = marketplace.id
    db_session.delete(marketplace)
    db_session.commit()
    sync.run_marketplace_sync(marketplace_id)
    lock = get_cache_backend().lock(f"marketplace_sync:{marketplace_id}", timeout=60)
    assert lock.acquire(blocking=False)
    lock.release()


@pytest.fixture
def send_task() -> Iterator[MagicMock]:
    with (
        patch.object(sync, "DISABLE_VECTOR_DB", False),
        patch.object(celery_app, "send_task") as sent,
    ):
        yield sent


def _sent_marketplace_ids(send_task: MagicMock) -> list[str]:
    assert all(
        call.args == (OnyxCeleryTask.SYNC_MARKETPLACE,)
        for call in send_task.call_args_list
    )
    return [
        call.kwargs["kwargs"]["marketplace_id"] for call in send_task.call_args_list
    ]


def test_time_budget_exit_with_a_new_request_starts_a_follow_up(
    db_session: Session,
    users: tuple[User, User, User],
    fake_github: FakeGitHub,
    connections: Connections,  # noqa: ARG001
    marketplace_ids: list[Any],
    send_task: MagicMock,
) -> None:
    owner = users[0]
    fake_github.push(OWNER, REPO, plugin_files("alpha"))
    marketplace = make_marketplace(
        db_session, marketplace_ids, login=owner, owner=owner
    )
    real_sync = sync.sync_marketplace

    def sync_with_new_request(
        marketplace_id: Any, lock: CacheLock | None = None
    ) -> MarketplaceSyncResult:
        result = real_sync(marketplace_id, lock)
        sync.run_marketplace_sync(marketplace_id)
        return result

    with (
        patch.object(sync, "SYNC_TIME_BUDGET_SECONDS", -1),
        patch.object(sync, "sync_marketplace", sync_with_new_request),
    ):
        sync.run_marketplace_sync(marketplace.id)

    assert reload(db_session, marketplace).sync_requested_at is not None
    assert _sent_marketplace_ids(send_task) == [str(marketplace.id)]
    lock = get_cache_backend().lock(f"marketplace_sync:{marketplace.id}", timeout=60)
    assert lock.acquire(blocking=False)
    lock.release()


def test_failed_sync_with_a_new_request_starts_one_follow_up(
    db_session: Session,
    users: tuple[User, User, User],
    fake_github: FakeGitHub,  # noqa: ARG001
    connections: Connections,  # noqa: ARG001
    marketplace_ids: list[Any],
    send_task: MagicMock,
) -> None:
    owner = users[0]
    marketplace = make_marketplace(
        db_session, marketplace_ids, login=owner, owner=owner
    )

    def failing_sync_with_new_request(
        marketplace_id: Any,
        _lock: CacheLock | None = None,
    ) -> MarketplaceSyncResult:
        sync.run_marketplace_sync(marketplace_id)
        raise RuntimeError("boom")

    with (
        patch.object(sync, "sync_marketplace", failing_sync_with_new_request),
        pytest.raises(RuntimeError),
    ):
        sync.run_marketplace_sync(marketplace.id)
    assert reload(db_session, marketplace).last_error == sync.SYNC_FAILED_ERROR
    assert _sent_marketplace_ids(send_task) == [str(marketplace.id)]

    def failing_sync(
        _marketplace_id: Any, _lock: CacheLock | None = None
    ) -> MarketplaceSyncResult:
        raise RuntimeError("boom")

    with (
        patch.object(sync, "sync_marketplace", failing_sync),
        pytest.raises(RuntimeError),
    ):
        sync.run_marketplace_sync(marketplace.id)
    assert reload(db_session, marketplace).sync_requested_at is None
    assert len(send_task.call_args_list) == 1


def test_stale_sync_request_is_not_reported_as_syncing(
    db_session: Session,
    users: tuple[User, User, User],
    marketplace_ids: list[Any],
) -> None:
    owner = users[0]
    marketplace = make_marketplace(
        db_session, marketplace_ids, login=owner, owner=owner
    )

    def sync_requested(requested_at: datetime) -> bool:
        row = reload(db_session, marketplace)
        row.sync_requested_at = requested_at
        db_session.commit()
        return api.get_marketplace(marketplace.id, owner, db_session).sync_requested

    now = datetime.now(timezone.utc)
    assert sync_requested(now - timedelta(minutes=1))
    stale_age = timedelta(seconds=sync.SYNC_LOCK_TIMEOUT_SECONDS + 10 * 60)
    assert not sync_requested(now - stale_age)


def test_first_sync_that_died_is_reported_as_failed(
    db_session: Session,
    users: tuple[User, User, User],
    marketplace_ids: list[Any],
) -> None:
    owner = users[0]
    marketplace = make_marketplace(
        db_session, marketplace_ids, login=owner, owner=owner
    )

    def summary(created_at: datetime) -> tuple[bool, str | None]:
        row = reload(db_session, marketplace)
        row.created_at = created_at
        row.last_synced_at = None
        row.last_error = None
        row.sync_requested_at = None
        db_session.commit()
        view = api.get_marketplace(marketplace.id, owner, db_session)
        return view.sync_requested, view.last_error

    now = datetime.now(timezone.utc)
    assert summary(now - timedelta(minutes=1)) == (False, None)
    stale_age = timedelta(seconds=sync.SYNC_LOCK_TIMEOUT_SECONDS + 10 * 60)
    assert summary(now - stale_age) == (False, sync.SYNC_FAILED_ERROR)
