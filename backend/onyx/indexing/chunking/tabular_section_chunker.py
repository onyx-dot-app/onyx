import csv
import io

from pydantic import BaseModel

from onyx.connectors.models import Section
from onyx.indexing.chunking.section_chunker import AccumulatorState
from onyx.indexing.chunking.section_chunker import ChunkPayload
from onyx.indexing.chunking.section_chunker import SectionChunker
from onyx.indexing.chunking.section_chunker import SectionChunkerOutput
from onyx.natural_language_processing.utils import BaseTokenizer
from onyx.utils.logger import setup_logger

logger = setup_logger()


COLUMNS_MARKER = "Columns:"
FIELD_VALUE_SEPARATOR = ", "
ROW_JOIN = "\n"


# --- Parsing --------------------------------------------------------------


class _ParsedSection(BaseModel):
    sheet_name: str
    link: str
    headers: list[str]
    rows: list[list[str]]


def _parse_section(section: Section) -> _ParsedSection | None:
    """Parse CSV into headers + rows. First non-empty row is the header;
    blank rows are skipped."""
    section_text = section.text or ""
    if not section_text.strip():
        return None

    reader = csv.reader(io.StringIO(section_text))
    non_empty_rows = [row for row in reader if any(cell.strip() for cell in row)]
    if not non_empty_rows:
        return None

    return _ParsedSection(
        sheet_name=section.link or "",
        link=section.link or "",
        headers=non_empty_rows[0],
        rows=non_empty_rows[1:],
    )


# --- Formatting -----------------------------------------------------------


def format_columns_header(headers: list[str]) -> str:
    """Format the 'Columns:' line. Each header is quoted; underscored
    headers also get a space-substituted friendly name in parens
    (e.g. ``"MTTR_hours" (MTTR hours)``)."""
    parts: list[str] = []
    for header in headers:
        friendly = header.replace("_", " ")
        if friendly != header:
            parts.append(f'"{header}" ({friendly})')
        else:
            parts.append(f'"{header}"')
    return f"{COLUMNS_MARKER} " + FIELD_VALUE_SEPARATOR.join(parts)


def _row_to_pairs(headers: list[str], row: list[str]) -> list[tuple[str, str]]:
    """Return ``(header, value)`` pairs, dropping empty / missing values."""
    pairs: list[tuple[str, str]] = []
    for i, header in enumerate(headers):
        value = row[i] if i < len(row) else ""
        if not value.strip():
            continue
        pairs.append((header, value))
    return pairs


def _pairs_to_row(pairs: list[tuple[str, str]]) -> str:
    """Render ``(header, value)`` pairs as ``col=val, col=val, ...``."""
    return FIELD_VALUE_SEPARATOR.join(f"{h}={v}" for h, v in pairs)


def _rows_to_block(rows: list[list[tuple[str, str]]]) -> str:
    """Render a list of rows as newline-joined ``col=val`` lines."""
    return ROW_JOIN.join(_pairs_to_row(pairs) for pairs in rows)


def _union_of_headers(
    rows: list[list[tuple[str, str]]],
    all_headers: list[str],
) -> list[str]:
    """Headers present in any row, in original column order."""
    present: set[str] = set()
    for row_pairs in rows:
        for h, _ in row_pairs:
            present.add(h)
    return [h for h in all_headers if h in present]


# --- Tokenizer helpers ----------------------------------------------------


def _count_tokens(tokenizer: BaseTokenizer, text: str) -> int:
    return len(tokenizer.encode(text))


def _token_split(tokenizer: BaseTokenizer, text: str, max_tokens: int) -> list[str]:
    """Split ``text`` into pieces of ≤ ``max_tokens`` tokens via
    encode/decode round-trip at token-id boundaries."""
    if not text:
        return []
    token_ids = tokenizer.encode(text)
    pieces: list[str] = []
    for start in range(0, len(token_ids), max_tokens):
        pieces.append(tokenizer.decode(token_ids[start : start + max_tokens]))
    return pieces


# --- Chunk construction ---------------------------------------------------


def _full_chunk_fits(
    tokenizer: BaseTokenizer,
    rows: list[list[tuple[str, str]]],
    all_headers: list[str],
    sheet_header: str,
    max_tokens: int,
) -> bool:
    """Admissibility for packing: does ``[sheet]`` + ``Columns`` + rows
    fit under ``max_tokens``? (Row block alone when no sheet header.)"""
    row_block = _rows_to_block(rows)
    if _count_tokens(tokenizer, row_block) > max_tokens:
        return False
    if not sheet_header:
        return True
    cols_line = format_columns_header(_union_of_headers(rows, all_headers))
    full = sheet_header + ROW_JOIN + cols_line + ROW_JOIN + row_block
    return _count_tokens(tokenizer, full) <= max_tokens


def _build_chunk(
    tokenizer: BaseTokenizer,
    rows: list[list[tuple[str, str]]],
    all_headers: list[str],
    sheet_header: str,
    max_tokens: int,
) -> str:
    """Build richest chunk for ``rows``: row block + ``[sheet]`` (if
    fits) + ``Columns: ...`` (if still fits). Caller ensures row block
    itself fits."""
    row_block = _rows_to_block(rows)
    if not sheet_header:
        return row_block

    with_sheet = sheet_header + ROW_JOIN + row_block
    if _count_tokens(tokenizer, with_sheet) > max_tokens:
        return row_block

    cols_line = format_columns_header(_union_of_headers(rows, all_headers))
    with_cols = sheet_header + ROW_JOIN + cols_line + ROW_JOIN + row_block
    if _count_tokens(tokenizer, with_cols) <= max_tokens:
        return with_cols
    return with_sheet


def _build_schema_only_chunks(
    tokenizer: BaseTokenizer,
    parsed: _ParsedSection,
    sheet_header: str,
    max_tokens: int,
) -> list[str]:
    """Header-only table: ``[sheet]\\nColumns: ...`` if it fits, else
    leaner fallbacks, token-splitting oversized Columns as a last step."""
    cols_line = format_columns_header(parsed.headers)
    if sheet_header:
        with_cols = sheet_header + ROW_JOIN + cols_line
        if _count_tokens(tokenizer, with_cols) <= max_tokens:
            return [with_cols]
        if _count_tokens(tokenizer, sheet_header) <= max_tokens:
            return [sheet_header] + _token_split(tokenizer, cols_line, max_tokens)
    if _count_tokens(tokenizer, cols_line) <= max_tokens:
        return [cols_line]
    return _token_split(tokenizer, cols_line, max_tokens)


def _split_oversized_row(
    tokenizer: BaseTokenizer, row_str: str, max_tokens: int
) -> list[str]:
    """Split an oversized row into ≤ ``max_tokens`` pieces at ``, ``
    boundaries; token-split any single field that's itself too big."""
    fields = row_str.split(FIELD_VALUE_SEPARATOR)
    pieces: list[str] = []
    buf: list[str] = []

    def flush() -> None:
        if buf:
            pieces.append(FIELD_VALUE_SEPARATOR.join(buf))
            buf.clear()

    for field in fields:
        candidate = FIELD_VALUE_SEPARATOR.join(buf + [field]) if buf else field
        if _count_tokens(tokenizer, candidate) <= max_tokens:
            buf.append(field)
            continue

        # Candidate busts the budget. Flush buf; then decide whether
        # the new field fits alone or needs token-level splitting.
        flush()
        if _count_tokens(tokenizer, field) > max_tokens:
            pieces.extend(_token_split(tokenizer, field, max_tokens))
        else:
            buf.append(field)

    flush()
    return pieces


# --- Packing state machine ------------------------------------------------


def _pack_rows(
    tokenizer: BaseTokenizer,
    parsed: _ParsedSection,
    max_tokens: int,
) -> list[str]:
    """Produce chunk-text list: pack rows into ``pending`` while the
    full chunk (prelude + rows) still fits; flush when it wouldn't."""
    sheet_header = f"[{parsed.sheet_name}]" if parsed.sheet_name else ""
    chunks: list[str] = []
    pending: list[list[tuple[str, str]]] = []
    any_row = False

    for row_values in parsed.rows:
        pairs = _row_to_pairs(parsed.headers, row_values)
        if not pairs:
            continue
        any_row = True
        row_str = _pairs_to_row(pairs)

        # Single row can't fit on its own — flush pending, split it.
        if _count_tokens(tokenizer, row_str) > max_tokens:
            if pending:
                chunks.append(
                    _build_chunk(
                        tokenizer, pending, parsed.headers, sheet_header, max_tokens
                    )
                )
                pending = []
            chunks.extend(_split_oversized_row(tokenizer, row_str, max_tokens))
            continue

        # Extend pending only if the full chunk (with prelude) still
        # fits. Otherwise flush and start a fresh chunk with this row.
        if _full_chunk_fits(
            tokenizer, pending + [pairs], parsed.headers, sheet_header, max_tokens
        ):
            pending.append(pairs)
        else:
            if pending:
                chunks.append(
                    _build_chunk(
                        tokenizer, pending, parsed.headers, sheet_header, max_tokens
                    )
                )
            pending = [pairs]

    if pending:
        chunks.append(
            _build_chunk(tokenizer, pending, parsed.headers, sheet_header, max_tokens)
        )

    # Header-only table: emit a schema chunk so columns still index.
    if not any_row:
        chunks.extend(
            _build_schema_only_chunks(tokenizer, parsed, sheet_header, max_tokens)
        )
    return chunks


# --- Orchestration --------------------------------------------------------


class TabularChunker(SectionChunker):
    """Chunks tabular sections row-by-row with greedy multi-row packing.

    Each chunk is ``[sheet]\\n`` + tailored ``Columns: ...\\n`` +
    ``col=val, col=val, ...`` row lines, packed while the full chunk
    fits under ``max_tokens``. Oversized rows split at ``, `` (and
    token boundaries for a single oversized field) with no prelude.
    """

    def __init__(self, tokenizer: BaseTokenizer) -> None:
        self.tokenizer = tokenizer

    def chunk_section(
        self,
        section: Section,
        accumulator: AccumulatorState,
        content_token_limit: int,
    ) -> SectionChunkerOutput:
        assert section.text is not None

        parsed = _parse_section(section)
        if parsed is None:
            logger.warning(
                f"TabularChunker: skipping unparseable section (link={section.link})"
            )
            return SectionChunkerOutput(payloads=[], accumulator=accumulator)

        chunk_texts = _pack_rows(self.tokenizer, parsed, content_token_limit)

        # Tabular sections are structurally standalone: flush any
        # pending text buffer before our own chunks.
        payloads = accumulator.flush_to_list()
        for i, text in enumerate(chunk_texts):
            n = _count_tokens(self.tokenizer, text)
            if n > content_token_limit:
                logger.warning(
                    f"TabularChunker: emitted chunk of {n} tokens exceeds "
                    f"max_tokens={content_token_limit} (link={section.link})"
                )
            payloads.append(
                ChunkPayload(
                    text=text,
                    links={0: parsed.link},
                    is_continuation=(i > 0),
                )
            )
        return SectionChunkerOutput(payloads=payloads, accumulator=AccumulatorState())
