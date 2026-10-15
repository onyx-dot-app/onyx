"""Bounded chunks for spreadsheets and CSVs.

A workbook (or a CSV file) becomes these blocks:

- One overview block: the sheets, their size and columns, and the text of
  text-only sheets such as a "Readme".
- All rows of each small sheet (rows that fit in a few chunks).
- A profile of each large sheet: column roles, identifier ranges, totals,
  breakdowns by category and by month, frequent values and sample rows.
- A few chunks of frequent text values of each large sheet.

Large sheets that have the same columns share one profile. The blocks are
packed greedily, so small blocks share chunks, and the workbook never uses
more than ``max_chunks`` chunks. The full data stays in the file; the chunks
only have to make the file findable and describe what it contains.
"""

import math
from collections.abc import Iterable
from itertools import chain

from onyx.indexing.chunking.tabular_section_chunker.cell_values import (
    VALUE_SEPARATOR,
    clean_cell,
    column_label,
    detect_header_row,
    format_number,
    format_row,
    is_id_name,
    row_width,
    text_line,
)
from onyx.indexing.chunking.tabular_section_chunker.models import (
    CATEGORY_MAX_DISTINCT,
    Block,
    Breakdowns,
    ColumnRole,
    ColumnStats,
    DateOrder,
    SheetKind,
    SheetProfile,
    SheetSource,
)
from onyx.natural_language_processing.utils import (
    BaseTokenizer,
    count_tokens,
    split_text_by_tokens,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Rows examined for the header, from the first row wide enough to be one.
_HEADER_SCAN_ROWS = 20
# Narrow rows skipped to get past a title block. A sheet with nothing wider
# than one column in this many rows is text, not a table.
_MAX_PREAMBLE_ROWS = 200
# Rows examined before the profiler picks breakdown columns.
_PROBE_ROWS = 200
# Columns compared for redundancy. The check is quadratic, so a very wide
# sheet would otherwise spend longer deduplicating than chunking.
_MAX_REDUNDANCY_COLUMNS = 40
# Breakdown limits: category columns, numeric columns, emitted lines, months.
_MAX_BREAKDOWN_CATEGORY_COLUMNS = 3
_MAX_BREAKDOWN_NUMERIC_COLUMNS = 4
_MAX_BREAKDOWN_LINES = 6
_MAX_MONTHLY_NUMERIC_COLUMNS = 2
# Frequent values shown in a profile line, and sample rows in a profile.
_PROFILE_TEXT_VALUES = 12
_PROFILE_SAMPLE_ROWS = 2
_PROFILE_MAX_CHUNKS = 2
# Tokens of text-only sheets copied into the overview.
_OVERVIEW_ABOUT_TOKENS = 150
# The overview is the one place every sheet is named, so it gets more than one
# chunk and a many-sheet workbook does not lose its tail.
_OVERVIEW_MAX_CHUNKS = 3


# ---------------------------------------------------------------------------
# Cell and column-name helpers
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Streaming profile of one sheet
# ---------------------------------------------------------------------------


def _pick_breakdowns(columns: list[ColumnStats]) -> Breakdowns:
    categories: list[int] = []
    numerics: list[int] = []
    date_column: int | None = None
    date_order: DateOrder | None = None
    for idx, col in enumerate(columns):
        if col.non_empty == 0:
            continue
        # An unresolved order would file rows under the wrong month.
        if col.is_date and col.date_min is not None and date_column is None:
            date_column = idx
            date_order = col.date_order
        elif col.is_numeric and not is_id_name(col.name):
            if len(numerics) < _MAX_BREAKDOWN_NUMERIC_COLUMNS:
                numerics.append(idx)
        elif (
            not col.is_numeric
            and not col.is_date
            and 1 < col.distinct <= CATEGORY_MAX_DISTINCT // 2
            and col.contact_hits == 0
            and len(categories) < _MAX_BREAKDOWN_CATEGORY_COLUMNS
        ):
            categories.append(idx)
    return Breakdowns(
        category_columns=categories,
        numeric_columns=numerics,
        date_column=date_column,
        date_order=date_order,
    )


def _redundant_columns(columns: list[ColumnStats], probe: list[list[str]]) -> set[int]:
    text_columns = [
        idx for idx, col in enumerate(columns) if col.non_empty and not col.is_numeric
    ][:_MAX_REDUNDANCY_COLUMNS]
    redundant: set[int] = set()
    for idx in text_columns:
        for other in text_columns:
            if other == idx or other in redundant:
                continue
            both = 0
            contained = 0
            for row in probe:
                if idx >= len(row) or other >= len(row):
                    continue
                value = row[idx].strip().lower()
                container = row[other].strip().lower()
                if not value or not container:
                    continue
                both += 1
                if value in container:
                    contained += 1
            if both >= 10 and contained >= 0.8 * both:
                redundant.add(idx)
                break
    return redundant


class _TableProfiler:
    """Accumulates one table sheet, row by row."""

    def __init__(
        self,
        profile: SheetProfile,
        tokenizer: BaseTokenizer,
        full_rows_token_budget: int,
    ) -> None:
        self._profile = profile
        self._tokenizer = tokenizer
        self._full_rows_token_budget = full_rows_token_budget
        self._full_rows_tokens = 0
        self._row_names = (
            [""] * len(profile.header) if profile.synthetic_header else profile.header
        )
        self._header_key = [cell.strip().lower() for cell in profile.header]
        # Rows seen before the breakdown columns are picked; None afterwards.
        self._probe: list[list[str]] | None = []

    def consume(self, cells: list[str]) -> None:
        profile = self._profile
        if [
            c.strip().lower() for c in cells[: len(profile.header)]
        ] == self._header_key:
            return  # repeated header row
        profile.row_count += 1
        for idx, col in enumerate(profile.columns):
            value = cells[idx].strip() if idx < len(cells) else ""
            if value:
                col.observe(value)
        if len(profile.samples) < _PROFILE_SAMPLE_ROWS:
            profile.samples.append(cells)
        self._keep_full_row(cells)
        if self._probe is None:
            profile.breakdowns.add(cells)
            return
        self._probe.append(cells)
        if len(self._probe) >= _PROBE_ROWS:
            self._end_probe()

    def _keep_full_row(self, cells: list[str]) -> None:
        if self._profile.full_rows is None:
            return
        line = format_row(self._row_names, cells)
        self._full_rows_tokens += count_tokens(line, self._tokenizer) + 1
        if self._full_rows_tokens > self._full_rows_token_budget:
            self._profile.full_rows = None
        else:
            self._profile.full_rows.append(line)

    def _end_probe(self) -> None:
        if self._probe is None:
            return
        profile = self._profile
        profile.redundant_columns = _redundant_columns(profile.columns, self._probe)
        profile.breakdowns = _pick_breakdowns(profile.columns)
        for buffered in self._probe:
            profile.breakdowns.add(buffered)
        self._probe = None

    def finish(self) -> SheetProfile:
        self._end_probe()
        profile = self._profile
        unresolved = [col.name for col in profile.columns if col.dates_unresolved]
        if unresolved:
            logger.warning(
                "Sheet %r: columns %s hold dates like 5/3/2024 where no value "
                "settles whether the day or the month comes first. Rather than "
                "guess, they get no time range or monthly totals.",
                profile.names[0] if profile.names else "",
                ", ".join(unresolved),
            )
        return profile


def _text_profile(
    name: str,
    rows: Iterable[list[str]],
    tokenizer: BaseTokenizer,
    token_budget: int,
) -> SheetProfile:
    lines: list[str] = []
    used = 0
    for row in rows:
        line = text_line(row)
        cost = count_tokens(line, tokenizer) + 1
        if used + cost > token_budget:
            # Keep the start of an overlong cell rather than nothing at all.
            remaining = token_budget - used - 1
            if not lines and remaining > 0:
                pieces = split_text_by_tokens(line, tokenizer, remaining)
                if pieces and pieces[0]:
                    lines.append(pieces[0])
            break
        used += cost
        lines.append(line)
    return SheetProfile(names=[name], kind=SheetKind.TEXT, text_lines=lines)


def profile_sheet(
    name: str,
    rows: Iterable[list[str]],
    tokenizer: BaseTokenizer,
    full_rows_token_budget: int,
) -> SheetProfile:
    """One streaming pass over a sheet. Memory stays bounded: formatted rows
    are kept only while they fit ``full_rows_token_budget``."""
    row_iter = (row for row in rows if any(cell.strip() for cell in row))
    # Skip a narrow title block to reach the table, keeping it as preamble.
    title_rows: list[list[str]] = []
    head: list[list[str]] = []
    for row in row_iter:
        if not head and row_width(row) < 2 and len(title_rows) < _MAX_PREAMBLE_ROWS:
            title_rows.append(row)
            continue
        head.append(row)
        if len(head) >= _HEADER_SCAN_ROWS:
            break
    if not head:
        if not title_rows:
            return SheetProfile(names=[name], kind=SheetKind.EMPTY)
        return _text_profile(
            name, chain(title_rows, row_iter), tokenizer, full_rows_token_budget
        )

    header_idx = detect_header_row(head)
    widest = max(row_width(row) for row in head)
    if header_idx is None and widest <= 1:
        return _text_profile(
            name,
            chain(title_rows, head, row_iter),
            tokenizer,
            full_rows_token_budget,
        )

    if header_idx is None:
        logger.debug(
            "Sheet %r: no header row found in the first %s rows; columns are unnamed.",
            name,
            _HEADER_SCAN_ROWS,
        )
        header = [f"Column {idx + 1}" for idx in range(max(len(r) for r in head))]
        preamble = [text_line(r) for r in title_rows]
        data_head = head
    else:
        header = [cell.strip() for cell in head[header_idx]]
        preamble = [text_line(r) for r in chain(title_rows, head[:header_idx])]
        data_head = head[header_idx + 1 :]

    profiler = _TableProfiler(
        SheetProfile(
            names=[name],
            kind=SheetKind.TABLE,
            header=header,
            synthetic_header=header_idx is None,
            preamble=preamble,
            columns=[ColumnStats(col) for col in header],
        ),
        tokenizer=tokenizer,
        full_rows_token_budget=full_rows_token_budget,
    )
    for cells in chain(data_head, row_iter):
        profiler.consume(cells)
    return profiler.finish()


# ---------------------------------------------------------------------------
# Blocks and packing
# ---------------------------------------------------------------------------


class Packer:
    def __init__(
        self, tokenizer: BaseTokenizer, max_tokens: int, max_chunks: int
    ) -> None:
        self._tokenizer = tokenizer
        self._max_tokens = max_tokens
        self._max_chunks = max_chunks
        self.chunks: list[str] = []
        self._lines: list[str] = []
        self._tokens = 0
        self._buffered: list[str] = []
        self._dropped: list[str] = []

    def _count(self, line: str) -> int:
        return count_tokens(line, self._tokenizer)

    def _fit_line(self, line: str, budget: int) -> tuple[str, int]:
        tokens = self._count(line)
        budget = max(1, budget)
        if tokens <= budget:
            return line, tokens
        pieces = split_text_by_tokens(line, self._tokenizer, budget)
        trimmed = pieces[0] if pieces else ""
        return trimmed, self._count(trimmed)

    def _flush(self) -> None:
        if self._lines:
            if self.full:
                self._dropped.extend(self._buffered)
            else:
                self.chunks.append("\n".join(self._lines))
        self._lines = []
        self._buffered = []
        self._tokens = 0

    @property
    def full(self) -> bool:
        return len(self.chunks) >= self._max_chunks

    def add(self, block: Block) -> None:
        label = block.label or "(unnamed block)"
        if not block.lines:
            return
        if self.full:
            self._dropped.append(label)
            return
        fitted = [self._fit_line(line, self._max_tokens) for line in block.lines]
        block_tokens = sum(tokens for _, tokens in fitted) + len(fitted) - 1
        separator = 1 if self._lines else 0
        if self._tokens + separator + block_tokens <= self._max_tokens:
            self._lines.extend(line for line, _ in fitted)
            self._tokens += separator + block_tokens
            self._buffered.append(label)
            return
        self._flush()
        # The flush can have filled the budget, so check again before writing.
        if self.full:
            self._dropped.append(label)
            return
        if block_tokens <= self._max_tokens:
            self._lines = [line for line, _ in fitted]
            self._tokens = block_tokens
            self._buffered = [label]
            return

        # The head starts every chunk of this block, so it has to leave room
        # for a body; lines fitted one by one can together fill the budget.
        # When it cannot, stop repeating it rather than trimming it: the head
        # is the content of some blocks, the overview's sheet list above all.
        head = fitted[: block.repeat]
        head_tokens = sum(tokens for _, tokens in head) + len(head) - 1
        # Drop the trailing heading lines until what repeats leaves room for a
        # body. The first line names the sheet, so it is the last to go.
        while head and head_tokens > self._max_tokens // 2:
            head = head[:-1]
            head_tokens = sum(tokens for _, tokens in head) + len(head) - 1
        body_start = len(head)
        body_budget = self._max_tokens - head_tokens - 1
        used = 0
        piece = [line for line, _ in head]
        piece_tokens = head_tokens
        for line, _ in fitted[body_start:]:
            line, tokens = self._fit_line(line, body_budget)
            if piece_tokens + 1 + tokens > self._max_tokens:
                if self.full:
                    self._dropped.append(label)
                    return
                self.chunks.append("\n".join(piece))
                used += 1
                if used >= block.max_chunks:
                    self._dropped.append(label)
                    return
                piece = [entry for entry, _ in head]
                piece_tokens = head_tokens
            piece.append(line)
            piece_tokens += 1 + tokens
        self._lines = piece
        self._tokens = piece_tokens
        self._buffered = [label]

    def finish(self) -> list[str]:
        self._flush()
        if self._dropped:
            logger.warning(
                "Chunk budget of %s reached; these were dropped or cut short: "
                "%s. Raise TABULAR_MAX_CHUNKS_PER_WORKBOOK to keep them.",
                self._max_chunks,
                ", ".join(dict.fromkeys(self._dropped)),
            )
        return self.chunks


def _join_limited(
    items: list[str], tokenizer: BaseTokenizer, budget: int
) -> tuple[str, int]:
    """Join items with the value separator until ``budget`` tokens are used.
    Returns the text and the number of items it holds."""
    separator_tokens = count_tokens(VALUE_SEPARATOR, tokenizer)
    text = ""
    used = 0
    tokens = 0
    for item in items:
        item_tokens = count_tokens(item, tokenizer) + (separator_tokens if used else 0)
        if tokens + item_tokens > budget and used > 0:
            break
        text = f"{text}{VALUE_SEPARATOR}{item}" if text else item
        tokens += item_tokens
        used += 1
    return text, used


def _sheet_title(file_name: str, profile: SheetProfile) -> str:
    names = [n for n in profile.names if n]
    if not names:
        return file_name
    if len(names) == 1:
        return f"{file_name} :: {names[0]}"
    return f"{file_name} :: sheets {', '.join(names)} (same columns)"


def _columns_line(profile: SheetProfile) -> str:
    if profile.synthetic_header:
        return f"Columns: {len(profile.header)} unnamed columns"
    labels = [column_label(name) for name in profile.header if name.strip()]
    return "Columns: " + ", ".join(labels)


def about_lines(profiles: list[SheetProfile], tokenizer: BaseTokenizer) -> list[str]:
    """The text the overview has room to carry. A table's title block competes
    with a Readme for this space, so the caller checks what survived before
    deciding a text sheet needs no block of its own."""
    about: list[str] = []
    for profile in profiles:
        about.extend(line for line in profile.text_lines + profile.preamble if line)
    kept: list[str] = []
    used = 0
    for line in about:
        used += count_tokens(line, tokenizer) + 1
        if used > _OVERVIEW_ABOUT_TOKENS and kept:
            break
        kept.append(line)
    return kept


def _overview_block(
    file_name: str,
    profiles: list[SheetProfile],
    tokenizer: BaseTokenizer,
) -> Block:
    sheet_names = [name for p in profiles for name in p.names if name]
    if sheet_names:
        lines = [
            f"Spreadsheet {file_name}: {len(sheet_names)} sheet"
            f"{'s' if len(sheet_names) != 1 else ''} ({', '.join(sheet_names)})"
        ]
    else:
        lines = [f"Spreadsheet {file_name}"]
    kept = about_lines(profiles, tokenizer)
    if kept:
        lines.append("About: " + " ".join(kept))
    for profile in profiles:
        if profile.kind != SheetKind.TABLE:
            continue
        label = ", ".join(profile.names) if any(profile.names) else "Data"
        lines.append(
            f"Sheet {label}: {profile.row_count} rows; " + _columns_line(profile)
        )
    return Block(lines=lines, repeat=1, max_chunks=_OVERVIEW_MAX_CHUNKS)


def _full_rows_block(
    file_name: str,
    profile: SheetProfile,
    tokenizer: BaseTokenizer,
    max_tokens: int,
    max_chunks: int,
) -> Block | None:
    if not profile.full_rows:
        return None
    repeat = 2
    lines = [
        f"{_sheet_title(file_name, profile)} (all {profile.row_count} rows)",
        _columns_line(profile),
        *profile.full_rows,
    ]
    # The first `repeat` lines start every chunk, so the rows have less room
    # than the budget that made this sheet "small". Ask for the chunks they
    # need, or the heading's "all N rows" is a lie.
    header_tokens = sum(count_tokens(line, tokenizer) + 1 for line in lines[:repeat])
    row_tokens = sum(count_tokens(line, tokenizer) + 1 for line in lines[repeat:])
    per_chunk = max(1, max_tokens - header_tokens)
    needed = math.ceil(row_tokens / per_chunk)
    return Block(lines=lines, repeat=repeat, max_chunks=max(max_chunks, needed))


def _profile_block(
    file_name: str,
    profile: SheetProfile,
    tokenizer: BaseTokenizer,
    line_budget: int,
) -> Block:
    header = profile.header
    roles = [col.role() for col in profile.columns]
    lines = [
        f"{_sheet_title(file_name, profile)}: {profile.row_count} rows x "
        f"{sum(1 for h in header if h.strip())} columns (summary; not every row is shown)",
        _columns_line(profile),
    ]

    dated = [
        (col.name, col.date_min, col.date_max)
        for col, role in zip(profile.columns, roles, strict=True)
        if role == ColumnRole.DATE and col.date_min and col.date_max
    ]
    if dated:
        lines.append(
            "Time range: "
            + VALUE_SEPARATOR.join(f"{name} {lo} to {hi}" for name, lo, hi in dated)
        )

    identifiers = [
        f"{column_label(col.name)} {_value_range(col)} "
        f"({col.distinct}{'+' if not col.counts_complete else ''} distinct)"
        for col, role in zip(profile.columns, roles, strict=True)
        if role == ColumnRole.IDENTIFIER
    ]
    if identifiers:
        lines.append("Identifiers: " + VALUE_SEPARATOR.join(identifiers))

    for col, role in zip(profile.columns, roles, strict=True):
        if role != ColumnRole.CATEGORY:
            continue
        ranked = col.counts.most_common()
        if ranked and ranked[0][1] > 1:
            items = [f"{clean_cell(value)} ({count})" for value, count in ranked]
            label = f"{column_label(col.name)} values (count)"
        else:
            items = [clean_cell(value) for value, _ in ranked]
            label = f"{column_label(col.name)} values"
        text, _ = _join_limited(items, tokenizer, line_budget)
        lines.append(f"{label}: {text}")

    numeric = [
        (col, role)
        for col, role in zip(profile.columns, roles, strict=True)
        if role == ColumnRole.NUMERIC
    ]
    if numeric:
        lines.append("Totals across all rows:")
        for col, _ in numeric:
            average = col.total / col.non_empty if col.non_empty else 0.0
            unit = col.unit or ""
            figures = (
                [f"total {format_number(col.total)}{unit}"] if col.summable else []
            )
            figures += [
                f"average {format_number(average)}{unit}",
                f"min {format_number(col.minimum or 0.0)}{unit}",
                f"max {format_number(col.maximum or 0.0)}{unit}",
                f"count {col.non_empty}",
            ]
            lines.append(f"{column_label(col.name)}: " + "; ".join(figures))

    lines.extend(_breakdown_lines(profile, roles, tokenizer, line_budget))

    for idx, (col, role) in enumerate(zip(profile.columns, roles, strict=True)):
        if role != ColumnRole.TEXT or idx in profile.redundant_columns:
            continue
        values = [
            clean_cell(value)
            for value, _ in col.counts.most_common(_PROFILE_TEXT_VALUES)
        ]
        text, _ = _join_limited(values, tokenizer, line_budget)
        lines.append(
            f"{column_label(col.name)} ({col.distinct}"
            f"{'+' if not col.counts_complete else ''} distinct; most common first): {text}"
        )

    if profile.samples:
        names = [""] * len(header) if profile.synthetic_header else header
        lines.extend(f"Sample row: {format_row(names, row)}" for row in profile.samples)
    return Block(lines=lines, repeat=1, max_chunks=_PROFILE_MAX_CHUNKS)


def _value_range(col: ColumnStats) -> str:
    if col.is_numeric and col.minimum is not None and col.maximum is not None:
        return f"{format_number(col.minimum)} ... {format_number(col.maximum)}"
    if col.id_min is not None and col.id_max is not None:
        return f"{col.id_min} ... {col.id_max}"
    return f"{col.text_min} ... {col.text_max}"


def _shown_suffix(used: int, total: int, complete: bool, noun: str) -> str:
    """Say so when a line holds only part of the list. A clipped breakdown that
    looks complete is worse than a short one that admits it."""
    if used >= total and complete:
        return ""
    return f" ({used} of {total}{'' if complete else '+'} {noun} shown)"


def _breakdown_lines(
    profile: SheetProfile,
    roles: list[ColumnRole],
    tokenizer: BaseTokenizer,
    line_budget: int,
) -> list[str]:
    breakdowns = profile.breakdowns
    numeric_columns = [
        (pos, col)
        for pos, col in enumerate(breakdowns.numeric_columns)
        if col < len(roles) and roles[col] == ColumnRole.NUMERIC
    ]
    lines: list[str] = []
    for category_col in breakdowns.category_columns:
        if category_col >= len(roles) or roles[category_col] != ColumnRole.CATEGORY:
            continue
        groups = breakdowns.by_category.get(category_col, {})
        if len(groups) < 2:
            continue
        category_name = profile.header[category_col]
        for pos, numeric_col in numeric_columns:
            if len(lines) >= _MAX_BREAKDOWN_LINES:
                return lines
            stats = profile.columns[numeric_col]
            unit = stats.unit or ""
            summable = stats.summable
            ranked = sorted(
                groups.items(),
                key=lambda kv: kv[1].sums[pos] if summable else kv[1].average(pos),
                reverse=True,
            )
            if summable:
                items = [
                    f"{key} {format_number(sums.sums[pos])}{unit} "
                    f"(avg {format_number(sums.average(pos))}{unit})"
                    for key, sums in ranked
                ]
                measure = "Total"
            else:
                items = [
                    f"{key} {format_number(sums.average(pos))}{unit}"
                    for key, sums in ranked
                ]
                measure = "Average"
            text, used = _join_limited(items, tokenizer, line_budget)
            lines.append(
                f"{measure} {profile.header[numeric_col]} by {category_name} "
                f"(highest first): {text}"
                f"{_shown_suffix(used, len(items), True, 'values')}"
            )
    date_column = breakdowns.date_column
    date_settled = (
        date_column is not None
        and date_column < len(roles)
        and roles[date_column] == ColumnRole.DATE
        and profile.columns[date_column].date_order == breakdowns.date_order
    )
    if date_settled and len(breakdowns.by_month) >= 2:
        months = sorted(breakdowns.by_month.items())
        for pos, numeric_col in numeric_columns[:_MAX_MONTHLY_NUMERIC_COLUMNS]:
            stats = profile.columns[numeric_col]
            unit = stats.unit or ""
            summable = stats.summable
            items = [
                f"{month} "
                f"{format_number(sums.sums[pos] if summable else sums.average(pos))}"
                f"{unit}"
                for month, sums in months
            ]
            text, used = _join_limited(items, tokenizer, line_budget)
            measure = "Total" if summable else "Average"
            lines.append(
                f"{measure} {profile.header[numeric_col]} by month: {text}"
                f"{_shown_suffix(used, len(items), breakdowns.months_complete, 'months')}"
            )
    return lines


def _value_blocks(
    file_name: str,
    profile: SheetProfile,
    tokenizer: BaseTokenizer,
    max_tokens: int,
    max_chunks: int,
) -> list[Block]:
    """Round-robin the frequent values of the free-text columns that the
    profile could only sample, so each chunk covers every such column."""
    columns = [
        col
        for idx, col in enumerate(profile.columns)
        if col.role() == ColumnRole.TEXT and idx not in profile.redundant_columns
    ]
    if not columns or max_chunks <= 0:
        return []
    queues = [
        [clean_cell(value) for value, _ in col.counts.most_common()][
            _PROFILE_TEXT_VALUES:
        ]
        for col in columns
    ]
    heading = f"{_sheet_title(file_name, profile)}: more values"
    # Each column line also costs a newline.
    share = max(
        1,
        (max_tokens - count_tokens(heading, tokenizer) - len(columns)) // len(columns),
    )
    blocks: list[Block] = []
    for _ in range(max_chunks):
        lines = [heading]
        for col, queue in zip(columns, queues, strict=True):
            if not queue:
                continue
            label = column_label(col.name)
            budget = share - count_tokens(f"{label}: ", tokenizer)
            text, used = _join_limited(queue, tokenizer, budget)
            if used == 0:
                continue
            del queue[:used]
            lines.append(f"{label}: {text}")
        if len(lines) == 1:
            break
        blocks.append(Block(lines=lines, repeat=1, max_chunks=1))
    return blocks


def _can_merge(into: SheetProfile, other: SheetProfile) -> bool:
    """Whether merging keeps the breakdowns both sides already have.

    Merging two tabs pools their values, which can push a category column past
    ``CATEGORY_MAX_DISTINCT`` and silently cost the merged profile a breakdown
    that each tab had on its own. Better two profiles than one that says less.
    """
    mine, theirs = into.breakdowns, other.breakdowns
    if (
        mine.category_columns != theirs.category_columns
        or mine.numeric_columns != theirs.numeric_columns
        or mine.date_column != theirs.date_column
        or mine.date_order != theirs.date_order
    ):
        return False
    for idx in mine.category_columns:
        if idx >= len(into.columns) or idx >= len(other.columns):
            return False
        pooled = set(into.columns[idx].counts) | set(other.columns[idx].counts)
        if len(pooled) > CATEGORY_MAX_DISTINCT:
            return False
    # Dollars on one tab and euros on the other do not add up to a total.
    for mine_col, other_col in zip(into.columns, other.columns, strict=False):
        if mine_col.unit and other_col.unit and mine_col.unit != other_col.unit:
            return False
    return True


def _group_same_header(profiles: list[SheetProfile]) -> list[SheetProfile]:
    """Merge large sheets that have the same columns (monthly tabs, for
    example) into one profile, when merging does not cost information."""
    merged: list[SheetProfile] = []
    by_header: dict[tuple[str, ...], SheetProfile] = {}
    for profile in profiles:
        if profile.kind != SheetKind.TABLE or profile.is_small:
            merged.append(profile)
            continue
        key = tuple(name.strip().lower() for name in profile.header)
        target = by_header.get(key)
        if target is not None and _can_merge(target, profile):
            target.merge(profile)
            continue
        if target is not None:
            logger.debug(
                "Sheets %s and %s share columns but are profiled separately: "
                "merging them would drop a breakdown.",
                target.names,
                profile.names,
            )
        by_header.setdefault(key, profile)
        merged.append(profile)
    return merged


def build_workbook_chunks(
    file_name: str,
    sheets: list[SheetSource],
    tokenizer: BaseTokenizer,
    max_tokens: int,
    full_rows_max_chunks: int,
    value_chunks_per_sheet: int,
    max_chunks: int,
) -> list[str]:
    profiles = [
        profile_sheet(
            name=sheet.name,
            rows=sheet.open_rows(),
            tokenizer=tokenizer,
            full_rows_token_budget=full_rows_max_chunks * max_tokens,
        )
        for sheet in sheets
    ]
    profiles = _group_same_header([p for p in profiles if p.kind != SheetKind.EMPTY])
    if not profiles:
        return []

    line_budget = max(1, max_tokens // 2)
    blocks: list[Block] = [_overview_block(file_name, profiles, tokenizer)]
    in_overview = set(about_lines(profiles, tokenizer))
    # One block per sheet first, so running out of chunks costs every sheet its
    # extras rather than costing the last sheets everything.
    for profile in profiles:
        label = _sheet_title(file_name, profile)
        if profile.kind == SheetKind.TEXT:
            # Only skip the block when every line of this sheet reached the
            # overview; otherwise its text appears nowhere.
            if any(line not in in_overview for line in profile.text_lines):
                blocks.append(
                    Block(
                        lines=[_sheet_title(file_name, profile), *profile.text_lines],
                        repeat=1,
                        max_chunks=full_rows_max_chunks,
                    )
                )
        elif profile.is_small:
            block = _full_rows_block(
                file_name, profile, tokenizer, max_tokens, full_rows_max_chunks
            )
            if block is not None:
                blocks.append(block)
        else:
            blocks.append(_profile_block(file_name, profile, tokenizer, line_budget))
        if blocks and not blocks[-1].label:
            blocks[-1].label = label
    for profile in profiles:
        if profile.kind == SheetKind.TABLE and not profile.is_small:
            blocks.extend(
                _value_blocks(
                    file_name, profile, tokenizer, max_tokens, value_chunks_per_sheet
                )
            )

    packer = Packer(tokenizer=tokenizer, max_tokens=max_tokens, max_chunks=max_chunks)
    for block in blocks:
        packer.add(block)
    return packer.finish()
