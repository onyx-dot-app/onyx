"""External dependency tests for the `Document.file_id` enrichment pipeline.

Two tightly-coupled surfaces live in this file:

  1. `get_document_id_to_file_id_map` — the batched DB lookup that joins
     chunk-level `document_id`s to their `Document.file_id` rows.
  2. `populate_file_ids_on_sections` — the post-retrieval enrichment step
     that calls (1) and stamps `file_id` onto every `InferenceChunk` in a
     batch of sections.

Uses real Postgres — mocking the ORM would defeat the point of the batched
query (1) and would hide the section-mutation behavior of (2).
"""

from collections.abc import Generator
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.context.search.models import InferenceChunk
from onyx.context.search.models import InferenceSection
from onyx.context.search.utils import populate_file_ids_on_sections
from onyx.db.document import get_document_id_to_file_id_map
from onyx.db.models import Document as DBDocument
from onyx.kg.models import KGStage


@pytest.fixture
def doc_cleanup(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[list[str], None, None]:
    """Tracks doc_ids seeded by the test so teardown can reap them.

    These tests seed Document rows directly (no cc_pair wiring) because the
    lookup under test only touches `Document.id` / `Document.file_id`.
    """
    created: list[str] = []
    try:
        yield created
    finally:
        if created:
            db_session.query(DBDocument).filter(DBDocument.id.in_(created)).delete(
                synchronize_session="fetch"
            )
            db_session.commit()


def _seed_doc(
    db_session: Session,
    tracker: list[str],
    doc_id: str,
    file_id: str | None,
) -> DBDocument:
    doc = DBDocument(
        id=doc_id,
        semantic_id=f"semantic-{doc_id}",
        kg_stage=KGStage.NOT_STARTED,
        file_id=file_id,
    )
    db_session.add(doc)
    db_session.commit()
    tracker.append(doc_id)
    return doc


class TestGetDocumentIdToFileIdMap:
    def test_returns_mapping_only_for_docs_with_file_id(
        self,
        db_session: Session,
        doc_cleanup: list[str],
    ) -> None:
        with_file = f"doc-{uuid4().hex[:8]}"
        without_file = f"doc-{uuid4().hex[:8]}"
        _seed_doc(db_session, doc_cleanup, with_file, file_id="file-abc")
        _seed_doc(db_session, doc_cleanup, without_file, file_id=None)

        result = get_document_id_to_file_id_map(
            db_session=db_session,
            document_ids=[with_file, without_file],
        )

        # Only the doc with a file_id appears; missing keys mean "no file".
        assert result == {with_file: "file-abc"}

    def test_empty_input_returns_empty_map(self, db_session: Session) -> None:
        assert get_document_id_to_file_id_map(db_session, []) == {}

    def test_unknown_document_ids_are_silently_ignored(
        self,
        db_session: Session,
        doc_cleanup: list[str],
    ) -> None:
        known = f"doc-{uuid4().hex[:8]}"
        _seed_doc(db_session, doc_cleanup, known, file_id="file-xyz")

        result = get_document_id_to_file_id_map(
            db_session=db_session,
            document_ids=[known, "doc-does-not-exist"],
        )

        assert result == {known: "file-xyz"}

    def test_multiple_docs_all_with_file_ids(
        self,
        db_session: Session,
        doc_cleanup: list[str],
    ) -> None:
        doc_a = f"doc-{uuid4().hex[:8]}"
        doc_b = f"doc-{uuid4().hex[:8]}"
        doc_c = f"doc-{uuid4().hex[:8]}"
        _seed_doc(db_session, doc_cleanup, doc_a, file_id="file-a")
        _seed_doc(db_session, doc_cleanup, doc_b, file_id="file-b")
        _seed_doc(db_session, doc_cleanup, doc_c, file_id="file-c")

        result = get_document_id_to_file_id_map(
            db_session=db_session,
            document_ids=[doc_a, doc_b, doc_c],
        )

        assert result == {doc_a: "file-a", doc_b: "file-b", doc_c: "file-c"}


# ---------------------------------------------------------------------------
# `populate_file_ids_on_sections` — helpers for InferenceChunk fabrication
# ---------------------------------------------------------------------------


def _make_chunk(document_id: str, chunk_id: int = 0) -> InferenceChunk:
    return InferenceChunk(
        document_id=document_id,
        chunk_id=chunk_id,
        content=f"content-{document_id}-{chunk_id}",
        source_type=DocumentSource.MOCK_CONNECTOR,
        semantic_identifier=f"sem-{document_id}",
        title=document_id,
        boost=1,
        score=0.5,
        hidden=False,
        metadata={},
        match_highlights=[],
        doc_summary="",
        chunk_context="",
        updated_at=None,
        image_file_id=None,
        source_links={},
        section_continuation=False,
        blurb="",
        file_id=None,
    )


def _make_section(
    center: InferenceChunk,
    *adjacent: InferenceChunk,
) -> InferenceSection:
    return InferenceSection(
        center_chunk=center,
        chunks=[center, *adjacent],
        combined_content=" ".join(c.content for c in (center, *adjacent)),
    )


class TestPopulateFileIdsOnSections:
    def test_stamps_file_id_on_matching_chunk(
        self,
        db_session: Session,
        doc_cleanup: list[str],
    ) -> None:
        doc_id = f"doc-{uuid4().hex[:8]}"
        _seed_doc(db_session, doc_cleanup, doc_id, file_id="file-abc")

        section = _make_section(_make_chunk(doc_id))
        populate_file_ids_on_sections([section], db_session)

        assert section.center_chunk.file_id == "file-abc"

    def test_stamps_file_id_on_all_chunks_in_section(
        self,
        db_session: Session,
        doc_cleanup: list[str],
    ) -> None:
        """Adjacent chunks for the same doc all share the same file_id so
        downstream code doesn't care which chunk it inspects."""
        doc_id = f"doc-{uuid4().hex[:8]}"
        _seed_doc(db_session, doc_cleanup, doc_id, file_id="file-shared")

        center = _make_chunk(doc_id, chunk_id=5)
        above = _make_chunk(doc_id, chunk_id=4)
        below = _make_chunk(doc_id, chunk_id=6)
        section = _make_section(center, above, below)

        populate_file_ids_on_sections([section], db_session)

        assert all(c.file_id == "file-shared" for c in section.chunks)

    def test_doc_without_file_id_leaves_chunk_unchanged(
        self,
        db_session: Session,
        doc_cleanup: list[str],
    ) -> None:
        doc_id = f"doc-{uuid4().hex[:8]}"
        _seed_doc(db_session, doc_cleanup, doc_id, file_id=None)

        section = _make_section(_make_chunk(doc_id))
        populate_file_ids_on_sections([section], db_session)

        assert section.center_chunk.file_id is None

    def test_unknown_document_leaves_chunk_unchanged(
        self,
        db_session: Session,
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        """Federated hits (Slack, internet) have no `Document` row in
        Postgres — they should cleanly stay `file_id=None`."""
        section = _make_section(_make_chunk("nonexistent-doc-id"))
        populate_file_ids_on_sections([section], db_session)

        assert section.center_chunk.file_id is None

    def test_mixed_batch_only_matches_get_stamped(
        self,
        db_session: Session,
        doc_cleanup: list[str],
    ) -> None:
        with_file = f"doc-{uuid4().hex[:8]}"
        without_file = f"doc-{uuid4().hex[:8]}"
        _seed_doc(db_session, doc_cleanup, with_file, file_id="file-mixed")
        _seed_doc(db_session, doc_cleanup, without_file, file_id=None)

        section_a = _make_section(_make_chunk(with_file))
        section_b = _make_section(_make_chunk(without_file))
        section_c = _make_section(_make_chunk("nonexistent-id"))

        populate_file_ids_on_sections([section_a, section_b, section_c], db_session)

        assert section_a.center_chunk.file_id == "file-mixed"
        assert section_b.center_chunk.file_id is None
        assert section_c.center_chunk.file_id is None

    def test_empty_input_is_noop(
        self,
        db_session: Session,
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        # Shouldn't raise, shouldn't query the DB meaningfully.
        populate_file_ids_on_sections([], db_session)

    def test_all_chunks_unknown_shortcircuits_cleanly(
        self,
        db_session: Session,
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        """When no Document rows exist for any chunk, the early-return
        path skips the per-section mutation loop — just assert nothing
        explodes and chunks stay None."""
        sections = [_make_section(_make_chunk(f"ghost-{i}")) for i in range(3)]
        populate_file_ids_on_sections(sections, db_session)
        assert all(s.center_chunk.file_id is None for s in sections)
