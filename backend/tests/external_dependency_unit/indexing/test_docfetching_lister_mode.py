"""Docfetching as the lister of the conversion stage, against real Postgres,
Redis and the file store.

With the switch on, docfetching stores stub batches and sends conversion
tasks, and the conversion tasks make the document batches. With the switch
off, docfetching fetches documents as before. An attempt that continues a
failed one takes over its stub batches."""

from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.background.indexing import run_docconversion, run_docfetching
from onyx.background.indexing.run_docconversion import (
    DOCCONVERSION_TASK_EXPIRES_SECONDS,
    convert_stub_batch,
)
from onyx.background.indexing.run_docfetching import (
    connector_document_extraction,
    list_stub_batches,
)
from onyx.configs.constants import OnyxCeleryTask
from onyx.connectors.interfaces import (
    CheckpointedConnector,
    CheckpointedSlimConnector,
    CheckpointOutput,
    Resolver,
    SecondsSinceUnixEpoch,
    SlimCheckpointOutput,
)
from onyx.connectors.models import (
    ConnectorCheckpoint,
    ConnectorFailure,
    Document,
    HierarchyNode,
    ListingPayload,
    ResolveTarget,
    SlimDocument,
    SlimDocumentStub,
)
from onyx.db.enums import HierarchyNodeType, IndexingStatus
from onyx.db.models import ConnectorCredentialPair, IndexAttempt
from onyx.db.models import HierarchyNode as DBHierarchyNode
from onyx.db.search_settings import get_current_search_settings
from onyx.file_store.document_batch_storage import (
    get_document_batch_storage,
    get_stub_batch_storage,
)
from onyx.redis.redis_docprocessing import RedisDocprocessing
from onyx.redis.redis_hierarchy import invalidate_hierarchy_cache_for_source
from onyx.redis.redis_pool import get_redis_client
from shared_configs.contextvars import get_current_tenant_id
from tests.external_dependency_unit.indexing_helpers import (
    cleanup_cc_pair,
    make_cc_pair,
    make_doc,
)

_WINDOW_END = datetime(2026, 1, 2, tzinfo=timezone.utc)


class _Payload(ListingPayload):
    title: str


class _FakeLister(
    CheckpointedConnector[ConnectorCheckpoint],
    CheckpointedSlimConnector[ConnectorCheckpoint],
    Resolver,
):
    """Lists its documents in calls of three, with one folder first and one
    document that the indexing filters drop."""

    listing_payload_type = _Payload

    def __init__(self, tag: str, doc_count: int) -> None:
        self.folder_id = f"folder_{tag}"
        self.doc_ids = [f"doc_{tag}_{i}" for i in range(doc_count)]
        self.listed = 0
        self.fetch_calls = 0
        self.listing_permissions: list[bool] = []

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:  # noqa: ARG002
        return None

    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,  # noqa: ARG002
        end: SecondsSinceUnixEpoch,  # noqa: ARG002
        checkpoint: ConnectorCheckpoint,  # noqa: ARG002
    ) -> CheckpointOutput[ConnectorCheckpoint]:
        self.fetch_calls += 1
        for doc_id in self.doc_ids:
            yield make_doc(doc_id)
        return ConnectorCheckpoint(has_more=False)

    def retrieve_slim_docs_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,  # noqa: ARG002
        end: SecondsSinceUnixEpoch,  # noqa: ARG002
        checkpoint: ConnectorCheckpoint,  # noqa: ARG002
        include_permissions: bool = False,
    ) -> SlimCheckpointOutput[ConnectorCheckpoint]:
        self.listing_permissions.append(include_permissions)
        if self.listed == 0:
            yield HierarchyNode(
                raw_node_id=self.folder_id,
                raw_parent_id=None,
                display_name="Folder",
                node_type=HierarchyNodeType.FOLDER,
            )
            yield SlimDocument(id="dropped by the indexing filters")
        for doc_id in self.doc_ids[self.listed : self.listed + 3]:
            yield SlimDocumentStub(id=doc_id, listing_payload=_Payload(title=doc_id))
        self.listed += 3
        return ConnectorCheckpoint(has_more=self.listed < len(self.doc_ids))

    def build_dummy_checkpoint(self) -> ConnectorCheckpoint:
        return ConnectorCheckpoint(has_more=True)

    def validate_checkpoint_json(self, checkpoint_json: str) -> ConnectorCheckpoint:
        return ConnectorCheckpoint.model_validate_json(checkpoint_json)

    def reindex(
        self,
        errors: list[ConnectorFailure],  # noqa: ARG002
        include_permissions: bool = False,  # noqa: ARG002
    ) -> Generator[Document | ConnectorFailure | HierarchyNode, None, None]:
        raise AssertionError("conversion must use the listing payload")

    def resolve_targets(
        self,
        targets: list[ResolveTarget],
        include_permissions: bool = False,  # noqa: ARG002
    ) -> Generator[Document | ConnectorFailure | HierarchyNode, None, None]:
        for target in targets:
            assert isinstance(target.listing_payload, _Payload)
            yield make_doc(target.document_id)


class _Run:
    def __init__(self, db_session: Session, pair: ConnectorCredentialPair) -> None:
        self.db_session = db_session
        self.pair = pair
        self.tenant_id = get_current_tenant_id()
        self.search_settings_id = get_current_search_settings(db_session).id
        self.tag = uuid4().hex[:8]
        self.connector = _FakeLister(self.tag, doc_count=5)
        self.app = MagicMock()
        self.attempt_ids: list[int] = []

    def add_attempt(
        self, status: IndexingStatus, created: datetime, **fields: Any
    ) -> IndexAttempt:
        attempt = IndexAttempt(
            connector_credential_pair_id=self.pair.id,
            search_settings_id=self.search_settings_id,
            from_beginning=False,
            status=status,
            celery_task_id=f"task_{uuid4().hex[:8]}",
            time_created=created,
            **fields,
        )
        self.db_session.add(attempt)
        self.db_session.commit()
        self.attempt_ids.append(attempt.id)
        return attempt

    def extract(self, attempt_id: int) -> None:
        runner = MagicMock()
        runner.connector = self.connector
        runner.run.side_effect = lambda _checkpoint: iter(
            [
                (
                    [make_doc(doc_id) for doc_id in self.connector.doc_ids],
                    None,
                    None,
                    None,
                ),
                (None, None, None, ConnectorCheckpoint(has_more=False)),
            ]
        )
        self.runner = runner
        with (
            patch.object(run_docfetching, "_get_connector_runner", return_value=runner),
            patch.object(run_docfetching, "MemoryTracer"),
            patch.object(run_docfetching, "INDEX_BATCH_SIZE", 2),
        ):
            connector_document_extraction(
                app=self.app,
                index_attempt_id=attempt_id,
                cc_pair_id=self.pair.id,
                search_settings_id=self.search_settings_id,
                tenant_id=self.tenant_id,
                callback=None,
            )

    def convert(self, attempt_id: int, batch_num: int) -> None:
        convert_stub_batch(
            self.app,
            index_attempt_id=attempt_id,
            cc_pair_id=self.pair.id,
            tenant_id=self.tenant_id,
            batch_num=batch_num,
        )

    def attempt(self, attempt_id: int) -> IndexAttempt:
        self.db_session.expire_all()
        attempt = self.db_session.get(IndexAttempt, attempt_id)
        assert attempt is not None
        return attempt

    def sent_batch_nums(self, task: str) -> list[int]:
        return [
            call.kwargs["kwargs"]["batch_num"]
            for call in self.app.send_task.call_args_list
            if call.args[0] == task
        ]

    def stub_doc_ids(self, attempt_id: int, batch_num: int) -> list[str]:
        stubs = get_stub_batch_storage(
            self.pair.id, attempt_id, is_backfill=False
        ).get_batch(batch_num, _Payload)
        assert stubs is not None, f"stub batch {batch_num} is not stored"
        return [stub.id for stub in stubs]

    def doc_batch_ids(self, attempt_id: int, batch_num: int) -> list[str]:
        docs = get_document_batch_storage(
            self.pair.id, attempt_id, is_backfill=False
        ).get_batch(batch_num)
        assert docs is not None, f"document batch {batch_num} is not stored"
        return [doc.id for doc in docs]


@pytest.fixture
def run(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[_Run, None, None]:
    pair = make_cc_pair(db_session)
    run = _Run(db_session, pair)
    run_docconversion.clear_conversion_context_cache()
    with patch.object(
        run_docconversion, "instantiate_connector", return_value=run.connector
    ):
        try:
            yield run
        finally:
            run_docconversion.clear_conversion_context_cache()
            db_session.rollback()
            for attempt_id in run.attempt_ids:
                RedisDocprocessing(attempt_id, get_redis_client()).cleanup()
                get_document_batch_storage(
                    pair.id, attempt_id, is_backfill=False
                ).cleanup_all_batches()
            db_session.query(IndexAttempt).filter(
                IndexAttempt.connector_credential_pair_id == pair.id
            ).delete(synchronize_session="fetch")
            db_session.query(DBHierarchyNode).filter(
                DBHierarchyNode.raw_node_id == run.connector.folder_id
            ).delete(synchronize_session="fetch")
            db_session.commit()
            source = pair.connector.source
            cleanup_cc_pair(db_session, pair)
            # The node rows are gone, so the cache must not name them.
            invalidate_hierarchy_cache_for_source(get_redis_client(), source)


def test_list_stub_batches_sends_a_folder_before_the_stubs_under_it() -> None:
    connector = _FakeLister("order", doc_count=3)

    items = list(
        list_stub_batches(
            connector,
            ConnectorCheckpoint(has_more=True),
            datetime.fromtimestamp(0, tz=timezone.utc),
            _WINDOW_END,
            batch_size=2,
        )
    )

    stub_batches = [[stub.id for stub in stubs] for stubs, _, _, _ in items if stubs]
    assert stub_batches == [connector.doc_ids[:2], connector.doc_ids[2:]]
    # The folder goes out before the first stub batch, and the checkpoint last.
    assert items[0][1] is not None and items[0][1][0].raw_node_id == connector.folder_id
    assert items[-1][3] == ConnectorCheckpoint(has_more=False)
    assert all(checkpoint is None for _, _, _, checkpoint in items[:-1])
    # The listing reads no permissions: the conversion reads them.
    assert connector.listing_permissions == [False]


def test_with_the_switch_on_docfetching_lists_and_conversion_makes_the_documents(
    run: _Run,
) -> None:
    attempt = run.add_attempt(IndexingStatus.IN_PROGRESS, _WINDOW_END)

    with patch.object(run_docfetching, "ENABLE_CONVERSION_STAGE", True):
        run.extract(attempt.id)

    # Two calls of three and two stubs, in batches of two: 2 + 1, then 2.
    doc_ids = run.connector.doc_ids
    assert run.stub_doc_ids(attempt.id, 0) == doc_ids[0:2]
    assert run.stub_doc_ids(attempt.id, 1) == doc_ids[2:3]
    assert run.stub_doc_ids(attempt.id, 2) == doc_ids[3:5]
    row = run.attempt(attempt.id)
    assert row.uses_conversion_stage is True
    assert (row.stub_batches_stored, row.stub_batches_sent) == (3, 3)
    assert row.total_batches == 3
    assert row.last_dispatch_task_id == attempt.celery_task_id
    assert row.last_dispatch_at is not None
    # Docfetching fetched nothing and sent nothing to docprocessing.
    run.runner.run.assert_not_called()
    assert run.connector.fetch_calls == 0
    assert run.sent_batch_nums(OnyxCeleryTask.DOCPROCESSING_TASK) == []
    assert run.sent_batch_nums(OnyxCeleryTask.DOCCONVERSION_TASK) == [0, 1, 2]
    for call in run.app.send_task.call_args_list:
        assert call.kwargs["expires"] == DOCCONVERSION_TASK_EXPIRES_SECONDS
    # The folder of the listing is stored.
    assert (
        run.db_session.query(DBHierarchyNode)
        .filter(DBHierarchyNode.raw_node_id == run.connector.folder_id)
        .count()
        == 1
    )

    for batch_num in range(3):
        run.convert(attempt.id, batch_num)

    # Each listed document is in one document batch, with no gap and no copy.
    converted = [
        doc_id
        for batch_num in range(3)
        for doc_id in run.doc_batch_ids(attempt.id, batch_num)
    ]
    assert converted == doc_ids
    assert run.sent_batch_nums(OnyxCeleryTask.DOCPROCESSING_TASK) == [0, 1, 2]
    assert run.attempt(attempt.id).stub_batches_converted == 3


def test_with_the_switch_off_docfetching_fetches_the_documents(run: _Run) -> None:
    attempt = run.add_attempt(IndexingStatus.IN_PROGRESS, _WINDOW_END)

    # Off here even when the environment turns the switch on.
    with patch.object(run_docfetching, "ENABLE_CONVERSION_STAGE", False):
        run.extract(attempt.id)

    row = run.attempt(attempt.id)
    assert row.uses_conversion_stage is False
    assert row.stub_batches_stored == 0
    assert run.connector.listing_permissions == []
    assert run.sent_batch_nums(OnyxCeleryTask.DOCCONVERSION_TASK) == []
    assert run.sent_batch_nums(OnyxCeleryTask.DOCPROCESSING_TASK) == [0]
    assert run.doc_batch_ids(attempt.id, 0) == run.connector.doc_ids


def _failed_lister_attempt(run: _Run, uses_conversion_stage: bool) -> IndexAttempt:
    """A failed attempt that completed two batches and left two stub batches
    that no task converted."""
    failed = run.add_attempt(
        IndexingStatus.FAILED,
        _WINDOW_END,
        poll_range_start=datetime.fromtimestamp(0, tz=timezone.utc),
        poll_range_end=_WINDOW_END,
        completed_batches=2,
        uses_conversion_stage=uses_conversion_stage,
    )
    old_stubs = get_stub_batch_storage(run.pair.id, failed.id, is_backfill=False)
    for batch_num in (3, 7):
        old_stubs.store_batch(
            batch_num,
            [
                SlimDocumentStub(
                    id=f"old_{run.tag}_{batch_num}",
                    listing_payload=_Payload(title="old"),
                )
            ],
        )
    return failed


def test_an_attempt_that_continues_takes_over_the_stub_batches(run: _Run) -> None:
    failed = _failed_lister_attempt(run, uses_conversion_stage=True)
    attempt = run.add_attempt(
        IndexingStatus.IN_PROGRESS, _WINDOW_END + timedelta(seconds=5)
    )
    # The failed attempt listed the first three documents.
    run.connector.listed = 3

    with (
        patch.object(run_docfetching, "ENABLE_CONVERSION_STAGE", True),
        patch.object(
            run_docfetching,
            "get_latest_valid_checkpoint",
            return_value=(ConnectorCheckpoint(has_more=True), True),
        ),
    ):
        run.extract(attempt.id)

    # The two old stub batches follow the two completed batches, in their old
    # order. The new stub batch follows them.
    assert run.stub_doc_ids(attempt.id, 2) == [f"old_{run.tag}_3"]
    assert run.stub_doc_ids(attempt.id, 3) == [f"old_{run.tag}_7"]
    assert run.stub_doc_ids(attempt.id, 4) == run.connector.doc_ids[3:5]
    assert (
        get_stub_batch_storage(
            run.pair.id, failed.id, is_backfill=False
        ).stored_batch_nums()
        == set()
    )
    row = run.attempt(attempt.id)
    assert (row.stub_batches_stored, row.stub_batches_sent) == (5, 5)
    assert row.stub_batches_converted == 2
    assert row.completed_batches == 2
    assert row.total_batches == 5
    assert run.sent_batch_nums(OnyxCeleryTask.DOCCONVERSION_TASK) == [2, 3, 4]


def test_a_change_of_the_switch_starts_the_listing_again(run: _Run) -> None:
    failed = _failed_lister_attempt(run, uses_conversion_stage=False)
    attempt = run.add_attempt(
        IndexingStatus.IN_PROGRESS, _WINDOW_END + timedelta(seconds=5)
    )

    with (
        patch.object(run_docfetching, "ENABLE_CONVERSION_STAGE", True),
        patch.object(run_docfetching, "get_latest_valid_checkpoint") as load,
    ):
        run.extract(attempt.id)

    # A checkpoint of a fetch cannot continue a listing.
    load.assert_not_called()
    assert (
        get_stub_batch_storage(
            run.pair.id, failed.id, is_backfill=False
        ).stored_batch_nums()
        == set()
    )
    row = run.attempt(attempt.id)
    assert row.total_batches == 3
    assert run.sent_batch_nums(OnyxCeleryTask.DOCCONVERSION_TASK) == [0, 1, 2]
