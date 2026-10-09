"""External dependency tests for open_url URL -> Document.id resolution.

Uses real Postgres because the resolution under test (_resolve_urls_to_document_ids)
matches candidate URLs against actual `Document.id` rows via `filter_existing_document_ids`.
The bug this guards: a Google Doc indexed under the `docs.google.com/document/d/<id>`
form must still be found when the user pastes the type-ambiguous
`drive.google.com/file/d/<id>` form.
"""

from collections.abc import Generator
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.db.models import Document as DBDocument
from onyx.kg.models import KGStage
from onyx.tools.tool_implementations.open_url.open_url_tool import (
    _resolve_urls_to_document_ids,
)


@pytest.fixture
def doc_cleanup(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[list[str], None, None]:
    created: list[str] = []
    try:
        yield created
    finally:
        if created:
            db_session.query(DBDocument).filter(DBDocument.id.in_(created)).delete(
                synchronize_session="fetch"
            )
            db_session.commit()


def _seed_doc(db_session: Session, tracker: list[str], doc_id: str) -> None:
    doc = DBDocument(
        id=doc_id,
        semantic_id=f"semantic-{doc_id}",
        kg_stage=KGStage.NOT_STARTED,
    )
    db_session.add(doc)
    db_session.commit()
    tracker.append(doc_id)


def test_file_d_url_resolves_to_indexed_native_doc(
    db_session: Session,
    doc_cleanup: list[str],
) -> None:
    """A pasted drive.google.com/file/d/<id> URL resolves to a doc indexed under
    the docs.google.com/document/d/<id> form."""
    file_id = uuid4().hex
    indexed_id = f"https://docs.google.com/document/d/{file_id}"
    _seed_doc(db_session, doc_cleanup, indexed_id)

    pasted = f"https://drive.google.com/file/d/{file_id}/view"
    matches, unresolved = _resolve_urls_to_document_ids([pasted], db_session)

    assert unresolved == []
    assert len(matches) == 1
    assert matches[0].document_id == indexed_id
    assert matches[0].original_url == pasted


def test_unindexed_file_id_is_unresolved(
    db_session: Session,
    doc_cleanup: list[str],  # noqa: ARG001
) -> None:
    """A file id that isn't in the index resolves to nothing (falls back to crawl)."""
    pasted = f"https://drive.google.com/file/d/{uuid4().hex}/view"
    matches, unresolved = _resolve_urls_to_document_ids([pasted], db_session)

    assert matches == []
    assert unresolved == [pasted]
