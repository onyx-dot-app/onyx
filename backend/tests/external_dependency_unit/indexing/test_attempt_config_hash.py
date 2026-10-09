"""An index attempt stores the hash of the connector config it ran with. A later
attempt reuses its checkpoint and poll window only with the same config, or when
the stored hash is NULL (attempts created before the hash existed)."""

from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.background.indexing.checkpointing_utils import get_latest_valid_checkpoint
from onyx.background.indexing.run_docfetching import connector_document_extraction
from onyx.connectors.config_hash import compute_connector_config_hash
from onyx.connectors.models import ConnectorCheckpoint
from onyx.db.enums import IndexingStatus
from onyx.db.index_attempt import (
    create_synthetic_seed_attempt,
    mock_successful_index_attempt,
)
from onyx.db.indexing_coordination import IndexingCoordination
from onyx.db.models import (
    ConnectorCredentialPair,
    IndexAttempt,
    TargetedReindexJob,
    TargetedReindexJobTarget,
)
from onyx.db.search_settings import get_current_search_settings
from onyx.db.targeted_reindex import TargetSpec, create_targeted_reindex_job
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from tests.external_dependency_unit.indexing_helpers import (
    cleanup_cc_pair,
    make_cc_pair,
)

_CONFIG: dict[str, Any] = {"channels": ["general"], "include_bots": False}
_OTHER_CONFIG_HASH = compute_connector_config_hash({"channels": ["random"]})
_RUN_DOCFETCHING = "onyx.background.indexing.run_docfetching"


class _PreviousHash(str, Enum):
    SAME = "same"
    OTHER = "other"
    NULL = "null"


def _previous_hash(kind: _PreviousHash) -> str | None:
    if kind == _PreviousHash.SAME:
        return compute_connector_config_hash(_CONFIG)
    if kind == _PreviousHash.OTHER:
        return _OTHER_CONFIG_HASH
    return None


@pytest.fixture
def cc_pair(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[ConnectorCredentialPair, None, None]:
    pair = make_cc_pair(db_session)
    pair.connector.connector_specific_config = _CONFIG
    db_session.commit()
    try:
        yield pair
    finally:
        db_session.rollback()
        job_ids = [
            job_id
            for (job_id,) in db_session.query(IndexAttempt.targeted_reindex_job_id)
            .filter(
                IndexAttempt.connector_credential_pair_id == pair.id,
                IndexAttempt.targeted_reindex_job_id.isnot(None),
            )
            .all()
        ]
        db_session.query(TargetedReindexJobTarget).filter(
            TargetedReindexJobTarget.cc_pair_id == pair.id
        ).delete(synchronize_session="fetch")
        db_session.query(IndexAttempt).filter(
            IndexAttempt.connector_credential_pair_id == pair.id
        ).delete(synchronize_session="fetch")
        db_session.query(TargetedReindexJob).filter(
            TargetedReindexJob.id.in_(job_ids)
        ).delete(synchronize_session="fetch")
        db_session.commit()
        cleanup_cc_pair(db_session, pair)


def _add_finished_attempt(
    db_session: Session,
    cc_pair_id: int,
    search_settings_id: int,
    connector_config_hash: str | None,
    poll_range_start: datetime,
    poll_range_end: datetime,
) -> IndexAttempt:
    attempt = IndexAttempt(
        connector_credential_pair_id=cc_pair_id,
        search_settings_id=search_settings_id,
        from_beginning=False,
        status=IndexingStatus.FAILED,
        poll_range_start=poll_range_start,
        poll_range_end=poll_range_end,
        checkpoint_pointer=f"checkpoint_test_{uuid4().hex[:8]}.json",
        connector_config_hash=connector_config_hash,
    )
    db_session.add(attempt)
    db_session.commit()
    return attempt


def test_every_creation_path_stamps_config_hash(
    db_session: Session, cc_pair: ConnectorCredentialPair
) -> None:
    search_settings_id = get_current_search_settings(db_session).id
    expected_hash = compute_connector_config_hash(_CONFIG)

    coordinated_id = IndexingCoordination.try_create_index_attempt(
        db_session=db_session,
        cc_pair_id=cc_pair.id,
        search_settings_id=search_settings_id,
        celery_task_id=None,
    )
    seed_id = create_synthetic_seed_attempt(
        connector_credential_pair_id=cc_pair.id,
        search_settings_id=search_settings_id,
        db_session=db_session,
        poll_range_end=datetime.now(tz=timezone.utc).timestamp(),
    )
    db_session.commit()
    mock_success_id = mock_successful_index_attempt(
        connector_credential_pair_id=cc_pair.id,
        search_settings_id=search_settings_id,
        docs_indexed=1,
        db_session=db_session,
    )
    targeted = create_targeted_reindex_job(
        db_session=db_session,
        requested_by_user_id=None,
        targets=[TargetSpec(cc_pair_id=cc_pair.id, document_id="doc-1")],
    )

    assert coordinated_id is not None
    attempt_ids = [
        coordinated_id,
        seed_id,
        mock_success_id,
        *targeted.synthetic_attempt_ids,
    ]
    attempts = (
        db_session.query(IndexAttempt).filter(IndexAttempt.id.in_(attempt_ids)).all()
    )
    assert len(attempts) == len(attempt_ids)
    assert all(a.connector_config_hash == expected_hash for a in attempts)


@pytest.mark.parametrize(
    "previous_hash,expect_resume",
    [
        (_PreviousHash.SAME, True),
        (_PreviousHash.OTHER, False),
        (_PreviousHash.NULL, True),
    ],
)
def test_checkpoint_reused_only_with_matching_config(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    previous_hash: _PreviousHash,
    expect_resume: bool,
) -> None:
    search_settings_id = get_current_search_settings(db_session).id
    window_start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    window_end = window_start + timedelta(days=1)
    candidate = _add_finished_attempt(
        db_session,
        cc_pair_id=cc_pair.id,
        search_settings_id=search_settings_id,
        connector_config_hash=_previous_hash(previous_hash),
        poll_range_start=window_start,
        poll_range_end=window_end,
    )
    saved_checkpoint = ConnectorCheckpoint(has_more=True)
    dummy_checkpoint = ConnectorCheckpoint(has_more=True)
    connector = MagicMock()
    connector.build_dummy_checkpoint.return_value = dummy_checkpoint

    with patch(
        "onyx.background.indexing.checkpointing_utils.load_checkpoint",
        return_value=saved_checkpoint,
    ) as mock_load_checkpoint:
        checkpoint, resuming = get_latest_valid_checkpoint(
            db_session=db_session,
            cc_pair_id=cc_pair.id,
            search_settings_id=search_settings_id,
            window_start=window_start,
            window_end=window_end,
            connector=connector,
            connector_config_hash=compute_connector_config_hash(_CONFIG),
        )

    assert resuming is expect_resume
    if expect_resume:
        assert checkpoint is saved_checkpoint
        assert mock_load_checkpoint.call_args.kwargs["index_attempt_id"] == (
            candidate.id
        )
    else:
        assert checkpoint is dummy_checkpoint
        mock_load_checkpoint.assert_not_called()


@pytest.mark.parametrize(
    "previous_hash,expect_reuse",
    [
        (_PreviousHash.SAME, True),
        (_PreviousHash.OTHER, False),
        (_PreviousHash.NULL, True),
    ],
)
@patch(f"{_RUN_DOCFETCHING}.get_document_batch_storage")
@patch(f"{_RUN_DOCFETCHING}.MemoryTracer")
@patch(f"{_RUN_DOCFETCHING}._get_connector_runner")
@patch(f"{_RUN_DOCFETCHING}.strip_null_characters", side_effect=lambda batch: batch)
@patch(f"{_RUN_DOCFETCHING}.get_last_successful_attempt_poll_range_end")
@patch(f"{_RUN_DOCFETCHING}.save_checkpoint")
@patch(f"{_RUN_DOCFETCHING}.get_latest_valid_checkpoint")
@patch(f"{_RUN_DOCFETCHING}.get_redis_client")
@patch(f"{_RUN_DOCFETCHING}.ensure_source_node_exists")
@patch(f"{_RUN_DOCFETCHING}.get_source_node_id_from_cache")
@patch(f"{_RUN_DOCFETCHING}.get_node_id_from_raw_id")
@patch(f"{_RUN_DOCFETCHING}.cache_hierarchy_nodes_batch")
def test_window_and_checkpoint_reused_only_with_matching_config(
    mock_cache_hierarchy_nodes_batch: MagicMock,  # noqa: ARG001
    mock_get_node_id_from_raw_id: MagicMock,
    mock_get_source_node_id_from_cache: MagicMock,
    mock_ensure_source_node_exists: MagicMock,
    mock_get_redis_client: MagicMock,
    mock_get_latest_valid_checkpoint: MagicMock,
    mock_save_checkpoint: MagicMock,  # noqa: ARG001
    mock_get_last_successful_attempt_poll_range_end: MagicMock,
    mock_strip_null_characters: MagicMock,  # noqa: ARG001
    mock_get_connector_runner: MagicMock,
    mock_memory_tracer_class: MagicMock,  # noqa: ARG001
    mock_get_batch_storage: MagicMock,
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    previous_hash: _PreviousHash,
    expect_reuse: bool,
) -> None:
    search_settings_id = get_current_search_settings(db_session).id
    previous_window_end = datetime(2026, 1, 2, tzinfo=timezone.utc)
    _add_finished_attempt(
        db_session,
        cc_pair_id=cc_pair.id,
        search_settings_id=search_settings_id,
        connector_config_hash=_previous_hash(previous_hash),
        poll_range_start=datetime.fromtimestamp(0, tz=timezone.utc),
        poll_range_end=previous_window_end,
    )
    attempt = IndexAttempt(
        connector_credential_pair_id=cc_pair.id,
        search_settings_id=search_settings_id,
        from_beginning=False,
        status=IndexingStatus.IN_PROGRESS,
        celery_task_id=f"test_celery_task_{uuid4().hex[:8]}",
    )
    db_session.add(attempt)
    db_session.commit()

    mock_get_batch_storage.return_value = MagicMock()
    mock_get_redis_client.return_value = MagicMock()
    mock_ensure_source_node_exists.return_value = 1
    mock_get_source_node_id_from_cache.return_value = 1
    mock_get_node_id_from_raw_id.return_value = (None, False)
    mock_get_last_successful_attempt_poll_range_end.return_value = 0
    mock_get_latest_valid_checkpoint.return_value = (MagicMock(has_more=True), False)

    mock_doc = MagicMock()
    mock_doc.to_short_descriptor.return_value = "test_doc"
    mock_doc.sections = []
    mock_doc.parent_hierarchy_raw_node_id = None
    mock_doc.parent_hierarchy_node_id = None
    connector_runner = MagicMock()
    connector_runner.run.return_value = iter(
        [([mock_doc], None, None, MagicMock(has_more=False))]
    )
    mock_get_connector_runner.return_value = connector_runner

    started_at = datetime.now(tz=timezone.utc)
    connector_document_extraction(
        app=MagicMock(),
        index_attempt_id=attempt.id,
        cc_pair_id=cc_pair.id,
        search_settings_id=search_settings_id,
        tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE,
        callback=None,
    )

    db_session.expire_all()
    refreshed = db_session.get(IndexAttempt, attempt.id)
    assert refreshed is not None
    assert refreshed.connector_config_hash == compute_connector_config_hash(_CONFIG)
    assert refreshed.poll_range_end is not None
    if expect_reuse:
        assert refreshed.poll_range_end == previous_window_end
        mock_get_latest_valid_checkpoint.assert_called_once()
    else:
        assert refreshed.poll_range_end >= started_at
        mock_get_latest_valid_checkpoint.assert_not_called()
        connector_runner.connector.build_dummy_checkpoint.assert_called_once()
