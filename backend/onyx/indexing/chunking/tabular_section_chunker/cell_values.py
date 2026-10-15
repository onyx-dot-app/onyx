"""Reading one cell: numbers, dates, column names and row text.

Leaf level. Nothing here knows about sheets, profiles or chunks.
"""

import calendar
import math
import re
import unicodedata
from datetime import date
from enum import Enum

_ISO_DATE_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?)?$"
)


_YMD_SLASH_RE = re.compile(r"^(\d{4})/(\d{1,2})/(\d{1,2})$")


_NUMERIC_DMY_RE = re.compile(r"^(\d{1,2})([/.])(\d{1,2})\2(\d{4})$")


_DAY_MONTH_YEAR_RE = re.compile(r"^(\d{1,2})[ -]([A-Za-z]{3,9})\.?,?[ -](\d{4})$")


_MONTH_DAY_YEAR_RE = re.compile(r"^([A-Za-z]{3,9})\.?[ -](\d{1,2}),?[ -](\d{4})$")


_YEAR_RE = re.compile(r"^(?:19|20|21)\d{2}$")


_ID_VALUE_RE = re.compile(r"^[A-Za-z]{1,10}[-_ #]?\d+[A-Za-z]?$")


_WORD_RE = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")


_NAME_SPLIT_RE = re.compile(r"[\s_\-./]+")


_DIGITS_RE = re.compile(r"(\d+)")


_LONG_DECIMAL_RE = re.compile(r"^-?\d+\.\d{7,}$")


_ID_NAME_TOKENS = ("id", "uuid", "uid", "guid", "key")


_VALUE_SEPARATOR = "; "


class DateOrder(str, Enum):
    """Which part of ``5/3/2024`` is the day. Inferred per column, never
    assumed from a locale."""

    DAY_FIRST = "day_first"
    MONTH_FIRST = "month_first"


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


def _natural_key(value: str) -> tuple[tuple[int, int, str], ...]:
    """Sort key that orders "Project 2" before "Project 10"."""
    return tuple(
        (1, int(part), "") if part.isdigit() else (0, 0, part)
        for part in _DIGITS_RE.split(value)
        if part
    )


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


def is_id_name(name: str) -> bool:
    """Whether a column name reads like an identifier (``id``, ``order_uuid``)."""
    lowered = name.lower().strip().replace("-", "_")
    return lowered in _ID_NAME_TOKENS or any(
        lowered.endswith(f"_{token}") for token in _ID_NAME_TOKENS
    )


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
        _ISO_DATE_RE.match(text)
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
    """A cell's pattern with digit runs collapsed, so ``PAY-9`` and ``PAY-10``
    share a shape and a sequence of records is not read as a heading."""
    shape = re.sub(r"\d+", "9", value.strip())
    return re.sub(r"[A-Za-z]+", "a", shape)


def _looks_like_a_label(value: str) -> bool:
    """Whether a cell reads as a column name. Years count: ``Region,2023,2024``
    is a header, and rejecting it feeds the real names into the data."""
    text = value.strip()
    if _YEAR_RE.match(text):
        return True
    return _parse_number(text) is None and date_key(text) is None


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
        # A year over a plain number is a heading above its data, not the
        # next record in a sequence.
        if bool(_YEAR_RE.match(cell.strip())) != bool(_YEAR_RE.match(below.strip())):
            continue
        compared += 1
        if _cell_shape(cell) == _cell_shape(below):
            same += 1
    return compared > 0 and same * 2 >= compared


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


def _row_width(row: list[str]) -> int:
    return sum(1 for cell in row if cell.strip())


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
