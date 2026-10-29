"""Batch error resolution closes only the pair's open errors for the given
documents: other documents, entity errors and other pairs stay open."""

from collections.abc import Generator

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.enums import IndexingStatus
from onyx.db.index_attempt import resolve_index_attempt_errors_for_documents
from onyx.db.models import ConnectorCredentialPair, IndexAttempt, IndexAttemptError
from onyx.db.search_settings import get_current_search_settings
from tests.external_dependency_unit.indexing_helpers import (
    cleanup_cc_pair,
    make_cc_pair,
)


@pytest.fixture
def pairs(
    db_session: Session,
) -> Generator[tuple[ConnectorCredentialPair, ConnectorCredentialPair], None, None]:
    made = (make_cc_pair(db_session), make_cc_pair(db_session))
    yield made
    db_session.rollback()
    for pair in made:
        db_session.query(IndexAttemptError).filter(
            IndexAttemptError.connector_credential_pair_id == pair.id
        ).delete(synchronize_session=False)
        db_session.query(IndexAttempt).filter(
            IndexAttempt.connector_credential_pair_id == pair.id
        ).delete(synchronize_session=False)
        db_session.commit()
        cleanup_cc_pair(db_session, pair)


def _add_error(
    db_session: Session,
    pair: ConnectorCredentialPair,
    *,
    document_id: str | None = None,
    entity_id: str | None = None,
) -> IndexAttemptError:
    attempt = IndexAttempt(
        connector_credential_pair_id=pair.id,
        search_settings_id=get_current_search_settings(db_session).id,
        from_beginning=False,
        status=IndexingStatus.IN_PROGRESS,
    )
    db_session.add(attempt)
    db_session.flush()
    error = IndexAttemptError(
        index_attempt_id=attempt.id,
        connector_credential_pair_id=pair.id,
        document_id=document_id,
        entity_id=entity_id,
        failure_message="boom",
        is_resolved=False,
    )
    db_session.add(error)
    db_session.commit()
    return error


def _is_resolved(db_session: Session, error: IndexAttemptError) -> bool:
    return (
        db_session.scalar(
            select(IndexAttemptError.is_resolved).where(
                IndexAttemptError.id == error.id
            )
        )
        is True
    )


def test_resolves_only_the_pairs_open_errors_for_the_given_documents(
    db_session: Session,
    pairs: tuple[ConnectorCredentialPair, ConnectorCredentialPair],
) -> None:
    pair, other_pair = pairs
    first = _add_error(db_session, pair, document_id="doc-a")
    repeat = _add_error(db_session, pair, document_id="doc-a")
    other_doc = _add_error(db_session, pair, document_id="doc-b")
    entity = _add_error(db_session, pair, entity_id="entity-a")
    other_pair_same_doc = _add_error(db_session, other_pair, document_id="doc-a")

    resolve_index_attempt_errors_for_documents(
        db_session=db_session,
        cc_pair_id=pair.id,
        document_ids=["doc-a", "doc-without-errors"],
    )

    assert _is_resolved(db_session, first)
    assert _is_resolved(db_session, repeat)
    for still_open in (other_doc, entity, other_pair_same_doc):
        assert not _is_resolved(db_session, still_open)
