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

import calendar
import math
import re
import unicodedata
from collections import Counter
from collections.abc import Callable, Iterable, Iterator
from datetime import date
from enum import Enum
from itertools import chain

from pydantic import BaseModel, ConfigDict, Field

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
# A text column with at most this many distinct values is a category.
_CATEGORY_MAX_DISTINCT = 50
# Distinct values tracked per column; later ones are not counted, which keeps
# memory flat on very large sheets.
_MAX_TRACKED_VALUES = 20_000
# Columns compared for redundancy. The check is quadratic, so a very wide
# sheet would otherwise spend longer deduplicating than chunking.
_MAX_REDUNDANCY_COLUMNS = 40
# Breakdown limits: category columns, numeric columns, emitted lines, months.
_MAX_BREAKDOWN_CATEGORY_COLUMNS = 3
_MAX_BREAKDOWN_NUMERIC_COLUMNS = 4
_MAX_BREAKDOWN_LINES = 6
_MAX_MONTHLY_NUMERIC_COLUMNS = 2
_MAX_TRACKED_MONTHS = 1200
# Frequent values shown in a profile line, and sample rows in a profile.
_PROFILE_TEXT_VALUES = 12
_PROFILE_SAMPLE_ROWS = 2
_PROFILE_MAX_CHUNKS = 2
# Tokens of text-only sheets copied into the overview.
_OVERVIEW_ABOUT_TOKENS = 150
# The overview is the one place every sheet is named, so it gets more than one
# chunk and a many-sheet workbook does not lose its tail.
_OVERVIEW_MAX_CHUNKS = 3
_VALUE_SEPARATOR = "; "

_ISO_DATE_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?)?$"
)
# ``5/3/2024`` is 5 March to most of the world and May 3 in the US, and the
# separator does not settle it. Neither order is assumed: a column is read only
# once one of its values rules an order out, since a part above 12 cannot be a
# month. A column that never settles is left as text and logged.
_YMD_SLASH_RE = re.compile(r"^(\d{4})/(\d{1,2})/(\d{1,2})$")
_NUMERIC_DMY_RE = re.compile(r"^(\d{1,2})([/.])(\d{1,2})\2(\d{4})$")
_DAY_MONTH_YEAR_RE = re.compile(r"^(\d{1,2})[ -]([A-Za-z]{3,9})\.?,?[ -](\d{4})$")
_MONTH_DAY_YEAR_RE = re.compile(r"^([A-Za-z]{3,9})\.?[ -](\d{1,2}),?[ -](\d{4})$")
_LONG_DECIMAL_RE = re.compile(r"^-?\d+\.\d{7,}$")
_ID_VALUE_RE = re.compile(r"^[A-Za-z]{1,10}[-_ #]?\d+[A-Za-z]?$")
_YEAR_RE = re.compile(r"^(?:19|20|21)\d{2}$")
_WORD_RE = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")
_NAME_SPLIT_RE = re.compile(r"[\s_\-./]+")
_DIGITS_RE = re.compile(r"(\d+)")
# Column names that read as an identifier rather than a value.
_ID_NAME_TOKENS = ("id", "uuid", "uid", "guid", "key")


class DateOrder(str, Enum):
    """Which part of ``5/3/2024`` is the day. Inferred per column, never
    assumed from a locale."""

    DAY_FIRST = "day_first"
    MONTH_FIRST = "month_first"


class ColumnRole(str, Enum):
    IDENTIFIER = "identifier"
    DATE = "date"
    NUMERIC = "numeric"
    CATEGORY = "category"
    TEXT = "text"
    CONTACT = "contact"
    EMPTY = "empty"


class SheetSource(BaseModel):
    """One sheet (or CSV file). ``open_rows`` yields the raw CSV rows."""

    model_config = ConfigDict(frozen=True)

    name: str
    open_rows: Callable[[], Iterator[list[str]]]


# ---------------------------------------------------------------------------
# Cell and column-name helpers
# ---------------------------------------------------------------------------


def _is_number(value: str) -> bool:
    return _parse_number(value) is not None


def _parse_number(value: str) -> float | None:
    text = value.strip().replace(",", "").removesuffix("%").strip()
    if not text:
        return None
    # A negative currency amount signs the whole thing: -$5, not $-5.
    sign = ""
    if text[0] in ("+", "-"):
        sign, text = text[0], text[1:].lstrip()
    if text and _is_currency_symbol(text[0]):
        text = text[1:].lstrip()
    elif text and _is_currency_symbol(text[-1]):
        text = text[:-1].rstrip()
    if not text:
        return None
    text = sign + text
    try:
        number = float(text)
    except ValueError:
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def is_id_name(name: str) -> bool:
    """Whether a column name reads like an identifier (``id``, ``order_uuid``)."""
    lowered = name.lower().strip().replace("-", "_")
    return lowered in _ID_NAME_TOKENS or any(
        lowered.endswith(f"_{token}") for token in _ID_NAME_TOKENS
    )


def _is_currency_symbol(char: str) -> bool:
    """Unicode classifies currency symbols, so there is no list to maintain."""
    return unicodedata.category(char) == "Sc"


def _unit_marker(value: str) -> str:
    """The unit a number carries, so totals keep it and percentages are never
    summed. Empty when the number is bare."""
    text = value.strip()
    if not text:
        return ""
    if text.endswith("%"):
        return "%"
    if text[0] in ("+", "-"):
        text = text[1:].lstrip()
    if not text:
        return ""
    if _is_currency_symbol(text[0]):
        return text[0]
    if _is_currency_symbol(text[-1]):
        return text[-1]
    return ""


def _natural_key(value: str) -> tuple[tuple[int, int, str], ...]:
    """Sort key that orders "Project 2" before "Project 10"."""
    return tuple(
        (1, int(part), "") if part.isdigit() else (0, 0, part)
        for part in _DIGITS_RE.split(value)
        if part
    )


def _is_iso_date(value: str) -> bool:
    return bool(_ISO_DATE_RE.match(value.strip()))


def _month_number(name: str) -> int | None:
    """The month a written name denotes. Any prefix of three letters or more
    works, so Jan, Sept and September all resolve without a table of
    spellings; three letters already tell the twelve apart."""
    text = name.lower().rstrip(".")
    if len(text) < 3:
        return None
    for number in range(1, 13):
        if calendar.month_name[number].lower().startswith(text):
            return number
    return None


def _ymd(year: int, month: int, day: int) -> str | None:
    """Format a real calendar day, or None. ``date`` rejects 31 February and
    the like, which a range check would let through."""
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def date_key(value: str, order: DateOrder | None = None) -> str | None:
    """The day a cell names, as ``YYYY-MM-DD``, or None.

    ``order`` settles a bare ``5/3/2024``. Without it such a cell returns None
    rather than pick a reading; a value with a part above 12 settles itself and
    ignores ``order``.
    """
    text = value.strip()
    if _ISO_DATE_RE.match(text):
        return _ymd(int(text[:4]), int(text[5:7]), int(text[8:10]))

    match = _YMD_SLASH_RE.match(text)
    if match:
        return _ymd(int(match[1]), int(match[2]), int(match[3]))

    match = _NUMERIC_DMY_RE.match(text)
    if match:
        first, second, year = int(match[1]), int(match[3]), int(match[4])
        if first > 12:  # cannot be a month, so it is the day
            return _ymd(year, second, first)
        if second > 12:
            return _ymd(year, first, second)
        if order is DateOrder.DAY_FIRST:
            return _ymd(year, second, first)
        if order is DateOrder.MONTH_FIRST:
            return _ymd(year, first, second)
        return None

    match = _DAY_MONTH_YEAR_RE.match(text)
    if match:
        month = _month_number(match[2])
        return _ymd(int(match[3]), month, int(match[1])) if month else None

    match = _MONTH_DAY_YEAR_RE.match(text)
    if match:
        month = _month_number(match[1])
        return _ymd(int(match[3]), month, int(match[2])) if month else None

    return None


def date_order_evidence(value: str) -> DateOrder | None:
    """The order a single value proves, when one of its parts is above 12."""
    match = _NUMERIC_DMY_RE.match(value.strip())
    if not match:
        return None
    first, second = int(match[1]), int(match[3])
    if first > 12 and second <= 12:
        return DateOrder.DAY_FIRST
    if second > 12 and first <= 12:
        return DateOrder.MONTH_FIRST
    return None


def format_number(number: float) -> str:
    if abs(number) < 1e15 and number == int(number):
        return str(int(number))
    if abs(number) >= 1000:
        return f"{number:.2f}"
    return f"{number:.4g}"


def clean_cell(value: str) -> str:
    """Shorten cell text without losing meaning: midnight timestamps become
    dates and long decimals are rounded."""
    text = value.strip()
    if (
        _is_iso_date(text)
        and len(text) > 10
        and text[10:].strip("T ")
        in (
            "00:00:00",
            "00:00",
        )
    ):
        return text[:10]
    if _LONG_DECIMAL_RE.match(text):
        return format_number(float(text))
    return text


def _split_name_words(name: str) -> list[str]:
    words: list[str] = []
    for part in _NAME_SPLIT_RE.split(name):
        pending = ""
        for piece in _WORD_RE.findall(part):
            # Glue a lone capital to the next piece, so "MWh" stays whole.
            if len(piece) == 1 and piece.isupper():
                pending += piece
                continue
            words.append(pending + piece)
            pending = ""
        if pending:
            words.append(pending)
    return words


def column_label(name: str) -> str:
    """The column name, plus a readable alias when the name is compressed
    (``AcqPriceUSD`` -> ``AcqPriceUSD (acquisition Price USD)``)."""
    stripped = name.strip()
    if not stripped:
        return ""
    if any(ch.isspace() for ch in stripped):
        return stripped
    words = _split_name_words(stripped)
    alias = " ".join(words)
    if not alias or alias == stripped:
        return stripped
    return f"{stripped} ({alias})"


def _cell_shape(value: str) -> str:
    """A cell's pattern, digit for digit. Keeping the digit count apart tells
    a year heading (``2023``) from the figures under it (``100``), while
    ``PAY-001`` and ``PAY-002`` still share a shape."""
    shape = re.sub(r"\d", "9", value.strip())
    return re.sub(r"[A-Za-z]+", "a", shape)


def detect_header_row(rows: list[list[str]]) -> int | None:
    """Index of the header row among the first rows of a sheet, or None when
    the sheet has no header (one column of text, or data from the first row).
    """
    widths = [_row_width(row) for row in rows]
    max_width = max(widths, default=0)
    if max_width <= 1:
        return None
    min_width = max(2, math.ceil(max_width * 0.5))
    for idx, row in enumerate(rows):
        filled = [cell.strip() for cell in row if cell.strip()]
        if len(filled) < min_width:
            continue
        labels = [c for c in filled if _looks_like_a_label(c)]
        if len(labels) < 0.6 * len(filled):
            continue
        if len(set(filled)) < 0.6 * len(filled):
            continue
        if idx + 1 < len(rows) and _looks_like_data_pair(row, rows[idx + 1]):
            continue
        if idx > 0 and _looks_like_data_pair(rows[idx - 1], row):
            continue
        return idx
    return None


def _looks_like_a_label(value: str) -> bool:
    """Whether a cell reads as a column name. Years count: ``Region,2023,2024``
    is a header, and rejecting it feeds the real names into the data."""
    text = value.strip()
    if _YEAR_RE.match(text):
        return True
    return not _is_number(text) and date_key(text) is None


def _looks_like_data_pair(row: list[str], next_row: list[str]) -> bool:
    """True when the row has the same shape as the next row in the columns
    that hold digits (for example ``PAY-001`` above ``PAY-002``)."""
    compared = 0
    same = 0
    for cell, below in zip(row, next_row, strict=False):
        if not cell.strip() or not below.strip():
            continue
        if not any(ch.isdigit() for ch in cell + below):
            continue
        compared += 1
        if _cell_shape(cell) == _cell_shape(below):
            same += 1
    return compared > 0 and same * 2 >= compared


def _row_width(row: list[str]) -> int:
    return sum(1 for cell in row if cell.strip())


def _non_empty_rows(rows: Iterable[list[str]]) -> Iterator[list[str]]:
    for row in rows:
        if any(cell.strip() for cell in row):
            yield row


def format_row(header: list[str], row: list[str]) -> str:
    """``name=value`` pairs; cells without a column name keep only the value."""
    parts: list[str] = []
    for idx, raw in enumerate(row):
        value = clean_cell(raw)
        if not value:
            continue
        name = header[idx].strip() if idx < len(header) else ""
        parts.append(f"{name}={value}" if name else value)
    return ", ".join(parts)


def _text_line(row: list[str]) -> str:
    return " | ".join(clean_cell(cell) for cell in row if cell.strip())


# ---------------------------------------------------------------------------
# Streaming profile of one sheet
# ---------------------------------------------------------------------------


class _ColumnStats:
    __slots__ = (
        "name",
        "non_empty",
        "is_numeric",
        "unit",
        "units_mixed",
        "total",
        "minimum",
        "maximum",
        "is_date",
        # Both readings run side by side until a value settles the order.
        "date_min_day_first",
        "date_max_day_first",
        "date_min_month_first",
        "date_max_month_first",
        "has_ambiguous_dates",
        "day_first_hits",
        "month_first_hits",
        "counts",
        "counts_complete",
        "id_hits",
        "contact_hits",
        "text_min",
        "text_max",
        "id_min",
        "id_max",
    )

    def __init__(self, name: str) -> None:
        self.name = name
        self.non_empty = 0
        self.is_numeric = True
        # "%", "$" or "" once seen; None until the first number.
        self.unit: str | None = None
        self.units_mixed = False
        self.total = 0.0
        self.minimum: float | None = None
        self.maximum: float | None = None
        self.is_date = True
        self.date_min_day_first: str | None = None
        self.date_max_day_first: str | None = None
        self.date_min_month_first: str | None = None
        self.date_max_month_first: str | None = None
        self.has_ambiguous_dates = False
        self.day_first_hits = 0
        self.month_first_hits = 0
        self.counts: Counter[str] = Counter()
        self.counts_complete = True
        self.id_hits = 0
        self.contact_hits = 0
        self.text_min: str | None = None
        self.text_max: str | None = None
        self.id_min: str | None = None
        self.id_max: str | None = None

    def observe(self, value: str) -> None:
        self.non_empty += 1
        if self.is_numeric:
            number = _parse_number(value)
            if number is None:
                self.is_numeric = False
            else:
                marker = _unit_marker(value)
                if self.unit is None:
                    self.unit = marker
                elif self.unit != marker:
                    self.unit = ""
                    self.units_mixed = True
                self.total += number
                self.minimum = (
                    number if self.minimum is None else min(self.minimum, number)
                )
                self.maximum = (
                    number if self.maximum is None else max(self.maximum, number)
                )
        if self.is_date:
            day_first = date_key(value, DateOrder.DAY_FIRST)
            month_first = date_key(value, DateOrder.MONTH_FIRST)
            if day_first is None or month_first is None:
                self.is_date = False
            else:
                self.date_min_day_first = _min_opt(self.date_min_day_first, day_first)
                self.date_max_day_first = _max_opt(self.date_max_day_first, day_first)
                self.date_min_month_first = _min_opt(
                    self.date_min_month_first, month_first
                )
                self.date_max_month_first = _max_opt(
                    self.date_max_month_first, month_first
                )
                if day_first != month_first:
                    self.has_ambiguous_dates = True
                evidence = date_order_evidence(value)
                if evidence is DateOrder.DAY_FIRST:
                    self.day_first_hits += 1
                elif evidence is DateOrder.MONTH_FIRST:
                    self.month_first_hits += 1
        if value in self.counts or len(self.counts) < _MAX_TRACKED_VALUES:
            self.counts[value] += 1
        else:
            self.counts_complete = False
        if _ID_VALUE_RE.match(value):
            self.id_hits += 1
            if self.id_min is None or _natural_key(value) < _natural_key(self.id_min):
                self.id_min = value
            if self.id_max is None or _natural_key(value) > _natural_key(self.id_max):
                self.id_max = value
        if "@" in value or "://" in value:
            self.contact_hits += 1
        self.text_min = value if self.text_min is None else min(self.text_min, value)
        self.text_max = value if self.text_max is None else max(self.text_max, value)

    def merge(self, other: "_ColumnStats") -> None:
        if other.non_empty == 0:
            return
        self.non_empty += other.non_empty
        self.is_numeric = self.is_numeric and other.is_numeric
        self.units_mixed = self.units_mixed or other.units_mixed
        if self.unit is None:
            self.unit = other.unit
        elif other.unit is not None and other.unit != self.unit:
            self.unit = ""
            self.units_mixed = True
        self.total += other.total
        self.minimum = _min_opt(self.minimum, other.minimum)
        self.maximum = _max_opt(self.maximum, other.maximum)
        self.is_date = self.is_date and other.is_date
        self.has_ambiguous_dates = self.has_ambiguous_dates or other.has_ambiguous_dates
        self.day_first_hits += other.day_first_hits
        self.month_first_hits += other.month_first_hits
        self.date_min_day_first = _min_opt(
            self.date_min_day_first, other.date_min_day_first
        )
        self.date_max_day_first = _max_opt(
            self.date_max_day_first, other.date_max_day_first
        )
        self.date_min_month_first = _min_opt(
            self.date_min_month_first, other.date_min_month_first
        )
        self.date_max_month_first = _max_opt(
            self.date_max_month_first, other.date_max_month_first
        )
        self.counts.update(other.counts)
        self.counts_complete = self.counts_complete and other.counts_complete
        self.id_hits += other.id_hits
        self.contact_hits += other.contact_hits
        self.text_min = _min_opt(self.text_min, other.text_min)
        self.text_max = _max_opt(self.text_max, other.text_max)
        for candidate in (other.id_min, other.id_max):
            if candidate is None:
                continue
            if self.id_min is None or _natural_key(candidate) < _natural_key(
                self.id_min
            ):
                self.id_min = candidate
            if self.id_max is None or _natural_key(candidate) > _natural_key(
                self.id_max
            ):
                self.id_max = candidate

    @property
    def is_percent(self) -> bool:
        """Every number carried a % sign, so a sum of them means nothing."""
        return self.unit == "%"

    @property
    def summable(self) -> bool:
        """Whether adding this column's numbers gives a real figure. Percentages
        do not add up, and dollars plus euros are not a total."""
        return not self.is_percent and not self.units_mixed

    @property
    def date_order(self) -> DateOrder | None:
        """The reading this column's own values prove. None when nothing in it
        settles the order, or when values disagree."""
        if self.day_first_hits and not self.month_first_hits:
            return DateOrder.DAY_FIRST
        if self.month_first_hits and not self.day_first_hits:
            return DateOrder.MONTH_FIRST
        return None

    @property
    def dates_unresolved(self) -> bool:
        """Every value parses as a date, but which part is the day is unknown."""
        return self.is_date and self.has_ambiguous_dates and self.date_order is None

    def _resolved_date(
        self, day_first: str | None, month_first: str | None
    ) -> str | None:
        if not self.has_ambiguous_dates:
            return day_first  # the two readings agree on every value
        order = self.date_order
        if order is DateOrder.DAY_FIRST:
            return day_first
        if order is DateOrder.MONTH_FIRST:
            return month_first
        return None

    @property
    def date_min(self) -> str | None:
        return self._resolved_date(self.date_min_day_first, self.date_min_month_first)

    @property
    def date_max(self) -> str | None:
        return self._resolved_date(self.date_max_day_first, self.date_max_month_first)

    @property
    def distinct(self) -> int:
        return len(self.counts)

    def role(self) -> ColumnRole:
        if self.non_empty == 0:
            return ColumnRole.EMPTY
        many_values = self.distinct > _CATEGORY_MAX_DISTINCT or not self.counts_complete
        if many_values and (
            is_id_name(self.name) or self.id_hits >= 0.8 * self.non_empty
        ):
            return ColumnRole.IDENTIFIER
        if self.is_date and self.date_min is not None:
            return ColumnRole.DATE
        if self.is_numeric:
            return ColumnRole.NUMERIC
        if self.contact_hits >= 0.5 * self.non_empty:
            return ColumnRole.CONTACT
        if not many_values:
            return ColumnRole.CATEGORY
        return ColumnRole.TEXT


def _min_opt[T: (float, str)](a: T | None, b: T | None) -> T | None:
    if a is None:
        return b
    if b is None:
        return a
    return min(a, b)


def _max_opt[T: (float, str)](a: T | None, b: T | None) -> T | None:
    if a is None:
        return b
    if b is None:
        return a
    return max(a, b)


class _Sums(BaseModel):
    """Running sum and count of each numeric column within one group."""

    sums: list[float]
    counts: list[int]

    @classmethod
    def zeros(cls, size: int) -> "_Sums":
        return cls(sums=[0.0] * size, counts=[0] * size)

    def add(self, numbers: list[float | None]) -> None:
        for idx, number in enumerate(numbers):
            if number is not None:
                self.sums[idx] += number
                self.counts[idx] += 1

    def merge(self, other: "_Sums") -> None:
        for idx in range(len(self.sums)):
            self.sums[idx] += other.sums[idx]
            self.counts[idx] += other.counts[idx]

    def average(self, idx: int) -> float:
        return self.sums[idx] / self.counts[idx] if self.counts[idx] else 0.0


class _Breakdowns(BaseModel):
    """Sums of numeric columns grouped by category values and by month."""

    category_columns: list[int] = Field(default_factory=list)
    numeric_columns: list[int] = Field(default_factory=list)
    date_column: int | None = None
    # How to read the date column's values; see DateOrder.
    date_order: DateOrder | None = None
    # category column -> category value -> (sums, counts) aligned with
    # numeric_columns
    by_category: dict[int, dict[str, "_Sums"]] = Field(default_factory=dict)
    # month (YYYY-MM) -> sums aligned with numeric_columns
    by_month: dict[str, "_Sums"] = Field(default_factory=dict)
    months_complete: bool = True

    def add(self, cells: list[str]) -> None:
        if not self.numeric_columns:
            return
        numbers = [
            _parse_number(cells[col]) if col < len(cells) else None
            for col in self.numeric_columns
        ]
        for col in self.category_columns:
            key = cells[col].strip() if col < len(cells) else ""
            if not key:
                continue
            groups = self.by_category.setdefault(col, {})
            if key not in groups:
                if len(groups) >= _CATEGORY_MAX_DISTINCT:
                    continue
                groups[key] = _Sums.zeros(len(self.numeric_columns))
            groups[key].add(numbers)
        if self.date_column is not None and self.date_column < len(cells):
            day = date_key(cells[self.date_column], self.date_order)
            if day is not None:
                month = day[:7]
                if month not in self.by_month:
                    if len(self.by_month) >= _MAX_TRACKED_MONTHS:
                        self.months_complete = False
                        return
                    self.by_month[month] = _Sums.zeros(len(self.numeric_columns))
                self.by_month[month].add(numbers)

    def merge(self, other: "_Breakdowns") -> None:
        if (
            other.category_columns != self.category_columns
            or other.numeric_columns != self.numeric_columns
            or other.date_column != self.date_column
            or other.date_order != self.date_order
        ):
            # Different probes picked different columns: keep only this side.
            return
        for col, groups in other.by_category.items():
            mine = self.by_category.setdefault(col, {})
            for key, sums in groups.items():
                if key in mine:
                    mine[key].merge(sums)
                elif len(mine) < _CATEGORY_MAX_DISTINCT:
                    mine[key] = sums.model_copy(deep=True)
        for month, sums in other.by_month.items():
            if month in self.by_month:
                self.by_month[month].merge(sums)
            elif len(self.by_month) < _MAX_TRACKED_MONTHS:
                self.by_month[month] = sums.model_copy(deep=True)
            else:
                self.months_complete = False
        self.months_complete = self.months_complete and other.months_complete


class SheetKind(str, Enum):
    TABLE = "table"
    TEXT = "text"
    EMPTY = "empty"


class SheetProfile(BaseModel):
    """What one streaming pass over a sheet learned about it."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    names: list[str]
    kind: SheetKind
    header: list[str] = Field(default_factory=list)
    # True when the sheet has no header row and the names are made up.
    synthetic_header: bool = False
    preamble: list[str] = Field(default_factory=list)
    text_lines: list[str] = Field(default_factory=list)
    row_count: int = 0
    columns: list[_ColumnStats] = Field(default_factory=list)
    breakdowns: _Breakdowns = Field(default_factory=_Breakdowns)
    samples: list[list[str]] = Field(default_factory=list)
    # Formatted rows while they fit the full-rows budget; None once they do not.
    full_rows: list[str] | None = Field(default_factory=list)
    # Values repeat inside another column (a first name inside a full name),
    # so these get no value lists.
    redundant_columns: set[int] = Field(default_factory=set)

    @property
    def is_small(self) -> bool:
        return self.full_rows is not None

    def header_key(self) -> tuple[str, ...]:
        return tuple(name.strip().lower() for name in self.header)

    def merge(self, other: "SheetProfile") -> None:
        self.names.extend(other.names)
        self.row_count += other.row_count
        for mine, theirs in zip(self.columns, other.columns, strict=True):
            mine.merge(theirs)
        self.breakdowns.merge(other.breakdowns)
        self.full_rows = None


def _pick_breakdowns(columns: list[_ColumnStats]) -> _Breakdowns:
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
            and 1 < col.distinct <= _CATEGORY_MAX_DISTINCT // 2
            and col.contact_hits == 0
            and len(categories) < _MAX_BREAKDOWN_CATEGORY_COLUMNS
        ):
            categories.append(idx)
    return _Breakdowns(
        category_columns=categories,
        numeric_columns=numerics,
        date_column=date_column,
        date_order=date_order,
    )


def _redundant_columns(columns: list[_ColumnStats], probe: list[list[str]]) -> set[int]:
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
        line = _text_line(row)
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
    row_iter = _non_empty_rows(rows)
    # Skip a narrow title block to reach the table, keeping it as preamble.
    title_rows: list[list[str]] = []
    head: list[list[str]] = []
    for row in row_iter:
        if not head and _row_width(row) < 2 and len(title_rows) < _MAX_PREAMBLE_ROWS:
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
    widest = max(_row_width(row) for row in head)
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
        preamble = [_text_line(r) for r in title_rows]
        data_head = head
    else:
        header = [cell.strip() for cell in head[header_idx]]
        preamble = [_text_line(r) for r in chain(title_rows, head[:header_idx])]
        data_head = head[header_idx + 1 :]

    profiler = _TableProfiler(
        SheetProfile(
            names=[name],
            kind=SheetKind.TABLE,
            header=header,
            synthetic_header=header_idx is None,
            preamble=preamble,
            columns=[_ColumnStats(col) for col in header],
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


class _Block(BaseModel):
    """Lines that stay together. When a block needs several chunks, its first
    ``repeat`` lines start every one of them."""

    lines: list[str]
    repeat: int = 1
    max_chunks: int = 1
    # Named in the log when the chunk budget drops this block.
    label: str = ""


class _Packer:
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

    def add(self, block: _Block) -> None:
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
        if head and head_tokens > self._max_tokens // 2:
            head = []
            head_tokens = 0
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
    separator_tokens = count_tokens(_VALUE_SEPARATOR, tokenizer)
    text = ""
    used = 0
    tokens = 0
    for item in items:
        item_tokens = count_tokens(item, tokenizer) + (separator_tokens if used else 0)
        if tokens + item_tokens > budget and used > 0:
            break
        text = f"{text}{_VALUE_SEPARATOR}{item}" if text else item
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
) -> _Block:
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
    return _Block(lines=lines, repeat=1, max_chunks=_OVERVIEW_MAX_CHUNKS)


def _full_rows_block(
    file_name: str,
    profile: SheetProfile,
    tokenizer: BaseTokenizer,
    max_tokens: int,
    max_chunks: int,
) -> _Block | None:
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
    return _Block(lines=lines, repeat=repeat, max_chunks=max(max_chunks, needed))


def _text_block(file_name: str, profile: SheetProfile, max_chunks: int) -> _Block:
    return _Block(
        lines=[_sheet_title(file_name, profile), *profile.text_lines],
        repeat=1,
        max_chunks=max_chunks,
    )


def _profile_block(
    file_name: str,
    profile: SheetProfile,
    tokenizer: BaseTokenizer,
    line_budget: int,
) -> _Block:
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
            + _VALUE_SEPARATOR.join(f"{name} {lo} to {hi}" for name, lo, hi in dated)
        )

    identifiers = [
        f"{column_label(col.name)} {_value_range(col)} "
        f"({col.distinct}{'+' if not col.counts_complete else ''} distinct)"
        for col, role in zip(profile.columns, roles, strict=True)
        if role == ColumnRole.IDENTIFIER
    ]
    if identifiers:
        lines.append("Identifiers: " + _VALUE_SEPARATOR.join(identifiers))

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
    return _Block(lines=lines, repeat=1, max_chunks=_PROFILE_MAX_CHUNKS)


def _value_range(col: _ColumnStats) -> str:
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
) -> list[_Block]:
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
    blocks: list[_Block] = []
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
        blocks.append(_Block(lines=lines, repeat=1, max_chunks=1))
    return blocks


def _can_merge(into: SheetProfile, other: SheetProfile) -> bool:
    """Whether merging keeps the breakdowns both sides already have.

    Merging two tabs pools their values, which can push a category column past
    ``_CATEGORY_MAX_DISTINCT`` and silently cost the merged profile a breakdown
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
        if len(pooled) > _CATEGORY_MAX_DISTINCT:
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
        key = profile.header_key()
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
    blocks: list[_Block] = [_overview_block(file_name, profiles, tokenizer)]
    in_overview = set(about_lines(profiles, tokenizer))
    # One block per sheet first, so running out of chunks costs every sheet its
    # extras rather than costing the last sheets everything.
    for profile in profiles:
        label = _sheet_title(file_name, profile)
        if profile.kind == SheetKind.TEXT:
            # Only skip the block when every line of this sheet reached the
            # overview; otherwise its text appears nowhere.
            if any(line not in in_overview for line in profile.text_lines):
                blocks.append(_text_block(file_name, profile, full_rows_max_chunks))
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

    packer = _Packer(tokenizer=tokenizer, max_tokens=max_tokens, max_chunks=max_chunks)
    for block in blocks:
        packer.add(block)
    return packer.finish()
