from danswer.configs.app_configs import BLURB_SIZE
from danswer.configs.app_configs import LARGE_CHUNK_RATIO
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
from danswer.indexing.indexing_heartbeat import Heartbeat
from danswer.indexing.models import DocAwareChunk
from danswer.natural_language_processing.utils import BaseTokenizer
from danswer.utils.logger import setup_logger
from danswer.utils.text_processing import shared_precompare_cleanup
from shared_configs.configs import STRICT_CHUNK_TOKEN_LIMIT

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


def _combine_chunks(chunks: list[DocAwareChunk], index: int) -> DocAwareChunk:
    merged_chunk = DocAwareChunk(
        source_document=chunks[0].source_document,
        chunk_id=index,
        blurb=chunks[0].blurb,
        content=chunks[0].content,
        source_links=chunks[0].source_links or {},
        section_continuation=(index > 0),
        title_prefix=chunks[0].title_prefix,
        metadata_suffix_semantic=chunks[0].metadata_suffix_semantic,
        metadata_suffix_keyword=chunks[0].metadata_suffix_keyword,
        large_chunk_reference_ids=[chunks[0].chunk_id],
        mini_chunk_texts=None,
    )

    offset = 0
    for i in range(1, len(chunks)):
        merged_chunk.content += SECTION_SEPARATOR + chunks[i].content
        merged_chunk.large_chunk_reference_ids.append(chunks[i].chunk_id)

        offset += len(SECTION_SEPARATOR) + len(chunks[i - 1].content)
        for link_offset, link_text in (chunks[i].source_links or {}).items():
            if merged_chunk.source_links is None:
                merged_chunk.source_links = {}
            merged_chunk.source_links[link_offset + offset] = link_text

    return merged_chunk


def generate_large_chunks(chunks: list[DocAwareChunk]) -> list[DocAwareChunk]:
    large_chunks = [
        _combine_chunks(chunks[i : i + LARGE_CHUNK_RATIO], idx)
        for idx, i in enumerate(range(0, len(chunks), LARGE_CHUNK_RATIO))
        if len(chunks[i : i + LARGE_CHUNK_RATIO]) > 1
    ]
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
        blurb_size: int = BLURB_SIZE,
        include_metadata: bool = not SKIP_METADATA_IN_CHUNK,
        chunk_token_limit: int = DOC_EMBEDDING_CONTEXT_SIZE,
        chunk_overlap: int = CHUNK_OVERLAP,
        mini_chunk_size: int = MINI_CHUNK_SIZE,
        heartbeat: Heartbeat | None = None,
    ) -> None:
        from llama_index.text_splitter import SentenceSplitter

        self.include_metadata = include_metadata
        self.chunk_token_limit = chunk_token_limit
        self.enable_multipass = enable_multipass
        self.enable_large_chunks = enable_large_chunks
        self.tokenizer = tokenizer
        self.heartbeat = heartbeat

        self.blurb_splitter = SentenceSplitter(
            tokenizer=tokenizer.tokenize,
            chunk_size=blurb_size,
            chunk_overlap=0,
        )

        self.chunk_splitter = SentenceSplitter(
            tokenizer=tokenizer.tokenize,
            chunk_size=chunk_token_limit,
            chunk_overlap=chunk_overlap,
        )

        self.mini_chunk_splitter = (
            SentenceSplitter(
                tokenizer=tokenizer.tokenize,
                chunk_size=mini_chunk_size,
                chunk_overlap=0,
            )
            if enable_multipass
            else None
        )

    def _split_oversized_chunk(self, text: str, content_token_limit: int) -> list[str]:
        """
        Splits the text into smaller chunks based on token count to ensure
        no chunk exceeds the content_token_limit.
        """
        tokens = self.tokenizer.tokenize(text)
        chunks = []
        start = 0
        total_tokens = len(tokens)
        while start < total_tokens:
            end = min(start + content_token_limit, total_tokens)
            token_chunk = tokens[start:end]
            # Join the tokens to reconstruct the text
            chunk_text = " ".join(token_chunk)
            chunks.append(chunk_text)
            start = end
        return chunks

    def _extract_blurb(self, text: str) -> str:
        texts = self.blurb_splitter.split_text(text)
        if not texts:
            return ""
        return texts[0]

    def _get_mini_chunk_texts(self, chunk_text: str) -> list[str] | None:
        if self.mini_chunk_splitter and chunk_text.strip():
            return self.mini_chunk_splitter.split_text(chunk_text)
        return None

    def _chunk_document(
        self,
        document: Document,
        title_prefix: str,
        metadata_suffix_semantic: str,
        metadata_suffix_keyword: str,
        content_token_limit: int,
    ) -> list[DocAwareChunk]:
        """
        Loops through sections of the document, adds metadata and converts them into chunks.
        """
        chunks: list[DocAwareChunk] = []
        link_offsets: dict[int, str] = {}
        chunk_text = ""

        def _create_chunk(
            text: str,
            links: dict[int, str],
            is_continuation: bool = False,
        ) -> DocAwareChunk:
            return DocAwareChunk(
                source_document=document,
                chunk_id=len(chunks),
                blurb=self._extract_blurb(text),
                content=text,
                source_links=links or {0: ""},
                section_continuation=is_continuation,
                title_prefix=title_prefix,
                metadata_suffix_semantic=metadata_suffix_semantic,
                metadata_suffix_keyword=metadata_suffix_keyword,
                mini_chunk_texts=self._get_mini_chunk_texts(text),
            )

        for section in document.sections:
            section_text = section.text
            section_link_text = section.link or ""

            section_token_count = len(self.tokenizer.tokenize(section_text))

            # Large sections are considered self-contained/unique
            # Therefore, they start a new chunk and are not concatenated
            # at the end by other sections
            if section_token_count > content_token_limit:
                if chunk_text:
                    chunks.append(_create_chunk(chunk_text, link_offsets))
                    link_offsets = {}
                    chunk_text = ""

                split_texts = self.chunk_splitter.split_text(section_text)

                for i, split_text in enumerate(split_texts):
                    split_token_count = len(self.tokenizer.tokenize(split_text))

                    if STRICT_CHUNK_TOKEN_LIMIT:
                        split_token_count = len(self.tokenizer.tokenize(split_text))
                        if split_token_count > content_token_limit:
                            # Further split the oversized chunk
                            smaller_chunks = self._split_oversized_chunk(
                                split_text, content_token_limit
                            )
                            for i, small_chunk in enumerate(smaller_chunks):
                                chunks.append(
                                    _create_chunk(
                                        text=small_chunk,
                                        links={0: section_link_text},
                                        is_continuation=(i != 0),
                                    )
                                )
                        else:
                            chunks.append(
                                _create_chunk(
                                    text=split_text,
                                    links={0: section_link_text},
                                )
                            )

                    else:
                        chunks.append(
                            _create_chunk(
                                text=split_text,
                                links={0: section_link_text},
                                is_continuation=(i != 0),
                            )
                        )

                continue

            current_token_count = len(self.tokenizer.tokenize(chunk_text))
            current_offset = len(shared_precompare_cleanup(chunk_text))
            # In the case where the whole section is shorter than a chunk, either add
            # to chunk or start a new one
            next_section_tokens = (
                len(self.tokenizer.tokenize(SECTION_SEPARATOR)) + section_token_count
            )
            if next_section_tokens + current_token_count <= content_token_limit:
                if chunk_text:
                    chunk_text += SECTION_SEPARATOR
                chunk_text += section_text
                link_offsets[current_offset] = section_link_text
            else:
                chunks.append(_create_chunk(chunk_text, link_offsets))
                link_offsets = {0: section_link_text}
                chunk_text = section_text

        # Once we hit the end, if we're still in the process of building a chunk, add what we have.
        # If there is only whitespace left then don't include it. If there are no chunks at all
        # from the doc, we can just create a single chunk with the title.
        if chunk_text.strip() or not chunks:
            chunks.append(
                _create_chunk(
                    chunk_text,
                    link_offsets or {0: section_link_text},
                )
            )

        # If the chunk does not have any useable content, it will not be indexed
        return chunks

    def _handle_single_document(self, document: Document) -> list[DocAwareChunk]:
        # Specifically for reproducing an issue with gmail
        if document.source == DocumentSource.GMAIL:
            logger.debug(f"Chunking {document.semantic_identifier}")

        title = self._extract_blurb(document.get_title_for_document_index() or "")
        title_prefix = title + RETURN_SEPARATOR if title else ""
        title_tokens = len(self.tokenizer.tokenize(title_prefix))

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
            metadata_tokens = len(self.tokenizer.tokenize(metadata_suffix_semantic))

        if metadata_tokens >= self.chunk_token_limit * MAX_METADATA_PERCENTAGE:
            # Note: we can keep the keyword suffix even if the semantic suffix is too long to fit in the model
            # context, there is no limit for the keyword component
            metadata_suffix_semantic = ""
            metadata_tokens = 0

        content_token_limit = self.chunk_token_limit - title_tokens - metadata_tokens
        # If there is not enough context remaining then just index the chunk with no prefix/suffix
        if content_token_limit <= CHUNK_MIN_CONTENT:
            content_token_limit = self.chunk_token_limit
            title_prefix = ""
            metadata_suffix_semantic = ""

        normal_chunks = self._chunk_document(
            document,
            title_prefix,
            metadata_suffix_semantic,
            metadata_suffix_keyword,
            content_token_limit,
        )

        if self.enable_multipass and self.enable_large_chunks:
            large_chunks = generate_large_chunks(normal_chunks)
            normal_chunks.extend(large_chunks)

        return normal_chunks

    def chunk(self, documents: list[Document]) -> list[DocAwareChunk]:
        final_chunks: list[DocAwareChunk] = []
        for document in documents:
            final_chunks.extend(self._handle_single_document(document))

            if self.heartbeat:
                self.heartbeat.heartbeat()

        return final_chunks
