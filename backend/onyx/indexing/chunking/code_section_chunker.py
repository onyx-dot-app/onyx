from typing import NamedTuple, cast

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
from onyx.utils.circuit_breaker import CircuitBreaker
from onyx.utils.logger import setup_logger
from onyx.utils.text_processing import clean_code_text

logger = setup_logger()

# An uncached grammar makes the pack fetch its archive, which on a firewalled
# network blocks until timeout (60s in testing). One archive serves every
# language, so the failure is shared and the breaker covers all loads.
# Module-level: a Chunker is built per document batch.
_GRAMMAR_LOADS = CircuitBreaker()


class _CodeSpan(NamedTuple):
    """One syntax-bounded slice of a code section, and the 1-based line range
    it occupies in that section."""

    text: str
    start_line: int
    end_line: int


class _CachedSplitter(NamedTuple):
    """A splitter and the token budget it was built for. The budget varies per
    document, so an entry built for a different one is rebuilt."""

    token_limit: int
    splitter: ChonkieCodeChunker


def _line_range(text: str, first_line: int) -> tuple[int, int]:
    """Lines `text` spans, starting from its first non-blank line."""
    start = first_line + len(text) - len(text.lstrip("\n"))
    return start, start + text.strip("\n").count("\n")


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
        self._splitters: dict[str, _CachedSplitter] = {}

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

        # Also enforced in connectors, but sections can arrive from the
        # ingestion API with any path or language.
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
        for i, span in enumerate(spans):
            # A single syntax node can exceed the budget; build_payloads
            # hard-splits it.
            payloads.extend(
                code_payloads(
                    span.text,
                    _line_anchored_link(section_link, span.start_line, span.end_line),
                    is_continuation=(i != 0),
                )
            )
        return payloads

    def _split_at_syntax_boundaries(
        self,
        section_text: str,
        language: str | None,
        content_token_limit: int,
    ) -> list[_CodeSpan] | None:
        """Split at tree-sitter node boundaries, or None when no grammar is
        available."""
        if language is None:
            return None

        splitter = self._get_splitter(language, content_token_limit)
        if splitter is None:
            return None

        # chunk() returns list[CodeChunk] | list[str] depending on the
        # return_type passed to the constructor, which the signature cannot
        # express. _get_splitter always builds with return_type="texts".
        texts = cast(list[str], splitter.chunk(section_text))

        # chonkie's chunks reconstruct the input exactly, so a running counter
        # tracks lines. Its CodeChunk.start_line is never populated.
        spans: list[_CodeSpan] = []
        line = 1
        for text in texts:
            if text.strip():
                spans.append(_CodeSpan(text, *_line_range(text, line)))
            line += text.count("\n")
        return spans

    def _get_splitter(
        self, language: str, content_token_limit: int
    ) -> ChonkieCodeChunker | None:
        """Cached chonkie splitter for a language, or None when its grammar is
        unavailable."""
        cached = self._splitters.get(language)
        if cached is not None and cached.token_limit == content_token_limit:
            return cached.splitter

        if not has_language(language):
            logger.info(
                "No tree-sitter grammar named %s; falling back to token splitting",
                language,
            )
            return None

        if _GRAMMAR_LOADS.is_open:
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
            failures = _GRAMMAR_LOADS.record_failure()
            log = logger.warning if failures == 1 else logger.debug
            log(
                "Could not load the tree-sitter grammar for language=%s; falling "
                "back to token splitting for now. Grammars "
                "are extracted from a bundle the image build caches, so this "
                "means that cache is missing or not writable.",
                language,
                exc_info=failures == 1,
            )
            return None

        _GRAMMAR_LOADS.record_success()
        self._splitters[language] = _CachedSplitter(content_token_limit, splitter)
        return splitter
