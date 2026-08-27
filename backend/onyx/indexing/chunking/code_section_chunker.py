from typing import cast

from chonkie import CodeChunker as ChonkieCodeChunker
from tree_sitter_language_pack import has_language

from onyx.connectors.cross_connector_utils.code_file_utils import (
    infer_code_language,
    is_sensitive_code_file,
)
from onyx.connectors.models import CodeSection, Section
from onyx.indexing.chunking.section_chunker import (
    AccumulatorState,
    ChunkPayload,
    SectionChunker,
    SectionChunkerOutput,
    build_payloads,
)
from onyx.natural_language_processing.utils import BaseTokenizer, count_tokens
from onyx.utils.logger import setup_logger
from onyx.utils.text_processing import clean_code_text

logger = setup_logger()


def _line_anchored_link(link: str, start_line: int, end_line: int) -> str:
    """Append a line-range fragment to a code file link (GitHub-style anchors)."""
    if not link or "#" in link:
        return link
    if start_line == end_line:
        return f"{link}#L{start_line}"
    return f"{link}#L{start_line}-L{end_line}"


class CodeChunker(SectionChunker):
    """Chunks CodeSections at syntactic boundaries via chonkie's tree-sitter
    CodeChunker. Falls back to token-based splitting when the language cannot
    be parsed. Code never merges with buffered prose from other sections."""

    def __init__(self, tokenizer: BaseTokenizer) -> None:
        self.tokenizer = tokenizer
        # One chonkie splitter per language, stored with the token budget it
        # was built for. The budget varies per document (title/metadata
        # deductions), so a mismatched entry is rebuilt; keying by language
        # alone keeps the cache bounded.
        self._splitters: dict[str, tuple[int, ChonkieCodeChunker]] = {}

    def chunk_section(
        self,
        section: Section,
        accumulator: AccumulatorState,
        content_token_limit: int,
    ) -> SectionChunkerOutput:
        if not isinstance(section, CodeSection):
            raise ValueError(
                f"CodeChunker received a non-code section: {type(section).__name__}"
            )

        # Enforced here, not only in connectors: sections can arrive from the
        # ingestion API with any path/language, and a supplied language must
        # not bypass the credential-format exclusion.
        if is_sensitive_code_file(section.file_path):
            logger.warning(
                "Refusing to chunk sensitive code file %s; section dropped",
                section.file_path,
            )
            return SectionChunkerOutput(
                payloads=accumulator.flush_to_list(),
                accumulator=AccumulatorState(),
            )

        section_text = clean_code_text(section.text)
        section_link = section.link or ""
        language = section.language or infer_code_language(section.file_path)

        # Flush any buffered prose — code chunks stay pure code.
        payloads = accumulator.flush_to_list()
        payloads.extend(
            self._chunk_code(
                section_text=section_text,
                section_link=section_link,
                language=language,
                content_token_limit=content_token_limit,
            )
        )

        return SectionChunkerOutput(
            payloads=payloads,
            accumulator=AccumulatorState(),
        )

    def _chunk_code(
        self,
        section_text: str,
        section_link: str,
        language: str | None,
        content_token_limit: int,
    ) -> list[ChunkPayload]:
        def code_payloads(
            text: str, link: str, is_continuation: bool
        ) -> list[ChunkPayload]:
            return build_payloads(
                text=text,
                link=link,
                tokenizer=self.tokenizer,
                content_token_limit=content_token_limit,
                is_continuation=is_continuation,
                # Sentence-based mini-chunks cut code mid-statement.
                skip_mini_chunks=True,
            )

        if count_tokens(section_text, self.tokenizer) <= content_token_limit:
            return code_payloads(section_text, section_link, is_continuation=False)

        try:
            spans = self._split_at_syntax_boundaries(
                section_text, language, content_token_limit
            )
        except Exception:
            logger.warning(
                "Syntax-aware code chunking failed for language=%s; "
                "falling back to token splitting",
                language,
                exc_info=True,
            )
            spans = None

        if spans is None:
            return code_payloads(section_text, section_link, is_continuation=False)

        payloads: list[ChunkPayload] = []
        for i, (text, start_line, end_line) in enumerate(spans):
            # A single syntax node can exceed the budget (e.g. a giant
            # literal); build_payloads hard-splits it.
            payloads.extend(
                code_payloads(
                    text,
                    _line_anchored_link(section_link, start_line, end_line),
                    is_continuation=(i != 0),
                )
            )
        return payloads

    def _split_at_syntax_boundaries(
        self,
        section_text: str,
        language: str | None,
        content_token_limit: int,
    ) -> list[tuple[str, int, int]] | None:
        """Split at tree-sitter node boundaries. Returns (text, start_line,
        end_line) per chunk, or None when no grammar is available."""
        if language is None:
            return None

        splitter = self._get_splitter(language, content_token_limit)
        if splitter is None:
            return None

        # chonkie's chunk texts are contiguous and reconstruct the input
        # exactly, so one running line counter covers the whole file.
        # (CodeChunk carries start_line/end_line fields, but chonkie never
        # populates them.)
        texts = cast(list[str], splitter.chunk(section_text))
        spans: list[tuple[str, int, int]] = []
        line = 1
        for text in texts:
            if text.strip():
                # Anchor to the first real code line, past any leading newlines.
                start_line = line + len(text) - len(text.lstrip("\n"))
                end_line = start_line + text.strip("\n").count("\n")
                spans.append((text, start_line, end_line))
            line += text.count("\n")
        return spans

    def _get_splitter(
        self, language: str, content_token_limit: int
    ) -> ChonkieCodeChunker | None:
        """Cached chonkie splitter for a language, or None when its grammar is
        unavailable."""
        cached = self._splitters.get(language)
        if cached is not None and cached[0] == content_token_limit:
            return cached[1]

        if not has_language(language):
            logger.info(
                "No tree-sitter grammar named %s; falling back to token splitting",
                language,
            )
            return None

        try:
            splitter = ChonkieCodeChunker(
                tokenizer_or_token_counter=(
                    lambda text: len(self.tokenizer.encode(text))
                ),
                chunk_size=content_token_limit,
                language=language,
                return_type="texts",
            )
        except Exception:
            logger.warning(
                "Could not load the tree-sitter grammar for language=%s; "
                "falling back to token splitting.",
                language,
                exc_info=True,
            )
            return None

        self._splitters[language] = (content_token_limit, splitter)
        return splitter
