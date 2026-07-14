"""External dependency unit tests for the docprocessing stall watchdog.

These cover the "saturated-but-alive vs dead" distinction added to
``validate_active_indexing_attempts``: a stale heartbeat alone must not destroy
a multi-day index attempt when the workers are still alive (e.g. blocked on a
saturated embedder). Real crashes (no live workers) must still be invalidated.

Postgres + Redis must be available. Celery worker liveness is mocked so the
tests do not depend on a running docprocessing worker.
"""

import threading
from collections.abc import Generator
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from unittest.mock import MagicMock
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.background.celery.tasks.docprocessing import heartbeat as heartbeat_module
from onyx.background.celery.tasks.docprocessing.tasks import HEARTBEAT_TIMEOUT_SECONDS
from onyx.background.celery.tasks.docprocessing.tasks import (
    validate_active_indexing_attempts,
)
from onyx.configs.constants import DocumentSource
from onyx.connectors.models import InputType
from onyx.db.enums import AccessType
from onyx.db.enums import ConnectorCredentialPairStatus
from onyx.db.enums import EmbeddingPrecision
from onyx.db.enums import IndexingStatus
from onyx.db.enums import IndexModelStatus
from onyx.db.models import Connector
from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import Credential
from onyx.db.models import IndexAttempt
from onyx.db.models import SearchSettings
from onyx.redis.redis_docprocessing import RedisDocprocessing
from onyx.redis.redis_pool import get_redis_client

_WATCHDOG_PATH = "onyx.background.celery.tasks.docprocessing.tasks"


def _make_attempt(
    db_session: Session,
    *,
    total_batches: int | None,
    completed_batches: int,
    heartbeat_counter: int,
    last_heartbeat_value: int,
    last_batches_completed_count: int,
    heartbeat_age_seconds: float,
) -> IndexAttempt:
    connector = Connector(
        name=f"wd_conn_{uuid4().hex[:8]}",
        source=DocumentSource.FILE,
        input_type=InputType.LOAD_STATE,
        connector_specific_config={},
        refresh_freq=3600,
    )
    db_session.add(connector)
    db_session.commit()

    credential = Credential(
        name=f"wd_cred_{uuid4().hex[:8]}",
        source=DocumentSource.FILE,
        credential_json={},
        admin_public=True,
    )
    db_session.add(credential)
    db_session.commit()

    cc_pair = ConnectorCredentialPair(
        name=f"wd_ccpair_{uuid4().hex[:8]}",
        connector_id=connector.id,
        credential_id=credential.id,
        status=ConnectorCredentialPairStatus.ACTIVE,
        access_type=AccessType.PUBLIC,
    )
    db_session.add(cc_pair)
    db_session.commit()

    search_settings = SearchSettings(
        model_name="test-model",
        model_dim=768,
        normalize=True,
        query_prefix="",
        passage_prefix="",
        status=IndexModelStatus.PRESENT,
        index_name=f"wd_index_{uuid4().hex[:8]}",
        embedding_precision=EmbeddingPrecision.FLOAT,
    )
    db_session.add(search_settings)
    db_session.commit()

    attempt = IndexAttempt(
        connector_credential_pair_id=cc_pair.id,
        search_settings_id=search_settings.id,
        from_beginning=True,
        status=IndexingStatus.IN_PROGRESS,
        celery_task_id=f"wd_task_{uuid4().hex[:8]}",
        total_batches=total_batches,
        completed_batches=completed_batches,
        heartbeat_counter=heartbeat_counter,
        last_heartbeat_value=last_heartbeat_value,
        last_batches_completed_count=last_batches_completed_count,
        last_heartbeat_time=datetime.now(timezone.utc)
        - timedelta(seconds=heartbeat_age_seconds),
    )
    db_session.add(attempt)
    db_session.commit()
    db_session.refresh(attempt)
    return attempt


def _set_in_flight(index_attempt_id: int, count: int) -> None:
    rd = RedisDocprocessing(index_attempt_id, get_redis_client())
    rd.cleanup()
    for _ in range(count):
        rd.incr_pending()
        rd.decr_pending_incr_in_flight()


@pytest.fixture(autouse=True)
def _no_not_started_scan() -> Generator[None, None, None]:
    """The watchdog also scans NOT_STARTED attempts via the Celery broker.

    Stub it out so these tests never touch pre-existing rows in the shared DB
    or reach for a live broker.
    """
    with patch(
        f"{_WATCHDOG_PATH}.get_stale_not_started_index_attempts",
        return_value=[],
    ):
        yield


@pytest.mark.usefixtures("tenant_context")
def test_progress_advancing_is_not_invalidated(db_session: Session) -> None:
    """Stale heartbeat + in_flight > 0 but completed_batches advancing → alive."""
    attempt = _make_attempt(
        db_session,
        total_batches=10,
        completed_batches=6,  # advanced past last_batches_completed_count
        heartbeat_counter=5,
        last_heartbeat_value=5,  # counter did NOT advance
        last_batches_completed_count=5,
        heartbeat_age_seconds=HEARTBEAT_TIMEOUT_SECONDS + 120,
    )
    _set_in_flight(attempt.id, 2)

    # Workers-alive should not even be consulted; assert it if it is.
    with patch(f"{_WATCHDOG_PATH}._docprocessing_workers_alive", return_value=True):
        validate_active_indexing_attempts(MagicMock())

    db_session.refresh(attempt)
    assert attempt.status == IndexingStatus.IN_PROGRESS
    # Progress observation is recorded so the next pass compares against it.
    assert attempt.last_batches_completed_count == 6


@pytest.mark.usefixtures("tenant_context")
def test_stale_no_progress_workers_alive_is_spared(db_session: Session) -> None:
    """Stale heartbeat + no progress + workers alive → saturated, not crashed."""
    attempt = _make_attempt(
        db_session,
        total_batches=10,
        completed_batches=6,
        heartbeat_counter=5,
        last_heartbeat_value=5,
        last_batches_completed_count=6,  # no progress since last pass
        heartbeat_age_seconds=HEARTBEAT_TIMEOUT_SECONDS + 120,
    )
    _set_in_flight(attempt.id, 2)

    with patch(f"{_WATCHDOG_PATH}._docprocessing_workers_alive", return_value=True):
        validate_active_indexing_attempts(MagicMock())

    db_session.refresh(attempt)
    assert attempt.status == IndexingStatus.IN_PROGRESS
    # The grace path resets the window so the loud log is throttled.
    assert attempt.last_heartbeat_time is not None
    assert attempt.last_heartbeat_time > datetime.now(timezone.utc) - timedelta(
        seconds=HEARTBEAT_TIMEOUT_SECONDS
    )


@pytest.mark.usefixtures("tenant_context")
def test_stale_no_progress_no_workers_is_invalidated(db_session: Session) -> None:
    """Stale heartbeat + no progress + no live workers → real crash, invalidate."""
    attempt = _make_attempt(
        db_session,
        total_batches=10,
        completed_batches=6,
        heartbeat_counter=5,
        last_heartbeat_value=5,
        last_batches_completed_count=6,
        heartbeat_age_seconds=HEARTBEAT_TIMEOUT_SECONDS + 120,
    )
    _set_in_flight(attempt.id, 2)

    with patch(f"{_WATCHDOG_PATH}._docprocessing_workers_alive", return_value=False):
        validate_active_indexing_attempts(MagicMock())

    db_session.refresh(attempt)
    assert attempt.status == IndexingStatus.FAILED
    assert attempt.error_msg is not None
    assert "workers crashed holding batches" in attempt.error_msg


@pytest.mark.usefixtures("tenant_context")
def test_liveness_ping_is_computed_once_per_pass(db_session: Session) -> None:
    """Worker liveness is cached per pass — the (up to 4s) inspect ping must not
    fire once per stale in-flight attempt."""
    attempts = [
        _make_attempt(
            db_session,
            total_batches=10,
            completed_batches=6,
            heartbeat_counter=5,
            last_heartbeat_value=5,
            last_batches_completed_count=6,
            heartbeat_age_seconds=HEARTBEAT_TIMEOUT_SECONDS + 120,
        )
        for _ in range(3)
    ]
    for attempt in attempts:
        _set_in_flight(attempt.id, 2)

    ping = MagicMock(return_value=False)
    with patch(f"{_WATCHDOG_PATH}._docprocessing_workers_alive", ping):
        validate_active_indexing_attempts(MagicMock())

    # Multiple stale in-flight attempts, but the ping is evaluated at most once.
    assert ping.call_count == 1
    for attempt in attempts:
        db_session.refresh(attempt)
        assert attempt.status == IndexingStatus.FAILED


def test_heartbeat_failure_is_surfaced_loudly() -> None:
    """Killing the heartbeat's DB session factory must escalate to ERROR, not
    stay silently swallowed forever."""
    error_logged = threading.Event()

    fake_logger = MagicMock()
    fake_logger.error.side_effect = lambda *_a, **_k: error_logged.set()

    with patch.object(heartbeat_module, "INDEXING_WORKER_HEARTBEAT_INTERVAL", 0.02):
        with patch.object(
            heartbeat_module,
            "get_session_with_current_tenant",
            side_effect=RuntimeError("session factory is dead"),
        ):
            with patch.object(heartbeat_module, "logger", fake_logger):
                thread, stop_event = heartbeat_module.start_heartbeat(
                    index_attempt_id=1
                )
                try:
                    # Threshold is 3 consecutive failures at ~0.02s each.
                    assert error_logged.wait(timeout=5.0), (
                        "heartbeat never escalated a sustained failure to ERROR"
                    )
                finally:
                    heartbeat_module.stop_heartbeat(thread, stop_event)

    # Sanity: it also warned on the earlier (sub-threshold) failures.
    assert fake_logger.warning.called
    # And it did not simply give up silently.
    assert fake_logger.error.called
