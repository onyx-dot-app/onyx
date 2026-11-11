"""The watchdog and a broken conversion chain, against real Postgres, Redis
and the file store.

The lister and each conversion task send the next stub batches. When the
task that must send next is gone, stub batches wait and no task runs. The
watchdog must start the chain again, not fail the attempt. It fails the
attempt only when a restart sends nothing in two runs in a row."""

import base64
import json
from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from redis import Redis
from sqlalchemy.orm import Session

from onyx.background.celery.configs.base import CELERY_SEPARATOR
from onyx.background.celery.tasks.docprocessing import tasks as docprocessing_tasks
from onyx.background.celery.tasks.docprocessing.tasks import (
    validate_active_indexing_attempts,
)
from onyx.background.indexing import conversion_recovery
from onyx.background.indexing.conversion_recovery import (
    ConversionChainState,
    check_conversion_chain,
)
from onyx.configs.app_configs import REDIS_HOST, REDIS_PORT
from onyx.configs.constants import OnyxCeleryQueues, OnyxCeleryTask
from onyx.connectors.models import SlimDocumentStub
from onyx.db.enums import IndexingStatus
from onyx.db.indexing_coordination import IndexingCoordination
from onyx.db.models import ConnectorCredentialPair, IndexAttempt
from onyx.db.search_settings import get_current_search_settings
from onyx.file_store.document_batch_storage import (
    get_document_batch_storage,
    get_stub_batch_storage,
)
from onyx.redis.redis_docprocessing import (
    BatchStage,
    RedisDocprocessing,
    reset_conversion_recovery_misses,
)
from onyx.redis.redis_pool import get_redis_client
from shared_configs.contextvars import get_current_tenant_id
from tests.external_dependency_unit.indexing_helpers import (
    cleanup_cc_pair,
    make_cc_pair,
    make_doc,
)

# A Redis database that stands in for the Celery broker.
_BROKER_DB = 14
_LONG_AGO = datetime.now(timezone.utc) - timedelta(hours=2)


class _Run:
    """One attempt in lister mode whose heartbeat stopped long ago."""

    def __init__(
        self, db_session: Session, pair: ConnectorCredentialPair, broker: Redis
    ) -> None:
        self.db_session = db_session
        self.pair = pair
        self.broker = broker
        self.tenant_id = get_current_tenant_id()
        self.app = MagicMock()
        attempt = IndexAttempt(
            connector_credential_pair_id=pair.id,
            search_settings_id=get_current_search_settings(db_session).id,
            from_beginning=False,
            status=IndexingStatus.IN_PROGRESS,
            celery_task_id=f"lister_{uuid4().hex[:8]}",
            uses_conversion_stage=True,
            heartbeat_counter=5,
            last_heartbeat_value=5,
            last_heartbeat_time=_LONG_AGO,
        )
        db_session.add(attempt)
        db_session.commit()
        self.attempt_id = attempt.id
        self.stubs = get_stub_batch_storage(pair.id, self.attempt_id, is_backfill=False)
        self.docs = get_document_batch_storage(
            pair.id, self.attempt_id, is_backfill=False
        )

    def store_stub_batch(self, batch_num: int) -> None:
        self.stubs.store_batch(
            batch_num, [SlimDocumentStub(id=f"doc_{self.attempt_id}_{batch_num}")]
        )
        IndexingCoordination.record_stub_batch_stored(
            self.db_session, self.attempt_id, batch_num
        )

    def claim(self, task_id: str, dispatched_at: datetime = _LONG_AGO) -> list[int]:
        """A dispatch by `task_id` that claimed batches and then sent nothing."""
        batch_nums = IndexingCoordination.claim_stub_batches(
            self.db_session, self.attempt_id, 32, task_id
        )
        attempt = self.attempt()
        attempt.last_dispatch_at = dispatched_at
        self.db_session.commit()
        return batch_nums

    def queue_task(self, task_id: str, queue: str) -> None:
        self.broker.lpush(queue, json.dumps({"headers": {"id": task_id}}))

    def conversion_message(
        self, index_attempt_id: int, tenant_id: str | None = None
    ) -> dict[str, Any]:
        """A conversion task message as kombu stores it in Redis."""
        kwargs = {
            "index_attempt_id": index_attempt_id,
            "tenant_id": tenant_id or self.tenant_id,
            "batch_num": 0,
        }
        body = [[], kwargs, {}]
        return {
            "body": base64.b64encode(json.dumps(body).encode()).decode(),
            "content-encoding": "utf-8",
            "content-type": "application/json",
            "headers": {
                "id": uuid4().hex,
                "task": OnyxCeleryTask.DOCCONVERSION_TASK,
            },
            "properties": {"body_encoding": "base64"},
        }

    def hold_unacked(self, message: dict[str, Any]) -> None:
        """A worker took the task and did not ack it."""
        queue = OnyxCeleryQueues.DOCCONVERSION
        self.broker.hset(
            "unacked",
            message["headers"]["id"],
            json.dumps([message, queue, queue]),
        )

    def watchdog(self) -> None:
        with (
            patch.object(docprocessing_tasks, "current_app", self.app),
            patch.object(
                docprocessing_tasks,
                "celery_get_broker_client",
                return_value=self.broker,
            ),
        ):
            validate_active_indexing_attempts(MagicMock())

    def chain_state(self) -> ConversionChainState:
        return check_conversion_chain(
            self.app,
            self.broker,
            index_attempt_id=self.attempt_id,
            tenant_id=self.tenant_id,
        )

    def attempt(self) -> IndexAttempt:
        self.db_session.expire_all()
        attempt = self.db_session.get(IndexAttempt, self.attempt_id)
        assert attempt is not None
        return attempt

    def sent_batch_nums(self, task: str) -> list[int]:
        return [
            call.kwargs["kwargs"]["batch_num"]
            for call in self.app.send_task.call_args_list
            if call.args[0] == task
        ]


@pytest.fixture
def run(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[_Run, None, None]:
    broker = Redis(host=REDIS_HOST, port=REDIS_PORT, db=_BROKER_DB)
    broker.flushdb()
    pair = make_cc_pair(db_session)
    run = _Run(db_session, pair, broker)
    try:
        yield run
    finally:
        db_session.rollback()
        broker.flushdb()
        broker.close()
        RedisDocprocessing(run.attempt_id, get_redis_client()).cleanup()
        reset_conversion_recovery_misses(get_redis_client(), run.attempt_id)
        run.docs.cleanup_all_batches()
        db_session.query(IndexAttempt).filter(
            IndexAttempt.connector_credential_pair_id == pair.id
        ).delete(synchronize_session="fetch")
        db_session.commit()
        cleanup_cc_pair(db_session, pair)


def test_the_watchdog_sends_a_stored_batch_whose_sender_is_gone(run: _Run) -> None:
    """The lister stored batch 0 and stopped before it dispatched."""
    run.store_stub_batch(0)
    attempt = run.attempt()
    attempt.last_dispatch_task_id = "a task that is gone"
    attempt.last_dispatch_at = _LONG_AGO
    run.db_session.commit()

    run.watchdog()

    assert run.sent_batch_nums(OnyxCeleryTask.DOCCONVERSION_TASK) == [0]
    row = run.attempt()
    assert row.status == IndexingStatus.IN_PROGRESS
    # The restart counts as a heartbeat, and the first sender stays on record.
    assert row.heartbeat_counter == 6
    assert row.stub_batches_sent == 1
    assert row.last_dispatch_task_id == "a task that is gone"
    assert row.last_dispatch_at is not None and row.last_dispatch_at > _LONG_AGO


def test_the_watchdog_leaves_an_attempt_whose_sender_is_in_the_queue(run: _Run) -> None:
    run.store_stub_batch(0)
    attempt = run.attempt()
    attempt.last_dispatch_task_id = "a task in the queue"
    attempt.last_dispatch_at = _LONG_AGO
    run.db_session.commit()
    run.queue_task("a task in the queue", OnyxCeleryQueues.DOCCONVERSION)

    run.watchdog()

    assert run.app.send_task.call_count == 0
    row = run.attempt()
    assert row.status == IndexingStatus.IN_PROGRESS
    assert row.stub_batches_sent == 0
    assert row.heartbeat_counter == 5


def test_the_watchdog_fails_the_attempt_when_two_restarts_send_nothing(
    run: _Run,
) -> None:
    run.store_stub_batch(0)
    attempt = run.attempt()
    attempt.last_dispatch_at = _LONG_AGO
    run.db_session.commit()

    with patch.object(conversion_recovery, "restart_conversion_chain", return_value=0):
        run.watchdog()
        assert run.attempt().status == IndexingStatus.IN_PROGRESS
        run.watchdog()

    assert run.attempt().status == IndexingStatus.FAILED


def test_a_restart_between_two_misses_keeps_the_attempt(run: _Run) -> None:
    run.store_stub_batch(0)
    attempt = run.attempt()
    attempt.last_dispatch_at = _LONG_AGO
    run.db_session.commit()

    with patch.object(conversion_recovery, "restart_conversion_chain", return_value=0):
        run.watchdog()
    # This run sends the batch, so the count of misses starts again.
    run.watchdog()
    attempt = run.attempt()
    attempt.last_dispatch_at = _LONG_AGO
    attempt.last_heartbeat_time = _LONG_AGO
    attempt.last_heartbeat_value = attempt.heartbeat_counter
    run.db_session.commit()
    RedisDocprocessing(
        run.attempt_id, get_redis_client(), BatchStage.DOCCONVERSION
    ).cleanup()
    with patch.object(conversion_recovery, "restart_conversion_chain", return_value=0):
        run.watchdog()

    assert run.attempt().status == IndexingStatus.IN_PROGRESS


def test_a_sent_batch_with_no_task_is_sent_again(run: _Run) -> None:
    """A conversion task was lost: the batch is sent, its stub batch is in
    the store, and no task of the attempt exists."""
    run.store_stub_batch(0)
    run.store_stub_batch(1)
    assert run.claim("a conversion task that is gone") == [0, 1]
    # Batch 0 was converted. Batch 1 was not.
    run.stubs.delete_batch_by_num(0)
    IndexingCoordination.record_stub_batch_converted(run.db_session, run.attempt_id)

    assert run.chain_state() == ConversionChainState.RECOVERED

    assert run.sent_batch_nums(OnyxCeleryTask.DOCCONVERSION_TASK) == [1]


def test_a_live_conversion_task_keeps_the_watchdog_away(run: _Run) -> None:
    run.store_stub_batch(0)
    assert run.claim("a conversion task") == [0]
    counters = RedisDocprocessing(
        run.attempt_id, get_redis_client(), BatchStage.DOCCONVERSION
    )
    counters.incr_pending()
    counters.decr_pending_incr_in_flight()

    assert run.chain_state() == ConversionChainState.BUSY

    assert run.app.send_task.call_count == 0


def test_a_pending_count_with_an_empty_queue_does_not_block_a_restart(
    run: _Run,
) -> None:
    """The conversion task expired in the queue. It left its pending count."""
    run.store_stub_batch(0)
    assert run.claim("a conversion task that expired") == [0]
    RedisDocprocessing(
        run.attempt_id, get_redis_client(), BatchStage.DOCCONVERSION
    ).incr_pending()

    assert run.chain_state() == ConversionChainState.RECOVERED

    assert run.sent_batch_nums(OnyxCeleryTask.DOCCONVERSION_TASK) == [0]


def test_an_unacked_task_of_another_attempt_does_not_block_a_restart(
    run: _Run,
) -> None:
    """A killed worker left a conversion task of another attempt unacked.
    The task of this attempt is gone, so the watchdog sends the batch again."""
    run.store_stub_batch(0)
    assert run.claim("a conversion task that is gone") == [0]
    RedisDocprocessing(
        run.attempt_id, get_redis_client(), BatchStage.DOCCONVERSION
    ).incr_pending()
    run.hold_unacked(run.conversion_message(run.attempt_id + 100_000))
    # The same attempt id in another tenant is another attempt.
    run.hold_unacked(run.conversion_message(run.attempt_id, "another_tenant"))

    assert run.chain_state() == ConversionChainState.RECOVERED

    assert run.sent_batch_nums(OnyxCeleryTask.DOCCONVERSION_TASK) == [0]


def test_a_task_of_the_attempt_in_the_queue_keeps_the_watchdog_away(
    run: _Run,
) -> None:
    run.store_stub_batch(0)
    run.store_stub_batch(1)
    assert run.claim("a conversion task") == [0, 1]
    RedisDocprocessing(
        run.attempt_id, get_redis_client(), BatchStage.DOCCONVERSION
    ).incr_pending()
    run.broker.lpush(
        f"{OnyxCeleryQueues.DOCCONVERSION}{CELERY_SEPARATOR}2",
        json.dumps(run.conversion_message(run.attempt_id)),
    )

    assert run.chain_state() == ConversionChainState.BUSY

    assert run.app.send_task.call_count == 0


def test_an_unacked_task_of_the_attempt_keeps_the_watchdog_away(
    run: _Run,
) -> None:
    run.store_stub_batch(0)
    assert run.claim("a conversion task") == [0]
    RedisDocprocessing(
        run.attempt_id, get_redis_client(), BatchStage.DOCCONVERSION
    ).incr_pending()
    run.hold_unacked(run.conversion_message(run.attempt_id))

    assert run.chain_state() == ConversionChainState.BUSY

    assert run.app.send_task.call_count == 0


def test_a_recent_dispatch_is_healthy(run: _Run) -> None:
    run.store_stub_batch(0)
    assert run.claim("a task", dispatched_at=datetime.now(timezone.utc)) == [0]

    assert run.chain_state() == ConversionChainState.HEALTHY

    assert run.app.send_task.call_count == 0


def test_a_task_that_stopped_after_it_deleted_its_stub_batch_is_recovered(
    run: _Run,
) -> None:
    """The task stored the document batch and deleted the stub batch. It
    stopped before it counted the batch and before it sent it on."""
    run.store_stub_batch(0)
    run.store_stub_batch(1)
    assert IndexingCoordination.claim_stub_batches(
        run.db_session, run.attempt_id, 1, "a conversion task that is gone"
    ) == [0]
    attempt = run.attempt()
    attempt.last_dispatch_at = _LONG_AGO
    run.db_session.commit()
    run.docs.store_batch(0, [make_doc(f"doc_{run.attempt_id}_0")])
    run.stubs.delete_batch_by_num(0)

    with patch.object(conversion_recovery, "DOCCONVERSION_STALL_SECONDS", 300):
        assert run.chain_state() == ConversionChainState.RECOVERED

    # The document batch goes to docprocessing, and the count is corrected.
    assert run.sent_batch_nums(OnyxCeleryTask.DOCPROCESSING_TASK) == [0]
    assert run.attempt().stub_batches_converted == 1
    # The window has room again, so batch 1 goes to conversion.
    assert run.sent_batch_nums(OnyxCeleryTask.DOCCONVERSION_TASK) == [1]
