import abc
from collections.abc import Callable
from typing import TYPE_CHECKING

from danswer.configs.app_configs import BLURB_SIZE
from danswer.configs.app_configs import MINI_CHUNK_SIZE
from danswer.configs.app_configs import SKIP_METADATA_IN_CHUNK
from danswer.configs.constants import DocumentSource
from danswer.configs.constants import MAX_CHUNK_TITLE_LEN
from danswer.configs.constants import RETURN_SEPARATOR
from danswer.configs.constants import SECTION_SEPARATOR
from danswer.configs.model_configs import DOC_EMBEDDING_CONTEXT_SIZE
from danswer.connectors.cross_connector_utils.miscellaneous_utils import (
    get_metadata_keys_to_ignore,
)
from danswer.connectors.models import Document
from danswer.indexing.models import DocAwareChunk
from danswer.natural_language_processing.search_nlp_models import get_default_tokenizer
from danswer.utils.logger import setup_logger
from danswer.utils.text_processing import shared_precompare_cleanup

if TYPE_CHECKING:
    from transformers import AutoTokenizer  # type:ignore


# Not supporting overlaps, we need a clean combination of chunks and it is unclear if overlaps
# actually help quality at all
CHUNK_OVERLAP = 0
# Fairly arbitrary numbers but the general concept is we don't want the title/metadata to
# overwhelm the actual contents of the chunk
MAX_METADATA_PERCENTAGE = 0.25
CHUNK_MIN_CONTENT = 256

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
    title_prefix: str = "",
    metadata_suffix: str = "",
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
            content=f"{title_prefix}{chunk_str}{metadata_suffix}",
            content_summary=chunk_str,
            source_links={0: section_link_text},
            section_continuation=(chunk_ind != 0),
            metadata_suffix=metadata_suffix,
        )
        for chunk_ind, chunk_str in enumerate(split_texts)
    ]
    return chunks


def _get_metadata_suffix_for_document_index(
    metadata: dict[str, str | list[str]]
) -> str:
    if not metadata:
        return ""
    metadata_str = "Metadata:\n"
    for key, value in metadata.items():
        if key in get_metadata_keys_to_ignore():
            continue

        value_str = ", ".join(value) if isinstance(value, list) else value
        metadata_str += f"\t{key} - {value_str}\n"
    return metadata_str.strip()


def chunk_document(
    document: Document,
    chunk_tok_size: int = DOC_EMBEDDING_CONTEXT_SIZE,
    subsection_overlap: int = CHUNK_OVERLAP,
    blurb_size: int = BLURB_SIZE,
    include_metadata: bool = not SKIP_METADATA_IN_CHUNK,
) -> list[DocAwareChunk]:
    tokenizer = get_default_tokenizer()

    title = document.get_title_for_document_index()
    title_prefix = f"{title[:MAX_CHUNK_TITLE_LEN]}{RETURN_SEPARATOR}" if title else ""
    title_tokens = len(tokenizer.tokenize(title_prefix))

    metadata_suffix = ""
    metadata_tokens = 0
    if include_metadata:
        metadata = _get_metadata_suffix_for_document_index(document.metadata)
        metadata_suffix = RETURN_SEPARATOR + metadata if metadata else ""
        metadata_tokens = len(tokenizer.tokenize(metadata_suffix))

    if metadata_tokens >= chunk_tok_size * MAX_METADATA_PERCENTAGE:
        metadata_suffix = ""
        metadata_tokens = 0

    content_token_limit = chunk_tok_size - title_tokens - metadata_tokens

    # If there is not enough context remaining then just index the chunk with no prefix/suffix
    if content_token_limit <= CHUNK_MIN_CONTENT:
        content_token_limit = chunk_tok_size
        title_prefix = ""
        metadata_suffix = ""

    chunks: list[DocAwareChunk] = []
    link_offsets: dict[int, str] = {}
    chunk_text = ""
    for section in document.sections:
        section_text = section.text
        section_link_text = section.link or ""

        section_tok_length = len(tokenizer.tokenize(section_text))
        current_tok_length = len(tokenizer.tokenize(chunk_text))
        curr_offset_len = len(shared_precompare_cleanup(chunk_text))

        # Large sections are considered self-contained/unique therefore they start a new chunk and are not concatenated
        # at the end by other sections
        if section_tok_length > content_token_limit:
            if chunk_text:
                chunks.append(
                    DocAwareChunk(
                        source_document=document,
                        chunk_id=len(chunks),
                        blurb=extract_blurb(chunk_text, blurb_size),
                        content=f"{title_prefix}{chunk_text}{metadata_suffix}",
                        content_summary=chunk_text,
                        source_links=link_offsets,
                        section_continuation=False,
                        metadata_suffix=metadata_suffix,
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
                chunk_size=content_token_limit,
                chunk_overlap=subsection_overlap,
                blurb_size=blurb_size,
                title_prefix=title_prefix,
                metadata_suffix=metadata_suffix,
            )
            chunks.extend(large_section_chunks)
            continue

        # In the case where the whole section is shorter than a chunk, either adding to chunk or start a new one
        if (
            current_tok_length
            + len(tokenizer.tokenize(SECTION_SEPARATOR))
            + section_tok_length
            <= content_token_limit
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
                    content=f"{title_prefix}{chunk_text}{metadata_suffix}",
                    content_summary=chunk_text,
                    source_links=link_offsets,
                    section_continuation=False,
                    metadata_suffix=metadata_suffix,
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
                content=f"{title_prefix}{chunk_text}{metadata_suffix}",
                content_summary=chunk_text,
                source_links=link_offsets,
                section_continuation=False,
                metadata_suffix=metadata_suffix,
            )
        )
    return chunks


def split_chunk_text_into_mini_chunks(
    chunk_text: str, mini_chunk_size: int = MINI_CHUNK_SIZE
) -> list[str]:
    """The minichunks won't all have the title prefix or metadata suffix
    It could be a significant percentage of every minichunk so better to not include it
    """
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
