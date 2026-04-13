from chonkie import SentenceChunker

from onyx.configs.app_configs import AVERAGE_SUMMARY_EMBEDDINGS
from onyx.configs.app_configs import BLURB_SIZE
from onyx.configs.app_configs import LARGE_CHUNK_RATIO
from onyx.configs.app_configs import MINI_CHUNK_SIZE
from onyx.configs.app_configs import SKIP_METADATA_IN_CHUNK
from onyx.configs.app_configs import USE_CHUNK_SUMMARY
from onyx.configs.app_configs import USE_DOCUMENT_SUMMARY
from onyx.configs.constants import DocumentSource
from onyx.configs.constants import RETURN_SEPARATOR
from onyx.configs.constants import SECTION_SEPARATOR
from onyx.connectors.cross_connector_utils.miscellaneous_utils import (
    get_metadata_keys_to_ignore,
)
from onyx.connectors.models import IndexingDocument
from onyx.indexing.chunking import DocumentChunker
from onyx.indexing.chunking import extract_blurb
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.indexing.models import DocAwareChunk
from onyx.llm.utils import MAX_CONTEXT_TOKENS
from onyx.natural_language_processing.utils import BaseTokenizer
from onyx.utils.logger import setup_logger
from shared_configs.configs import DOC_EMBEDDING_CONTEXT_SIZE

# Not supporting overlaps, we need a clean combination of chunks and it is unclear if overlaps
# actually help quality at all
CHUNK_OVERLAP = 0
# Fairly arbitrary numbers but the general concept is we don't want the title/metadata to
# overwhelm the actual contents of the chunk
MAX_METADATA_PERCENTAGE = 0.25
CHUNK_MIN_CONTENT = 256

logger = setup_logger()


def _get_metadata_suffix_for_document_index(
    metadata: dict[str, str | list[str]], include_separator: bool = False
) -> tuple[str, str]:
    """
    Returns the metadata as a natural language string representation with all of the keys and values
    for the vector embedding and a string of all of the values for the keyword search.
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


def _combine_chunks(chunks: list[DocAwareChunk], large_chunk_id: int) -> DocAwareChunk:
    """
    Combines multiple DocAwareChunks into one large chunk (for "multipass" mode),
    appending the content and adjusting source_links accordingly.
    """
    merged_chunk = DocAwareChunk(
        source_document=chunks[0].source_document,
        chunk_id=chunks[0].chunk_id,
        blurb=chunks[0].blurb,
        content=chunks[0].content,
        source_links=chunks[0].source_links or {},
        image_file_id=None,
        section_continuation=(chunks[0].chunk_id > 0),
        title_prefix=chunks[0].title_prefix,
        metadata_suffix_semantic=chunks[0].metadata_suffix_semantic,
        metadata_suffix_keyword=chunks[0].metadata_suffix_keyword,
        large_chunk_reference_ids=[chunk.chunk_id for chunk in chunks],
        mini_chunk_texts=None,
        large_chunk_id=large_chunk_id,
        chunk_context="",
        doc_summary="",
        contextual_rag_reserved_tokens=0,
    )

    offset = 0
    for i in range(1, len(chunks)):
        merged_chunk.content += SECTION_SEPARATOR + chunks[i].content

        offset += len(SECTION_SEPARATOR) + len(chunks[i - 1].content)
        for link_offset, link_text in (chunks[i].source_links or {}).items():
            if merged_chunk.source_links is None:
                merged_chunk.source_links = {}
            merged_chunk.source_links[link_offset + offset] = link_text

    return merged_chunk


def generate_large_chunks(chunks: list[DocAwareChunk]) -> list[DocAwareChunk]:
    """
    Generates larger "grouped" chunks by combining sets of smaller chunks.
    """
    large_chunks = []
    for idx, i in enumerate(range(0, len(chunks), LARGE_CHUNK_RATIO)):
        chunk_group = chunks[i : i + LARGE_CHUNK_RATIO]
        if len(chunk_group) > 1:
            large_chunk = _combine_chunks(chunk_group, idx)
            large_chunks.append(large_chunk)
    return large_chunks


class Chunker:
    """
    Chunks documents into smaller chunks for indexing.
    """

    def __init__(
        self,
        tokenizer: BaseTokenizer,
        enable_multipass: bool = False,
        enable_large_chunks: bool = False,
        enable_contextual_rag: bool = False,
        blurb_size: int = BLURB_SIZE,
        include_metadata: bool = not SKIP_METADATA_IN_CHUNK,
        chunk_token_limit: int = DOC_EMBEDDING_CONTEXT_SIZE,
        chunk_overlap: int = CHUNK_OVERLAP,
        mini_chunk_size: int = MINI_CHUNK_SIZE,
        callback: IndexingHeartbeatInterface | None = None,
    ) -> None:
        self.include_metadata = include_metadata
        self.chunk_token_limit = chunk_token_limit
        self.enable_multipass = enable_multipass
        self.enable_large_chunks = enable_large_chunks
        self.enable_contextual_rag = enable_contextual_rag
        if enable_contextual_rag:
            assert (
                USE_CHUNK_SUMMARY or USE_DOCUMENT_SUMMARY
            ), "Contextual RAG requires at least one of chunk summary and document summary enabled"
        self.default_contextual_rag_reserved_tokens = MAX_CONTEXT_TOKENS * (
            int(USE_CHUNK_SUMMARY) + int(USE_DOCUMENT_SUMMARY)
        )
        self.tokenizer = tokenizer
        self.callback = callback

        # Create a token counter function that returns the count instead of the tokens
        def token_counter(text: str) -> int:
            return len(tokenizer.encode(text))

        self.blurb_splitter = SentenceChunker(
            tokenizer_or_token_counter=token_counter,
            chunk_size=blurb_size,
            chunk_overlap=0,
            return_type="texts",
        )

        self.chunk_splitter = SentenceChunker(
            tokenizer_or_token_counter=token_counter,
            chunk_size=chunk_token_limit,
            chunk_overlap=chunk_overlap,
            return_type="texts",
        )

        self.mini_chunk_splitter = (
            SentenceChunker(
                tokenizer_or_token_counter=token_counter,
                chunk_size=mini_chunk_size,
                chunk_overlap=0,
                return_type="texts",
            )
            if enable_multipass
            else None
        )

        self._document_chunker = DocumentChunker(
            tokenizer=tokenizer,
            blurb_splitter=self.blurb_splitter,
            chunk_splitter=self.chunk_splitter,
            mini_chunk_splitter=self.mini_chunk_splitter,
        )

    def _handle_single_document(
        self, document: IndexingDocument
    ) -> list[DocAwareChunk]:
        # Specifically for reproducing an issue with gmail
        if document.source == DocumentSource.GMAIL:
            logger.debug(f"Chunking {document.semantic_identifier}")

        # Title prep
        title = extract_blurb(
            document.get_title_for_document_index() or "",
            self.blurb_splitter,
        )
        title_prefix = title + RETURN_SEPARATOR if title else ""
        title_tokens = len(self.tokenizer.encode(title_prefix))

        # Metadata prep
        metadata_suffix_semantic = ""
        metadata_suffix_keyword = ""
        metadata_tokens = 0
        if self.include_metadata:
            (
                metadata_suffix_semantic,
                metadata_suffix_keyword,
            ) = _get_metadata_suffix_for_document_index(
                document.metadata, include_separator=True
            )
            metadata_tokens = len(self.tokenizer.encode(metadata_suffix_semantic))

        # If metadata is too large, skip it in the semantic content
        if metadata_tokens >= self.chunk_token_limit * MAX_METADATA_PERCENTAGE:
            metadata_suffix_semantic = ""
            metadata_tokens = 0

        single_chunk_fits = True
        doc_token_count = 0
        if self.enable_contextual_rag:
            doc_content = document.get_text_content()
            tokenized_doc = self.tokenizer.tokenize(doc_content)
            doc_token_count = len(tokenized_doc)

            # check if doc + title + metadata fits in a single chunk. If so, no need for contextual RAG
            single_chunk_fits = (
                doc_token_count + title_tokens + metadata_tokens
                <= self.chunk_token_limit
            )

        # expand the size of the context used for contextual rag based on whether chunk context and doc summary are used
        context_size = 0
        if (
            self.enable_contextual_rag
            and not single_chunk_fits
            and not AVERAGE_SUMMARY_EMBEDDINGS
        ):
            context_size += self.default_contextual_rag_reserved_tokens

        # Adjust content token limit to accommodate title + metadata
        content_token_limit = (
            self.chunk_token_limit - title_tokens - metadata_tokens - context_size
        )

        # first check: if there is not enough actual chunk content when including contextual rag,
        # then don't do contextual rag
        if content_token_limit <= CHUNK_MIN_CONTENT:
            context_size = 0  # Don't do contextual RAG
            # revert to previous content token limit
            content_token_limit = (
                self.chunk_token_limit - title_tokens - metadata_tokens
            )

        # If there is not enough context remaining then just index the chunk with no prefix/suffix
        if content_token_limit <= CHUNK_MIN_CONTENT:
            # Not enough space left, so revert to full chunk without the prefix
            content_token_limit = self.chunk_token_limit
            title_prefix = ""
            metadata_suffix_semantic = ""

        # Use processed_sections if available (IndexingDocument), otherwise use original sections
        sections_to_chunk = document.processed_sections

        normal_chunks = self._document_chunker.chunk(
            document,
            sections_to_chunk,
            title_prefix,
            metadata_suffix_semantic,
            metadata_suffix_keyword,
            content_token_limit,
        )

        # Optional "multipass" large chunk creation
        if self.enable_multipass and self.enable_large_chunks:
            large_chunks = generate_large_chunks(normal_chunks)
            normal_chunks.extend(large_chunks)

        for chunk in normal_chunks:
            chunk.contextual_rag_reserved_tokens = context_size

        return normal_chunks

    def chunk(self, documents: list[IndexingDocument]) -> list[DocAwareChunk]:
        """
        Takes in a list of documents and chunks them into smaller chunks for indexing
        while persisting the document metadata.

        Works with both standard Document objects and IndexingDocument objects with processed_sections.
        """
        final_chunks: list[DocAwareChunk] = []
        for document in documents:
            if self.callback and self.callback.should_stop():
                raise RuntimeError("Chunker.chunk: Stop signal detected")

            chunks = self._handle_single_document(document)
            final_chunks.extend(chunks)

            if self.callback:
                self.callback.progress("Chunker.chunk", len(chunks))

        return final_chunks
