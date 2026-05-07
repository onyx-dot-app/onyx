"""Tests for INTERRUPTED-status auto-recovery behaviour.

When a docfetching worker dies (pod OOM, rolling-deploy SIGKILL), the
heartbeat watchdog should mark the attempt INTERRUPTED — not FAILED — so
that the scheduler retries it immediately and the strike counter that
auto-pauses the connector after 5 logical failures is not incremented.

Covered:
    1. Watchdog: docfetching-phase + checkpoint  -> INTERRUPTED
    2. Watchdog: docfetching-phase + no checkpoint -> FAILED (unchanged)
    3. Watchdog: docprocessing-phase             -> FAILED (unchanged)
    4. should_index bypasses cadence when last attempt is INTERRUPTED
    5. is_in_repeated_error_state ignores INTERRUPTED runs

Runs against real Postgres because IndexAttempt's row-level locking and
the watchdog's commit semantics are part of what we're verifying.
"""

from datetime import datetime
from datetime import timedelta
from datetime import timezone
from unittest.mock import MagicMock
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.background.celery.tasks.docprocessing.tasks import HEARTBEAT_TIMEOUT_SECONDS
from onyx.background.celery.tasks.docprocessing.tasks import (
    validate_active_indexing_attempts,
)
from onyx.background.celery.tasks.docprocessing.utils import is_in_repeated_error_state
from onyx.background.celery.tasks.docprocessing.utils import (
    NUM_REPEAT_ERRORS_BEFORE_REPEATED_ERROR_STATE,
)
from onyx.background.celery.tasks.docprocessing.utils import should_index
from onyx.db.enums import EmbeddingPrecision
from onyx.db.enums import IndexingStatus
from onyx.db.enums import IndexModelStatus
from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import IndexAttempt
from onyx.db.models import SearchSettings
from tests.external_dependency_unit.indexing_helpers import cleanup_cc_pair
from tests.external_dependency_unit.indexing_helpers import make_cc_pair

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def cc_pair(db_session: Session):
    """A throwaway cc_pair backed by a real Postgres row."""
    pair = make_cc_pair(db_session)
    # Default refresh_freq=None blocks should_index by design; tests that
    # care about cadence override this on the connector directly.
    yield pair
    # IndexAttempt has a non-cascading FK to connector_credential_pair, so
    # cleanup_cc_pair's bulk delete fails if any attempts still reference
    # this pair. Clear them first.
    db_session.query(IndexAttempt).filter(
        IndexAttempt.connector_credential_pair_id == pair.id
    ).delete(synchronize_session="fetch")
    db_session.commit()
    cleanup_cc_pair(db_session, pair)


@pytest.fixture
def search_settings(db_session: Session):
    settings = SearchSettings(
        model_name="test-model",
        model_dim=768,
        normalize=True,
        query_prefix="",
        passage_prefix="",
        status=IndexModelStatus.PRESENT,
        index_name=f"test-index-{uuid4().hex[:8]}",
        embedding_precision=EmbeddingPrecision.FLOAT,
    )
    db_session.add(settings)
    db_session.commit()
    db_session.refresh(settings)
    yield settings
    db_session.delete(settings)
    db_session.commit()


def _make_in_progress_attempt(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    search_settings: SearchSettings,
    *,
    total_batches: int | None,
    completed_batches: int = 0,
    checkpoint_pointer: str | None,
    stale_seconds: int,
) -> IndexAttempt:
    """Build an IndexAttempt that the watchdog will see as a stale heartbeat
    on its next pass: heartbeat_counter == last_heartbeat_value (no advance)
    and last_heartbeat_time set far enough in the past to exceed the timeout.
    """
    now = datetime.now(timezone.utc)
    attempt = IndexAttempt(
        connector_credential_pair_id=cc_pair.id,
        search_settings_id=search_settings.id,
        from_beginning=False,
        status=IndexingStatus.IN_PROGRESS,
        celery_task_id=f"task-{uuid4().hex[:8]}",
        time_started=now - timedelta(seconds=stale_seconds + 60),
        heartbeat_counter=5,
        last_heartbeat_value=5,
        last_heartbeat_time=now - timedelta(seconds=stale_seconds),
        total_batches=total_batches,
        completed_batches=completed_batches,
        checkpoint_pointer=checkpoint_pointer,
    )
    db_session.add(attempt)
    db_session.commit()
    db_session.refresh(attempt)
    return attempt


def _make_terminal_attempt(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    search_settings: SearchSettings,
    *,
    status: IndexingStatus,
    time_updated: datetime | None = None,
) -> IndexAttempt:
    attempt = IndexAttempt(
        connector_credential_pair_id=cc_pair.id,
        search_settings_id=search_settings.id,
        from_beginning=False,
        status=status,
        time_started=datetime.now(timezone.utc),
    )
    db_session.add(attempt)
    db_session.commit()
    if time_updated is not None:
        attempt.time_updated = time_updated
        db_session.commit()
    db_session.refresh(attempt)
    return attempt


# ---------------------------------------------------------------------------
# Watchdog branching
# ---------------------------------------------------------------------------


class TestWatchdogInterruptedBranch:
    """validate_active_indexing_attempts must distinguish pod-death (which
    has a checkpoint to resume from) from a logical failure."""

    def test_docfetching_phase_with_checkpoint_marks_interrupted(
        self,
        db_session: Session,
        cc_pair: ConnectorCredentialPair,
        search_settings: SearchSettings,
    ) -> None:
        attempt = _make_in_progress_attempt(
            db_session,
            cc_pair,
            search_settings,
            total_batches=None,  # docfetching phase
            checkpoint_pointer=f"checkpoint_{uuid4().hex}.json",
            stale_seconds=HEARTBEAT_TIMEOUT_SECONDS + 60,
        )

        validate_active_indexing_attempts(MagicMock())

        db_session.expire_all()
        refreshed = db_session.get(IndexAttempt, attempt.id)
        assert refreshed is not None
        assert refreshed.status == IndexingStatus.INTERRUPTED
        assert refreshed.celery_task_id is None
        assert refreshed.error_msg is not None
        assert "auto-resume" in refreshed.error_msg.lower()

    def test_docfetching_phase_without_checkpoint_falls_back_to_failed(
        self,
        db_session: Session,
        cc_pair: ConnectorCredentialPair,
        search_settings: SearchSettings,
    ) -> None:
        attempt = _make_in_progress_attempt(
            db_session,
            cc_pair,
            search_settings,
            total_batches=None,
            checkpoint_pointer=None,  # nothing to resume from
            stale_seconds=HEARTBEAT_TIMEOUT_SECONDS + 60,
        )

        validate_active_indexing_attempts(MagicMock())

        db_session.expire_all()
        refreshed = db_session.get(IndexAttempt, attempt.id)
        assert refreshed is not None
        assert refreshed.status == IndexingStatus.FAILED

    def test_docprocessing_phase_marks_failed(
        self,
        db_session: Session,
        cc_pair: ConnectorCredentialPair,
        search_settings: SearchSettings,
    ) -> None:
        # Docprocessing phase consults Redis batch counters before
        # invalidating (per `9c631d3cfd`). Stub them to in_flight>0 so the
        # watchdog takes the "workers crashed holding batches" path.
        attempt = _make_in_progress_attempt(
            db_session,
            cc_pair,
            search_settings,
            total_batches=10,
            completed_batches=3,
            checkpoint_pointer=f"checkpoint_{uuid4().hex}.json",  # should be ignored
            stale_seconds=HEARTBEAT_TIMEOUT_SECONDS + 60,
        )

        mock_redis_doc = MagicMock()
        mock_redis_doc.in_flight.return_value = 2
        mock_redis_doc.pending.return_value = 0
        with (
            patch(
                "onyx.background.celery.tasks.docprocessing.tasks.RedisDocprocessing",
                return_value=mock_redis_doc,
            ),
            patch(
                "onyx.background.celery.tasks.docprocessing.tasks.get_redis_client",
                return_value=MagicMock(),
            ),
        ):
            validate_active_indexing_attempts(MagicMock())

        db_session.expire_all()
        refreshed = db_session.get(IndexAttempt, attempt.id)
        assert refreshed is not None
        assert refreshed.status == IndexingStatus.FAILED, (
            "Docprocessing-phase pod death with in_flight>0 should mark "
            "the attempt FAILED — INTERRUPTED is docfetching-only in PR 1."
        )


# ---------------------------------------------------------------------------
# Scheduler bypass for INTERRUPTED predecessor
# ---------------------------------------------------------------------------


class TestShouldIndexInterruptedBypass:
    def test_interrupted_predecessor_bypasses_cadence(
        self,
        db_session: Session,
        cc_pair: ConnectorCredentialPair,
        search_settings: SearchSettings,
    ) -> None:
        # Give the connector a long refresh cadence so the only way
        # should_index returns True is the INTERRUPTED bypass.
        cc_pair.connector.refresh_freq = 60 * 60
        db_session.commit()

        # Last attempt was just marked INTERRUPTED — under normal cadence
        # rules we'd wait a full hour, but we should retry now.
        _make_terminal_attempt(
            db_session,
            cc_pair,
            search_settings,
            status=IndexingStatus.INTERRUPTED,
            time_updated=datetime.now(timezone.utc),
        )

        assert should_index(
            cc_pair=cc_pair,
            search_settings_instance=search_settings,
            secondary_index_building=False,
            db_session=db_session,
        )

    def test_interrupted_predecessor_bypasses_refresh_freq_none(
        self,
        db_session: Session,
        cc_pair: ConnectorCredentialPair,
        search_settings: SearchSettings,
    ) -> None:
        """Regression for greptile review on PR #10926: one-time-sync
        connectors (refresh_freq=None) must still auto-recover from an
        INTERRUPTED predecessor — the INTERRUPTED check has to come before
        the refresh_freq=None early-return, otherwise pod death on a
        no-cadence connector strands the run forever.
        """
        cc_pair.connector.refresh_freq = None
        db_session.commit()

        _make_terminal_attempt(
            db_session,
            cc_pair,
            search_settings,
            status=IndexingStatus.INTERRUPTED,
            time_updated=datetime.now(timezone.utc),
        )

        assert should_index(
            cc_pair=cc_pair,
            search_settings_instance=search_settings,
            secondary_index_building=False,
            db_session=db_session,
        )

    def test_failed_predecessor_still_respects_cadence(
        self,
        db_session: Session,
        cc_pair: ConnectorCredentialPair,
        search_settings: SearchSettings,
    ) -> None:
        """Sanity: ensure we didn't accidentally let FAILED bypass cadence too."""
        cc_pair.connector.refresh_freq = 60 * 60
        db_session.commit()

        _make_terminal_attempt(
            db_session,
            cc_pair,
            search_settings,
            status=IndexingStatus.FAILED,
            time_updated=datetime.now(timezone.utc),
        )

        assert not should_index(
            cc_pair=cc_pair,
            search_settings_instance=search_settings,
            secondary_index_building=False,
            db_session=db_session,
        )


# ---------------------------------------------------------------------------
# Strike count
# ---------------------------------------------------------------------------


class TestRepeatedErrorStateIgnoresInterrupted:
    def test_five_interrupted_in_a_row_does_not_pause_connector(
        self,
        db_session: Session,
        cc_pair: ConnectorCredentialPair,
        search_settings: SearchSettings,
    ) -> None:
        # refresh_freq must be set, otherwise a single error pauses immediately.
        cc_pair.connector.refresh_freq = 60 * 60
        db_session.commit()

        for _ in range(NUM_REPEAT_ERRORS_BEFORE_REPEATED_ERROR_STATE):
            _make_terminal_attempt(
                db_session,
                cc_pair,
                search_settings,
                status=IndexingStatus.INTERRUPTED,
            )

        assert not is_in_repeated_error_state(
            cc_pair=cc_pair,
            search_settings_id=search_settings.id,
            db_session=db_session,
        )

    def test_five_failed_in_a_row_does_pause_connector(
        self,
        db_session: Session,
        cc_pair: ConnectorCredentialPair,
        search_settings: SearchSettings,
    ) -> None:
        """Sanity: ensure the FAILED-only strike rule still triggers."""
        cc_pair.connector.refresh_freq = 60 * 60
        db_session.commit()

        for _ in range(NUM_REPEAT_ERRORS_BEFORE_REPEATED_ERROR_STATE):
            _make_terminal_attempt(
                db_session,
                cc_pair,
                search_settings,
                status=IndexingStatus.FAILED,
            )

        assert is_in_repeated_error_state(
            cc_pair=cc_pair,
            search_settings_id=search_settings.id,
            db_session=db_session,
        )
