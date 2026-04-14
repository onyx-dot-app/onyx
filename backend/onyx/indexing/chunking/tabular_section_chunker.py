import csv
import io
from collections.abc import Generator
from collections.abc import Iterator

from pydantic import BaseModel

from onyx.connectors.models import Section
from onyx.indexing.chunking.section_chunker import AccumulatorState
from onyx.indexing.chunking.section_chunker import ChunkPayload
from onyx.indexing.chunking.section_chunker import SectionChunker
from onyx.indexing.chunking.section_chunker import SectionChunkerOutput
from onyx.natural_language_processing.utils import BaseTokenizer
from onyx.natural_language_processing.utils import count_tokens
from onyx.utils.logger import setup_logger

logger = setup_logger()


COLUMNS_MARKER = "Columns:"
FIELD_VALUE_SEPARATOR = ", "
ROW_JOIN = "\n"


class _ParsedRow(BaseModel):
    header: list[str]
    row: list[str]


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
        friendly = header.replace("_", " ")
        if friendly != header:
            parts.append(f"{header} ({friendly})")
        else:
            parts.append(header)
    return f"{COLUMNS_MARKER} " + FIELD_VALUE_SEPARATOR.join(parts)


def parse_section(section: Section) -> Generator[_ParsedRow, None, None]:
    """Parse CSV into headers + rows. First non-empty row is the header;
    blank rows are skipped."""
    section_text = section.text or ""
    if not section_text.strip():
        return None

    reader = csv.reader(io.StringIO(section_text))
    non_empty_rows = (row for row in reader if any(cell.strip() for cell in row))

    header = next(non_empty_rows, None)
    if header is None:
        return None

    for row in non_empty_rows:
        yield _ParsedRow(header=header, row=row)


def _row_to_pairs(headers: list[str], row: list[str]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for i, header in enumerate(headers):
        value = row[i] if i < len(row) else ""
        if not value.strip():
            continue
        pairs.append((header, value))
    return pairs


def can_pack(
    chunk_content: str, new_row: str, tokenizer: BaseTokenizer, max_tokens: int
) -> bool:
    """
    Check that adding this row will not exceed the chunk content
    """
    chunk_token_count = count_tokens(chunk_content, tokenizer)
    new_row_count = count_tokens(new_row, tokenizer)

    # Add the additional 1 token for the \n for packing
    return chunk_token_count + new_row_count + 1 <= max_tokens


def pack_chunk(chunk: str, new_row: str) -> str:
    return chunk + "\n" + new_row


def _token_split(
    text: str,
    tokenizer: BaseTokenizer,
    max_tokens: int,
) -> Generator[str, None, None]:
    """Split ``text`` into pieces of ≤ ``max_tokens`` tokens via
    encode/decode at token-id boundaries."""
    if not text:
        return
    token_ids = tokenizer.encode(text)
    for start in range(0, len(token_ids), max_tokens):
        yield tokenizer.decode(token_ids[start : start + max_tokens])


def _split_row_by_pairs(
    pairs: list[tuple[str, str]],
    tokenizer: BaseTokenizer,
    max_tokens: int,
) -> Generator[str, None, None]:
    """Greedily pack pairs into max-sized pieces. Any single pair that
    itself exceeds ``max_tokens`` is token-split at id boundaries.
    No headers."""
    current: list[tuple[str, str]] = []
    for pair in pairs:
        candidate = current + [pair]
        candidate_str = FIELD_VALUE_SEPARATOR.join(f"{h}={v}" for h, v in candidate)
        if count_tokens(candidate_str, tokenizer) <= max_tokens:
            current = candidate
            continue

        # Candidate busts the budget — flush what we have.
        if current:
            yield FIELD_VALUE_SEPARATOR.join(f"{h}={v}" for h, v in current)
            current = []

        # Single pair itself too large — fall back to token-level split.
        pair_str = f"{pair[0]}={pair[1]}"
        if count_tokens(pair_str, tokenizer) > max_tokens:
            yield from _token_split(pair_str, tokenizer, max_tokens)
        else:
            current = [pair]
    if current:
        yield FIELD_VALUE_SEPARATOR.join(f"{h}={v}" for h, v in current)


def build_chunk_from_scratch(
    header: list[str],
    pairs: list[tuple[str, str]],
    sheet_header: str,
    tokenizer: BaseTokenizer,
    max_tokens: int,
) -> Generator[str, None, None]:
    formatted_row = FIELD_VALUE_SEPARATOR.join(f"{h}={v}" for h, v in pairs)

    # 1. Row alone is too large — split by pairs, no headers.
    if count_tokens(formatted_row, tokenizer) > max_tokens:
        yield from _split_row_by_pairs(pairs, tokenizer, max_tokens)
        return

    chunk = formatted_row

    # 2. Attempt to add column header
    column_header = format_columns_header(header)
    candidate = column_header + ROW_JOIN + chunk

    if count_tokens(candidate, tokenizer) <= max_tokens:
        chunk = candidate

    # 3. Attempt to add sheet header
    if sheet_header:
        candidate = sheet_header + ROW_JOIN + chunk

        if count_tokens(candidate, tokenizer) <= max_tokens:
            chunk = candidate

    yield chunk


def parse_to_chunks(
    rows: Iterator[_ParsedRow],
    sheet_header: str,
    tokenizer: BaseTokenizer,
    max_tokens: int,
) -> Generator[str, None, None]:
    current_chunk = ""

    for row in rows:
        pairs: list[tuple[str, str]] = _row_to_pairs(row.header, row.row)
        formatted = format_row(row.header, row.row)

        if current_chunk:
            # Attempt to pack it in
            if can_pack(current_chunk, formatted, tokenizer, max_tokens):
                current_chunk = pack_chunk(current_chunk, formatted)
                continue
            else:
                # We need to start a new chunk
                yield current_chunk
                current_chunk = ""

        # Build chunk from scratch
        for chunk in build_chunk_from_scratch(
            header=row.header,
            pairs=pairs,
            sheet_header=sheet_header,
            tokenizer=tokenizer,
            max_tokens=max_tokens,
        ):
            if current_chunk:
                yield current_chunk
            current_chunk = chunk

    # Flush remaining
    if current_chunk:
        yield current_chunk


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
        if parsed_rows is None:
            logger.warning(
                f"TabularChunker: skipping unparseable section (link={section.link})"
            )
            return SectionChunkerOutput(
                payloads=payloads, accumulator=AccumulatorState()
            )

        sheet_header = section.link or ""
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
