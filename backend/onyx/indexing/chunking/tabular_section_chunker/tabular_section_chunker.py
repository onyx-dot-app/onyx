"""Chunking for spreadsheets and CSVs.

Every sheet of a workbook is chunked together, once, so the chunks can describe
the whole file and stay bounded in number. See `workbook_chunks.py` for what they hold.
"""

import io
from collections.abc import Iterator
from functools import partial

from onyx.configs.app_configs import (
    TABULAR_FULL_ROWS_MAX_CHUNKS,
    TABULAR_MAX_CHUNKS_PER_WORKBOOK,
    TABULAR_VALUE_CHUNKS_PER_SHEET,
)
from onyx.connectors.models import Section, TabularSection
from onyx.file_store.file_store import get_default_file_store
from onyx.indexing.chunking.section_chunker import (
    AccumulatorState,
    ChunkPayload,
    SectionChunker,
    SectionChunkerOutput,
)
from onyx.indexing.chunking.tabular_section_chunker.workbook_chunks import (
    SheetSource,
    build_workbook_chunks,
)
from onyx.natural_language_processing.utils import BaseTokenizer
from onyx.utils.csv_utils import csv_reader
from onyx.utils.logger import setup_logger

logger = setup_logger()

_HEADING_SHEET_SEPARATOR = " :: "


def _open_staged_csv_rows(csv_file_id: str) -> Iterator[list[str]]:
    file_store = get_default_file_store()
    with file_store.read_file(csv_file_id, use_tempfile=True) as raw:
        yield from csv_reader(io.TextIOWrapper(raw, encoding="utf-8", newline=""))


def _sheet_name(section: TabularSection) -> str:
    heading = section.heading or ""
    if _HEADING_SHEET_SEPARATOR in heading:
        return heading.split(_HEADING_SHEET_SEPARATOR, 1)[1]
    return heading


def _file_name(section: TabularSection) -> str:
    heading = section.heading or ""
    if _HEADING_SHEET_SEPARATOR in heading:
        return heading.split(_HEADING_SHEET_SEPARATOR, 1)[0]
    return section.link or heading or "Table"


class TabularChunker(SectionChunker):
    def __init__(self, tokenizer: BaseTokenizer) -> None:
        self.tokenizer = tokenizer

    def chunk_workbook(
        self,
        sections: list[TabularSection],
        accumulator: AccumulatorState,
        content_token_limit: int,
        file_name: str | None = None,
    ) -> SectionChunkerOutput:
        """Chunk every sheet of one workbook (or one CSV file) together."""
        payloads = accumulator.flush_to_list()
        if not sections:
            return SectionChunkerOutput(
                payloads=payloads, accumulator=AccumulatorState()
            )
        sheets = [
            SheetSource(
                name=_sheet_name(section),
                open_rows=partial(_open_staged_csv_rows, section.csv_file_id),
            )
            for section in sections
        ]
        resolved_name = file_name or _file_name(sections[0])
        chunk_texts = build_workbook_chunks(
            file_name=resolved_name,
            sheets=sheets,
            tokenizer=self.tokenizer,
            max_tokens=content_token_limit,
            full_rows_max_chunks=TABULAR_FULL_ROWS_MAX_CHUNKS,
            value_chunks_per_sheet=TABULAR_VALUE_CHUNKS_PER_SHEET,
            max_chunks=TABULAR_MAX_CHUNKS_PER_WORKBOOK,
        )
        if not chunk_texts:
            # DocumentChunker still emits an empty payload, so the document is
            # findable by title and metadata -- but none of its sheets are.
            logger.warning(
                "Tabular file %r (%s sheet(s)) produced no chunks; none of its "
                "contents will be searchable.",
                resolved_name,
                len(sections),
            )
        return self._build_output(chunk_texts, sections[0], payloads)

    def chunk_section(
        self,
        section: Section,
        accumulator: AccumulatorState,
        content_token_limit: int,
    ) -> SectionChunkerOutput:
        if not isinstance(section, TabularSection):
            raise ValueError(
                "TabularChunker received a non-tabular section: "
                f"{type(section).__name__}"
            )
        return self.chunk_workbook([section], accumulator, content_token_limit)

    def _build_output(
        self,
        chunk_texts: list[str],
        section: Section,
        payloads: list[ChunkPayload],
    ) -> SectionChunkerOutput:
        for i, text in enumerate(chunk_texts):
            payloads.append(
                ChunkPayload(
                    text=text,
                    links={0: section.link or ""},
                    is_continuation=(i > 0),
                )
            )
        return SectionChunkerOutput(payloads=payloads, accumulator=AccumulatorState())
