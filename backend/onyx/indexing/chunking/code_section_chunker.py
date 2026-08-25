from typing import Any, cast

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
)
from onyx.natural_language_processing.utils import (
    BaseTokenizer,
    count_tokens,
    split_text_by_tokens,
)
from onyx.utils.logger import setup_logger
from onyx.utils.text_processing import clean_text

logger = setup_logger()

# Language passed to chonkie's CodeChunker when we cannot name one; magika
# then detects the language from the content itself.
_AUTO_LANGUAGE = "auto"


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
        self._splitters: dict[str, tuple[int, Any]] = {}

    def chunk_section(
        self,
        section: Section,
        accumulator: AccumulatorState,
        content_token_limit: int,
    ) -> SectionChunkerOutput:
        assert isinstance(section, CodeSection)

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

        section_text = clean_text(section.text)
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
        def make_payload(text: str, link: str, is_continuation: bool) -> ChunkPayload:
            return ChunkPayload(
                text=text,
                links={0: link},
                is_continuation=is_continuation,
                # Sentence-based mini-chunks cut code mid-statement.
                skip_mini_chunks=True,
            )

        if count_tokens(section_text, self.tokenizer) <= content_token_limit:
            return [make_payload(section_text, section_link, is_continuation=False)]

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
            texts = split_text_by_tokens(
                section_text, self.tokenizer, content_token_limit
            )
            return [
                make_payload(text, section_link, is_continuation=(i != 0))
                for i, text in enumerate(texts)
            ]

        payloads: list[ChunkPayload] = []
        for i, (text, start_line, end_line) in enumerate(spans):
            link = _line_anchored_link(section_link, start_line, end_line)
            # A single syntax node can exceed the budget (e.g. a giant
            # literal); hard-split it so the embedder never truncates.
            if count_tokens(text, self.tokenizer) > content_token_limit:
                payloads.extend(
                    make_payload(small_text, link, is_continuation=(i != 0 or j != 0))
                    for j, small_text in enumerate(
                        split_text_by_tokens(text, self.tokenizer, content_token_limit)
                    )
                )
            else:
                payloads.append(make_payload(text, link, is_continuation=(i != 0)))
        return payloads

    def _split_at_syntax_boundaries(
        self,
        section_text: str,
        language: str | None,
        content_token_limit: int,
    ) -> list[tuple[str, int, int]] | None:
        """Split at tree-sitter node boundaries. Returns (text, start_line,
        end_line) per chunk, or None if the language is unsupported."""
        # Local import: pulls in tree-sitter language packs.
        from chonkie import CodeChunker as ChonkieCodeChunker

        language_key = language or _AUTO_LANGUAGE
        cached = self._splitters.get(language_key)
        splitter = (
            cached[1]
            if cached is not None and cached[0] == content_token_limit
            else None
        )
        if splitter is None:
            try:
                splitter = ChonkieCodeChunker(
                    tokenizer_or_token_counter=(
                        lambda text: len(self.tokenizer.encode(text))
                    ),
                    chunk_size=content_token_limit,
                    language=language_key,
                    return_type="chunks",
                )
            except Exception:
                logger.warning(
                    "No tree-sitter grammar for language=%s; "
                    "falling back to token splitting",
                    language,
                )
                return None
            self._splitters[language_key] = (content_token_limit, splitter)

        chunks = cast(list[Any], splitter.chunk(section_text))
        spans: list[tuple[str, int, int]] = []
        for chunk in chunks:
            if not chunk.text.strip():
                continue
            # Anchor to the first real code line, past any leading newlines.
            leading = len(chunk.text) - len(chunk.text.lstrip("\n"))
            start_line = section_text.count("\n", 0, chunk.start_index + leading) + 1
            end_line = start_line + chunk.text.strip("\n").count("\n")
            spans.append((chunk.text, start_line, end_line))
        return spans
