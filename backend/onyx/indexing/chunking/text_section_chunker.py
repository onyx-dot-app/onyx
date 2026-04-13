from typing import cast

from chonkie import SentenceChunker

from onyx.configs.constants import SECTION_SEPARATOR
from onyx.connectors.models import Section
from onyx.indexing.chunking.section_chunker import AccumulatorState
from onyx.indexing.chunking.section_chunker import ChunkPayload
from onyx.indexing.chunking.section_chunker import SectionChunker
from onyx.indexing.chunking.section_chunker import SectionChunkerOutput
from onyx.natural_language_processing.utils import BaseTokenizer
from onyx.natural_language_processing.utils import count_tokens
from onyx.utils.text_processing import clean_text
from onyx.utils.text_processing import shared_precompare_cleanup
from shared_configs.configs import STRICT_CHUNK_TOKEN_LIMIT


class TextChunker(SectionChunker):
    def __init__(
        self,
        tokenizer: BaseTokenizer,
        chunk_splitter: SentenceChunker,
    ) -> None:
        self.tokenizer = tokenizer
        self.chunk_splitter = chunk_splitter

        self.section_separator_token_count = count_tokens(
            SECTION_SEPARATOR,
            self.tokenizer,
        )

    def chunk_section(
        self,
        section: Section,
        accumulator: AccumulatorState,
        content_token_limit: int,
    ) -> SectionChunkerOutput:
        section_text = clean_text(str(section.text or ""))
        section_link = section.link or ""
        section_token_count = len(self.tokenizer.encode(section_text))

        # Oversized — flush buffer and split the section
        if section_token_count > content_token_limit:
            return self._handle_oversized_section(
                section_text=section_text,
                section_link=section_link,
                accumulator=accumulator,
                content_token_limit=content_token_limit,
            )

        current_token_count = count_tokens(accumulator.text, self.tokenizer)
        next_section_tokens = self.section_separator_token_count + section_token_count

        # Fits — extend the accumulator
        if next_section_tokens + current_token_count <= content_token_limit:
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

        # Doesn't fit — flush buffer and restart with this section
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

        split_texts = cast(list[str], self.chunk_splitter.chunk(section_text))
        for i, split_text in enumerate(split_texts):
            if (
                STRICT_CHUNK_TOKEN_LIMIT
                and count_tokens(split_text, self.tokenizer) > content_token_limit
            ):
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

    def _split_oversized_chunk(self, text: str, content_token_limit: int) -> list[str]:
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
