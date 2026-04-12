from chonkie import SentenceChunker

from onyx.connectors.models import IndexingDocument
from onyx.connectors.models import Section
from onyx.connectors.models import SectionKind
from onyx.indexing.document_chunker.image_section_chunker import ImageChunker
from onyx.indexing.document_chunker.section_chunker import AccumulatorState
from onyx.indexing.document_chunker.section_chunker import ChunkPayload
from onyx.indexing.document_chunker.section_chunker import SectionChunker
from onyx.indexing.document_chunker.text_section_chunker import TextChunker
from onyx.indexing.models import DocAwareChunk
from onyx.natural_language_processing.utils import BaseTokenizer
from onyx.utils.logger import setup_logger
from onyx.utils.text_processing import clean_text

logger = setup_logger()


class DocumentChunker:
    """Converts a document's processed sections into DocAwareChunks.

    Drop-in replacement for `Chunker._chunk_document_with_sections` in
    `onyx/indexing/chunker.py`. This class owns:

    - The section dispatch loop (routing each section to the right
      `SectionChunker` — text, image, future spreadsheet, etc.)
    - The cross-section accumulator threading
    - The empty-text skip guard
    - The final-flush + empty-doc safety branch
    - Chunk_id assignment and payload → `DocAwareChunk` conversion

    Everything upstream of this — title prep, metadata prep, contextual-
    RAG token negotiation, large-chunk multipass, heartbeat callbacks —
    stays in the caller (`Chunker._handle_single_document`).
    """

    def __init__(
        self,
        tokenizer: BaseTokenizer,
        blurb_splitter: SentenceChunker,
        chunk_splitter: SentenceChunker,
        mini_chunk_splitter: SentenceChunker | None = None,
    ) -> None:
        self.blurb_splitter = blurb_splitter
        self.mini_chunk_splitter = mini_chunk_splitter

        self._dispatch: dict[SectionKind, SectionChunker] = {
            SectionKind.TEXT: TextChunker(
                tokenizer=tokenizer,
                chunk_splitter=chunk_splitter,
            ),
            SectionKind.IMAGE: ImageChunker(),
        }

    # --- Public entry point ------------------------------------------------

    def chunk(
        self,
        document: IndexingDocument,
        sections: list[Section],
        title_prefix: str,
        metadata_suffix_semantic: str,
        metadata_suffix_keyword: str,
        content_token_limit: int,
    ) -> list[DocAwareChunk]:
        """Convert a document's sections into chunks.

        Matches the signature and behavior of
        `Chunker._chunk_document_with_sections` so the caller
        (`_handle_single_document`) can swap in this method with no
        other changes.
        """
        payloads = self._collect_section_payloads(
            document=document,
            sections=sections,
            content_token_limit=content_token_limit,
        )

        # Safety branch: every document produces at least one chunk.
        # Matches the legacy `if chunk_text.strip() or not chunks:`
        # guard, keeping titled-but-empty documents indexable.
        if not payloads:
            payloads.append(ChunkPayload(text="", links={0: ""}))

        # Upgrade payloads → DocAwareChunks with enumerated ids.
        return [
            payload.to_doc_aware_chunk(
                document=document,
                chunk_id=idx,
                blurb_splitter=self.blurb_splitter,
                mini_chunk_splitter=self.mini_chunk_splitter,
                title_prefix=title_prefix,
                metadata_suffix_semantic=metadata_suffix_semantic,
                metadata_suffix_keyword=metadata_suffix_keyword,
            )
            for idx, payload in enumerate(payloads)
        ]

    # --- Section dispatch loop --------------------------------------------

    def _collect_section_payloads(
        self,
        document: IndexingDocument,
        sections: list[Section],
        content_token_limit: int,
    ) -> list[ChunkPayload]:
        """Iterate sections, dispatch each to the appropriate
        `SectionChunker`, thread the accumulator state across calls, and
        return the combined payload list (including the final flush).
        """
        accumulator = AccumulatorState()
        payloads: list[ChunkPayload] = []

        for section_idx, section in enumerate(sections):
            section_text = clean_text(str(section.text or ""))

            # Skip empty-text sections but ensure at least 1 chunk exists
			# for the section
            if not section_text and (
                not document.title or section_idx > 0
            ):
                logger.warning(
                    f"Skipping empty or irrelevant section in doc "
                    f"{document.semantic_identifier}, link={section.link}"
                )
                continue

            chunker = self._select_chunker(section)
            result = chunker.chunk_section(
                section=section,
                accumulator=accumulator,
                content_token_limit=content_token_limit,
            )
            payloads.extend(result.payloads)
            accumulator = result.accumulator

        # Final flush — any leftover buffered text becomes one last payload.
        payloads.extend(accumulator.flush_to_list())

        return payloads

    def _select_chunker(self, section: Section) -> SectionChunker:
        try:
            return self._dispatch[section.kind]
        except KeyError:
            raise ValueError(
                f"No SectionChunker registered for kind={section.kind}"
            )
