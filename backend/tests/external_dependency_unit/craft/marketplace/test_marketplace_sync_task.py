from typing import Any
from unittest.mock import patch

from sqlalchemy.orm import Session

from onyx.background.celery.tasks.marketplace_sync.tasks import sync_marketplace_task
from onyx.cache.factory import get_cache_backend
from onyx.db.models import User
from onyx.skills.marketplace import sync
from onyx.skills.marketplace.models import MarketplaceSyncResult
from tests.external_dependency_unit.craft.fake_github import FakeGitHub
from tests.external_dependency_unit.craft.marketplace.helpers import (
    OWNER,
    REPO,
    Connections,
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

    # A sync asked for while another holds the lock only sets the mark.
    lock = get_cache_backend().lock(f"marketplace_sync:{marketplace.id}", timeout=60)
    assert lock.acquire(blocking=False)
    try:
        sync.run_marketplace_sync(marketplace.id)
    finally:
        lock.release()
    assert reload(db_session, marketplace).sync_requested_at is not None
    assert synced_plugins(db_session, marketplace.id) == {}

    # While the holder runs, a push and a new request land. The holder goes
    # again and syncs the second commit.
    real_sync = sync.sync_marketplace
    runs = 0

    def sync_with_push_during_first_run(marketplace_id: Any) -> MarketplaceSyncResult:
        nonlocal runs
        runs += 1
        result = real_sync(marketplace_id)
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
