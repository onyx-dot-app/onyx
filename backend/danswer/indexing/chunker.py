import abc
from collections.abc import Callable
from typing import TYPE_CHECKING

from danswer.configs.app_configs import BLURB_SIZE
from danswer.configs.app_configs import CHUNK_OVERLAP
from danswer.configs.app_configs import MINI_CHUNK_SIZE
from danswer.configs.constants import DocumentSource
from danswer.configs.constants import SECTION_SEPARATOR
from danswer.configs.constants import TITLE_SEPARATOR
from danswer.configs.model_configs import DOC_EMBEDDING_CONTEXT_SIZE
from danswer.connectors.models import Document
from danswer.indexing.models import DocAwareChunk
from danswer.search.search_nlp_models import get_default_tokenizer
from danswer.utils.logger import setup_logger
from danswer.utils.text_processing import shared_precompare_cleanup

if TYPE_CHECKING:
    from transformers import AutoTokenizer  # type:ignore


logger = setup_logger()

ChunkFunc = Callable[[Document], list[DocAwareChunk]]


def extract_blurb(text: str, blurb_size: int) -> str:
    from llama_index.text_splitter import SentenceSplitter

    token_count_func = get_default_tokenizer().tokenize
    blurb_splitter = SentenceSplitter(
        tokenizer=token_count_func, chunk_size=blurb_size, chunk_overlap=0
    )

    return blurb_splitter.split_text(text)[0]


def chunk_large_section(
    section_text: str,
    section_link_text: str,
    document: Document,
    start_chunk_id: int,
    tokenizer: "AutoTokenizer",
    chunk_size: int = DOC_EMBEDDING_CONTEXT_SIZE,
    chunk_overlap: int = CHUNK_OVERLAP,
    blurb_size: int = BLURB_SIZE,
) -> list[DocAwareChunk]:
    from llama_index.text_splitter import SentenceSplitter

    blurb = extract_blurb(section_text, blurb_size)

    sentence_aware_splitter = SentenceSplitter(
        tokenizer=tokenizer.tokenize, chunk_size=chunk_size, chunk_overlap=chunk_overlap
    )

    split_texts = sentence_aware_splitter.split_text(section_text)

    chunks = [
        DocAwareChunk(
            source_document=document,
            chunk_id=start_chunk_id + chunk_ind,
            blurb=blurb,
            content=chunk_str,
            source_links={0: section_link_text},
            section_continuation=(chunk_ind != 0),
        )
        for chunk_ind, chunk_str in enumerate(split_texts)
    ]
    return chunks


def chunk_document(
    document: Document,
    chunk_tok_size: int = DOC_EMBEDDING_CONTEXT_SIZE,
    subsection_overlap: int = CHUNK_OVERLAP,
    blurb_size: int = BLURB_SIZE,
) -> list[DocAwareChunk]:
    title = document.get_title_for_document_index()
    title_prefix = title.replace("\n", " ") + TITLE_SEPARATOR if title else ""
    tokenizer = get_default_tokenizer()

    chunks: list[DocAwareChunk] = []
    link_offsets: dict[int, str] = {}
    chunk_text = ""
    for ind, section in enumerate(document.sections):
        section_text = title_prefix + section.text if ind == 0 else section.text
        section_link_text = section.link or ""

        section_tok_length = len(tokenizer.tokenize(section_text))
        current_tok_length = len(tokenizer.tokenize(chunk_text))
        curr_offset_len = len(shared_precompare_cleanup(chunk_text))

        # Large sections are considered self-contained/unique therefore they start a new chunk and are not concatenated
        # at the end by other sections
        if section_tok_length > chunk_tok_size:
            if chunk_text:
                chunks.append(
                    DocAwareChunk(
                        source_document=document,
                        chunk_id=len(chunks),
                        blurb=extract_blurb(chunk_text, blurb_size),
                        content=chunk_text,
                        source_links=link_offsets,
                        section_continuation=False,
                    )
                )
                link_offsets = {}
                chunk_text = ""

            large_section_chunks = chunk_large_section(
                section_text=section_text,
                section_link_text=section_link_text,
                document=document,
                start_chunk_id=len(chunks),
                tokenizer=tokenizer,
                chunk_size=chunk_tok_size,
                chunk_overlap=subsection_overlap,
                blurb_size=blurb_size,
            )
            chunks.extend(large_section_chunks)
            continue

        # In the case where the whole section is shorter than a chunk, either adding to chunk or start a new one
        if (
            current_tok_length
            + len(tokenizer.tokenize(SECTION_SEPARATOR))
            + section_tok_length
            <= chunk_tok_size
        ):
            chunk_text += (
                SECTION_SEPARATOR + section_text if chunk_text else section_text
            )
            link_offsets[curr_offset_len] = section_link_text
        else:
            chunks.append(
                DocAwareChunk(
                    source_document=document,
                    chunk_id=len(chunks),
                    blurb=extract_blurb(chunk_text, blurb_size),
                    content=chunk_text,
                    source_links=link_offsets,
                    section_continuation=False,
                )
            )
            link_offsets = {0: section_link_text}
            chunk_text = section_text

    # Once we hit the end, if we're still in the process of building a chunk, add what we have
    # NOTE: if it's just whitespace, ignore it.
    if chunk_text.strip():
        chunks.append(
            DocAwareChunk(
                source_document=document,
                chunk_id=len(chunks),
                blurb=extract_blurb(chunk_text, blurb_size),
                content=chunk_text,
                source_links=link_offsets,
                section_continuation=False,
            )
        )
    return chunks


def split_chunk_text_into_mini_chunks(
    chunk_text: str, mini_chunk_size: int = MINI_CHUNK_SIZE
) -> list[str]:
    from llama_index.text_splitter import SentenceSplitter

    token_count_func = get_default_tokenizer().tokenize
    sentence_aware_splitter = SentenceSplitter(
        tokenizer=token_count_func, chunk_size=mini_chunk_size, chunk_overlap=0
    )

    return sentence_aware_splitter.split_text(chunk_text)


class Chunker:
    @abc.abstractmethod
    def chunk(self, document: Document) -> list[DocAwareChunk]:
        raise NotImplementedError


class DefaultChunker(Chunker):
    def chunk(self, document: Document) -> list[DocAwareChunk]:
        # Specifically for reproducing an issue with gmail
        if document.source == DocumentSource.GMAIL:
            logger.debug(f"Chunking {document.semantic_identifier}")
        return chunk_document(document)
