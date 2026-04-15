import csv
import io
from collections.abc import Iterable

from pydantic import BaseModel

from onyx.connectors.models import Section
from onyx.indexing.chunking.section_chunker import AccumulatorState
from onyx.indexing.chunking.section_chunker import ChunkPayload
from onyx.indexing.chunking.section_chunker import SectionChunker
from onyx.indexing.chunking.section_chunker import SectionChunkerOutput
from onyx.natural_language_processing.utils import BaseTokenizer
from onyx.natural_language_processing.utils import count_tokens
from onyx.natural_language_processing.utils import split_text_by_tokens
from onyx.utils.logger import setup_logger

logger = setup_logger()


COLUMNS_MARKER = "Columns:"
FIELD_VALUE_SEPARATOR = ", "
ROW_JOIN = "\n"
NEWLINE_TOKENS = 1


class _ParsedRow(BaseModel):
    header: list[str]
    row: list[str]


class _TokenizedText(BaseModel):
    text: str
    token_count: int


def format_row(header: list[str], row: list[str]) -> str:
    """
    A header-row combination is formatted like this:
    field1=value1, field2=value2, field3=value3
    """
    pairs = _row_to_pairs(header, row)
    formatted = FIELD_VALUE_SEPARATOR.join(f"{h}={v}" for h, v in pairs)
    return formatted


def format_columns_header(headers: list[str]) -> str:
    """
    Format the column header line. Underscored headers get a
    space-substituted friendly alias in parens.
    Example:
        headers = ["id", "MTTR_hours"]
        => "Columns: id, MTTR_hours (MTTR hours)"
    """
    parts: list[str] = []
    for header in headers:
        friendly = header
        if "_" in header:
            friendly = f'{header} ({header.replace("_", " ")})'
        parts.append(friendly)
    return f"{COLUMNS_MARKER} " + FIELD_VALUE_SEPARATOR.join(parts)


def parse_section(section: Section) -> list[_ParsedRow]:
    """Parse CSV into headers + rows. First non-empty row is the header;
    blank rows are skipped."""
    section_text = section.text or ""
    if not section_text.strip():
        return []

    reader = csv.reader(io.StringIO(section_text))
    non_empty_rows = [row for row in reader if any(cell.strip() for cell in row)]

    if not non_empty_rows:
        return []

    header, *data_rows = non_empty_rows
    return [_ParsedRow(header=header, row=row) for row in data_rows]


def _row_to_pairs(headers: list[str], row: list[str]) -> list[tuple[str, str]]:
    return [(h, v) for h, v in zip(headers, row) if v.strip()]


def pack_chunk(chunk: str, new_row: str) -> str:
    return chunk + "\n" + new_row


def _split_row_by_pairs(
    pairs: list[tuple[str, str]],
    tokenizer: BaseTokenizer,
    max_tokens: int,
) -> list[_TokenizedText]:
    """Greedily pack pairs into max-sized pieces. Any single pair that
    itself exceeds ``max_tokens`` is token-split at id boundaries.
    No headers."""
    separator_tokens = count_tokens(FIELD_VALUE_SEPARATOR, tokenizer)
    pieces: list[_TokenizedText] = []
    current_parts: list[str] = []
    current_tokens = 0

    for pair in pairs:
        pair_str = f"{pair[0]}={pair[1]}"
        pair_tokens = count_tokens(pair_str, tokenizer)
        increment = pair_tokens if not current_parts else separator_tokens + pair_tokens

        if current_tokens + increment <= max_tokens:
            current_parts.append(pair_str)
            current_tokens += increment
            continue

        if current_parts:
            pieces.append(
                _TokenizedText(
                    text=FIELD_VALUE_SEPARATOR.join(current_parts),
                    token_count=current_tokens,
                )
            )
            current_parts = []
            current_tokens = 0

        if pair_tokens > max_tokens:
            for split_text in split_text_by_tokens(pair_str, tokenizer, max_tokens):
                pieces.append(
                    _TokenizedText(
                        text=split_text,
                        token_count=count_tokens(split_text, tokenizer),
                    )
                )
        else:
            current_parts = [pair_str]
            current_tokens = pair_tokens

    if current_parts:
        pieces.append(
            _TokenizedText(
                text=FIELD_VALUE_SEPARATOR.join(current_parts),
                token_count=current_tokens,
            )
        )
    return pieces


def _build_chunk_from_scratch(
    pairs: list[tuple[str, str]],
    formatted_row: str,
    row_tokens: int,
    column_header: str,
    column_header_tokens: int,
    sheet_header: str,
    sheet_header_tokens: int,
    tokenizer: BaseTokenizer,
    max_tokens: int,
) -> list[_TokenizedText]:
    # 1. Row alone is too large — split by pairs, no headers.
    if row_tokens > max_tokens:
        return _split_row_by_pairs(pairs, tokenizer, max_tokens)

    chunk = formatted_row
    chunk_tokens = row_tokens

    # 2. Attempt to add column header
    candidate_tokens = column_header_tokens + NEWLINE_TOKENS + chunk_tokens
    if candidate_tokens <= max_tokens:
        chunk = column_header + ROW_JOIN + chunk
        chunk_tokens = candidate_tokens

    # 3. Attempt to add sheet header
    if sheet_header:
        candidate_tokens = sheet_header_tokens + NEWLINE_TOKENS + chunk_tokens
        if candidate_tokens <= max_tokens:
            chunk = sheet_header + ROW_JOIN + chunk
            chunk_tokens = candidate_tokens

    return [_TokenizedText(text=chunk, token_count=chunk_tokens)]


def parse_to_chunks(
    rows: Iterable[_ParsedRow],
    sheet_header: str,
    tokenizer: BaseTokenizer,
    max_tokens: int,
) -> list[str]:
    rows_list = list(rows)
    if not rows_list:
        return []

    column_header = format_columns_header(rows_list[0].header)
    column_header_tokens = count_tokens(column_header, tokenizer)
    sheet_header_tokens = count_tokens(sheet_header, tokenizer) if sheet_header else 0

    chunks: list[str] = []
    current_chunk = ""
    current_chunk_tokens = 0

    for row in rows_list:
        pairs: list[tuple[str, str]] = _row_to_pairs(row.header, row.row)
        formatted = format_row(row.header, row.row)
        row_tokens = count_tokens(formatted, tokenizer)

        if current_chunk:
            # Attempt to pack it in (additive approximation)
            if current_chunk_tokens + NEWLINE_TOKENS + row_tokens <= max_tokens:
                current_chunk = pack_chunk(current_chunk, formatted)
                current_chunk_tokens += NEWLINE_TOKENS + row_tokens
                continue
            # Doesn't fit — flush and start new
            chunks.append(current_chunk)
            current_chunk = ""
            current_chunk_tokens = 0

        # Build chunk from scratch
        for piece in _build_chunk_from_scratch(
            pairs=pairs,
            formatted_row=formatted,
            row_tokens=row_tokens,
            column_header=column_header,
            column_header_tokens=column_header_tokens,
            sheet_header=sheet_header,
            sheet_header_tokens=sheet_header_tokens,
            tokenizer=tokenizer,
            max_tokens=max_tokens,
        ):
            if current_chunk:
                chunks.append(current_chunk)
            current_chunk = piece.text
            current_chunk_tokens = piece.token_count

    # Flush remaining
    if current_chunk:
        chunks.append(current_chunk)

    return chunks


class TabularChunker(SectionChunker):
    def __init__(self, tokenizer: BaseTokenizer) -> None:
        self.tokenizer = tokenizer

    def chunk_section(
        self,
        section: Section,
        accumulator: AccumulatorState,
        content_token_limit: int,
    ) -> SectionChunkerOutput:
        payloads = accumulator.flush_to_list()

        parsed_rows = parse_section(section)
        if not parsed_rows:
            logger.warning(
                f"TabularChunker: skipping unparseable section (link={section.link})"
            )
            return SectionChunkerOutput(
                payloads=payloads, accumulator=AccumulatorState()
            )

        sheet_header = section.heading or ""
        chunk_texts = parse_to_chunks(
            rows=parsed_rows,
            sheet_header=sheet_header,
            tokenizer=self.tokenizer,
            max_tokens=content_token_limit,
        )

        for i, text in enumerate(chunk_texts):
            payloads.append(
                ChunkPayload(
                    text=text,
                    links={0: section.link or ""},
                    is_continuation=(i > 0),
                )
            )
        return SectionChunkerOutput(payloads=payloads, accumulator=AccumulatorState())
