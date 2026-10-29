"""A resumed attempt re-issues the batches a failed attempt left in the file
store while that attempt's docprocessing tasks still run. Each task counts its
batch in completed_batches and then deletes it. These tests run one task's
count and delete at the points where they race the re-issue. No batch can be
lost, and a new batch must not reuse a re-issued batch's number."""

import contextvars
import threading
import time
from collections.abc import Callable, Generator
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import event, text
from sqlalchemy.orm import Session

from onyx.background.indexing.run_docfetching import reissue_old_batches
from onyx.configs.constants import OnyxCeleryPriority
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import IndexingStatus
from onyx.db.indexing_coordination import IndexingCoordination
from onyx.db.models import ConnectorCredentialPair, IndexAttempt
from onyx.db.search_settings import get_current_search_settings
from onyx.file_store.document_batch_storage import (
    DocumentBatchStorage,
    FileStoreDocumentBatchStorage,
    get_document_batch_storage,
)
from onyx.file_store.file_store import S3BackedFileStore, get_default_file_store
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from tests.external_dependency_unit.indexing_helpers import (
    cleanup_cc_pair,
    make_cc_pair,
    make_doc,
)

_OLD_BATCH_COUNT = 3
_LOCK_WAIT_TIMEOUT_S = 10.0


@pytest.fixture
def cc_pair(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[ConnectorCredentialPair, None, None]:
    pair = make_cc_pair(db_session)
    try:
        yield pair
    finally:
        db_session.rollback()
        get_document_batch_storage(pair.id, 0).cleanup_all_batches()
        db_session.query(IndexAttempt).filter(
            IndexAttempt.connector_credential_pair_id == pair.id
        ).delete(synchronize_session="fetch")
        db_session.commit()
        cleanup_cc_pair(db_session, pair)


def _make_attempt(
    db_session: Session, cc_pair_id: int, status: IndexingStatus
) -> IndexAttempt:
    attempt = IndexAttempt(
        connector_credential_pair_id=cc_pair_id,
        search_settings_id=get_current_search_settings(db_session).id,
        from_beginning=False,
        status=status,
        completed_batches=0,
    )
    db_session.add(attempt)
    db_session.commit()
    return attempt


def _doc_id(batch_num: int) -> str:
    return f"reissue-race-doc-{batch_num}"


def _old_task_finishes(old_storage: DocumentBatchStorage, batch_num: int) -> None:
    """What a docprocessing task of the failed attempt does when it ends."""
    with get_session_with_current_tenant() as session:
        IndexingCoordination.update_batch_completion_and_docs(
            db_session=session,
            index_attempt_id=old_storage.index_attempt_id,
            total_docs_indexed=1,
            new_docs_indexed=1,
            total_chunks=1,
        )
    old_storage.delete_batch_by_num(batch_num)


def _reissue(
    db_session: Session,
    storage: DocumentBatchStorage,
    attempt: IndexAttempt,
    old_attempt_id: int,
    app: MagicMock,
) -> int:
    return reissue_old_batches(
        storage,
        db_session,
        attempt,
        attempt.connector_credential_pair_id,
        POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE,
        app,
        old_attempt_id,
        OnyxCeleryPriority.MEDIUM,
    )


def _assert_no_batch_lost(
    db_session: Session,
    storage: DocumentBatchStorage,
    attempt_id: int,
    old_attempt_id: int,
    next_batch_num: int,
    app: MagicMock,
) -> None:
    """Every old batch is re-issued and readable, or counted as completed. The
    next new batch does not overwrite a re-issued one."""
    reissued = sorted(
        call.kwargs["kwargs"]["batch_num"] for call in app.send_task.call_args_list
    )
    storage.store_batch(next_batch_num, [make_doc("reissue-race-new-doc")])
    for batch_num in reissued:
        documents = storage.get_batch(batch_num)
        assert documents is not None
        assert [d.id for d in documents] == [_doc_id(batch_num)]

    old_completed = IndexingCoordination.get_completed_batches(
        db_session, old_attempt_id
    )
    assert old_completed + len(reissued) >= _OLD_BATCH_COUNT
    assert IndexingCoordination.get_completed_batches(db_session, attempt_id) == (
        next_batch_num - len(reissued)
    )


@pytest.fixture
def attempts(
    db_session: Session, cc_pair: ConnectorCredentialPair
) -> tuple[IndexAttempt, IndexAttempt, DocumentBatchStorage, DocumentBatchStorage]:
    """A failed attempt with three batches in the file store, and the attempt
    that resumes it."""
    old_attempt = _make_attempt(db_session, cc_pair.id, IndexingStatus.FAILED)
    old_storage = get_document_batch_storage(cc_pair.id, old_attempt.id)
    for batch_num in range(_OLD_BATCH_COUNT):
        old_storage.store_batch(batch_num, [make_doc(_doc_id(batch_num))])
    new_attempt = _make_attempt(db_session, cc_pair.id, IndexingStatus.IN_PROGRESS)
    new_storage = get_document_batch_storage(cc_pair.id, new_attempt.id)
    return old_attempt, new_attempt, old_storage, new_storage


def test_batch_done_after_old_attempt_loaded(
    db_session: Session,
    attempts: tuple[
        IndexAttempt, IndexAttempt, DocumentBatchStorage, DocumentBatchStorage
    ],
) -> None:
    """A batch ends after docfetching loaded the old attempt and before the
    listing. The loaded completed_batches does not count it."""
    old_attempt, new_attempt, old_storage, new_storage = attempts
    assert old_attempt.completed_batches == 0  # loaded, now stale
    _old_task_finishes(old_storage, 0)

    app = MagicMock()
    next_batch_num = _reissue(db_session, new_storage, new_attempt, old_attempt.id, app)

    _assert_no_batch_lost(
        db_session, new_storage, new_attempt.id, old_attempt.id, next_batch_num, app
    )
    assert next_batch_num == _OLD_BATCH_COUNT


def test_batch_done_between_listing_and_move(
    db_session: Session,
    attempts: tuple[
        IndexAttempt, IndexAttempt, DocumentBatchStorage, DocumentBatchStorage
    ],
) -> None:
    """A listed batch ends and is deleted before the re-issue moves it."""
    old_attempt, new_attempt, old_storage, new_storage = attempts
    list_batches = new_storage.get_all_batches_for_cc_pair

    def list_then_old_task_finishes() -> list[str]:
        batches = list_batches()
        _old_task_finishes(old_storage, 1)
        return batches

    app = MagicMock()
    with patch.object(
        new_storage, "get_all_batches_for_cc_pair", list_then_old_task_finishes
    ):
        next_batch_num = _reissue(
            db_session, new_storage, new_attempt, old_attempt.id, app
        )

    _assert_no_batch_lost(
        db_session, new_storage, new_attempt.id, old_attempt.id, next_batch_num, app
    )
    assert next_batch_num == _OLD_BATCH_COUNT


def _wait_until_lock_wait(thread: threading.Thread, pids: set[int]) -> None:
    """Returns when one of the thread's connections waits on a lock. Fails the
    test if the thread ends or the deadline passes first."""
    deadline = time.monotonic() + _LOCK_WAIT_TIMEOUT_S
    while thread.is_alive() and time.monotonic() < deadline:
        with get_session_with_current_tenant() as session:
            waiting = session.scalar(
                text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE pid = ANY(:pids) AND wait_event_type = 'Lock'"
                ),
                {"pids": list(pids)},
            )
        if waiting:
            return
        time.sleep(0.05)
    pytest.fail("The re-issue did not wait on the lock the delete holds")


def test_batch_deleted_while_being_moved(
    db_session: Session,
    attempts: tuple[
        IndexAttempt, IndexAttempt, DocumentBatchStorage, DocumentBatchStorage
    ],
) -> None:
    """The re-issue lists and moves a batch while an old task deletes it. The
    moved record must not point at an object the delete removed."""
    # The delete is paused through the S3 client's delete_object.
    if not isinstance(get_default_file_store(), S3BackedFileStore):
        pytest.skip("Needs the S3 file store backend")
    old_attempt, new_attempt, old_storage, new_storage = attempts
    assert isinstance(old_storage, FileStoreDocumentBatchStorage)
    assert isinstance(old_storage.file_store, S3BackedFileStore)
    s3_client = old_storage.file_store._get_s3_client()
    app = MagicMock()
    result: list[int] = []

    def run_reissue() -> None:
        with get_session_with_current_tenant() as session:
            attempt = session.get(IndexAttempt, new_attempt.id)
            assert attempt is not None
            result.append(_reissue(session, new_storage, attempt, old_attempt.id, app))

    reissue_thread = threading.Thread(
        target=contextvars.copy_context().run, args=(run_reissue,)
    )
    reissue_pids: set[int] = set()

    def record_reissue_pid(
        dbapi_connection: Any,
        _connection_record: Any,
        _connection_proxy: Any,
    ) -> None:
        if threading.current_thread() is not reissue_thread:
            return
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("SELECT pg_backend_pid()")
            reissue_pids.add(cursor.fetchone()[0])
        finally:
            cursor.close()

    real_delete_object: Callable[..., Any] = s3_client.delete_object

    # The delete has read the batch's record and is about to remove its object.
    def reissue_during_delete(**kwargs: Any) -> Any:
        reissue_thread.start()
        _wait_until_lock_wait(reissue_thread, reissue_pids)
        return real_delete_object(**kwargs)

    engine = db_session.get_bind()
    event.listen(engine, "checkout", record_reissue_pid)
    try:
        with patch.object(
            s3_client, "delete_object", side_effect=reissue_during_delete
        ):
            _old_task_finishes(old_storage, 1)
    finally:
        event.remove(engine, "checkout", record_reissue_pid)
    reissue_thread.join(timeout=_LOCK_WAIT_TIMEOUT_S)
    assert not reissue_thread.is_alive()

    assert len(result) == 1
    db_session.expire_all()
    _assert_no_batch_lost(
        db_session, new_storage, new_attempt.id, old_attempt.id, result[0], app
    )
    assert result == [_OLD_BATCH_COUNT]


def test_store_batch_refuses_to_overwrite(
    attempts: tuple[
        IndexAttempt, IndexAttempt, DocumentBatchStorage, DocumentBatchStorage
    ],
) -> None:
    old_storage = attempts[2]
    with pytest.raises(RuntimeError, match="already exists"):
        old_storage.store_batch(0, [make_doc("reissue-race-other-doc")])
    documents = old_storage.get_batch(0)
    assert documents is not None
    assert [d.id for d in documents] == [_doc_id(0)]


def test_count_from_attempt_that_fetched_nothing(
    db_session: Session, cc_pair: ConnectorCredentialPair
) -> None:
    """The attempt before the resume failed before it fetched anything, so its
    count does not cover the batches an earlier attempt left."""
    old_attempt = _make_attempt(db_session, cc_pair.id, IndexingStatus.FAILED)
    old_storage = get_document_batch_storage(cc_pair.id, old_attempt.id)
    old_storage.store_batch(7, [make_doc(_doc_id(7))])
    empty_attempt = _make_attempt(db_session, cc_pair.id, IndexingStatus.FAILED)
    new_attempt = _make_attempt(db_session, cc_pair.id, IndexingStatus.IN_PROGRESS)
    new_storage = get_document_batch_storage(cc_pair.id, new_attempt.id)

    app = MagicMock()
    next_batch_num = _reissue(
        db_session, new_storage, new_attempt, empty_attempt.id, app
    )

    assert next_batch_num == 8
    assert IndexingCoordination.get_completed_batches(db_session, new_attempt.id) == 7
    documents = new_storage.get_batch(7)
    assert documents is not None
    assert [d.id for d in documents] == [_doc_id(7)]
