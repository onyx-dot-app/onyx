from abc import ABC
from abc import abstractmethod
from collections.abc import Sequence
from typing import cast

from chonkie import SentenceChunker
from pydantic import BaseModel
from pydantic import Field

from onyx.connectors.models import IndexingDocument
from onyx.connectors.models import Section
from onyx.indexing.models import DocAwareChunk


def extract_blurb(text: str, blurb_splitter: SentenceChunker) -> str:
    texts = cast(list[str], blurb_splitter.chunk(text))
    if not texts:
        return ""
    return texts[0]


def get_mini_chunk_texts(
    chunk_text: str,
    mini_chunk_splitter: SentenceChunker | None,
) -> list[str] | None:
    if mini_chunk_splitter and chunk_text.strip():
        return list(cast(Sequence[str], mini_chunk_splitter.chunk(chunk_text)))
    return None


class ChunkPayload(BaseModel):
    """Section-local chunk content without document-scoped fields.

    The orchestrator upgrades these to DocAwareChunks via
    `to_doc_aware_chunk` after assigning chunk_ids and attaching
    title/metadata.
    """

    text: str
    links: dict[int, str]
    is_continuation: bool = False
    image_file_id: str | None = None

    def to_doc_aware_chunk(
        self,
        document: IndexingDocument,
        chunk_id: int,
        blurb_splitter: SentenceChunker,
        title_prefix: str = "",
        metadata_suffix_semantic: str = "",
        metadata_suffix_keyword: str = "",
        mini_chunk_splitter: SentenceChunker | None = None,
    ) -> DocAwareChunk:
        return DocAwareChunk(
            source_document=document,
            chunk_id=chunk_id,
            blurb=extract_blurb(self.text, blurb_splitter),
            content=self.text,
            source_links=self.links or {0: ""},
            image_file_id=self.image_file_id,
            section_continuation=self.is_continuation,
            title_prefix=title_prefix,
            metadata_suffix_semantic=metadata_suffix_semantic,
            metadata_suffix_keyword=metadata_suffix_keyword,
            mini_chunk_texts=get_mini_chunk_texts(self.text, mini_chunk_splitter),
            large_chunk_id=None,
            doc_summary="",
            chunk_context="",
            contextual_rag_reserved_tokens=0,
        )


class AccumulatorState(BaseModel):
    """Cross-section text buffer threaded through SectionChunkers."""

    text: str = ""
    link_offsets: dict[int, str] = Field(default_factory=dict)

    def is_empty(self) -> bool:
        return not self.text.strip()

    def flush_to_list(self) -> list[ChunkPayload]:
        if self.is_empty():
            return []
        return [ChunkPayload(text=self.text, links=self.link_offsets)]


class SectionChunkerOutput(BaseModel):
    payloads: list[ChunkPayload]
    accumulator: AccumulatorState


class SectionChunker(ABC):
    @abstractmethod
    def chunk_section(
        self,
        section: Section,
        accumulator: AccumulatorState,
        content_token_limit: int,
    ) -> SectionChunkerOutput: ...
