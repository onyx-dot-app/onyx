from abc import ABC
from abc import abstractmethod
from typing import cast

from chonkie import SentenceChunker
from pydantic import BaseModel
from pydantic import Field

from onyx.connectors.models import IndexingDocument
from onyx.connectors.models import Section
from onyx.indexing.models import DocAwareChunk


def extract_blurb(text: str, blurb_splitter: SentenceChunker) -> str:
    """Extract a short blurb from the text (first chunk of `blurb_size`)."""
    texts = cast(list[str], blurb_splitter.chunk(text))
    if not texts:
        return ""
    return texts[0]


def get_mini_chunk_texts(
    chunk_text: str,
    mini_chunk_splitter: SentenceChunker | None,
) -> list[str] | None:
    """For multipass mode: additional sub-chunks for certain embeddings."""
    if mini_chunk_splitter and chunk_text.strip():
        return cast(list[str], mini_chunk_splitter.chunk(chunk_text))
    return None


class ChunkPayload(BaseModel):
    """A finalized chunk's section-local content.

    Intentionally does NOT carry document-scoped fields (chunk_id,
    source_document, title_prefix, metadata_suffix_*,
    contextual_rag_reserved_tokens) — those are layered on by the
    orchestrator when it converts payloads into DocAwareChunks via
    `to_doc_aware_chunk`.
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
        """Upgrade this section-local payload to a full DocAwareChunk."""
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
            mini_chunk_texts=get_mini_chunk_texts(
                self.text, mini_chunk_splitter
            ),
            large_chunk_id=None,
            doc_summary="",
            chunk_context="",
            contextual_rag_reserved_tokens=0,
        )


class AccumulatorState(BaseModel):
    """Cross-section combining state threaded through SectionChunkers.

    Mirrors the `chunk_text` / `link_offsets` locals in the legacy
    `_chunk_document_with_sections`, but lifted to a first-class type so
    it can be passed explicitly between section chunkers and the
    orchestrator.
    """

    text: str = ""
    link_offsets: dict[int, str] = Field(default_factory=dict)

    def is_empty(self) -> bool:
        return not self.text.strip()

    def flush_to_list(self) -> list["ChunkPayload"]:
        """Return a single-element list if non-empty, else empty list.

        Convenience for the common flush-extend pattern so callers can
        write `payloads.extend(accumulator.flush_to_list())` instead of
        a 3-line conditional.
        """
        if self.is_empty():
            return []
        return [ChunkPayload(text=self.text, links=self.link_offsets)]


class SectionChunkerOutput(BaseModel):
    """What a SectionChunker returns after processing a single section.

    `payloads` are chunks that have been fully finalized and should be
    appended to the orchestrator's running list (in order). `accumulator`
    is the new cross-section buffer state to carry into the next section.
    """

    payloads: list[ChunkPayload]
    accumulator: AccumulatorState


class SectionChunker(ABC):
    """Per-section chunker. Stateless — all cross-section state is threaded
    through the `accumulator` argument, and all document-scoped concerns
    (chunk_id assignment, title/metadata propagation, skip logic, safety
    fallback chunk) are handled by the orchestrator.
    """

    @abstractmethod
    def chunk_section(
        self,
        section: Section,
        accumulator: AccumulatorState,
        content_token_limit: int,
    ) -> SectionChunkerOutput:
        ...
