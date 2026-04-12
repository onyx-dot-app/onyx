from typing import cast

from chonkie import SentenceChunker

from onyx.configs.constants import SECTION_SEPARATOR
from onyx.connectors.models import Section
from onyx.indexing.document_chunker.section_chunker import AccumulatorState
from onyx.indexing.document_chunker.section_chunker import ChunkPayload
from onyx.indexing.document_chunker.section_chunker import SectionChunker
from onyx.indexing.document_chunker.section_chunker import SectionChunkerOutput
from onyx.natural_language_processing.utils import BaseTokenizer
from onyx.utils.text_processing import clean_text
from onyx.utils.text_processing import shared_precompare_cleanup
from shared_configs.configs import STRICT_CHUNK_TOKEN_LIMIT


class TextChunker(SectionChunker):
    """Per-section chunker for text sections.

    Stateless: all cross-section combining state is threaded through the
    `accumulator` argument to `chunk_section`, and document-scoped
    concerns (chunk_id assignment, title/metadata propagation, skip
    logic, the empty-doc safety branch) are handled by the orchestrator.
    """

    def __init__(
        self,
        tokenizer: BaseTokenizer,
        chunk_splitter: SentenceChunker,
    ) -> None:
        self.tokenizer = tokenizer
        self.chunk_splitter = chunk_splitter

    def chunk_section(
        self,
        section: Section,
        accumulator: AccumulatorState,
        content_token_limit: int,
    ) -> SectionChunkerOutput:
        section_text = clean_text(str(section.text or ""))
        section_link = section.link or ""
        section_token_count = len(self.tokenizer.encode(section_text))

        # CASE A: the section alone exceeds the limit.
        if section_token_count > content_token_limit:
            return self._handle_oversized_section(
                section_text=section_text,
                section_link=section_link,
                accumulator=accumulator,
                content_token_limit=content_token_limit,
            )

        current_token_count = len(self.tokenizer.encode(accumulator.text))
        next_section_tokens = (
            len(self.tokenizer.encode(SECTION_SEPARATOR)) + section_token_count
        )

        # CASE B: the section fits together with the current buffer.
        if next_section_tokens + current_token_count <= content_token_limit:
            # Offset is measured against the *pre-extension* buffer so
            # link_offsets map onto the cleaned-text representation the
            # rest of the pipeline uses for highlight matching.
            offset = len(shared_precompare_cleanup(accumulator.text))
            new_text = accumulator.text
            if new_text:
                new_text += SECTION_SEPARATOR
            new_text += section_text
            return SectionChunkerOutput(
                payloads=[],
                accumulator=AccumulatorState(
                    text=new_text,
                    link_offsets={**accumulator.link_offsets, offset: section_link},
                ),
            )

        # CASE C: the section doesn't fit — flush buffer and restart.
        return SectionChunkerOutput(
            payloads=accumulator.flush_to_list(),
            accumulator=AccumulatorState(
                text=section_text,
                link_offsets={0: section_link},
            ),
        )

    def _handle_oversized_section(
        self,
        section_text: str,
        section_link: str,
        accumulator: AccumulatorState,
        content_token_limit: int,
    ) -> SectionChunkerOutput:
        payloads = accumulator.flush_to_list()

        split_texts = cast(
            list[str], self.chunk_splitter.chunk(section_text)
        )
        for i, split_text in enumerate(split_texts):
            if (
                STRICT_CHUNK_TOKEN_LIMIT
                and len(self.tokenizer.encode(split_text)) > content_token_limit
            ):
                # NOTE: `j` is local to this inner loop, so the first
                # sub-chunk of a strict-split always has
                # is_continuation=False even when the outer `i > 0`.
                # This matches the legacy behavior — the existing
                # pinning tests depend on it.
                smaller_chunks = self._split_oversized_chunk(
                    split_text, content_token_limit
                )
                for j, small_chunk in enumerate(smaller_chunks):
                    payloads.append(
                        ChunkPayload(
                            text=small_chunk,
                            links={0: section_link},
                            is_continuation=(j != 0),
                        )
                    )
            else:
                payloads.append(
                    ChunkPayload(
                        text=split_text,
                        links={0: section_link},
                        is_continuation=(i != 0),
                    )
                )

        return SectionChunkerOutput(
            payloads=payloads,
            accumulator=AccumulatorState(),
        )

    def _split_oversized_chunk(
        self, text: str, content_token_limit: int
    ) -> list[str]:
        """Split text by raw tokens when even the sentence-chunker output
        is still too large."""
        tokens = self.tokenizer.tokenize(text)
        chunks: list[str] = []
        start = 0
        total_tokens = len(tokens)
        while start < total_tokens:
            end = min(start + content_token_limit, total_tokens)
            token_chunk = tokens[start:end]
            chunk_text = " ".join(token_chunk)
            chunks.append(chunk_text)
            start = end
        return chunks
