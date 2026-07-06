"""External dependency unit tests for the reindexing-port DB layer.

Scoped to behavior/invariants worth guarding (the column existence + defaults are
covered by applying the migration, which this repo does not test programmatically):
- the partial-unique "one active attempt per (cc_pair, FUTURE)" index — and that
  its predicate matches the stored (uppercase) enum name, not the value
- the PortAttempt lifecycle helpers (create -> in_progress -> cursor -> terminal)
  and first-terminal-write-wins
- mark_document_synced_secondary_pending sets the flag (and clears needs-sync),
  and a later mark_document_as_synced clears it again
- the synthetic seed: writer row shape, seed-blind filtering for counts/latest/swap (a
  seed must not count toward the swap or appear as the latest run) while it DOES prime the
  resume poll cursor, and the gated should_index FUTURE branch (legacy once-only vs
  port-flow continuous)
- run_port_attempt: ports docs in batches, advances/commits the cursor, retries a
  failed batch then marks FAILED (cursor left at the prior good batch)
"""

from collections.abc import Generator
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import cast
from unittest.mock import MagicMock
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from onyx.background.celery.tasks.beat_schedule import BEAT_EXPIRES_DEFAULT
from onyx.background.celery.tasks.docprocessing.utils import should_index
from onyx.background.celery.tasks.port import tasks as port_task
from onyx.background.celery.tasks.port.tasks import run_check_for_port
from onyx.background.celery.tasks.port.tasks import run_port_attempt
from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.app_configs import MAX_CONCURRENT_PORT_ATTEMPTS
from onyx.configs.constants import OnyxCeleryQueues
from onyx.configs.constants import OnyxCeleryTask
from onyx.context.search.models import SavedSearchSettings
from onyx.db import port_attempt as port_attempt_db
from onyx.db.connector_credential_pair import get_last_successful_attempt_poll_range_end
from onyx.db.document import document_has_indexable_cc_pair
from onyx.db.document import filter_existing_cc_pair_document_ids
from onyx.db.document import get_document_ids_for_cc_pair_batch
from onyx.db.document import get_max_document_id_for_cc_pair
from onyx.db.document import mark_document_as_modified
from onyx.db.document import mark_document_as_synced
from onyx.db.document import mark_document_synced_secondary_pending
from onyx.db.enums import ConnectorCredentialPairStatus
from onyx.db.enums import EmbeddingPrecision
from onyx.db.enums import IndexingStatus
from onyx.db.enums import IndexModelStatus
from onyx.db.enums import PortAttemptStatus
from onyx.db.index_attempt import (
    count_unique_active_cc_pairs_with_successful_index_attempts,
)
from onyx.db.index_attempt import count_unique_cc_pairs_with_successful_index_attempts
from onyx.db.index_attempt import create_synthetic_seed_attempt
from onyx.db.index_attempt import get_latest_successful_index_attempt_for_cc_pair_id
from onyx.db.index_attempt import mock_successful_index_attempt
from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import Document as DbDocument
from onyx.db.models import DocumentByConnectorCredentialPair
from onyx.db.models import IndexAttempt
from onyx.db.models import PortAttempt
from onyx.db.models import SearchSettings
from onyx.db.port_attempt import cancel_active_port_attempts
from onyx.db.port_attempt import commit_port_cursor
from onyx.db.port_attempt import count_consecutive_failed_port_attempts_no_progress
from onyx.db.port_attempt import create_port_attempt
from onyx.db.port_attempt import get_active_port_attempt
from onyx.db.port_attempt import get_latest_port_attempt
from onyx.db.port_attempt import mark_port_canceled
from onyx.db.port_attempt import mark_port_failed
from onyx.db.port_attempt import mark_port_in_progress
from onyx.db.port_attempt import mark_port_succeeded
from onyx.db.port_attempt import port_backfill_has_pending_work
from onyx.db.port_attempt import request_port_cancel
from onyx.db.search_settings import create_search_settings
from onyx.db.search_settings import get_current_search_settings
from onyx.db.swap_index import _port_swap_ready
from onyx.document_index.opensearch import port_copy
from onyx.document_index.opensearch.port_copy import copy_present_chunks_to_future
from onyx.indexing.port_reembed import ReembedStrategy
from onyx.kg.models import KGStage
from shared_configs.contextvars import get_current_tenant_id
from tests.external_dependency_unit.indexing_helpers import cleanup_cc_pair
from tests.external_dependency_unit.indexing_helpers import cleanup_cc_pair_and_future
from tests.external_dependency_unit.indexing_helpers import make_cc_pair
from tests.external_dependency_unit.indexing_helpers import make_future_search_settings
from tests.external_dependency_unit.indexing_helpers import (
    seed_cc_pair_documents as _seed_cc_pair_documents,
)


def _run_check_for_port(
    cc_pair: ConnectorCredentialPair,
    future_id: int,
    celery_app: MagicMock | None = None,
) -> tuple[int | None, MagicMock]:
    """Run check_for_port scoped to this test's FUTURE + cc_pair (the real
    get_secondary/fetch helpers are global). Returns (result, celery_app)."""
    celery_app = celery_app or MagicMock()
    with (
        patch.object(
            port_task,
            "get_secondary_search_settings",
            lambda db, *_, **__: db.get(SearchSettings, future_id),
        ),
        patch.object(
            port_task,
            "fetch_indexable_standard_connector_credential_pair_ids",
            lambda *_, **__: [cc_pair.id],
        ),
    ):
        result = run_check_for_port(get_current_tenant_id(), celery_app)
    return result, celery_app


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
        db_session.query(PortAttempt).filter(PortAttempt.cc_pair_id == pair.id).delete(
            synchronize_session="fetch"
        )
        db_session.commit()
        cleanup_cc_pair(db_session, pair)


def test_port_attempt_active_unique_constraint(
    db_session: Session, cc_pair: ConnectorCredentialPair
) -> None:
    """At most one active (NOT_STARTED/IN_PROGRESS) attempt per (cc_pair, FUTURE);
    terminal rows may coexist. Also guards the index predicate against the stored
    enum casing (uppercase name) — a lowercase predicate would silently no-op."""
    ss = get_current_search_settings(db_session)

    db_session.add(
        PortAttempt(
            cc_pair_id=cc_pair.id,
            search_settings_id=ss.id,
            status=PortAttemptStatus.IN_PROGRESS,
        )
    )
    db_session.commit()

    db_session.add(
        PortAttempt(
            cc_pair_id=cc_pair.id,
            search_settings_id=ss.id,
            status=PortAttemptStatus.NOT_STARTED,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    # a terminal attempt for the same pair is allowed (outside the predicate)
    db_session.add(
        PortAttempt(
            cc_pair_id=cc_pair.id,
            search_settings_id=ss.id,
            status=PortAttemptStatus.SUCCESS,
        )
    )
    db_session.commit()

    active = (
        db_session.query(PortAttempt)
        .filter(
            PortAttempt.cc_pair_id == cc_pair.id,
            PortAttempt.status.in_(
                [PortAttemptStatus.NOT_STARTED, PortAttemptStatus.IN_PROGRESS]
            ),
        )
        .count()
    )
    assert active == 1


def test_mark_secondary_pending_then_synced_clears_it(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    doc_id = "test-secondary-pending-doc"
    db_session.add(
        DbDocument(id=doc_id, semantic_id=doc_id, kg_stage=KGStage.NOT_STARTED)
    )
    db_session.commit()
    try:
        mark_document_as_modified(doc_id, db_session)  # needs-sync

        # PRESENT synced but FUTURE missing -> defer
        mark_document_synced_secondary_pending(doc_id, db_session)
        db_session.expire_all()
        row = db_session.query(DbDocument).filter(DbDocument.id == doc_id).one()
        assert row.last_synced is not None and row.last_modified is not None
        assert row.last_synced >= row.last_modified  # needs-sync cleared
        assert row.secondary_only_sync_pending is True

        # a later full sync reaches FUTURE -> flag flips back to False
        mark_document_as_synced(doc_id, db_session)
        db_session.expire_all()
        row = db_session.query(DbDocument).filter(DbDocument.id == doc_id).one()
        assert row.secondary_only_sync_pending is False
    finally:
        db_session.query(DbDocument).filter(DbDocument.id == doc_id).delete(
            synchronize_session="fetch"
        )
        db_session.commit()


def test_mark_secondary_pending_raises_on_missing_document(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    with pytest.raises(ValueError):
        mark_document_synced_secondary_pending("does-not-exist", db_session)


def test_port_attempt_lifecycle_helpers(
    db_session: Session, cc_pair: ConnectorCredentialPair
) -> None:
    """create -> in_progress -> cursor commit -> success; get_active tracks the
    active attempt and stops returning it once the attempt is terminal."""
    ss = get_current_search_settings(db_session)

    attempt = create_port_attempt(db_session, cc_pair.id, ss.id, celery_task_id="t-1")
    attempt_id = attempt.id
    assert attempt.status == PortAttemptStatus.NOT_STARTED
    assert get_active_port_attempt(db_session, cc_pair.id, ss.id) is not None

    mark_port_in_progress(db_session, attempt_id, celery_task_id="t-1")
    commit_port_cursor(
        db_session, attempt_id, last_processed_doc_id="doc-50", docs_ported=50
    )
    db_session.expire_all()
    row = db_session.get(PortAttempt, attempt_id)
    assert row is not None
    assert row.status == PortAttemptStatus.IN_PROGRESS
    assert row.last_processed_doc_id == "doc-50"
    assert row.docs_ported == 50
    assert row.time_started is not None and row.last_progress_time is not None

    # a second cursor commit advances the (absolute) cumulative counter
    commit_port_cursor(
        db_session, attempt_id, last_processed_doc_id="doc-80", docs_ported=80
    )
    db_session.expire_all()
    row = db_session.get(PortAttempt, attempt_id)
    assert row is not None
    assert row.last_processed_doc_id == "doc-80" and row.docs_ported == 80

    mark_port_succeeded(db_session, attempt_id)
    db_session.expire_all()
    row = db_session.get(PortAttempt, attempt_id)
    assert row is not None
    assert row.status == PortAttemptStatus.SUCCESS
    assert row.time_completed is not None
    # terminal attempts are no longer "active"
    assert get_active_port_attempt(db_session, cc_pair.id, ss.id) is None


def test_port_attempt_terminal_is_first_write_wins(
    db_session: Session, cc_pair: ConnectorCredentialPair
) -> None:
    """A terminal attempt ignores later transitions, so a late task SUCCESS can't
    clobber a watchdog FAILED (the row lock makes this deterministic)."""
    ss = get_current_search_settings(db_session)
    attempt = create_port_attempt(db_session, cc_pair.id, ss.id)
    mark_port_in_progress(db_session, attempt.id)

    mark_port_failed(db_session, attempt.id, error_msg="stalled")
    mark_port_succeeded(db_session, attempt.id)  # no-op: already terminal

    db_session.expire_all()
    row = db_session.get(PortAttempt, attempt.id)
    assert row is not None
    assert row.status == PortAttemptStatus.FAILED
    assert row.error_msg == "stalled"


@pytest.fixture
def cc_pair_and_future(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[tuple[ConnectorCredentialPair, int], None, None]:
    """A cc_pair plus an isolated FUTURE SearchSettings (unique index_name) so the
    global count/cursor helpers see only this test's attempts."""
    pair = make_cc_pair(db_session)
    future_id = make_future_search_settings(db_session).id
    try:
        yield pair, future_id
    finally:
        cleanup_cc_pair_and_future(db_session, pair, future_id)


def test_use_port_flow_default_and_round_trip(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    """use_port_flow persists as False via the server default when the saved model
    omits it, and an explicit True round-trips through a fresh read + the
    SavedSearchSettings mapper the port flow uses. PAST status avoids the
    PRESENT-uniqueness + concurrent-FUTURE collisions a round-trip test would hit.
    """

    def _saved() -> SavedSearchSettings:
        # Minimal explicit settings (not a clone of the polluted live row) so the
        # omitted use_port_flow falls through to the server default.
        return SavedSearchSettings(
            model_name="test-port-flow-model",
            model_dim=128,
            normalize=True,
            query_prefix="",
            passage_prefix="",
            provider_type=None,
            multipass_indexing=False,
            embedding_precision=EmbeddingPrecision.FLOAT,
            index_name=f"test_port_flow_{uuid4().hex[:8]}",
            enable_contextual_rag=False,
        )

    default_id = create_search_settings(
        _saved(), db_session, status=IndexModelStatus.PAST
    ).id
    true_id = create_search_settings(
        _saved().model_copy(update={"use_port_flow": True}),
        db_session,
        status=IndexModelStatus.PAST,
    ).id
    try:
        db_session.expire_all()
        default_fresh = db_session.get(SearchSettings, default_id)
        assert default_fresh is not None and default_fresh.use_port_flow is False
        true_fresh = db_session.get(SearchSettings, true_id)
        assert true_fresh is not None and true_fresh.use_port_flow is True
        # Rehydrate through the pydantic mapper the port flow reads through.
        assert SavedSearchSettings.from_db_model(true_fresh).use_port_flow is True
    finally:
        for row_id in (default_id, true_id):
            row = db_session.get(SearchSettings, row_id)
            if row is not None:
                db_session.delete(row)
        db_session.commit()


def test_create_synthetic_seed_attempt(
    db_session: Session, cc_pair_and_future: tuple[ConnectorCredentialPair, int]
) -> None:
    cc_pair, future_id = cc_pair_and_future
    epoch = 1_700_000_000.0

    seed_id = create_synthetic_seed_attempt(
        cc_pair.id, future_id, poll_range_end=epoch, db_session=db_session
    )
    db_session.expire_all()
    seed = db_session.get(IndexAttempt, seed_id)
    assert seed is not None
    assert seed.status == IndexingStatus.SUCCESS
    assert seed.is_synthetic_seed is True
    # time_started == time_created so the swap criterion's "real attempt after the
    # port" comparison is well-defined for the run that supersedes the seed
    assert seed.time_started is not None and seed.time_created is not None
    assert seed.time_started == seed.time_created
    assert seed.poll_range_end is not None
    assert seed.poll_range_end.timestamp() == epoch


def test_seed_excluded_from_latest_and_counts(
    db_session: Session, cc_pair_and_future: tuple[ConnectorCredentialPair, int]
) -> None:
    cc_pair, future_id = cc_pair_and_future

    # only a synthetic seed exists
    create_synthetic_seed_attempt(
        cc_pair.id, future_id, poll_range_end=1000.0, db_session=db_session
    )
    db_session.expire_all()
    assert (
        count_unique_cc_pairs_with_successful_index_attempts(future_id, db_session) == 0
    )
    assert (
        count_unique_active_cc_pairs_with_successful_index_attempts(
            future_id, db_session
        )
        == 0
    )
    assert (
        get_latest_successful_index_attempt_for_cc_pair_id(
            db_session, cc_pair.id, secondary_index=True
        )
        is None
    )

    # a real SUCCESS attempt IS counted and returned
    real_id = mock_successful_index_attempt(
        cc_pair.id, future_id, docs_indexed=5, db_session=db_session
    )
    db_session.expire_all()
    assert (
        count_unique_cc_pairs_with_successful_index_attempts(future_id, db_session) == 1
    )
    latest = get_latest_successful_index_attempt_for_cc_pair_id(
        db_session, cc_pair.id, secondary_index=True
    )
    assert latest is not None and latest.id == real_id


def test_seed_primes_poll_cursor(
    db_session: Session, cc_pair_and_future: tuple[ConnectorCredentialPair, int]
) -> None:
    """The seed IS the resume cursor: with only a seed present, the FUTURE's first
    connector attempt starts from PRESENT's cursor (carried by the seed), not the
    earliest_index fallback. A later real SUCCESS attempt then supersedes the seed."""
    cc_pair, future_id = cc_pair_and_future
    future_ss = db_session.get(SearchSettings, future_id)
    assert future_ss is not None

    seed_cursor = 1000.0
    create_synthetic_seed_attempt(
        cc_pair.id, future_id, poll_range_end=seed_cursor, db_session=db_session
    )
    db_session.expire_all()
    # resume from the seed cursor, not the earliest_index arg (42.0)
    assert (
        get_last_successful_attempt_poll_range_end(
            cc_pair.id, 42.0, future_ss, db_session
        )
        == seed_cursor
    )

    # a real SUCCESS attempt with a later cursor supersedes the seed
    later_cursor = seed_cursor + 5000.0
    real_id = mock_successful_index_attempt(
        cc_pair.id, future_id, docs_indexed=5, db_session=db_session
    )
    real = db_session.get(IndexAttempt, real_id)
    assert real is not None
    real.poll_range_end = datetime.fromtimestamp(later_cursor, tz=timezone.utc)
    db_session.commit()
    db_session.expire_all()
    assert (
        get_last_successful_attempt_poll_range_end(
            cc_pair.id, 42.0, future_ss, db_session
        )
        == later_cursor
    )


def test_should_index_future_gated_on_port_flow(
    db_session: Session, cc_pair_and_future: tuple[ConnectorCredentialPair, int]
) -> None:
    cc_pair, future_id = cc_pair_and_future
    # make the connector pollable on the continuous path
    cc_pair.connector.refresh_freq = 60
    # a real SUCCESS attempt, old enough to be re-pollable
    old = datetime.now(timezone.utc) - timedelta(hours=1)
    db_session.add(
        IndexAttempt(
            connector_credential_pair_id=cc_pair.id,
            search_settings_id=future_id,
            from_beginning=True,
            status=IndexingStatus.SUCCESS,
            time_started=old,
            time_updated=old,
        )
    )
    db_session.commit()
    future_ss = db_session.get(SearchSettings, future_id)
    assert future_ss is not None

    # legacy (flag off): one success is enough -> don't index again
    future_ss.use_port_flow = False
    db_session.commit()
    assert (
        should_index(
            cc_pair, future_ss, secondary_index_building=True, db_session=db_session
        )
        is False
    )

    # port flow (flag on): polls continuously -> index again
    future_ss.use_port_flow = True
    db_session.commit()
    assert (
        should_index(
            cc_pair, future_ss, secondary_index_building=True, db_session=db_session
        )
        is True
    )


def test_get_document_ids_for_cc_pair_batch(
    db_session: Session, cc_pair: ConnectorCredentialPair
) -> None:
    """Cursor pagination over a cc_pair's doc ids: ascending, exclusive of the
    cursor, capped at limit, empty once exhausted -> the port's resume scan."""
    doc_ids = _seed_cc_pair_documents(db_session, cc_pair, 5)

    first = get_document_ids_for_cc_pair_batch(
        db_session, cc_pair.id, after_doc_id=None, limit=2
    )
    assert first == doc_ids[:2]

    # resume past the last id of the prior page
    second = get_document_ids_for_cc_pair_batch(
        db_session, cc_pair.id, after_doc_id=first[-1], limit=2
    )
    assert second == doc_ids[2:4]

    third = get_document_ids_for_cc_pair_batch(
        db_session, cc_pair.id, after_doc_id=second[-1], limit=2
    )
    assert third == doc_ids[4:]

    # cursor at/after the last id -> exhausted
    assert (
        get_document_ids_for_cc_pair_batch(
            db_session, cc_pair.id, after_doc_id=doc_ids[-1], limit=2
        )
        == []
    )


def test_get_document_ids_for_cc_pair_batch_up_to_doc_id(
    db_session: Session, cc_pair: ConnectorCredentialPair
) -> None:
    """up_to_doc_id caps the scan at the start-of-run snapshot INCLUSIVELY, so the
    exact boundary doc is kept and docs added after the snapshot are excluded. It
    composes with the exclusive after_doc_id lower bound."""
    doc_ids = _seed_cc_pair_documents(
        db_session, cc_pair, 5, prefix="upto-", unique=True
    )

    # inclusive upper bound: the boundary id is included
    assert (
        get_document_ids_for_cc_pair_batch(
            db_session, cc_pair.id, after_doc_id=None, limit=10, up_to_doc_id=doc_ids[2]
        )
        == doc_ids[:3]
    )
    # exclusive lower + inclusive upper together
    assert (
        get_document_ids_for_cc_pair_batch(
            db_session,
            cc_pair.id,
            after_doc_id=doc_ids[0],
            limit=10,
            up_to_doc_id=doc_ids[2],
        )
        == doc_ids[1:3]
    )


def test_get_document_ids_for_cc_pair_batch_missing_cc_pair(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    """A missing cc_pair id is a caller bug, not an empty page -> raises ValueError."""
    with pytest.raises(ValueError):
        get_document_ids_for_cc_pair_batch(
            db_session, cc_pair_id=999_999_999, after_doc_id=None, limit=2
        )


def test_get_max_document_id_for_cc_pair(
    db_session: Session, cc_pair: ConnectorCredentialPair
) -> None:
    """Snapshots the lexicographic-max linked doc id (the port's start-of-run upper
    bound); None when the cc_pair has no docs."""
    assert get_max_document_id_for_cc_pair(db_session, cc_pair.id) is None

    doc_ids = _seed_cc_pair_documents(
        db_session, cc_pair, 4, prefix="maxid-", unique=True
    )
    assert get_max_document_id_for_cc_pair(db_session, cc_pair.id) == max(doc_ids)


def test_get_max_document_id_for_cc_pair_missing(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    """A missing cc_pair yields None (unlike the batch scan, which raises)."""
    assert get_max_document_id_for_cc_pair(db_session, 999_999_999) is None


def test_filter_existing_cc_pair_document_ids(
    db_session: Session, cc_pair: ConnectorCredentialPair
) -> None:
    """Keeps only ids still linked to the cc_pair, so a doc unlinked mid-batch (or a
    bogus id) is dropped rather than resurrected into FUTURE. Empty input
    short-circuits without a query."""
    doc_ids = _seed_cc_pair_documents(
        db_session, cc_pair, 3, prefix="filt-", unique=True
    )

    assert filter_existing_cc_pair_document_ids(db_session, cc_pair.id, []) == set()

    # unlink the middle doc from this cc_pair
    db_session.query(DocumentByConnectorCredentialPair).filter(
        DocumentByConnectorCredentialPair.id == doc_ids[1],
        DocumentByConnectorCredentialPair.connector_id == cc_pair.connector_id,
        DocumentByConnectorCredentialPair.credential_id == cc_pair.credential_id,
    ).delete(synchronize_session="fetch")
    db_session.commit()

    assert filter_existing_cc_pair_document_ids(
        db_session, cc_pair.id, doc_ids + ["does-not-exist"]
    ) == {doc_ids[0], doc_ids[2]}


def test_filter_existing_cc_pair_document_ids_missing_cc_pair(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    """A missing cc_pair yields the empty set — nothing is 'still linked'."""
    assert (
        filter_existing_cc_pair_document_ids(db_session, 999_999_999, ["d0"]) == set()
    )


def test_copy_present_chunks_to_future_orchestration() -> None:
    """Per batch: each PIT-scan page is re-embedded and written to FUTURE
    create-only; returns (chunks written, aborted). Mocks the OpenSearch
    read/write + re-embed (covered by their own tests)."""
    present_client = MagicMock()
    future_index = MagicMock()
    strategy = cast(ReembedStrategy, MagicMock())
    embedder = MagicMock()
    # two pages out of the PIT scan
    present_client.iter_chunks_for_doc_ids.return_value = iter([["c1", "c2"], ["c3"]])

    with patch.object(
        port_copy,
        "re_embed_chunks",
        side_effect=lambda chunks, _strategy, _embedder, **_kwargs: [
            f"re:{c}" for c in chunks
        ],
    ) as mock_reembed:
        written, aborted = copy_present_chunks_to_future(
            present_client,
            future_index,
            ["d1", "d2"],
            strategy,
            embedder,
            present_tokenizer=MagicMock(),
        )

    assert written == 3
    assert aborted is False
    present_client.iter_chunks_for_doc_ids.assert_called_once_with(["d1", "d2"])
    # re-embed once per page, with that page's chunks + prebuilt strategy/embedder
    assert mock_reembed.call_count == 2
    assert mock_reembed.call_args_list[0].args == (["c1", "c2"], strategy, embedder)
    # FUTURE write once per page, always create-only (the port never overwrites)
    assert future_index.index_raw_chunks.call_count == 2
    first_write = future_index.index_raw_chunks.call_args_list[0]
    assert first_write.args[0] == ["re:c1", "re:c2"]
    assert first_write.kwargs == {"use_create_only": True}


def test_run_port_attempt_happy_path(
    db_session: Session, cc_pair_and_future: tuple[ConnectorCredentialPair, int]
) -> None:
    """Ports every doc in INDEX_BATCH_SIZE batches: copier called once per batch,
    cursor advanced to the last id, docs_ported == total, status SUCCESS."""
    cc_pair, future_id = cc_pair_and_future
    doc_ids = _seed_cc_pair_documents(db_session, cc_pair, INDEX_BATCH_SIZE + 4)
    attempt_id = create_port_attempt(db_session, cc_pair.id, future_id).id

    mock_copier = MagicMock()
    mock_copier.copy_doc_batch.side_effect = lambda ids, **_: (len(ids), False)
    with patch.object(port_task, "PortCopier", return_value=mock_copier):
        run_port_attempt(attempt_id)

    # two batches: a full INDEX_BATCH_SIZE then the remaining 4
    assert mock_copier.copy_doc_batch.call_count == 2
    assert (
        mock_copier.copy_doc_batch.call_args_list[0].args[0]
        == doc_ids[:INDEX_BATCH_SIZE]
    )
    assert (
        mock_copier.copy_doc_batch.call_args_list[1].args[0]
        == doc_ids[INDEX_BATCH_SIZE:]
    )

    db_session.expire_all()
    row = db_session.get(PortAttempt, attempt_id)
    assert row is not None
    assert row.status == PortAttemptStatus.SUCCESS
    assert row.last_processed_doc_id == doc_ids[-1]
    assert row.docs_ported == len(doc_ids)
    assert row.time_completed is not None


def test_run_port_attempt_batch_retry_then_failed(
    db_session: Session, cc_pair_and_future: tuple[ConnectorCredentialPair, int]
) -> None:
    """A batch that keeps failing is retried _PORT_BATCH_MAX_RETRIES times, then
    the attempt is FAILED with the cursor un-advanced (a fresh attempt resumes
    from the prior good batch -- here, the start)."""
    cc_pair, future_id = cc_pair_and_future
    _seed_cc_pair_documents(db_session, cc_pair, 3)
    attempt_id = create_port_attempt(db_session, cc_pair.id, future_id).id

    mock_copier = MagicMock()
    mock_copier.copy_doc_batch.side_effect = RuntimeError("opensearch down")
    with (
        patch.object(port_task, "PortCopier", return_value=mock_copier),
        patch.object(port_task.time, "sleep"),  # don't sleep between retries
    ):
        run_port_attempt(attempt_id)

    assert mock_copier.copy_doc_batch.call_count == port_task._PORT_BATCH_MAX_RETRIES
    db_session.expire_all()
    row = db_session.get(PortAttempt, attempt_id)
    assert row is not None
    assert row.status == PortAttemptStatus.FAILED
    assert row.error_msg == "opensearch down"
    assert row.last_processed_doc_id is None  # cursor never advanced
    assert row.docs_ported == 0
    assert row.time_completed is not None


def test_run_port_attempt_resumes_from_cursor(
    db_session: Session, cc_pair_and_future: tuple[ConnectorCredentialPair, int]
) -> None:
    """A resume is a fresh NOT_STARTED attempt seeded with the prior cursor (how
    check_for_port reschedules a FAILED port): it scans only ids past that cursor."""
    cc_pair, future_id = cc_pair_and_future
    doc_ids = _seed_cc_pair_documents(db_session, cc_pair, 5)
    # cursor at the 2nd doc, so only the 3 docs after it remain to port
    attempt_id = create_port_attempt(
        db_session, cc_pair.id, future_id, resume_from_doc_id=doc_ids[1]
    ).id

    mock_copier = MagicMock()
    mock_copier.copy_doc_batch.side_effect = lambda ids, **_: (len(ids), False)
    with patch.object(port_task, "PortCopier", return_value=mock_copier):
        run_port_attempt(attempt_id)

    # only the docs after the cursor are copied
    assert mock_copier.copy_doc_batch.call_count == 1
    assert mock_copier.copy_doc_batch.call_args_list[0].args[0] == doc_ids[2:]
    db_session.expire_all()
    row = db_session.get(PortAttempt, attempt_id)
    assert row is not None
    assert row.status == PortAttemptStatus.SUCCESS
    assert row.last_processed_doc_id == doc_ids[-1]
    assert row.docs_ported == 3  # this attempt ports the 3 docs after the cursor


def test_run_port_attempt_stops_when_canceled(
    db_session: Session, cc_pair_and_future: tuple[ConnectorCredentialPair, int]
) -> None:
    """An external terminal mark (operator CANCEL / stall-FAIL) landing mid-batch stops
    the task at the batch boundary: commit_port_cursor refuses to write the cursor onto
    the now-terminal attempt (its guard) and signals the caller to stop, so no progress
    is recorded on the dead row."""
    cc_pair, future_id = cc_pair_and_future
    _seed_cc_pair_documents(db_session, cc_pair, INDEX_BATCH_SIZE + 4)
    attempt_id = create_port_attempt(db_session, cc_pair.id, future_id).id

    def copy_then_cancel(ids: list[str], **_: object) -> tuple[int, bool]:
        mark_port_canceled(db_session, attempt_id)  # operator cancels after batch 1
        return len(ids), False

    mock_copier = MagicMock()
    mock_copier.copy_doc_batch.side_effect = copy_then_cancel
    with patch.object(port_task, "PortCopier", return_value=mock_copier):
        run_port_attempt(attempt_id)

    # first batch ran; commit_port_cursor saw the terminal status and stopped the task
    assert mock_copier.copy_doc_batch.call_count == 1
    db_session.expire_all()
    row = db_session.get(PortAttempt, attempt_id)
    assert row is not None
    assert row.status == PortAttemptStatus.CANCELED
    # cursor/progress NOT advanced onto the terminal row (the commit_port_cursor guard)
    assert row.last_processed_doc_id is None
    assert row.docs_ported == 0


def test_cancel_active_port_attempts_on_supersede(
    db_session: Session, cc_pair_and_future: tuple[ConnectorCredentialPair, int]
) -> None:
    """Superseding a FUTURE cancels its active port attempts via the two-phase
    cancel: an IN_PROGRESS attempt is only FLAGGED (cancel_requested), not
    terminalized here, so a concurrently-waiting deletion stays the last writer and
    the running task acks after its final write. Terminal attempts are left alone."""
    cc_pair, future_id = cc_pair_and_future

    active = create_port_attempt(db_session, cc_pair.id, future_id)
    mark_port_in_progress(db_session, active.id)
    # a terminal attempt for the same pair/future must be left alone
    db_session.add(
        PortAttempt(
            cc_pair_id=cc_pair.id,
            search_settings_id=future_id,
            status=PortAttemptStatus.SUCCESS,
        )
    )
    db_session.commit()

    canceled = cancel_active_port_attempts(db_session, search_settings_id=future_id)
    assert canceled == 1

    db_session.expire_all()
    active_row = db_session.get(PortAttempt, active.id)
    assert active_row is not None
    # flagged, not terminalized: status stays IN_PROGRESS with no completion stamp
    assert active_row.status == PortAttemptStatus.IN_PROGRESS
    assert active_row.cancel_requested is True
    assert active_row.time_completed is None
    # the terminal SUCCESS is preserved (first-terminal-write-wins)
    successes = (
        db_session.query(PortAttempt)
        .filter(
            PortAttempt.search_settings_id == future_id,
            PortAttempt.status == PortAttemptStatus.SUCCESS,
        )
        .count()
    )
    assert successes == 1


def test_cancel_active_port_attempts_terminalizes_not_started(
    db_session: Session, cc_pair_and_future: tuple[ConnectorCredentialPair, int]
) -> None:
    """A NOT_STARTED attempt (nothing running yet) is safe to terminalize directly:
    cancel flips it to CANCELED with a completion time + reason. A scope with no
    active attempts left is a no-op returning 0 (guards the count coalescing)."""
    cc_pair, future_id = cc_pair_and_future

    not_started = create_port_attempt(db_session, cc_pair.id, future_id)
    assert not_started.status == PortAttemptStatus.NOT_STARTED

    assert cancel_active_port_attempts(db_session, search_settings_id=future_id) == 1

    db_session.expire_all()
    row = db_session.get(PortAttempt, not_started.id)
    assert row is not None
    assert row.status == PortAttemptStatus.CANCELED
    assert row.time_completed is not None
    assert row.error_msg is not None

    # nothing active remains -> no-op, returns 0
    assert cancel_active_port_attempts(db_session, search_settings_id=future_id) == 0


def test_run_port_attempt_exits_when_cc_pair_deleting(
    db_session: Session, cc_pair_and_future: tuple[ConnectorCredentialPair, int]
) -> None:
    """A cc_pair flipped to DELETING stops the port at the boundary before any
    copy: the task acks by canceling itself (last-writer) so the waiting deletion
    can proceed; its CASCADE removes the attempt row later."""
    cc_pair, future_id = cc_pair_and_future
    _seed_cc_pair_documents(db_session, cc_pair, 3)
    attempt_id = create_port_attempt(db_session, cc_pair.id, future_id).id
    cc_pair.status = ConnectorCredentialPairStatus.DELETING
    db_session.commit()

    mock_copier = MagicMock()
    with patch.object(port_task, "PortCopier", return_value=mock_copier):
        run_port_attempt(attempt_id)

    assert mock_copier.copy_doc_batch.call_count == 0
    db_session.expire_all()
    row = db_session.get(PortAttempt, attempt_id)
    assert row is not None
    assert row.status == PortAttemptStatus.CANCELED


def test_run_port_attempt_soft_time_limit_yields(
    db_session: Session, cc_pair_and_future: tuple[ConnectorCredentialPair, int]
) -> None:
    """Hitting the self-enforced soft time limit yields (no copy) and marks the
    attempt FAILED, so check_for_port resumes it from the cursor next tick rather
    than leaving it IN_PROGRESS to idle out a full stall window."""
    cc_pair, future_id = cc_pair_and_future
    _seed_cc_pair_documents(db_session, cc_pair, 3)
    attempt_id = create_port_attempt(db_session, cc_pair.id, future_id).id

    mock_copier = MagicMock()
    with (
        patch.object(port_task, "PortCopier", return_value=mock_copier),
        patch.object(port_task, "_PORT_SOFT_TIME_LIMIT", -1),  # already "expired"
    ):
        run_port_attempt(attempt_id)

    assert mock_copier.copy_doc_batch.call_count == 0
    db_session.expire_all()
    row = db_session.get(PortAttempt, attempt_id)
    assert row is not None
    assert row.status == PortAttemptStatus.FAILED  # reschedulable; resumes from cursor


def test_check_for_port_creates_and_enqueues(
    db_session: Session, cc_pair_and_future: tuple[ConnectorCredentialPair, int]
) -> None:
    """A use_port_flow FUTURE with an in-scope cc_pair and no active attempt ->
    one NOT_STARTED PortAttempt created + run_port_attempt enqueued."""
    cc_pair, future_id = cc_pair_and_future
    future_ss = db_session.get(SearchSettings, future_id)
    assert future_ss is not None
    future_ss.use_port_flow = True
    db_session.commit()

    result, celery_app = _run_check_for_port(cc_pair, future_id)

    assert result == 1
    db_session.expire_all()
    attempts = (
        db_session.query(PortAttempt)
        .filter(
            PortAttempt.cc_pair_id == cc_pair.id,
            PortAttempt.search_settings_id == future_id,
        )
        .all()
    )
    assert len(attempts) == 1
    assert attempts[0].status == PortAttemptStatus.NOT_STARTED
    celery_app.send_task.assert_called_once()
    call = celery_app.send_task.call_args
    assert call.args[0] == OnyxCeleryTask.RUN_PORT_ATTEMPT
    assert call.kwargs["kwargs"] == {
        "port_attempt_id": attempts[0].id,
        "tenant_id": get_current_tenant_id(),
    }
    assert call.kwargs["queue"] == OnyxCeleryQueues.PORT
    assert call.kwargs["expires"] == BEAT_EXPIRES_DEFAULT


def test_check_for_port_caps_concurrent_attempts(
    db_session: Session, cc_pair_and_future: tuple[ConnectorCredentialPair, int]
) -> None:
    """More in-scope cc_pairs than MAX_CONCURRENT_PORT_ATTEMPTS -> only the cap's worth
    of attempts are created/enqueued per tick, so the port can't fill every
    docprocessing slot and starve live indexing."""
    cc_pair, future_id = cc_pair_and_future
    future_ss = db_session.get(SearchSettings, future_id)
    assert future_ss is not None
    future_ss.use_port_flow = True
    db_session.commit()

    # cap + 2 in-scope cc_pairs so the cap genuinely bites this tick.
    extra_pairs = [
        make_cc_pair(db_session) for _ in range(MAX_CONCURRENT_PORT_ATTEMPTS + 1)
    ]
    all_ids = [cc_pair.id] + [p.id for p in extra_pairs]
    celery_app = MagicMock()
    try:
        with (
            patch.object(
                port_task,
                "get_secondary_search_settings",
                lambda db, *_, **__: db.get(SearchSettings, future_id),
            ),
            patch.object(
                port_task,
                "fetch_indexable_standard_connector_credential_pair_ids",
                lambda *_, **__: all_ids,
            ),
        ):
            result = run_check_for_port(get_current_tenant_id(), celery_app)

        assert result == MAX_CONCURRENT_PORT_ATTEMPTS
        assert celery_app.send_task.call_count == MAX_CONCURRENT_PORT_ATTEMPTS
        db_session.expire_all()
        created = (
            db_session.query(PortAttempt)
            .filter(
                PortAttempt.search_settings_id == future_id,
                PortAttempt.cc_pair_id.in_(all_ids),
            )
            .count()
        )
        assert created == MAX_CONCURRENT_PORT_ATTEMPTS
    finally:
        db_session.rollback()
        for p in extra_pairs:
            db_session.query(PortAttempt).filter(PortAttempt.cc_pair_id == p.id).delete(
                synchronize_session="fetch"
            )
            db_session.commit()
            cleanup_cc_pair(db_session, p)


def test_port_backfill_pending_work_is_cc_pair_aware(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    """Regression: a promoted-PRESENT backfill stays pending until EVERY in-scope cc_pair
    is ported, not just until the attempts created so far are terminal. The concurrency
    cap defers cc_pairs across ticks, so all-SUCCESS existing rows with un-attempted
    cc_pairs remaining must still read pending (else the live index is left incomplete)."""
    ss = get_current_search_settings(db_session)
    pairs = [make_cc_pair(db_session) for _ in range(3)]
    ids = [p.id for p in pairs]

    def _succeed(cc_pair_id: int) -> None:
        db_session.add(
            PortAttempt(
                cc_pair_id=cc_pair_id,
                search_settings_id=ss.id,
                status=PortAttemptStatus.SUCCESS,
            )
        )
        db_session.commit()

    try:
        with patch.object(
            port_attempt_db,
            "fetch_indexable_standard_connector_credential_pair_ids",
            lambda *_, **__: ids,
        ):
            _succeed(pairs[0].id)
            # old code returned False here (all existing rows terminal); fixed -> pending
            assert port_backfill_has_pending_work(db_session, ss.id) is True

            _succeed(pairs[1].id)
            assert port_backfill_has_pending_work(db_session, ss.id) is True

            _succeed(pairs[2].id)
            assert port_backfill_has_pending_work(db_session, ss.id) is False
    finally:
        db_session.rollback()
        for p in pairs:
            db_session.query(PortAttempt).filter(PortAttempt.cc_pair_id == p.id).delete(
                synchronize_session="fetch"
            )
            db_session.commit()
            cleanup_cc_pair(db_session, p)


def test_port_backfill_pending_work_settled_statuses(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    """Per-cc_pair 'settled' mirrors check_for_port's no-retry set: SUCCESS and CANCELED
    are done; no-attempt or FAILED is still pending (check_for_port (re)creates/retries
    it). CANCELED must NOT read pending -- else the guard deadlocks on a cc_pair the
    scheduler refuses to retry."""
    ss = get_current_search_settings(db_session)

    def _pending_for(status: PortAttemptStatus | None) -> bool:
        pair = make_cc_pair(db_session)
        try:
            with patch.object(
                port_attempt_db,
                "fetch_indexable_standard_connector_credential_pair_ids",
                lambda *_, **__: [pair.id],
            ):
                if status is not None:
                    db_session.add(
                        PortAttempt(
                            cc_pair_id=pair.id,
                            search_settings_id=ss.id,
                            status=status,
                        )
                    )
                    db_session.commit()
                return port_backfill_has_pending_work(db_session, ss.id)
        finally:
            db_session.rollback()
            db_session.query(PortAttempt).filter(
                PortAttempt.cc_pair_id == pair.id
            ).delete(synchronize_session="fetch")
            db_session.commit()
            cleanup_cc_pair(db_session, pair)

    assert _pending_for(None) is True  # just promoted, no attempt yet
    assert _pending_for(PortAttemptStatus.FAILED) is True  # retryable
    assert _pending_for(PortAttemptStatus.SUCCESS) is False
    assert _pending_for(PortAttemptStatus.CANCELED) is False  # settled -> no deadlock


def test_resolve_clears_backfill_source_when_drained(
    db_session: Session, cc_pair_and_future: tuple[ConnectorCredentialPair, int]
) -> None:
    """Once every in-scope cc_pair of a promoted-PRESENT (INSTANT) backfill is ported,
    _resolve unpins port_backfill_source_id so the done job stops being re-checked and
    the source index becomes reclaimable (set at swap, otherwise never cleared)."""
    cc_pair, present_id = cc_pair_and_future
    present = db_session.get(SearchSettings, present_id)
    assert present is not None
    source = (
        db_session.query(SearchSettings.id)
        .filter(SearchSettings.id != present_id)
        .first()
    )
    assert source is not None
    present.use_port_flow = True
    present.port_backfill_source_id = source[0]
    db_session.add(
        PortAttempt(
            cc_pair_id=cc_pair.id,
            search_settings_id=present_id,
            status=PortAttemptStatus.SUCCESS,
        )
    )
    db_session.commit()

    try:
        with (
            patch.object(
                port_task, "get_secondary_search_settings", lambda *_, **__: None
            ),
            patch.object(
                port_task,
                "get_current_search_settings",
                lambda *_, **__: db_session.get(SearchSettings, present_id),
            ),
            patch.object(
                port_attempt_db,
                "fetch_indexable_standard_connector_credential_pair_ids",
                lambda *_, **__: [cc_pair.id],
            ),
        ):
            target = port_task._resolve_port_target_settings(db_session)

        assert target is None  # drained -> not a target
        db_session.expire_all()
        refreshed = db_session.get(SearchSettings, present_id)
        assert refreshed is not None
        assert refreshed.port_backfill_source_id is None
    finally:
        db_session.rollback()
        db_session.query(PortAttempt).filter(
            PortAttempt.cc_pair_id == cc_pair.id
        ).delete(synchronize_session="fetch")
        db_session.commit()


def test_check_for_port_gated_off_when_not_port_flow(
    db_session: Session, cc_pair_and_future: tuple[ConnectorCredentialPair, int]
) -> None:
    """A legacy FUTURE (use_port_flow=False) is a no-op -> nothing created/enqueued."""
    cc_pair, future_id = cc_pair_and_future  # use_port_flow stays False (default)

    result, celery_app = _run_check_for_port(cc_pair, future_id)

    assert result is None
    celery_app.send_task.assert_not_called()
    assert (
        db_session.query(PortAttempt)
        .filter(PortAttempt.cc_pair_id == cc_pair.id)
        .count()
        == 0
    )


def test_check_for_port_resumes_failed_cursor(
    db_session: Session, cc_pair_and_future: tuple[ConnectorCredentialPair, int]
) -> None:
    """A prior FAILED attempt is rescheduled with its cursor carried forward."""
    cc_pair, future_id = cc_pair_and_future
    future_ss = db_session.get(SearchSettings, future_id)
    assert future_ss is not None
    future_ss.use_port_flow = True
    db_session.commit()

    failed = create_port_attempt(db_session, cc_pair.id, future_id)
    mark_port_in_progress(db_session, failed.id)
    commit_port_cursor(
        db_session, failed.id, last_processed_doc_id="portdoc-042", docs_ported=42
    )
    mark_port_failed(db_session, failed.id, error_msg="boom")

    result, _ = _run_check_for_port(cc_pair, future_id)

    assert result == 1
    db_session.expire_all()
    fresh = (
        db_session.query(PortAttempt)
        .filter(
            PortAttempt.cc_pair_id == cc_pair.id,
            PortAttempt.status == PortAttemptStatus.NOT_STARTED,
        )
        .all()
    )
    assert len(fresh) == 1
    assert fresh[0].last_processed_doc_id == "portdoc-042"  # resumed cursor


def test_check_for_port_fails_stale_in_progress(
    db_session: Session, cc_pair_and_future: tuple[ConnectorCredentialPair, int]
) -> None:
    """A stalled IN_PROGRESS attempt is FAILED, then a fresh attempt is created
    and enqueued to resume."""
    cc_pair, future_id = cc_pair_and_future
    future_ss = db_session.get(SearchSettings, future_id)
    assert future_ss is not None
    future_ss.use_port_flow = True
    db_session.commit()

    stale = create_port_attempt(db_session, cc_pair.id, future_id)
    mark_port_in_progress(db_session, stale.id)
    # force last_progress_time well past the stall threshold
    old = datetime.now(timezone.utc) - timedelta(hours=1)
    db_session.query(PortAttempt).filter(PortAttempt.id == stale.id).update(
        {PortAttempt.last_progress_time: old}
    )
    db_session.commit()

    result, celery_app = _run_check_for_port(cc_pair, future_id)

    db_session.expire_all()
    stale_row = db_session.get(PortAttempt, stale.id)
    assert stale_row is not None
    assert stale_row.status == PortAttemptStatus.FAILED  # watchdog failed the stall
    fresh = (
        db_session.query(PortAttempt)
        .filter(
            PortAttempt.cc_pair_id == cc_pair.id,
            PortAttempt.status == PortAttemptStatus.NOT_STARTED,
        )
        .all()
    )
    assert len(fresh) == 1
    assert result == 1
    celery_app.send_task.assert_called_once()


def test_check_for_port_fails_stale_attempt_on_superseded_settings(
    db_session: Session, cc_pair_and_future: tuple[ConnectorCredentialPair, int]
) -> None:
    """The watchdog must fail a dead-worker IN_PROGRESS attempt even when its settings
    are no longer the current target, else it strands and blocks connector deletion.
    request_port_cancel flags it but leaves it IN_PROGRESS; use_port_flow stays False so
    _resolve_port_target_settings returns None — the pre-fix early return skipped the
    sweep, leaving the row IN_PROGRESS."""
    cc_pair, future_id = cc_pair_and_future

    stale = create_port_attempt(db_session, cc_pair.id, future_id)
    mark_port_in_progress(db_session, stale.id)
    request_port_cancel(db_session, stale.id)  # flag only; worker "dies" before acking
    old = datetime.now(timezone.utc) - timedelta(hours=1)
    db_session.query(PortAttempt).filter(PortAttempt.id == stale.id).update(
        {PortAttempt.last_progress_time: old}
    )
    db_session.commit()

    result, _ = _run_check_for_port(cc_pair, future_id)

    assert result is None  # no current port-flow target to enqueue against
    db_session.expire_all()
    row = db_session.get(PortAttempt, stale.id)
    assert row is not None
    assert row.status == PortAttemptStatus.FAILED  # global sweep terminalized it


def test_check_for_port_leaves_active_in_progress(
    db_session: Session, cc_pair_and_future: tuple[ConnectorCredentialPair, int]
) -> None:
    """A healthy (recent) IN_PROGRESS attempt is left untouched and not duplicated."""
    cc_pair, future_id = cc_pair_and_future
    future_ss = db_session.get(SearchSettings, future_id)
    assert future_ss is not None
    future_ss.use_port_flow = True
    db_session.commit()

    active = create_port_attempt(db_session, cc_pair.id, future_id)
    mark_port_in_progress(db_session, active.id)  # recent last_progress_time

    result, celery_app = _run_check_for_port(cc_pair, future_id)

    assert result == 0
    celery_app.send_task.assert_not_called()
    db_session.expire_all()
    row = db_session.get(PortAttempt, active.id)
    assert row is not None
    assert row.status == PortAttemptStatus.IN_PROGRESS  # untouched
    assert (
        db_session.query(PortAttempt)
        .filter(PortAttempt.cc_pair_id == cc_pair.id)
        .count()
        == 1
    )


def test_check_for_port_reissues_stale_not_started(
    db_session: Session, cc_pair_and_future: tuple[ConnectorCredentialPair, int]
) -> None:
    """A NOT_STARTED attempt whose enqueued task was lost/expired (not re-enqueued
    within the TTL window) is re-enqueued in place — not stranded, not duplicated —
    and the enqueue clock advances so it re-sends once per window, not every beat."""
    cc_pair, future_id = cc_pair_and_future
    future_ss = db_session.get(SearchSettings, future_id)
    assert future_ss is not None
    future_ss.use_port_flow = True
    db_session.commit()

    stale = create_port_attempt(db_session, cc_pair.id, future_id)
    # backdate time_updated past the TTL so the gate sees the task as expired
    # (explicit set wins over the column's onupdate)
    old = datetime.now(timezone.utc) - timedelta(seconds=BEAT_EXPIRES_DEFAULT + 60)
    stale.time_updated = old
    db_session.commit()

    result, celery_app = _run_check_for_port(cc_pair, future_id)

    assert result == 1
    celery_app.send_task.assert_called_once()
    assert (
        celery_app.send_task.call_args.kwargs["kwargs"]["port_attempt_id"] == stale.id
    )
    # re-issued in place: still the same single attempt, still NOT_STARTED
    db_session.expire_all()
    rows = (
        db_session.query(PortAttempt).filter(PortAttempt.cc_pair_id == cc_pair.id).all()
    )
    assert len(rows) == 1 and rows[0].id == stale.id
    assert rows[0].status == PortAttemptStatus.NOT_STARTED
    # the clock advanced past the backdate, so an immediate next tick is throttled
    assert rows[0].time_updated > old
    result2, celery_app2 = _run_check_for_port(cc_pair, future_id)
    assert result2 == 0
    celery_app2.send_task.assert_not_called()


def test_check_for_port_leaves_fresh_not_started(
    db_session: Session, cc_pair_and_future: tuple[ConnectorCredentialPair, int]
) -> None:
    """A recently-created NOT_STARTED attempt (task still in flight, within the TTL)
    is left alone — not re-enqueued or duplicated."""
    cc_pair, future_id = cc_pair_and_future
    future_ss = db_session.get(SearchSettings, future_id)
    assert future_ss is not None
    future_ss.use_port_flow = True
    db_session.commit()

    fresh = create_port_attempt(db_session, cc_pair.id, future_id)  # time_updated = now

    result, celery_app = _run_check_for_port(cc_pair, future_id)

    assert result == 0
    celery_app.send_task.assert_not_called()
    db_session.expire_all()
    assert (
        db_session.query(PortAttempt)
        .filter(PortAttempt.cc_pair_id == cc_pair.id)
        .count()
        == 1
    )
    row = db_session.get(PortAttempt, fresh.id)
    assert row is not None and row.status == PortAttemptStatus.NOT_STARTED


def test_check_for_port_fails_attempt_when_enqueue_raises(
    db_session: Session, cc_pair_and_future: tuple[ConnectorCredentialPair, int]
) -> None:
    """If send_task fails after the row is committed, the attempt is FAILED (not
    left orphaned NOT_STARTED) so the next tick recreates + re-enqueues it."""
    cc_pair, future_id = cc_pair_and_future
    future_ss = db_session.get(SearchSettings, future_id)
    assert future_ss is not None
    future_ss.use_port_flow = True
    db_session.commit()

    celery_app = MagicMock()
    celery_app.send_task.side_effect = RuntimeError("broker down")
    _run_check_for_port(cc_pair, future_id, celery_app=celery_app)

    db_session.expire_all()
    attempts = (
        db_session.query(PortAttempt).filter(PortAttempt.cc_pair_id == cc_pair.id).all()
    )
    assert len(attempts) == 1
    assert attempts[0].status == PortAttemptStatus.FAILED  # not orphaned NOT_STARTED
    assert attempts[0].error_msg == "enqueue failed"


def test_check_for_port_survives_create_failure(
    db_session: Session, cc_pair_and_future: tuple[ConnectorCredentialPair, int]
) -> None:
    """A create_port_attempt failure for one cc_pair is swallowed so the tick
    completes (the next tick retries) rather than aborting every other cc_pair."""
    cc_pair, future_id = cc_pair_and_future
    future_ss = db_session.get(SearchSettings, future_id)
    assert future_ss is not None
    future_ss.use_port_flow = True
    db_session.commit()

    celery_app = MagicMock()
    with (
        patch.object(
            port_task,
            "get_secondary_search_settings",
            lambda db, *_, **__: db.get(SearchSettings, future_id),
        ),
        patch.object(
            port_task,
            "fetch_indexable_standard_connector_credential_pair_ids",
            lambda *_, **__: [cc_pair.id],
        ),
        patch.object(
            port_task, "create_port_attempt", side_effect=RuntimeError("db blip")
        ),
    ):
        result = run_check_for_port(get_current_tenant_id(), celery_app)

    assert result == 0  # tick completed; the failed create was skipped
    celery_app.send_task.assert_not_called()
    db_session.expire_all()
    assert (
        db_session.query(PortAttempt)
        .filter(PortAttempt.cc_pair_id == cc_pair.id)
        .count()
        == 0
    )


def test_port_retry_delay_backoff() -> None:
    """First same-cursor failure retries immediately; repeats back off, then cap."""
    delay = port_task._port_retry_delay_seconds
    base = port_task._PORT_RETRY_BACKOFF_BASE_S
    assert delay(0) == 0.0
    assert delay(1) == 0.0  # first failure: retry now (likely transient)
    assert delay(2) == base  # second same-cursor failure: start backing off
    assert delay(3) == base * 2
    assert delay(4) == base * 4
    assert delay(1000) == port_task._PORT_RETRY_BACKOFF_MAX_S  # capped


def _fail_port_at(
    db_session: Session, cc_pair_id: int, future_id: int, cursor: str | None
) -> int:
    """Create a terminal FAILED attempt resuming from `cursor`; returns its id."""
    a = create_port_attempt(
        db_session, cc_pair_id, future_id, resume_from_doc_id=cursor
    )
    mark_port_in_progress(db_session, a.id)
    mark_port_failed(db_session, a.id, error_msg="durable")
    return a.id


def test_consecutive_failed_no_progress_streak(
    db_session: Session, cc_pair_and_future: tuple[ConnectorCredentialPair, int]
) -> None:
    """Streak counts trailing FAILED attempts at the same cursor; a cursor advance
    (progress) resets it to 1, and a non-FAILED latest attempt resets it to 0."""
    cc_pair, future_id = cc_pair_and_future
    streak = count_consecutive_failed_port_attempts_no_progress

    assert streak(db_session, cc_pair.id, future_id) == 0
    _fail_port_at(db_session, cc_pair.id, future_id, "doc-5")
    _fail_port_at(db_session, cc_pair.id, future_id, "doc-5")
    assert streak(db_session, cc_pair.id, future_id) == 2
    # an advanced cursor means progress was made -> streak resets to 1
    _fail_port_at(db_session, cc_pair.id, future_id, "doc-9")
    assert streak(db_session, cc_pair.id, future_id) == 1
    # a SUCCESS latest attempt breaks the streak entirely
    ok = create_port_attempt(
        db_session, cc_pair.id, future_id, resume_from_doc_id="doc-9"
    )
    mark_port_in_progress(db_session, ok.id)
    mark_port_succeeded(db_session, ok.id)
    assert streak(db_session, cc_pair.id, future_id) == 0


def test_check_for_port_backs_off_repeated_failures(
    db_session: Session, cc_pair_and_future: tuple[ConnectorCredentialPair, int]
) -> None:
    """A port stuck failing at the same cursor is not recreated within its backoff
    window, but is once the backoff has elapsed."""
    cc_pair, future_id = cc_pair_and_future
    future_ss = db_session.get(SearchSettings, future_id)
    assert future_ss is not None
    future_ss.use_port_flow = True
    db_session.commit()

    # two same-cursor failures -> streak 2 -> backoff = BASE seconds
    _fail_port_at(db_session, cc_pair.id, future_id, "doc-1")
    _fail_port_at(db_session, cc_pair.id, future_id, "doc-1")

    # latest failure just happened -> still within backoff -> not recreated
    result, celery_app = _run_check_for_port(cc_pair, future_id)
    assert result == 0
    celery_app.send_task.assert_not_called()

    # backdate the latest failure past the backoff -> recreated
    latest = get_latest_port_attempt(db_session, cc_pair.id, future_id)
    assert latest is not None
    latest.time_completed = datetime.now(timezone.utc) - timedelta(
        seconds=port_task._PORT_RETRY_BACKOFF_BASE_S + 30
    )
    db_session.commit()
    result, celery_app = _run_check_for_port(cc_pair, future_id)
    assert result == 1
    celery_app.send_task.assert_called_once()


def _cleanup_pairs(db_session: Session, *pairs: ConnectorCredentialPair) -> None:
    """Inline-cc_pair teardown (mirrors the cc_pair fixture): drop PortAttempts, then
    cleanup_cc_pair each (shared-doc safe)."""
    db_session.rollback()
    for pair in pairs:
        db_session.query(PortAttempt).filter(PortAttempt.cc_pair_id == pair.id).delete(
            synchronize_session="fetch"
        )
    db_session.commit()
    for pair in pairs:
        cleanup_cc_pair(db_session, pair)


def test_port_swap_ready_scoped_to_required_cc_pairs(
    db_session: Session,
    cc_pair_and_future: tuple[ConnectorCredentialPair, int],
) -> None:
    """Swap gate ignores an INVALID-only deferred doc (no deadlock) but STILL waits
    on a required cc_pair's deferred doc (regression guard)."""
    required_pair, future_id = cc_pair_and_future
    future_ss = db_session.get(SearchSettings, future_id)
    assert future_ss is not None

    # required pair's port is done (SUCCESS, none active)
    attempt = create_port_attempt(db_session, required_pair.id, future_id)
    mark_port_in_progress(db_session, attempt.id)
    mark_port_succeeded(db_session, attempt.id)

    invalid_pair = make_cc_pair(db_session)
    try:
        [invalid_doc] = _seed_cc_pair_documents(
            db_session, invalid_pair, 1, unique=True
        )
        mark_document_synced_secondary_pending(invalid_doc, db_session)
        invalid_pair.status = ConnectorCredentialPairStatus.INVALID
        db_session.commit()

        # not blocked by the INVALID-only deferred doc
        assert _port_swap_ready(db_session, future_ss, [required_pair]) is True

        # a deferred doc on the REQUIRED pair DOES still block the swap
        [req_doc] = _seed_cc_pair_documents(db_session, required_pair, 1, unique=True)
        mark_document_synced_secondary_pending(req_doc, db_session)
        db_session.commit()
        assert _port_swap_ready(db_session, future_ss, [required_pair]) is False
    finally:
        _cleanup_pairs(db_session, invalid_pair)


def test_document_has_indexable_cc_pair(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    """Writer-side gate the sync task consults before deferring a FUTURE write:
    True iff some owning cc_pair is indexable."""
    pair_active = make_cc_pair(db_session)
    pair_invalid = make_cc_pair(db_session)
    try:
        [doc_active] = _seed_cc_pair_documents(db_session, pair_active, 1, unique=True)
        [doc_invalid] = _seed_cc_pair_documents(
            db_session, pair_invalid, 1, unique=True
        )
        # doc_shared is owned by both the ACTIVE and the INVALID pair
        [doc_shared] = _seed_cc_pair_documents(db_session, pair_active, 1, unique=True)
        db_session.add(
            DocumentByConnectorCredentialPair(
                id=doc_shared,
                connector_id=pair_invalid.connector_id,
                credential_id=pair_invalid.credential_id,
                has_been_indexed=True,
            )
        )
        pair_invalid.status = ConnectorCredentialPairStatus.INVALID
        db_session.commit()

        assert document_has_indexable_cc_pair(db_session, doc_active) is True
        assert document_has_indexable_cc_pair(db_session, doc_invalid) is False
        assert document_has_indexable_cc_pair(db_session, doc_shared) is True
        assert document_has_indexable_cc_pair(db_session, "no-such-doc") is False
    finally:
        _cleanup_pairs(db_session, pair_active, pair_invalid)
