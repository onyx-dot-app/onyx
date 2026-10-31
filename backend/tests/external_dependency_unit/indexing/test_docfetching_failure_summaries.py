"""The attempt row says why docfetching ended: a pre-run 5xx fails it with that
error, a requested stop cancels it, and a stale stop fence still fails it."""

import contextlib
import threading
from collections.abc import Generator
from http.server import BaseHTTPRequestHandler, HTTPServer
from uuid import uuid4

import pytest
from sqlalchemy import update
from sqlalchemy.orm import Session

from onyx.background.celery.tasks.docfetching.tasks import docfetching_proxy_task
from onyx.background.indexing.run_docfetching import mark_attempt_failed_unless_terminal
from onyx.configs.constants import DocumentSource
from onyx.connectors.web.connector import WEB_CONNECTOR_VALID_SETTINGS
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import IndexingStatus
from onyx.db.index_attempt import mark_attempt_canceled
from onyx.db.models import ConnectorCredentialPair, IndexAttempt
from onyx.db.search_settings import get_current_search_settings
from onyx.redis.redis_connector import RedisConnector
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from tests.external_dependency_unit.indexing_helpers import (
    cleanup_cc_pair,
    make_cc_pair,
)


class _InternalServerErrorHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(500)
        self.end_headers()


@pytest.fixture
def failing_site_url(monkeypatch: pytest.MonkeyPatch) -> Generator[str, None, None]:
    """A loopback site that answers every request with HTTP 500."""
    # The spawned docfetching process reads this at import, so its web
    # connector may reach loopback.
    monkeypatch.setenv("OPEN_URL_VALIDATE_SSRF", "false")
    server = HTTPServer(("127.0.0.1", 0), _InternalServerErrorHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/"
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def web_cc_pair(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    failing_site_url: str,
) -> Generator[ConnectorCredentialPair, None, None]:
    pair = make_cc_pair(db_session, DocumentSource.WEB)
    pair.connector.connector_specific_config = {
        "base_url": failing_site_url,
        "web_connector_type": WEB_CONNECTOR_VALID_SETTINGS.SINGLE.value,
    }
    db_session.commit()
    try:
        yield pair
    finally:
        db_session.rollback()
        db_session.query(IndexAttempt).filter(
            IndexAttempt.connector_credential_pair_id == pair.id
        ).delete(synchronize_session="fetch")
        db_session.commit()
        cleanup_cc_pair(db_session, pair)


def _add_attempt(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    *,
    cancellation_requested: bool,
) -> IndexAttempt:
    attempt = IndexAttempt(
        connector_credential_pair_id=cc_pair.id,
        search_settings_id=get_current_search_settings(db_session).id,
        from_beginning=False,
        status=IndexingStatus.NOT_STARTED,
        celery_task_id=f"test_celery_task_{uuid4().hex[:8]}",
        cancellation_requested=cancellation_requested,
    )
    db_session.add(attempt)
    db_session.commit()
    return attempt


def _run_watchdog(attempt: IndexAttempt) -> None:
    docfetching_proxy_task.run(
        index_attempt_id=attempt.id,  # ty: ignore[invalid-argument-type]
        cc_pair_id=attempt.connector_credential_pair_id,  # ty: ignore[invalid-argument-type]
        search_settings_id=attempt.search_settings_id,  # ty: ignore[invalid-argument-type]
        tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE,  # ty: ignore[invalid-argument-type]
    )


def _reload(db_session: Session, attempt_id: int) -> IndexAttempt:
    db_session.expire_all()
    attempt = db_session.get(IndexAttempt, attempt_id)
    assert attempt is not None
    return attempt


def test_validation_5xx_fails_the_attempt_with_the_real_error(
    db_session: Session,
    web_cc_pair: ConnectorCredentialPair,
    failing_site_url: str,
) -> None:
    attempt = _add_attempt(db_session, web_cc_pair, cancellation_requested=False)

    # The watchdog raises when it reads the child's exit code. It can also see
    # the finalized attempt first and stop the child without raising.
    with contextlib.suppress(RuntimeError):
        _run_watchdog(attempt)

    finished = _reload(db_session, attempt.id)
    assert finished.status == IndexingStatus.FAILED
    assert finished.error_msg is not None
    assert finished.error_msg.startswith(
        f"Unexpected error validating '{failing_site_url}': Internal Server Error (500)"
    )
    assert finished.full_exception_trace is not None
    assert "UnexpectedValidationError" in finished.full_exception_trace


def test_cancel_request_before_start_cancels_the_attempt(
    db_session: Session,
    web_cc_pair: ConnectorCredentialPair,
) -> None:
    attempt = _add_attempt(db_session, web_cc_pair, cancellation_requested=True)

    _run_watchdog(attempt)

    finished = _reload(db_session, attempt.id)
    assert finished.status == IndexingStatus.CANCELED


@pytest.fixture
def stale_stop_fence(
    web_cc_pair: ConnectorCredentialPair,
) -> Generator[None, None, None]:
    """A stop fence on an active pair, as a pause whose commit failed leaves."""
    stop = RedisConnector(POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE, web_cc_pair.id).stop
    stop.set_fence(True)
    try:
        yield
    finally:
        stop.set_fence(False)


def test_stale_stop_fence_on_an_active_pair_fails_the_attempt(
    db_session: Session,
    web_cc_pair: ConnectorCredentialPair,
    stale_stop_fence: None,  # noqa: ARG001
) -> None:
    attempt = _add_attempt(db_session, web_cc_pair, cancellation_requested=False)

    with pytest.raises(RuntimeError):
        _run_watchdog(attempt)

    finished = _reload(db_session, attempt.id)
    assert finished.status == IndexingStatus.FAILED


def test_a_terminal_status_is_kept_under_the_row_lock(
    db_session: Session,
    web_cc_pair: ConnectorCredentialPair,
) -> None:
    attempt = _add_attempt(db_session, web_cc_pair, cancellation_requested=False)
    # This session keeps the row loaded as NOT_STARTED while another writer finalizes it.
    assert _reload(db_session, attempt.id).status == IndexingStatus.NOT_STARTED
    with get_session_with_current_tenant() as other_session:
        other_session.execute(
            update(IndexAttempt)
            .where(IndexAttempt.id == attempt.id)
            .values(status=IndexingStatus.INTERRUPTED)
        )
        other_session.commit()

    mark_attempt_canceled(attempt.id, db_session, "late cancel", unless_terminal=True)
    mark_attempt_failed_unless_terminal(attempt.id, RuntimeError("late failure"))

    assert _reload(db_session, attempt.id).status == IndexingStatus.INTERRUPTED
