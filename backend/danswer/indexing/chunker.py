import abc
from collections.abc import Callable
from typing import TYPE_CHECKING

from danswer.configs.app_configs import BLURB_SIZE
from danswer.configs.app_configs import MINI_CHUNK_SIZE
from danswer.configs.app_configs import SKIP_METADATA_IN_CHUNK
from danswer.configs.constants import DocumentSource
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
    from llama_index.text_splitter import SentenceSplitter  # type:ignore


# Not supporting overlaps, we need a clean combination of chunks and it is unclear if overlaps
# actually help quality at all
CHUNK_OVERLAP = 0
# Fairly arbitrary numbers but the general concept is we don't want the title/metadata to
# overwhelm the actual contents of the chunk
# For example in a rare case, this could be 128 tokens for the 512 chunk and title prefix
# could be another 128 tokens leaving 256 for the actual contents
MAX_METADATA_PERCENTAGE = 0.25
CHUNK_MIN_CONTENT = 256

logger = setup_logger()

ChunkFunc = Callable[[Document], list[DocAwareChunk]]


def extract_blurb(text: str, blurb_splitter: "SentenceSplitter") -> str:
    return blurb_splitter.split_text(text)[0]


def chunk_large_section(
    section_text: str,
    section_link_text: str,
    document: Document,
    start_chunk_id: int,
    blurb: str,
    chunk_splitter: "SentenceSplitter",
    title_prefix: str = "",
    metadata_suffix_semantic: str = "",
    metadata_suffix_keyword: str = "",
) -> list[DocAwareChunk]:
    split_texts = chunk_splitter.split_text(section_text)

    chunks = [
        DocAwareChunk(
            source_document=document,
            chunk_id=start_chunk_id + chunk_ind,
            blurb=blurb,
            content=chunk_str,
            source_links={0: section_link_text},
            section_continuation=(chunk_ind != 0),
            title_prefix=title_prefix,
            metadata_suffix_semantic=metadata_suffix_semantic,
            metadata_suffix_keyword=metadata_suffix_keyword,
        )
        for chunk_ind, chunk_str in enumerate(split_texts)
    ]
    return chunks


def _get_metadata_suffix_for_document_index(
    metadata: dict[str, str | list[str]], include_separator: bool = False
) -> tuple[str, str]:
    """
    Returns the metadata as a natural language string representation with all of the keys and values for the vector embedding
    and a string of all of the values for the keyword search

    For example, if we have the following metadata:
    {
        "author": "John Doe",
        "space": "Engineering"
    }
    The vector embedding string should include the relation between the key and value wheres as for keyword we only want John Doe
    and Engineering. The keys are repeat and much more noisy.
    """
    if not metadata:
        return "", ""

    metadata_str = "Metadata:\n"
    metadata_values = []
    for key, value in metadata.items():
        if key in get_metadata_keys_to_ignore():
            continue

        value_str = ", ".join(value) if isinstance(value, list) else value

        if isinstance(value, list):
            metadata_values.extend(value)
        else:
            metadata_values.append(value)

        metadata_str += f"\t{key} - {value_str}\n"

    metadata_semantic = metadata_str.strip()
    metadata_keyword = " ".join(metadata_values)

    if include_separator:
        return RETURN_SEPARATOR + metadata_semantic, RETURN_SEPARATOR + metadata_keyword
    return metadata_semantic, metadata_keyword


def chunk_document(
    document: Document,
    chunk_tok_size: int = DOC_EMBEDDING_CONTEXT_SIZE,
    subsection_overlap: int = CHUNK_OVERLAP,
    blurb_size: int = BLURB_SIZE,  # Used for both title and content
    include_metadata: bool = not SKIP_METADATA_IN_CHUNK,
) -> list[DocAwareChunk]:
    from llama_index.text_splitter import SentenceSplitter

    tokenizer = get_default_tokenizer()

    blurb_splitter = SentenceSplitter(
        tokenizer=tokenizer.tokenize, chunk_size=blurb_size, chunk_overlap=0
    )

    chunk_splitter = SentenceSplitter(
        tokenizer=tokenizer.tokenize,
        chunk_size=chunk_tok_size,
        chunk_overlap=subsection_overlap,
    )

    title = extract_blurb(document.get_title_for_document_index() or "", blurb_splitter)
    title_prefix = title + RETURN_SEPARATOR if title else ""
    title_tokens = len(tokenizer.tokenize(title_prefix))

    metadata_suffix_semantic = ""
    metadata_suffix_keyword = ""
    metadata_tokens = 0
    if include_metadata:
        (
            metadata_suffix_semantic,
            metadata_suffix_keyword,
        ) = _get_metadata_suffix_for_document_index(
            document.metadata, include_separator=True
        )
        metadata_tokens = len(tokenizer.tokenize(metadata_suffix_semantic))

    if metadata_tokens >= chunk_tok_size * MAX_METADATA_PERCENTAGE:
        # Note: we can keep the keyword suffix even if the semantic suffix is too long to fit in the model
        # context, there is no limit for the keyword component
        metadata_suffix_semantic = ""
        metadata_tokens = 0

    content_token_limit = chunk_tok_size - title_tokens - metadata_tokens

    # If there is not enough context remaining then just index the chunk with no prefix/suffix
    if content_token_limit <= CHUNK_MIN_CONTENT:
        content_token_limit = chunk_tok_size
        title_prefix = ""
        metadata_suffix_semantic = ""

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
                        blurb=extract_blurb(chunk_text, blurb_splitter),
                        content=chunk_text,
                        source_links=link_offsets,
                        section_continuation=False,
                        title_prefix=title_prefix,
                        metadata_suffix_semantic=metadata_suffix_semantic,
                        metadata_suffix_keyword=metadata_suffix_keyword,
                    )
                )
                link_offsets = {}
                chunk_text = ""

            large_section_chunks = chunk_large_section(
                section_text=section_text,
                section_link_text=section_link_text,
                document=document,
                start_chunk_id=len(chunks),
                chunk_splitter=chunk_splitter,
                blurb=extract_blurb(section_text, blurb_splitter),
                title_prefix=title_prefix,
                metadata_suffix_semantic=metadata_suffix_semantic,
                metadata_suffix_keyword=metadata_suffix_keyword,
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
                    blurb=extract_blurb(chunk_text, blurb_splitter),
                    content=chunk_text,
                    source_links=link_offsets,
                    section_continuation=False,
                    title_prefix=title_prefix,
                    metadata_suffix_semantic=metadata_suffix_semantic,
                    metadata_suffix_keyword=metadata_suffix_keyword,
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
                blurb=extract_blurb(chunk_text, blurb_splitter),
                content=chunk_text,
                source_links=link_offsets,
                section_continuation=False,
                title_prefix=title_prefix,
                metadata_suffix_semantic=metadata_suffix_semantic,
                metadata_suffix_keyword=metadata_suffix_keyword,
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
