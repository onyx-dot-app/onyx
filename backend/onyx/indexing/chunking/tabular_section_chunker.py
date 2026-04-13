import csv
import io
from collections.abc import Callable

from pydantic import BaseModel

from onyx.connectors.models import Section
from onyx.indexing.chunking.section_chunker import AccumulatorState
from onyx.indexing.chunking.section_chunker import ChunkPayload
from onyx.indexing.chunking.section_chunker import SectionChunker
from onyx.indexing.chunking.section_chunker import SectionChunkerOutput
from onyx.natural_language_processing.utils import BaseTokenizer
from onyx.utils.logger import setup_logger
from shared_configs.configs import STRICT_CHUNK_TOKEN_LIMIT

logger = setup_logger()


# --- Markers / separators used in emitted chunks --------------------------

ROWS_MARKER = "Rows:"
COLUMNS_MARKER = "Columns:"
FIELD_VALUE_SEPARATOR = ", "
ROW_JOIN = "\n"

# Minimum per-chunk row budget. Guards against a prelude so large that no
# row could possibly fit — keeps at least a token or two of headroom so
# the chunk still carries something.
_MIN_ROW_BUDGET_TOKENS = 16


# --- Parsing --------------------------------------------------------------


class _ParsedSection(BaseModel):
    sheet_name: str
    link: str
    headers: list[str]
    rows: list[list[str]]


def _parse_section(section: Section) -> _ParsedSection | None:
    """Parse a CSV-encoded tabular section into headers + rows.

    The first non-empty row is treated as the header. Blank rows are
    skipped so stray separator lines don't produce ghost rows. A CSV
    with only a header row is still parseable (returns empty rows).
    """
    section_text = section.text or ""
    if not section_text.strip():
        return None

    reader = csv.reader(io.StringIO(section_text))
    non_empty_rows = [
        row for row in reader if any(cell.strip() for cell in row)
    ]
    if not non_empty_rows:
        return None

    return _ParsedSection(
        sheet_name=section.link or "",
        link=section.link or "",
        headers=non_empty_rows[0],
        rows=non_empty_rows[1:],
    )


# --- Step 1: FORMATTING ---------------------------------------------------
#
# Converts header + row → a single formatted string. Swap these out to
# change the textual representation of rows in chunks (e.g. JSON-line,
# bullet-list, markdown table row, etc.) without touching packing.


def format_columns_header(headers: list[str]) -> str:
    """Format the 'Columns:' line that appears in every chunk's prelude."""
    return f"{COLUMNS_MARKER} " + FIELD_VALUE_SEPARATOR.join(headers)


def format_row_field_value(headers: list[str], row: list[str]) -> str:
    """Format one row as ``col=val, col=val, ...``.

    - Missing trailing cells (row shorter than headers) are treated as empty.
    - Empty values are dropped; omitting them keeps chunks dense with
      retrieval-relevant content rather than padded with ``col=``.
    """
    parts: list[str] = []
    for i, header in enumerate(headers):
        value = row[i] if i < len(row) else ""
        if not value.strip():
            continue
        parts.append(f"{header}={value}")
    return FIELD_VALUE_SEPARATOR.join(parts)


# --- Step 2: PACKING ------------------------------------------------------
#
# Given formatted row strings + a prelude + a token budget, emit a list of
# chunk strings that each fit within the budget. Swap this out to change
# the packing strategy (e.g. one-row-per-chunk, fixed-row-count, etc.)
# without touching formatting.


class _RowPacker:
    """Packs formatted rows into chunks under a token limit.

    Each emitted chunk looks like::

        <prelude>
        <row 1>
        <row 2>
        ...

    The prelude is repeated at the top of every chunk so each chunk is
    self-describing for downstream retrieval.
    """

    def __init__(
        self,
        prelude: str,
        token_counter: Callable[[str], int],
        max_tokens: int,
        strict: bool,
    ) -> None:
        self.prelude = prelude
        self.token_counter = token_counter
        self.max_tokens = max_tokens
        self.strict = strict

        prelude_tokens = token_counter(prelude)
        # Budget for the rows alone, reserving room for the prelude plus
        # the newline that joins it to the row block.
        self._row_budget = max(
            _MIN_ROW_BUDGET_TOKENS, max_tokens - prelude_tokens - 1
        )

    def pack(self, rows: list[str]) -> list[str]:
        chunks: list[str] = []
        buf: list[str] = []
        buf_tokens = 0

        for row in rows:
            if not row:
                continue
            row_tokens = self.token_counter(row)

            # Row that won't fit its own chunk: flush, split, emit each
            # piece as a standalone chunk.
            if row_tokens > self._row_budget:
                if buf:
                    chunks.append(self._assemble(buf))
                    buf, buf_tokens = [], 0
                for piece in self._split_oversized_row(row):
                    chunks.append(self._assemble([piece]))
                continue

            # +1 accounts for the newline separating rows in the buffer.
            sep_tokens = 1 if buf else 0
            if buf and buf_tokens + sep_tokens + row_tokens > self._row_budget:
                chunks.append(self._assemble(buf))
                buf, buf_tokens = [], 0
                sep_tokens = 0

            buf.append(row)
            buf_tokens += sep_tokens + row_tokens

        if buf:
            chunks.append(self._assemble(buf))
        return chunks

    def _assemble(self, rows: list[str]) -> str:
        return self.prelude + ROW_JOIN + ROW_JOIN.join(rows)

    def _split_oversized_row(self, row: str) -> list[str]:
        """Split a single over-budget row.

        First pass splits at ``field=value`` boundaries to preserve the
        column-level structure. If ``strict`` is set and any resulting
        piece is still over budget, fall back to a hard character-level
        split so no chunk ever exceeds ``max_tokens``.
        """
        pieces = _split_by_field_boundary(
            row, self._row_budget, self.token_counter
        )

        if not self.strict:
            return pieces

        out: list[str] = []
        for piece in pieces:
            if self.token_counter(piece) > self._row_budget:
                out.extend(_hard_split_by_chars(piece, self._row_budget, self.token_counter))
            else:
                out.append(piece)
        return out


def _split_by_field_boundary(
    row: str,
    max_tokens: int,
    token_counter: Callable[[str], int],
) -> list[str]:
    """Greedy split of a ``col=val, col=val, ...`` row at ``, `` boundaries."""
    parts = row.split(FIELD_VALUE_SEPARATOR)
    pieces: list[str] = []
    buf: list[str] = []
    buf_tokens = 0
    sep_tokens = token_counter(FIELD_VALUE_SEPARATOR)

    for part in parts:
        part_tokens = token_counter(part)
        add_sep = sep_tokens if buf else 0
        if buf and buf_tokens + add_sep + part_tokens > max_tokens:
            pieces.append(FIELD_VALUE_SEPARATOR.join(buf))
            buf, buf_tokens = [part], part_tokens
        else:
            buf.append(part)
            buf_tokens += add_sep + part_tokens

    if buf:
        pieces.append(FIELD_VALUE_SEPARATOR.join(buf))
    return pieces


def _hard_split_by_chars(
    text: str,
    max_tokens: int,
    token_counter: Callable[[str], int],
) -> list[str]:
    """Last-resort character split when field-level splitting can't
    reduce a piece below ``max_tokens`` (e.g. a single field contains a
    giant value). Approximates via chars-per-token from the input string
    itself, then slices."""
    total_tokens = max(1, token_counter(text))
    approx_chars_per_token = max(1, len(text) // total_tokens)
    window = max(1, max_tokens * approx_chars_per_token)
    return [text[i : i + window] for i in range(0, len(text), window)]


# --- Step 3: ORCHESTRATION ------------------------------------------------


class TabularChunker(SectionChunker):
    """Chunks tabular sections (csv text) into row-packed field=value chunks.

    Each emitted chunk carries a prelude (sheet name + Rows: marker +
    Columns: header line) followed by as many ``col=val, col=val``
    rows as fit under ``content_token_limit``. Rows too large for a
    single chunk are split at field boundaries (and, under
    ``STRICT_CHUNK_TOKEN_LIMIT``, hard-split by characters as a fallback).
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

        # Tabular sections are structurally standalone — flush any pending
        # text buffer before emitting our own chunks, matching ImageChunker.
        payloads = accumulator.flush_to_list()

        prelude = self._build_prelude(parsed)
        formatted_rows = [
            line
            for line in (
                format_row_field_value(parsed.headers, row)
                for row in parsed.rows
            )
            if line
        ]

        # Header-only table (no non-empty rows): emit a single
        # prelude-only chunk so the column schema is still indexed.
        if not formatted_rows:
            payloads.append(
                ChunkPayload(
                    text=prelude,
                    links={0: parsed.link},
                    is_continuation=False,
                )
            )
            return SectionChunkerOutput(
                payloads=payloads,
                accumulator=AccumulatorState(),
            )

        packer = _RowPacker(
            prelude=prelude,
            token_counter=self._count_tokens,
            max_tokens=content_token_limit,
            strict=STRICT_CHUNK_TOKEN_LIMIT,
        )
        chunk_texts = packer.pack(formatted_rows)

        for i, text in enumerate(chunk_texts):
            payloads.append(
                ChunkPayload(
                    text=text,
                    links={0: parsed.link},
                    is_continuation=(i != 0),
                )
            )

        return SectionChunkerOutput(
            payloads=payloads,
            accumulator=AccumulatorState(),
        )

    def _build_prelude(self, parsed: _ParsedSection) -> str:
        """The per-chunk header: sheet name (if any) + ``Rows:`` marker
        + ``Columns:`` header line. Swap this to change the prelude shape."""
        parts: list[str] = []
        if parsed.sheet_name:
            parts.append(parsed.sheet_name)
        parts.append(ROWS_MARKER)
        parts.append(format_columns_header(parsed.headers))
        return ROW_JOIN.join(parts)

    def _count_tokens(self, text: str) -> int:
        return len(self.tokenizer.encode(text))
