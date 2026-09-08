import pytest
from chonkie import SentenceChunker

from onyx.configs.constants import DocumentSource
from onyx.connectors.models import IndexingDocument, Section
from onyx.indexing.chunking import DocumentChunker
from onyx.indexing.embedder import DefaultIndexingEmbedder
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.natural_language_processing.utils import BaseTokenizer


class CharTokenizer(BaseTokenizer):
    """1 character == 1 token. Deterministic & trivial to reason about."""

    def encode(self, string: str) -> list[int]:
        return [ord(c) for c in string]

    def tokenize(self, string: str) -> list[str]:
        return list(string)

    def decode(self, tokens: list[int]) -> str:
        return "".join(chr(t) for t in tokens)


# With a char-level tokenizer, each char is a token. 200 is comfortably
# above BLURB_SIZE (128) so the blurb splitter won't get weird on small text.
CHUNK_LIMIT = 200


def make_document_chunker(
    chunk_token_limit: int = CHUNK_LIMIT,
    with_mini_chunks: bool = False,
) -> DocumentChunker:
    """DocumentChunker over CharTokenizer, with mini-chunking optional."""

    def token_counter(text: str) -> int:
        return len(text)

    def sentence_chunker(chunk_size: int) -> SentenceChunker:
        return SentenceChunker(
            tokenizer_or_token_counter=token_counter,
            chunk_size=chunk_size,
            chunk_overlap=0,
            return_type="texts",
        )

    return DocumentChunker(
        tokenizer=CharTokenizer(),
        blurb_splitter=sentence_chunker(128),
        chunk_splitter=sentence_chunker(chunk_token_limit),
        mini_chunk_splitter=sentence_chunker(150) if with_mini_chunks else None,
    )


def make_doc(
    sections: list[Section],
    title: str | None = "Test Doc",
    doc_id: str = "doc1",
    source: DocumentSource = DocumentSource.WEB,
) -> IndexingDocument:
    return IndexingDocument(
        id=doc_id,
        source=source,
        semantic_identifier=doc_id,
        title=title,
        metadata={},
        sections=[],  # real sections unused — method reads processed_sections
        processed_sections=sections,
    )


class MockHeartbeat(IndexingHeartbeatInterface):
    def __init__(self) -> None:
        self.call_count = 0

    def should_stop(self) -> bool:
        return False

    def progress(self, tag: str, amount: int) -> None:  # noqa: ARG002
        self.call_count += 1


@pytest.fixture
def mock_heartbeat() -> MockHeartbeat:
    return MockHeartbeat()


@pytest.fixture
def embedder() -> DefaultIndexingEmbedder:
    return DefaultIndexingEmbedder(
        model_name="intfloat/e5-base-v2",
        normalize=True,
        query_prefix=None,
        passage_prefix=None,
    )
