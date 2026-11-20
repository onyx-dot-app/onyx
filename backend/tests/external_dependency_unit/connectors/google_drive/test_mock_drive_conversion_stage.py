"""The conversion stage end to end with the real Google Drive connector and the
mock Drive server: docfetching lists the corpus as stub batches, and the
conversion tasks turn them into document batches. Every file of the corpus is
in one document batch, one time.

Celery is a recording app: the test runs each conversion task that the lister
or another conversion task sends, until no task is left."""

import json
import re
from collections.abc import Generator
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.background.indexing import run_docconversion, run_docfetching
from onyx.background.indexing.checkpointing_utils import cleanup_checkpoint
from onyx.background.indexing.run_docconversion import convert_stub_batch
from onyx.background.indexing.run_docfetching import connector_document_extraction
from onyx.configs.constants import DocumentSource, OnyxCeleryTask
from onyx.connectors.models import InputType
from onyx.db.enums import IndexingStatus
from onyx.db.models import (
    HierarchyNode,
    HierarchyNodeByConnectorCredentialPair,
    IndexAttempt,
    IndexAttemptError,
)
from onyx.db.search_settings import get_current_search_settings
from onyx.file_store.document_batch_storage import (
    get_document_batch_storage,
    get_stub_batch_storage,
)
from onyx.file_store.staging import cleanup_staged_files_for_attempt
from onyx.redis.redis_docprocessing import RedisDocprocessing
from onyx.redis.redis_hierarchy import invalidate_hierarchy_cache_for_source
from onyx.redis.redis_pool import get_redis_client
from shared_configs.contextvars import get_current_tenant_id
from tests.external_dependency_unit.connectors.google_drive.conftest import MockDrive
from tests.external_dependency_unit.indexing_helpers import (
    cleanup_cc_pair,
    make_cc_pair,
)

_FILE_ID = re.compile(r"/d/([A-Za-z0-9_-]+)")


def _sent_batch_nums(app: MagicMock, task: str) -> list[int]:
    return [
        call.kwargs["kwargs"]["batch_num"]
        for call in app.send_task.call_args_list
        if call.args[0] == task
    ]


@pytest.fixture
def drive_pair(
    mock_drive: MockDrive,
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[tuple[int, list[int]], None, None]:
    """A Google Drive cc_pair with the mock's service account. Yields its id
    and a list that collects the attempt ids to clean up."""
    nodes_before = {
        node_id
        for (node_id,) in db_session.query(HierarchyNode.id)
        .filter(HierarchyNode.source == DocumentSource.GOOGLE_DRIVE)
        .all()
    }
    pair = make_cc_pair(db_session, DocumentSource.GOOGLE_DRIVE)
    pair.connector.input_type = InputType.POLL
    pair.connector.connector_specific_config = {
        "include_shared_drives": True,
        "include_my_drives": True,
        "include_files_shared_with_me": True,
    }
    pair.credential.credential_json = {  # ty: ignore[invalid-assignment]
        "google_service_account_key": json.dumps(
            mock_drive.client.get("/_mock/service-account-key").json()
        ),
        "google_primary_admin": mock_drive.client.get("/_mock/corpus/summary").json()[
            "admin_email"
        ],
        "authentication_method": "uploaded",
    }
    db_session.commit()
    attempt_ids: list[int] = []
    run_docconversion.clear_conversion_context_cache()
    try:
        yield pair.id, attempt_ids
    finally:
        run_docconversion.clear_conversion_context_cache()
        db_session.rollback()
        for attempt_id in attempt_ids:
            cleanup_checkpoint(db_session, attempt_id)
            cleanup_staged_files_for_attempt(attempt_id, db_session)
            RedisDocprocessing(attempt_id, get_redis_client()).cleanup()
            get_document_batch_storage(
                pair.id, attempt_id, is_backfill=False
            ).cleanup_all_batches()
            get_stub_batch_storage(
                pair.id, attempt_id, is_backfill=False
            ).cleanup_all_batches()
        db_session.query(IndexAttempt).filter(
            IndexAttempt.connector_credential_pair_id == pair.id
        ).delete(synchronize_session="fetch")
        db_session.query(HierarchyNodeByConnectorCredentialPair).filter(
            HierarchyNodeByConnectorCredentialPair.connector_id == pair.connector_id,
            HierarchyNodeByConnectorCredentialPair.credential_id == pair.credential_id,
        ).delete(synchronize_session="fetch")
        db_session.query(HierarchyNode).filter(
            HierarchyNode.source == DocumentSource.GOOGLE_DRIVE,
            HierarchyNode.id.not_in(nodes_before),
        ).delete(synchronize_session="fetch")
        db_session.commit()
        cleanup_cc_pair(db_session, pair)
        invalidate_hierarchy_cache_for_source(
            get_redis_client(), DocumentSource.GOOGLE_DRIVE
        )


def test_conversion_stage_indexes_every_mock_drive_file_once(
    mock_drive: MockDrive,
    db_session: Session,
    drive_pair: tuple[int, list[int]],
) -> None:
    pair_id, attempt_ids = drive_pair
    tenant_id = get_current_tenant_id()
    attempt = IndexAttempt(
        connector_credential_pair_id=pair_id,
        search_settings_id=get_current_search_settings(db_session).id,
        status=IndexingStatus.IN_PROGRESS,
        celery_task_id=f"task_{uuid4().hex[:8]}",
        time_created=datetime.now(timezone.utc),
        from_beginning=True,
    )
    db_session.add(attempt)
    db_session.commit()
    attempt_ids.append(attempt.id)

    connector = mock_drive.build_connector()
    runner = MagicMock()
    runner.connector = connector
    app = MagicMock()
    with (
        patch.object(run_docfetching, "ENABLE_CONVERSION_STAGE", True),
        patch.object(run_docfetching, "_get_connector_runner", return_value=runner),
        patch.object(run_docfetching, "MemoryTracer"),
        patch.object(run_docfetching, "INDEX_BATCH_SIZE", 7),
        patch.object(run_docconversion, "DOCCONVERSION_WINDOW_BATCHES", 3),
    ):
        connector_document_extraction(
            app=app,
            index_attempt_id=attempt.id,
            cc_pair_id=pair_id,
            search_settings_id=attempt.search_settings_id,
            tenant_id=tenant_id,
            callback=None,
        )
        # Run each conversion task once, in the order it was sent. A task
        # sends the next stub batches when it ends.
        converted: list[int] = []
        while len(
            sent := _sent_batch_nums(app, OnyxCeleryTask.DOCCONVERSION_TASK)
        ) > len(converted):
            batch_num = sent[len(converted)]
            convert_stub_batch(
                app,
                index_attempt_id=attempt.id,
                cc_pair_id=pair_id,
                tenant_id=tenant_id,
                batch_num=batch_num,
            )
            converted.append(batch_num)

    runner.run.assert_not_called()
    db_session.expire_all()
    row = db_session.get(IndexAttempt, attempt.id)
    assert row is not None
    assert row.uses_conversion_stage is True
    assert row.stub_batches_stored > 3
    assert (
        row.stub_batches_stored
        == row.stub_batches_sent
        == row.stub_batches_converted
        == row.total_batches
    )
    assert sorted(converted) == list(range(row.stub_batches_stored))
    assert (
        db_session.query(IndexAttemptError)
        .filter(IndexAttemptError.index_attempt_id == attempt.id)
        .count()
        == 0
    )

    doc_storage = get_document_batch_storage(pair_id, attempt.id, is_backfill=False)
    file_ids: list[str] = []
    for batch_num in _sent_batch_nums(app, OnyxCeleryTask.DOCPROCESSING_TASK):
        documents = doc_storage.get_batch(batch_num)
        assert documents is not None
        for document in documents:
            match = _FILE_ID.search(document.id)
            assert match is not None, document.id
            file_ids.append(match.group(1))
    assert len(file_ids) == len(set(file_ids))
    assert set(file_ids) == mock_drive.content_file_ids()
