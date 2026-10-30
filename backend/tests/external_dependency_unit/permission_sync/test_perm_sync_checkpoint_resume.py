"""A checkpointed doc sync that failed or was canceled mid-crawl must hand its
progress to the next attempt, also past attempts canceled while queued: the
next attempt continues after the last saved element instead of restarting the
crawl, keeps the stopped attempt's window, and on success marks the cc_pair
synced as of that window and drops the checkpoints. A failed element write, a
requested full refresh, or a connector config change keeps the crawl from
skipping elements."""

from collections.abc import Callable, Generator
from datetime import datetime, timezone
from enum import Enum
from functools import partial
from typing import cast
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from ee.onyx.background.celery.tasks.doc_permission_syncing import (
    checkpointer as checkpointer_module,
)
from ee.onyx.background.celery.tasks.doc_permission_syncing import tasks as perm_tasks
from ee.onyx.external_permissions.perm_sync_types import (
    DocSyncCheckpointer,
    FetchAllDocumentsFunction,
    FetchAllDocumentsIdsFunction,
)
from ee.onyx.external_permissions.sync_params import DocSyncConfig, SyncConfig
from onyx.access.models import DocExternalAccess, ElementExternalAccess, ExternalAccess
from onyx.configs.constants import DocumentSource
from onyx.connectors.models import ConnectorCheckpoint
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import AccessType, PermissionSyncStatus
from onyx.db.models import ConnectorCredentialPair, DocPermissionSyncAttempt
from onyx.db.permission_sync_attempt import (
    cancel_open_doc_permission_sync_attempt,
    get_open_doc_permission_sync_attempt,
    try_create_doc_permission_sync_attempt,
)
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from shared_configs.configs import (
    POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE as TEST_TENANT_ID,
)
from tests.external_dependency_unit.permission_sync.conftest import (
    create_test_connector_credential_pair,
)

_NUM_ELEMENTS = 10
_STOP_AFTER = 4
_FIRST_WINDOW_END = datetime(2026, 1, 2, tzinfo=timezone.utc)
_CANCEL_REASON = "Canceled: the connector was paused"


class _FakeCrawlCheckpoint(ConnectorCheckpoint):
    next_index: int = 0


class _FakeCheckpointedCrawl:
    """Crawls elements 0.._NUM_ELEMENTS-1, saving after each one. The first run
    stops after _STOP_AFTER elements, as a stop signal or stall would, after
    calling ``before_stop``."""

    def __init__(self, before_stop: Callable[[], None] | None = None) -> None:
        self.crawled_by_run: list[list[int]] = []
        self._before_stop = before_stop

    def __call__(
        self,
        cc_pair: ConnectorCredentialPair,  # noqa: ARG002
        fetch_all_existing_docs_fn: FetchAllDocumentsFunction,  # noqa: ARG002
        fetch_all_existing_docs_ids_fn: FetchAllDocumentsIdsFunction,  # noqa: ARG002
        callback: IndexingHeartbeatInterface | None,  # noqa: ARG002
        checkpointer: DocSyncCheckpointer,
    ) -> Generator[ElementExternalAccess, None, None]:
        resume = checkpointer.resume
        checkpoint = (
            _FakeCrawlCheckpoint.model_validate_json(resume.checkpoint_json)
            if resume
            else _FakeCrawlCheckpoint(has_more=True)
        )
        window_end = resume.poll_range_end if resume else _FIRST_WINDOW_END
        crawled: list[int] = []
        self.crawled_by_run.append(crawled)

        for index in range(checkpoint.next_index, _NUM_ELEMENTS):
            if not resume and len(crawled) == _STOP_AFTER:
                if self._before_stop is not None:
                    self._before_stop()
                raise RuntimeError("gdrive_doc_sync: Stop signal detected")
            crawled.append(index)
            yield DocExternalAccess(
                doc_id=f"doc-{index}", external_access=ExternalAccess.empty()
            )
            checkpoint.next_index = index + 1
            checkpointer.save(checkpoint, None, window_end)


def _run(
    cc_pair_id: int,
    crawl: _FakeCheckpointedCrawl,
    failing_doc_ids: frozenset[str] = frozenset(),
) -> None:
    def write(
        new_permissions: list[ElementExternalAccess], **_: object
    ) -> perm_tasks.PermissionSyncResult:
        # The fake crawl yields only documents
        failed = sum(
            cast(DocExternalAccess, element).doc_id in failing_doc_ids
            for element in new_permissions
        )
        return perm_tasks.PermissionSyncResult(
            num_updated=len(new_permissions) - failed, num_errors=failed
        )

    sync_config = SyncConfig(
        doc_sync_config=DocSyncConfig(
            doc_sync_frequency=1,
            initial_index_should_sync=False,
            checkpointed_doc_sync_func=crawl,
        )
    )
    with (
        patch.object(checkpointer_module, "CHECKPOINT_SAVE_INTERVAL_SECONDS", 0),
        patch.object(perm_tasks, "validate_ccpair_for_user", return_value=True),
        patch.object(
            perm_tasks, "get_source_perm_sync_config", return_value=sync_config
        ),
        patch.object(
            perm_tasks,
            "update_element_permissions_batch",
            side_effect=write,
        ),
    ):
        with get_session_with_current_tenant() as db_session:
            attempt = get_open_doc_permission_sync_attempt(cc_pair_id, db_session)
            assert attempt is not None
            attempt_id = attempt.id
        perm_tasks.connector_permission_sync_generator_task.apply(
            args=(cc_pair_id,),
            kwargs={"tenant_id": TEST_TENANT_ID, "attempt_id": attempt_id},
        ).get()


def _dispatch(cc_pair_id: int, db_session: Session) -> int:
    attempt_id = try_create_doc_permission_sync_attempt(
        cc_pair_id, f"task-{uuid4().hex[:8]}", db_session
    )
    assert attempt_id is not None
    return attempt_id


def _cancel_open_attempt(cc_pair_id: int) -> None:
    with get_session_with_current_tenant() as db_session:
        cancel_open_doc_permission_sync_attempt(
            cc_pair_id, db_session, reason=_CANCEL_REASON
        )


class _ChainStop(str, Enum):
    """How the attempts before the resuming one ended."""

    FAILED = "failed"
    # A pause cancels the running attempt before its crawl sees the stop signal
    CANCELED_MID_CRAWL = "canceled_mid_crawl"
    FAILED_THEN_CANCELED_WHILE_QUEUED = "failed_then_canceled_while_queued"


@pytest.mark.parametrize("chain_stop", list(_ChainStop))
def test_stopped_sync_resumes_from_checkpoint(
    tenant_context: None,  # noqa: ARG001
    db_session: Session,
    chain_stop: _ChainStop,
) -> None:
    cc_pair = create_test_connector_credential_pair(
        db_session, source=DocumentSource.GOOGLE_DRIVE, access_type=AccessType.SYNC
    )
    canceled_mid_crawl = chain_stop == _ChainStop.CANCELED_MID_CRAWL
    crawl = _FakeCheckpointedCrawl(
        before_stop=(
            partial(_cancel_open_attempt, cc_pair.id) if canceled_mid_crawl else None
        )
    )

    stopped_attempt_id = _dispatch(cc_pair.id, db_session)
    with pytest.raises(RuntimeError, match="Stop signal detected"):
        _run(cc_pair.id, crawl)

    db_session.expire_all()
    stopped = db_session.get(DocPermissionSyncAttempt, stopped_attempt_id)
    assert stopped is not None
    # The task keeps a cancel that came before its own failure
    assert stopped.status == (
        PermissionSyncStatus.CANCELED
        if canceled_mid_crawl
        else PermissionSyncStatus.FAILED
    )
    assert checkpointer_module.has_doc_sync_checkpoint(cc_pair.id)

    if chain_stop == _ChainStop.FAILED_THEN_CANCELED_WHILE_QUEUED:
        _dispatch(cc_pair.id, db_session)
        cancel_open_doc_permission_sync_attempt(
            cc_pair.id, db_session, reason=_CANCEL_REASON
        )

    resumed_attempt_id = _dispatch(cc_pair.id, db_session)
    _run(cc_pair.id, crawl)

    # The next run picks up after the last saved element, not at element 0
    assert crawl.crawled_by_run == [
        list(range(_STOP_AFTER)),
        list(range(_STOP_AFTER, _NUM_ELEMENTS)),
    ]

    db_session.expire_all()
    resumed = db_session.get(DocPermissionSyncAttempt, resumed_attempt_id)
    assert resumed is not None
    assert resumed.status == PermissionSyncStatus.SUCCESS
    # Changes after the chain's window are left for the next incremental sync
    db_session.refresh(cc_pair)
    assert cc_pair.last_time_perm_sync == _FIRST_WINDOW_END
    assert not checkpointer_module.has_doc_sync_checkpoint(cc_pair.id)


def test_failed_write_is_retried_on_resume(
    tenant_context: None,  # noqa: ARG001
    db_session: Session,
) -> None:
    cc_pair = create_test_connector_credential_pair(
        db_session, source=DocumentSource.GOOGLE_DRIVE, access_type=AccessType.SYNC
    )
    crawl = _FakeCheckpointedCrawl()

    _dispatch(cc_pair.id, db_session)
    with pytest.raises(RuntimeError, match="Stop signal detected"):
        _run(cc_pair.id, crawl, failing_doc_ids=frozenset({"doc-1"}))

    _dispatch(cc_pair.id, db_session)
    _run(cc_pair.id, crawl)

    # The checkpoint stopped before doc-1, so the resume writes it again
    assert crawl.crawled_by_run[1] == list(range(1, _NUM_ELEMENTS))


def test_full_refresh_ignores_older_checkpoint(
    tenant_context: None,  # noqa: ARG001
    db_session: Session,
) -> None:
    cc_pair = create_test_connector_credential_pair(
        db_session, source=DocumentSource.GOOGLE_DRIVE, access_type=AccessType.SYNC
    )
    crawl = _FakeCheckpointedCrawl()

    _dispatch(cc_pair.id, db_session)
    with pytest.raises(RuntimeError, match="Stop signal detected"):
        _run(cc_pair.id, crawl)

    # Re-entering a synced access type stamps this to request a full refresh
    cc_pair.perm_sync_pending_since = datetime.now(timezone.utc)
    db_session.commit()

    # A fresh crawl starts at element 0 and stops like the first run
    _dispatch(cc_pair.id, db_session)
    with pytest.raises(RuntimeError, match="Stop signal detected"):
        _run(cc_pair.id, crawl)

    assert crawl.crawled_by_run[1] == list(range(_STOP_AFTER))


def test_config_change_ignores_older_checkpoint(
    tenant_context: None,  # noqa: ARG001
    db_session: Session,
) -> None:
    cc_pair = create_test_connector_credential_pair(
        db_session, source=DocumentSource.GOOGLE_DRIVE, access_type=AccessType.SYNC
    )
    crawl = _FakeCheckpointedCrawl()

    _dispatch(cc_pair.id, db_session)
    with pytest.raises(RuntimeError, match="Stop signal detected"):
        _run(cc_pair.id, crawl)

    # A new scope makes the old checkpoint's remaining work list wrong
    cc_pair.connector.connector_specific_config = {"shared_drive_urls": "new-drive"}
    db_session.commit()

    _dispatch(cc_pair.id, db_session)
    with pytest.raises(RuntimeError, match="Stop signal detected"):
        _run(cc_pair.id, crawl)

    assert crawl.crawled_by_run[1] == list(range(_STOP_AFTER))
