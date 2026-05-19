"""External dependency unit tests for the batched deletion / pruning fan-out.

After PR #11185 introduced `document_by_cc_pair_bulk_cleanup_task`, the fan-out
in `RedisConnectorDelete.generate_tasks` and `RedisConnectorPrune.generate_tasks`
switches from "one task per doc" to "one task per batch of
CONNECTOR_CLEANUP_BATCH_SIZE docs". The on-disk effects to verify here:

- One taskset SREM per BATCH instead of per doc (i.e. `taskset.scard()`
  reflects the batch count, not the doc count).
- The dispatched task uses the BULK task name and carries the full set of
  doc IDs split across batches.
- Trailing partial batches are flushed.
- Empty input dispatches zero tasks.

We capture `celery_app.send_task` invocations rather than running the task —
this isolates the fan-out logic from the task body (which has its own coverage
in `test_document_bulk_cleanup.py`).
"""

from collections.abc import Generator
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.configs.app_configs import CONNECTOR_CLEANUP_BATCH_SIZE
from onyx.configs.constants import OnyxCeleryTask
from onyx.connectors.models import IndexAttemptMetadata
from onyx.db.models import ConnectorCredentialPair
from onyx.indexing.indexing_pipeline import index_doc_batch_prepare
from onyx.redis.redis_connector_delete import RedisConnectorDelete
from onyx.redis.redis_connector_prune import RedisConnectorPrune
from onyx.redis.redis_pool import get_raw_redis_client
from onyx.redis.redis_pool import get_redis_client
from tests.external_dependency_unit.constants import TEST_TENANT_ID
from tests.external_dependency_unit.indexing_helpers import cleanup_cc_pair
from tests.external_dependency_unit.indexing_helpers import make_cc_pair
from tests.external_dependency_unit.indexing_helpers import make_doc


@pytest.fixture
def cc_pair(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    initialize_file_store: None,  # noqa: ARG001
) -> Generator[ConnectorCredentialPair, None, None]:
    pair = make_cc_pair(db_session)
    try:
        yield pair
    finally:
        cleanup_cc_pair(db_session, pair)


@pytest.fixture
def cleanup_tenant_redis() -> Generator[None, None, None]:
    """Wipe all keys this tenant touched after the test, so taskset / fence
    leftovers don't leak between runs."""
    yield
    raw = get_raw_redis_client()
    pattern = f"{TEST_TENANT_ID}:connector*"
    keys = list(raw.scan_iter(match=pattern))
    if keys:
        raw.delete(*keys)


def _index_n_docs(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    n: int,
    label: str,
) -> list[str]:
    """Index `n` docs against the cc_pair so generate_tasks has rows to find.
    Returns the list of doc IDs created."""
    docs = [make_doc(f"{label}-{uuid4().hex[:8]}") for _ in range(n)]
    index_doc_batch_prepare(
        documents=docs,
        index_attempt_metadata=IndexAttemptMetadata(
            connector_id=cc_pair.connector_id,
            credential_id=cc_pair.credential_id,
            attempt_id=None,
            request_id="test-request",
        ),
        db_session=db_session,
        ignore_time_skip=True,
    )
    db_session.commit()
    return [doc.id for doc in docs]


def _send_task_recorder() -> tuple[MagicMock, list[dict[str, Any]]]:
    """Return a (mock, captured) pair. Each entry on `captured` is a flat
    dict {"name": <task name>, "document_ids": [...], "queue": ..., ...},
    merging the positional task-name arg with the call's kwargs."""
    captured: list[dict[str, Any]] = []

    def _record(*args: Any, **kwargs: Any) -> MagicMock:
        entry: dict[str, Any] = {}
        if args:
            entry["name"] = args[0]
        entry.update(kwargs)
        captured.append(entry)
        return MagicMock()

    mock = MagicMock(side_effect=_record)
    return mock, captured


class TestRedisConnectorDeleteFanout:
    """`RedisConnectorDelete.generate_tasks` batches over docs attached to the
    cc_pair."""

    def test_taskset_shrinks_to_one_entry_per_batch(
        self,
        db_session: Session,
        cc_pair: ConnectorCredentialPair,
        full_deployment_setup: None,  # noqa: ARG002
        cleanup_tenant_redis: None,  # noqa: ARG002
    ) -> None:
        """250 docs at batch size 100 → 3 batches → 3 taskset entries
        (not 250)."""
        n_docs = (CONNECTOR_CLEANUP_BATCH_SIZE * 2) + (
            CONNECTOR_CLEANUP_BATCH_SIZE // 2
        )
        doc_ids = _index_n_docs(db_session, cc_pair, n_docs, "del")

        rcd = RedisConnectorDelete(
            tenant_id=TEST_TENANT_ID,
            id=cc_pair.id,
            redis=get_redis_client(tenant_id=TEST_TENANT_ID),
        )

        mock_app = MagicMock()
        send_task_mock, captured = _send_task_recorder()
        mock_app.send_task = send_task_mock
        mock_lock = MagicMock()

        num_docs = rcd.generate_tasks(mock_app, db_session, mock_lock)

        expected_batches = 3
        # Return value is doc count (callers persist as `num_docs_synced`),
        # not batch count.
        assert num_docs == n_docs
        assert send_task_mock.call_count == expected_batches

        # Every dispatched task uses the BULK task name.
        for kwargs in captured:
            assert (
                kwargs["name"] == OnyxCeleryTask.DOCUMENT_BY_CC_PAIR_BULK_CLEANUP_TASK
            )

        # Every doc ID lands in exactly one batch.
        dispatched_doc_ids: list[str] = []
        for kwargs in captured:
            dispatched_doc_ids.extend(kwargs["kwargs"]["document_ids"])
        assert sorted(dispatched_doc_ids) == sorted(doc_ids)

        # Batch sizes: two full, one trailing.
        sizes = [len(kwargs["kwargs"]["document_ids"]) for kwargs in captured]
        assert sizes.count(CONNECTOR_CLEANUP_BATCH_SIZE) == 2
        assert sizes.count(CONNECTOR_CLEANUP_BATCH_SIZE // 2) == 1

        # Taskset has one entry per batch, not per doc.
        assert rcd.get_remaining() == expected_batches

    def test_exact_batch_size_does_not_flush_empty_trailing_batch(
        self,
        db_session: Session,
        cc_pair: ConnectorCredentialPair,
        full_deployment_setup: None,  # noqa: ARG002
        cleanup_tenant_redis: None,  # noqa: ARG002
    ) -> None:
        """N == batch_size: exactly one batch. The trailing flush is a no-op
        for an empty buffer — must not enqueue a phantom empty task."""
        _index_n_docs(db_session, cc_pair, CONNECTOR_CLEANUP_BATCH_SIZE, "exact")

        rcd = RedisConnectorDelete(
            tenant_id=TEST_TENANT_ID,
            id=cc_pair.id,
            redis=get_redis_client(tenant_id=TEST_TENANT_ID),
        )

        mock_app = MagicMock()
        send_task_mock, captured = _send_task_recorder()
        mock_app.send_task = send_task_mock

        num_docs = rcd.generate_tasks(mock_app, db_session, MagicMock())

        assert num_docs == CONNECTOR_CLEANUP_BATCH_SIZE
        assert send_task_mock.call_count == 1
        assert (
            len(captured[0]["kwargs"]["document_ids"]) == CONNECTOR_CLEANUP_BATCH_SIZE
        )

    def test_empty_cc_pair_dispatches_zero_tasks(
        self,
        db_session: Session,
        cc_pair: ConnectorCredentialPair,
        full_deployment_setup: None,  # noqa: ARG002
        cleanup_tenant_redis: None,  # noqa: ARG002
    ) -> None:
        """No docs attached → no batches, no taskset entries."""
        rcd = RedisConnectorDelete(
            tenant_id=TEST_TENANT_ID,
            id=cc_pair.id,
            redis=get_redis_client(tenant_id=TEST_TENANT_ID),
        )

        mock_app = MagicMock()
        send_task_mock, _ = _send_task_recorder()
        mock_app.send_task = send_task_mock

        num_docs = rcd.generate_tasks(mock_app, db_session, MagicMock())

        assert num_docs == 0
        assert send_task_mock.call_count == 0
        assert rcd.get_remaining() == 0


class TestRedisConnectorPruneFanout:
    """`RedisConnectorPrune.generate_tasks` takes an explicit set of doc IDs
    (the diff between what's in PG and what the connector re-fetched) and
    batches over that set."""

    def test_taskset_shrinks_to_one_entry_per_batch(
        self,
        db_session: Session,
        cc_pair: ConnectorCredentialPair,
        full_deployment_setup: None,  # noqa: ARG002
        cleanup_tenant_redis: None,  # noqa: ARG002
    ) -> None:
        # 175 docs at batch 100 → 2 batches.
        documents_to_prune = {f"prune-{uuid4().hex[:8]}" for _ in range(175)}

        rcp = RedisConnectorPrune(
            tenant_id=TEST_TENANT_ID,
            id=cc_pair.id,
            redis=get_redis_client(tenant_id=TEST_TENANT_ID),
        )

        mock_app = MagicMock()
        send_task_mock, captured = _send_task_recorder()
        mock_app.send_task = send_task_mock

        num_docs = rcp.generate_tasks(documents_to_prune, mock_app, db_session, None)

        # Return value is doc count (callers persist as `num_docs_synced` /
        # `num_pruned`), not batch count.
        assert num_docs == len(documents_to_prune)
        assert send_task_mock.call_count == 2

        for kwargs in captured:
            assert (
                kwargs["name"] == OnyxCeleryTask.DOCUMENT_BY_CC_PAIR_BULK_CLEANUP_TASK
            )

        dispatched_doc_ids: set[str] = set()
        for kwargs in captured:
            dispatched_doc_ids.update(kwargs["kwargs"]["document_ids"])
        assert dispatched_doc_ids == documents_to_prune

        # One taskset entry per batch.
        assert rcp.taskset_key
        raw = get_raw_redis_client()
        prefixed = f"{TEST_TENANT_ID}:{rcp.taskset_key}"
        assert raw.scard(prefixed) == 2

    def test_empty_set_dispatches_zero_tasks(
        self,
        db_session: Session,
        cc_pair: ConnectorCredentialPair,
        full_deployment_setup: None,  # noqa: ARG002
        cleanup_tenant_redis: None,  # noqa: ARG002
    ) -> None:
        rcp = RedisConnectorPrune(
            tenant_id=TEST_TENANT_ID,
            id=cc_pair.id,
            redis=get_redis_client(tenant_id=TEST_TENANT_ID),
        )

        mock_app = MagicMock()
        send_task_mock, _ = _send_task_recorder()
        mock_app.send_task = send_task_mock

        num_docs = rcp.generate_tasks(set(), mock_app, db_session, None)

        assert num_docs == 0
        assert send_task_mock.call_count == 0
