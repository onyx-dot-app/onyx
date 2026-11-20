from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi import BackgroundTasks
from sqlalchemy.orm import Session

from onyx.background.celery.tasks.marketplace_sync.tasks import sync_marketplace_task
from onyx.background.celery.versioned_apps.client import app as celery_app
from onyx.cache.factory import get_cache_backend
from onyx.cache.interface import CacheLock
from onyx.configs.constants import OnyxCeleryTask
from onyx.db.models import User
from onyx.server.features.skill import marketplace_api as api
from onyx.skills.marketplace import sync
from onyx.skills.marketplace.models import MarketplaceSyncResult, MarketplaceSyncStatus
from tests.external_dependency_unit.craft.fake_github import FakeGitHub
from tests.external_dependency_unit.craft.marketplace.helpers import (
    OWNER,
    REPO,
    Connections,
    existing_files,
    http_request,
    make_marketplace,
    plugin_files,
    reload,
    synced_plugins,
)


def _hold_lock(marketplace_id: Any) -> CacheLock:
    lock = get_cache_backend().lock(f"marketplace_sync:{marketplace_id}", timeout=60)
    assert lock.acquire(blocking=False)
    return lock


@pytest.fixture
def send_task() -> Iterator[MagicMock]:
    with (
        patch.object(sync, "DISABLE_VECTOR_DB", False),
        patch.object(celery_app, "send_task") as sent,
    ):
        yield sent


def test_sync_now_during_a_sync_does_nothing(
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

    lock = _hold_lock(marketplace.id)
    try:
        sync.run_marketplace_sync(marketplace.id)
    finally:
        lock.release()
    assert synced_plugins(db_session, marketplace.id) == {}

    real_sync = sync.sync_marketplace
    during: list[bool] = []

    def sync_and_click_sync_now(
        marketplace_id: Any, lock: CacheLock | None = None
    ) -> MarketplaceSyncResult:
        result = real_sync(marketplace_id, lock)
        if not during:
            # A newer commit lands, and the user clicks Sync now.
            fake_github.push(OWNER, REPO, plugin_files("alpha", "beta"))
            view = api.sync_marketplace_now(
                http_request(), marketplace_id, BackgroundTasks(), owner, db_session
            )
            during.append(view.syncing)
        return result

    with patch.object(sync, "sync_marketplace", sync_and_click_sync_now):
        task_kwargs = {"marketplace_id": str(marketplace.id), "tenant_id": "public"}
        sync_marketplace_task.run(**task_kwargs)
    assert during == [True]
    assert send_task.call_args_list == []
    assert set(synced_plugins(db_session, marketplace.id)) == {"alpha"}
    assert not api.get_marketplace(
        http_request(), marketplace.id, owner, db_session
    ).syncing


def test_syncing_flag_lives_as_long_as_the_lock_lease(
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
    cache = get_cache_backend()
    ttls: list[int] = []

    def sync_and_read_ttl(
        marketplace_id: Any, _lock: CacheLock | None = None
    ) -> MarketplaceSyncResult:
        ttls.append(cache.ttl(f"marketplace_syncing:{marketplace_id}"))
        return MarketplaceSyncResult(status=MarketplaceSyncStatus.APPLIED)

    with patch.object(sync, "sync_marketplace", sync_and_read_ttl):
        sync.run_marketplace_sync(marketplace.id)
    assert len(ttls) == 1
    # A dead worker leaves the flag for minutes, not for the whole sync limit.
    assert 0 < ttls[0] <= 5 * 60


def test_sync_now_sends_one_task_until_it_runs(
    db_session: Session,
    users: tuple[User, User, User],
    marketplace_ids: list[Any],
    send_task: MagicMock,
) -> None:
    owner = users[0]
    marketplace = make_marketplace(
        db_session, marketplace_ids, login=owner, owner=owner
    )
    for _ in range(2):
        view = api.sync_marketplace_now(
            http_request(), marketplace.id, BackgroundTasks(), owner, db_session
        )
        assert view.syncing
    assert [call.args for call in send_task.call_args_list] == [
        (OnyxCeleryTask.SYNC_MARKETPLACE,)
    ]
    assert send_task.call_args.kwargs["kwargs"]["marketplace_id"] == str(marketplace.id)


def test_sync_now_after_a_failed_send_sends_again(
    db_session: Session,
    users: tuple[User, User, User],
    marketplace_ids: list[Any],
    send_task: MagicMock,
) -> None:
    owner = users[0]
    marketplace = make_marketplace(
        db_session, marketplace_ids, login=owner, owner=owner
    )
    send_task.side_effect = ConnectionError("broker down")
    with pytest.raises(ConnectionError):
        api.sync_marketplace_now(
            http_request(), marketplace.id, BackgroundTasks(), owner, db_session
        )
    assert not api.get_marketplace(
        http_request(), marketplace.id, owner, db_session
    ).syncing

    send_task.side_effect = None
    view = api.sync_marketplace_now(
        http_request(), marketplace.id, BackgroundTasks(), owner, db_session
    )
    assert view.syncing
    assert send_task.call_count == 2


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
    assert existing_files(db_session, staged_file_ids) == set()


def test_a_running_sync_extends_its_lock_between_steps(
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
    lock = _hold_lock(marketplace.id)
    try:
        with patch.object(lock, "extend", wraps=lock.extend) as extend:
            sync.sync_marketplace(marketplace.id, lock)
    finally:
        lock.release()
    assert set(synced_plugins(db_session, marketplace.id)) == {"alpha"}
    assert extend.call_count >= 3
    assert {call.args for call in extend.call_args_list} == {
        (sync.SYNC_LOCK_TIMEOUT_SECONDS,)
    }


def test_a_sync_that_lost_its_lock_keeps_the_newer_syncing_key(
    db_session: Session,
    users: tuple[User, User, User],
    marketplace_ids: list[Any],
) -> None:
    owner = users[0]
    marketplace = make_marketplace(
        db_session, marketplace_ids, login=owner, owner=owner
    )
    newer: list[CacheLock] = []

    def lose_the_lock(marketplace_id: Any, lock: CacheLock | None = None) -> None:
        assert lock is not None
        lock.release()
        newer.append(_hold_lock(marketplace_id))
        get_cache_backend().set(f"marketplace_syncing:{marketplace_id}", b"1", ex=60)

    with patch.object(sync, "sync_marketplace", lose_the_lock):
        sync.run_marketplace_sync(marketplace.id)
    try:
        assert sync.marketplace_syncing(marketplace.id)
        assert newer[0].owned()
    finally:
        newer[0].release()
        get_cache_backend().delete(f"marketplace_syncing:{marketplace.id}")


def test_a_failed_renewal_after_staging_deletes_the_staged_files(
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
    lock = _hold_lock(marketplace.id)

    def extend(_ttl: float) -> None:
        if staged_file_ids:
            raise ConnectionError("cache down")

    try:
        with (
            patch.object(lock, "extend", side_effect=extend),
            pytest.raises(ConnectionError),
        ):
            sync.sync_marketplace(marketplace.id, lock)
    finally:
        lock.release()
    assert staged_file_ids
    assert existing_files(db_session, staged_file_ids) == set()
    assert synced_plugins(db_session, marketplace.id) == {}


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
    _hold_lock(marketplace_id).release()


def test_failed_sync_records_the_error_and_frees_the_lock(
    db_session: Session,
    users: tuple[User, User, User],
    marketplace_ids: list[Any],
) -> None:
    owner = users[0]
    marketplace = make_marketplace(
        db_session, marketplace_ids, login=owner, owner=owner
    )

    def failing_sync(_marketplace_id: Any, _lock: CacheLock | None = None) -> None:
        raise RuntimeError("boom")

    with (
        patch.object(sync, "sync_marketplace", failing_sync),
        pytest.raises(RuntimeError),
    ):
        sync.run_marketplace_sync(marketplace.id)
    assert reload(db_session, marketplace).last_error == sync.SYNC_FAILED_ERROR
    _hold_lock(marketplace.id).release()
