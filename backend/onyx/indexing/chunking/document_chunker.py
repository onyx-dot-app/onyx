from chonkie import SentenceChunker

from onyx.connectors.models import IndexingDocument
from onyx.connectors.models import Section
from onyx.connectors.models import SectionType
from onyx.indexing.chunking.image_section_chunker import ImageChunker
from onyx.indexing.chunking.section_chunker import AccumulatorState
from onyx.indexing.chunking.section_chunker import ChunkPayload
from onyx.indexing.chunking.section_chunker import SectionChunker
from onyx.indexing.chunking.text_section_chunker import TextChunker
from onyx.indexing.models import DocAwareChunk
from onyx.natural_language_processing.utils import BaseTokenizer
from onyx.utils.logger import setup_logger
from onyx.utils.text_processing import clean_text

logger = setup_logger()


class DocumentChunker:
    """Converts a document's processed sections into DocAwareChunks.

    Drop-in replacement for `Chunker._chunk_document_with_sections`.
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

        self._dispatch: dict[SectionType, SectionChunker] = {
            SectionType.TEXT: TextChunker(
                tokenizer=tokenizer,
                chunk_splitter=chunk_splitter,
            ),
            SectionType.IMAGE: ImageChunker(),
        }

    def chunk(
        self,
        document: IndexingDocument,
        sections: list[Section],
        title_prefix: str,
        metadata_suffix_semantic: str,
        metadata_suffix_keyword: str,
        content_token_limit: int,
    ) -> list[DocAwareChunk]:
        payloads = self._collect_section_payloads(
            document=document,
            sections=sections,
            content_token_limit=content_token_limit,
        )

        if not payloads:
            payloads.append(ChunkPayload(text="", links={0: ""}))

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

    def _collect_section_payloads(
        self,
        document: IndexingDocument,
        sections: list[Section],
        content_token_limit: int,
    ) -> list[ChunkPayload]:
        accumulator = AccumulatorState()
        payloads: list[ChunkPayload] = []

        for section_idx, section in enumerate(sections):
            section_text = clean_text(str(section.text or ""))

            if not section_text and (not document.title or section_idx > 0):
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

        payloads.extend(accumulator.flush_to_list())
        return payloads

    def _select_chunker(self, section: Section) -> SectionChunker:
        try:
            return self._dispatch[section.type]
        except KeyError:
            raise ValueError(f"No SectionChunker registered for type={section.type}")
