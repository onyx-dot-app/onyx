"""ChunkBatchStore keeps source documents out of its batch files."""

from onyx.connectors.models import Document, DocumentSource, TextSection
from onyx.indexing.chunk_batch_store import ChunkBatchStore
from onyx.indexing.models import ChunkEmbedding, IndexChunk

_DOCUMENT_TEXT = "DOCUMENT-TEXT-MARKER " * 500


def _make_doc(doc_id: str) -> Document:
    return Document(
        id=doc_id,
        semantic_identifier=doc_id,
        source=DocumentSource.FILE,
        sections=[TextSection(text=_DOCUMENT_TEXT, link=None)],
        metadata={},
    )


def _make_chunk(document: Document, chunk_id: int) -> IndexChunk:
    return IndexChunk(
        chunk_id=chunk_id,
        blurb="blurb",
        content=f"content {chunk_id}",
        source_links={0: "link"},
        image_file_id=None,
        section_continuation=False,
        source_document=document,
        title_prefix="",
        metadata_suffix_semantic="",
        metadata_suffix_keyword="",
        mini_chunk_texts=None,
        large_chunk_id=None,
        doc_summary="",
        chunk_context="",
        contextual_rag_reserved_tokens=0,
        embeddings=ChunkEmbedding(
            full_embedding=[0.1, 0.2, 0.3],
            mini_chunk_embeddings=[],
        ),
    )


def test_batch_files_do_not_repeat_the_document() -> None:
    document = _make_doc("doc")
    first_batch = [_make_chunk(document, 0), _make_chunk(document, 1)]
    second_batch = [_make_chunk(document, 2)]

    with ChunkBatchStore() as store:
        store.save(first_batch, batch_idx=0)
        store.save(second_batch, batch_idx=1)

        for batch_file in store._batch_files():
            assert b"DOCUMENT-TEXT-MARKER" not in batch_file.read_bytes()

        # The write path reads the stream more than once.
        for _ in range(2):
            stored = list(store.stream())
            assert stored == first_batch + second_batch
            assert all(chunk.source_document is document for chunk in stored)


def test_scrub_keeps_the_documents_of_other_chunks() -> None:
    kept_document = _make_doc("kept")
    # Two objects with one id, as when each chunk carries its own copy.
    failed_documents = [_make_doc("failed"), _make_doc("failed")]
    chunks = [
        _make_chunk(failed_documents[0], 0),
        _make_chunk(kept_document, 0),
        _make_chunk(failed_documents[1], 1),
        _make_chunk(kept_document, 1),
    ]

    with ChunkBatchStore() as store:
        store.save(chunks[:2], batch_idx=0)
        store.save(chunks[2:], batch_idx=1)
        store.scrub_failed_docs({"failed"})

        stored = list(store.stream())

    assert stored == [chunks[1], chunks[3]]
    assert all(chunk.source_document is kept_document for chunk in stored)
