"""The conversion task against real Postgres, Redis and the file store.

One task converts a stored stub batch into a stored document batch with the
same number, sends it to docprocessing, and sends the next stub batches. A
stopped attempt converts nothing. The connector is a stand-in: the Drive
conversion has its own tests."""

from collections.abc import Generator
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.background.indexing import run_docconversion
from onyx.background.indexing.run_docconversion import (
    DOCCONVERSION_TASK_EXPIRES_SECONDS,
    convert_stub_batch,
    dispatch_stub_batches,
)
from onyx.configs.constants import (
    DocumentSource,
    OnyxCeleryQueues,
    OnyxCeleryTask,
)
from onyx.connectors.interfaces import Resolver
from onyx.connectors.models import (
    ConnectorFailure,
    Document,
    DocumentFailure,
    HierarchyNode,
    ListingPayload,
    ResolveTarget,
    SlimDocumentStub,
)
from onyx.db.enums import HierarchyNodeType, IndexingStatus
from onyx.db.hierarchy import ensure_source_node_exists
from onyx.db.indexing_coordination import IndexingCoordination
from onyx.db.models import (
    ConnectorCredentialPair,
    IndexAttempt,
    IndexAttemptError,
)
from onyx.db.models import HierarchyNode as DBHierarchyNode
from onyx.db.search_settings import get_current_search_settings
from onyx.file_store.document_batch_storage import (
    get_document_batch_storage,
    get_stub_batch_storage,
)
from onyx.redis.redis_connector import RedisConnector
from onyx.redis.redis_docprocessing import BatchStage, RedisDocprocessing
from onyx.redis.redis_pool import get_redis_client
from shared_configs.contextvars import get_current_tenant_id
from tests.external_dependency_unit.indexing_helpers import (
    cleanup_cc_pair,
    make_cc_pair,
    make_doc,
)


class _Payload(ListingPayload):
    outcome: str


class _FakeConnector(Resolver):
    """Converts a target as its payload says: a document, a failure, or
    nothing. It also yields one folder node for each call."""

    listing_payload_type = _Payload

    def __init__(self, folder_id: str) -> None:
        self.folder_id = folder_id
        self.calls: list[tuple[list[str], bool]] = []

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:  # noqa: ARG002
        return None

    def reindex(
        self,
        errors: list[ConnectorFailure],  # noqa: ARG002
        include_permissions: bool = False,  # noqa: ARG002
    ) -> Generator[Document | ConnectorFailure | HierarchyNode, None, None]:
        raise AssertionError("conversion must use the listing payload")

    def resolve_targets(
        self, targets: list[ResolveTarget], include_permissions: bool = False
    ) -> Generator[Document | ConnectorFailure | HierarchyNode, None, None]:
        self.calls.append(([t.document_id for t in targets], include_permissions))
        yield HierarchyNode(
            raw_node_id=self.folder_id,
            raw_parent_id=None,
            display_name="Folder",
            node_type=HierarchyNodeType.FOLDER,
        )
        for target in targets:
            payload = target.listing_payload
            assert isinstance(payload, _Payload), "the payload lost its type"
            if payload.outcome == "document":
                doc = make_doc(target.document_id)
                doc.parent_hierarchy_raw_node_id = self.folder_id
                yield doc
            elif payload.outcome == "failure":
                yield ConnectorFailure(
                    failed_document=DocumentFailure(document_id=target.document_id),
                    failure_message="the download failed",
                )


class _Run:
    """One index attempt with its stores, a stand-in connector and a
    recording Celery app."""

    def __init__(self, db_session: Session, pair: ConnectorCredentialPair) -> None:
        self.db_session = db_session
        self.pair = pair
        self.tenant_id = get_current_tenant_id()
        attempt = IndexAttempt(
            connector_credential_pair_id=pair.id,
            search_settings_id=get_current_search_settings(db_session).id,
            from_beginning=False,
            status=IndexingStatus.IN_PROGRESS,
        )
        db_session.add(attempt)
        db_session.commit()
        self.attempt_id = attempt.id
        self.tag = uuid4().hex[:8]
        self.connector = _FakeConnector(folder_id=f"folder_{self.tag}")
        self.app = MagicMock()
        self.stubs = get_stub_batch_storage(pair.id, self.attempt_id, is_backfill=False)
        self.docs = get_document_batch_storage(
            pair.id, self.attempt_id, is_backfill=False
        )

    def store_stub_batch(self, batch_num: int, outcomes: list[str]) -> list[str]:
        doc_ids = [f"doc_{self.tag}_{batch_num}_{i}" for i in range(len(outcomes))]
        self.stubs.store_batch(
            batch_num,
            [
                SlimDocumentStub(id=doc_id, listing_payload=_Payload(outcome=outcome))
                for doc_id, outcome in zip(doc_ids, outcomes, strict=True)
            ],
        )
        IndexingCoordination.record_stub_batch_stored(
            self.db_session, self.attempt_id, batch_num
        )
        return doc_ids

    def convert(self, batch_num: int) -> None:
        convert_stub_batch(
            self.app,
            index_attempt_id=self.attempt_id,
            cc_pair_id=self.pair.id,
            tenant_id=self.tenant_id,
            batch_num=batch_num,
        )

    def dispatch(self) -> list[int]:
        return dispatch_stub_batches(
            self.app,
            index_attempt_id=self.attempt_id,
            cc_pair_id=self.pair.id,
            tenant_id=self.tenant_id,
            is_backfill=False,
        )

    def attempt(self) -> IndexAttempt:
        self.db_session.expire_all()
        attempt = self.db_session.get(IndexAttempt, self.attempt_id)
        assert attempt is not None
        return attempt

    def sends(self, task: str) -> list[dict[str, Any]]:
        return [
            call.kwargs
            for call in self.app.send_task.call_args_list
            if call.args[0] == task
        ]

    def pending(self, stage: BatchStage) -> int:
        counters = RedisDocprocessing(self.attempt_id, get_redis_client(), stage)
        return int(get_redis_client().get(counters.pending_key) or 0)


@pytest.fixture
def run(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[_Run, None, None]:
    ensure_source_node_exists(db_session, DocumentSource.MOCK_CONNECTOR)
    pair = make_cc_pair(db_session)
    run = _Run(db_session, pair)
    run_docconversion.clear_conversion_context_cache()
    with patch.object(
        run_docconversion, "instantiate_connector", return_value=run.connector
    ) as build:
        run.build = build  # ty: ignore[unresolved-attribute]
        try:
            yield run
        finally:
            run_docconversion.clear_conversion_context_cache()
            db_session.rollback()
            RedisConnector(run.tenant_id, pair.id).stop.set_fence(False)
            RedisDocprocessing(run.attempt_id, get_redis_client()).cleanup()
            run.docs.cleanup_all_batches()
            run.stubs.cleanup_all_batches()
            db_session.query(IndexAttemptError).filter(
                IndexAttemptError.index_attempt_id == run.attempt_id
            ).delete(synchronize_session="fetch")
            db_session.query(IndexAttempt).filter(
                IndexAttempt.connector_credential_pair_id == pair.id
            ).delete(synchronize_session="fetch")
            db_session.query(DBHierarchyNode).filter(
                DBHierarchyNode.raw_node_id == run.connector.folder_id
            ).delete(synchronize_session="fetch")
            db_session.commit()
            cleanup_cc_pair(db_session, pair)


def test_a_task_converts_a_stub_batch_and_sends_it_to_docprocessing(run: _Run) -> None:
    doc_ids = run.store_stub_batch(0, ["document", "failure", "document", "nothing"])
    run.store_stub_batch(1, ["document"])
    # The lister's dispatch sends the two stored batches.
    assert run.dispatch() == [0, 1]
    assert run.pending(BatchStage.DOCCONVERSION) == 2

    run.convert(0)

    # The stub batch became a document batch with the same number.
    assert run.stubs.get_batch(0, _Payload) is None
    stored = run.docs.get_batch(0)
    assert stored is not None
    assert [doc.id for doc in stored] == [doc_ids[0], doc_ids[2]]
    # Each document has the node that the conversion yielded as its parent.
    folder = run.db_session.scalar(
        select(DBHierarchyNode).where(
            DBHierarchyNode.raw_node_id == run.connector.folder_id
        )
    )
    assert folder is not None
    assert {doc.parent_hierarchy_node_id for doc in stored} == {folder.id}

    attempt = run.attempt()
    assert (attempt.stub_batches_sent, attempt.stub_batches_converted) == (2, 1)
    # The docprocessing task counts the batch as complete, not conversion.
    assert (attempt.completed_batches or 0) == 0
    errors = run.db_session.scalars(
        select(IndexAttemptError).where(
            IndexAttemptError.index_attempt_id == run.attempt_id
        )
    ).all()
    assert [error.document_id for error in errors] == [doc_ids[1]]

    (docprocessing,) = run.sends(OnyxCeleryTask.DOCPROCESSING_TASK)
    assert docprocessing["queue"] == OnyxCeleryQueues.DOCPROCESSING
    assert docprocessing["kwargs"]["batch_num"] == 0
    assert docprocessing["expires"] == DOCCONVERSION_TASK_EXPIRES_SECONDS
    assert run.pending(BatchStage.DOCPROCESSING) == 1
    conversions = run.sends(OnyxCeleryTask.DOCCONVERSION_TASK)
    assert [send["kwargs"]["batch_num"] for send in conversions] == [0, 1]
    assert all(
        send["queue"] == OnyxCeleryQueues.DOCCONVERSION
        and send["expires"] == DOCCONVERSION_TASK_EXPIRES_SECONDS
        for send in conversions
    )


def test_a_worker_builds_the_connector_once_for_an_attempt(run: _Run) -> None:
    run.store_stub_batch(0, ["document"])
    run.store_stub_batch(1, ["document"])
    run.dispatch()

    run.convert(0)
    run.convert(1)

    assert run.build.call_count == 1  # ty: ignore[unresolved-attribute]
    assert len(run.connector.calls) == 2


def test_a_batch_with_no_documents_counts_as_complete(run: _Run) -> None:
    run.store_stub_batch(0, ["nothing", "failure"])
    run.dispatch()

    run.convert(0)

    assert run.stubs.get_batch(0, _Payload) is None
    assert run.docs.get_batch(0) is None
    attempt = run.attempt()
    assert attempt.stub_batches_converted == 1
    assert attempt.completed_batches == 1
    assert run.sends(OnyxCeleryTask.DOCPROCESSING_TASK) == []


@pytest.mark.parametrize("how", ["stop_fence", "cancellation", "ended"])
def test_a_stopped_attempt_converts_nothing(run: _Run, how: str) -> None:
    run.store_stub_batch(0, ["document"])
    run.dispatch()
    if how == "stop_fence":
        RedisConnector(run.tenant_id, run.pair.id).stop.set_fence(True)
    else:
        attempt = run.attempt()
        if how == "cancellation":
            attempt.cancellation_requested = True
        else:
            attempt.status = IndexingStatus.CANCELED
        run.db_session.commit()

    run.convert(0)

    assert run.connector.calls == []
    assert run.stubs.get_batch(0, _Payload) is not None
    assert run.docs.get_batch(0) is None
    assert run.attempt().stub_batches_converted == 0
    assert run.sends(OnyxCeleryTask.DOCPROCESSING_TASK) == []


def test_a_second_run_of_a_converted_batch_does_nothing(run: _Run) -> None:
    run.store_stub_batch(0, ["document"])
    run.dispatch()
    run.convert(0)

    run.convert(0)

    assert len(run.connector.calls) == 1
    assert len(run.sends(OnyxCeleryTask.DOCPROCESSING_TASK)) == 1
    assert run.attempt().stub_batches_converted == 1


def test_a_run_that_stopped_before_the_stub_delete_converts_again(run: _Run) -> None:
    """A worker died after it stored the document batch. The stub batch is
    still there, so the batch was not sent on. The next run stores the
    document batch again and sends it once."""
    doc_ids = run.store_stub_batch(0, ["document"])
    run.dispatch()
    run.docs.store_batch(0, [make_doc("left_by_the_dead_run")])

    run.convert(0)

    stored = run.docs.get_batch(0)
    assert stored is not None
    assert [doc.id for doc in stored] == doc_ids
    assert len(run.sends(OnyxCeleryTask.DOCPROCESSING_TASK)) == 1


def test_the_window_bounds_the_batches_in_conversion(
    run: _Run, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(run_docconversion, "DOCCONVERSION_WINDOW_BATCHES", 2)
    for batch_num in range(5):
        run.store_stub_batch(batch_num, ["document"])

    assert run.dispatch() == [0, 1]
    # The window is full: the lister's next dispatch sends nothing.
    assert run.dispatch() == []

    # A task that ends sends the next batch.
    run.convert(0)
    conversions = run.sends(OnyxCeleryTask.DOCCONVERSION_TASK)
    assert [send["kwargs"]["batch_num"] for send in conversions] == [0, 1, 2]
