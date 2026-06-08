"""External dependency unit tests for the reindex-port sync-enqueue priority (T8/D9).

Covers: the UNION select surfacing needs_sync + deferred docs (each self-tagged);
the gate count including deferred-only docs; the any-FUTURE-port-in-progress
pre-query; and the producer's per-doc priority (deferred doc LOW while a port runs,
HIGH once it stops; needs_sync MEDIUM normally but LOW while a completed port's
backlog drains) plus the expires= on every enqueue. The Celery send_task is mocked
— we assert the producer's decision, not real dispatch.
"""

from collections.abc import Generator
from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from onyx.background.celery.tasks.vespa.document_sync import (
    generate_document_sync_tasks,
)
from onyx.configs.constants import OnyxCeleryPriority
from onyx.db.document import (
    construct_document_id_select_by_needs_sync_or_secondary_pending,
)
from onyx.db.document import count_documents_by_needs_sync
from onyx.db.document import count_documents_by_needs_sync_or_secondary_pending
from onyx.db.document import mark_document_as_modified
from onyx.db.document import mark_document_synced_secondary_pending
from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import Document as DbDocument
from onyx.db.port_attempt import any_future_port_in_progress
from onyx.db.port_attempt import create_port_attempt
from onyx.db.port_attempt import mark_port_in_progress
from onyx.db.port_attempt import mark_port_succeeded
from onyx.kg.models import KGStage
from tests.external_dependency_unit.indexing_helpers import cleanup_cc_pair_and_future
from tests.external_dependency_unit.indexing_helpers import make_cc_pair
from tests.external_dependency_unit.indexing_helpers import make_future_search_settings

_DOC_PREFIX = "syncdoc-"


@pytest.fixture
def cc_pair_and_future(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[tuple[ConnectorCredentialPair, int], None, None]:
    pair = make_cc_pair(db_session)
    future_id = make_future_search_settings(db_session).id
    try:
        yield pair, future_id
    finally:
        cleanup_cc_pair_and_future(db_session, pair, future_id, doc_prefix=_DOC_PREFIX)


def _make_doc(db_session: Session, doc_id: str) -> None:
    db_session.add(
        DbDocument(id=doc_id, semantic_id=doc_id, kg_stage=KGStage.NOT_STARTED)
    )
    db_session.commit()
    mark_document_as_modified(doc_id, db_session)  # needs_sync


def _run_generate(db_session: Session) -> dict[str, dict[str, int]]:
    """Run the producer with mocked Celery/Redis; return {doc_id: {priority, expires}}
    for this test's docs only (the select is tenant-global)."""
    celery_app = MagicMock()
    generate_document_sync_tasks(
        MagicMock(),  # redis client
        10**9,  # max_tasks (process everything)
        celery_app,
        db_session,
        MagicMock(),  # lock
        "test-tenant",
    )
    captured: dict[str, dict[str, int]] = {}
    for call in celery_app.send_task.call_args_list:
        doc_id = call.kwargs["kwargs"]["document_id"]
        if doc_id.startswith(_DOC_PREFIX):
            captured[doc_id] = {
                "priority": call.kwargs["priority"],
                "expires": call.kwargs["expires"],
            }
    return captured


@pytest.mark.usefixtures("cc_pair_and_future")
def test_select_needs_sync_or_secondary_pending_surfaces_both(
    db_session: Session,
) -> None:
    _make_doc(db_session, f"{_DOC_PREFIX}A")  # needs_sync
    _make_doc(db_session, f"{_DOC_PREFIX}B")
    mark_document_synced_secondary_pending(f"{_DOC_PREFIX}B", db_session)  # deferred

    stmt = construct_document_id_select_by_needs_sync_or_secondary_pending()
    rows = {
        (doc_id, flag)
        for doc_id, flag in db_session.execute(stmt)
        if doc_id.startswith(_DOC_PREFIX)
    }
    assert (f"{_DOC_PREFIX}A", False) in rows  # needs_sync leg, self-tagged False
    assert (f"{_DOC_PREFIX}B", True) in rows  # deferred leg, self-tagged True


@pytest.mark.usefixtures("cc_pair_and_future")
def test_needs_sync_and_deferred_doc_tags_false(db_session: Session) -> None:
    """A doc that is BOTH needs_sync and deferred surfaces once via the needs_sync
    leg (tag False) -> real work wins, never under-prioritized to LOW."""
    doc_id = f"{_DOC_PREFIX}C"
    _make_doc(db_session, doc_id)  # needs_sync
    mark_document_synced_secondary_pending(
        doc_id, db_session
    )  # deferred (needs_sync cleared)
    mark_document_as_modified(doc_id, db_session)  # re-dirty -> needs_sync AND deferred

    stmt = construct_document_id_select_by_needs_sync_or_secondary_pending()
    rows = {(d, f) for d, f in db_session.execute(stmt) if d.startswith(_DOC_PREFIX)}
    assert (doc_id, False) in rows
    assert (doc_id, True) not in rows


@pytest.mark.usefixtures("cc_pair_and_future")
def test_count_or_includes_deferred_only(
    db_session: Session,
) -> None:
    before_or = count_documents_by_needs_sync_or_secondary_pending(db_session)
    before_needs_sync = count_documents_by_needs_sync(db_session)

    _make_doc(db_session, f"{_DOC_PREFIX}B")
    mark_document_synced_secondary_pending(f"{_DOC_PREFIX}B", db_session)  # deferred

    # the OR-count sees the deferred doc; the plain needs_sync count does not
    assert (
        count_documents_by_needs_sync_or_secondary_pending(db_session) == before_or + 1
    )
    assert count_documents_by_needs_sync(db_session) == before_needs_sync


def test_any_future_port_in_progress(
    db_session: Session, cc_pair_and_future: tuple[ConnectorCredentialPair, int]
) -> None:
    cc_pair, future_id = cc_pair_and_future
    assert any_future_port_in_progress(db_session) is False

    attempt = create_port_attempt(db_session, cc_pair.id, future_id)
    mark_port_in_progress(db_session, attempt.id)
    assert any_future_port_in_progress(db_session) is True

    mark_port_succeeded(db_session, attempt.id)
    assert any_future_port_in_progress(db_session) is False


def test_sync_priority_across_three_states(
    db_session: Session, cc_pair_and_future: tuple[ConnectorCredentialPair, int]
) -> None:
    cc_pair, future_id = cc_pair_and_future
    _make_doc(db_session, f"{_DOC_PREFIX}A")  # needs_sync
    _make_doc(db_session, f"{_DOC_PREFIX}B")
    mark_document_synced_secondary_pending(f"{_DOC_PREFIX}B", db_session)  # deferred

    # port running: needs_sync stays MEDIUM, deferred drops to LOW
    attempt = create_port_attempt(db_session, cc_pair.id, future_id)
    mark_port_in_progress(db_session, attempt.id)
    captured = _run_generate(db_session)
    assert captured[f"{_DOC_PREFIX}A"]["priority"] == OnyxCeleryPriority.MEDIUM
    assert captured[f"{_DOC_PREFIX}B"]["priority"] == OnyxCeleryPriority.LOW
    assert captured[f"{_DOC_PREFIX}A"]["expires"] > 0
    assert captured[f"{_DOC_PREFIX}B"]["expires"] > 0

    # port stopped with a deferred backlog still pending: that drain is the swap
    # gate, so the deferred doc goes HIGH and needs_sync yields to LOW
    mark_port_succeeded(db_session, attempt.id)
    captured = _run_generate(db_session)
    assert captured[f"{_DOC_PREFIX}B"]["priority"] == OnyxCeleryPriority.HIGH
    assert captured[f"{_DOC_PREFIX}A"]["priority"] == OnyxCeleryPriority.LOW
