"""The shapes one pass over a workbook produces."""

from collections import Counter
from collections.abc import Callable, Iterator
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from onyx.indexing.chunking.tabular_section_chunker.cell_values import (
    ID_VALUE_RE,
    DateOrder,
    date_key,
    date_order_evidence,
    is_id_name,
    max_opt,
    min_opt,
    natural_key,
    parse_number,
    unit_marker,
)

# A text column with at most this many distinct values is a category.
CATEGORY_MAX_DISTINCT = 50

# Distinct values tracked per column; later ones are not counted, which keeps
# memory flat on very large sheets.
_MAX_TRACKED_VALUES = 20_000

_MAX_TRACKED_MONTHS = 1200


class ColumnRole(str, Enum):
    IDENTIFIER = "identifier"
    DATE = "date"
    NUMERIC = "numeric"
    CATEGORY = "category"
    TEXT = "text"
    CONTACT = "contact"
    EMPTY = "empty"


class SheetKind(str, Enum):
    TABLE = "table"
    TEXT = "text"
    EMPTY = "empty"


class SheetSource(BaseModel):
    """One sheet (or CSV file). ``open_rows`` yields the raw CSV rows."""

    model_config = ConfigDict(frozen=True)

    name: str
    open_rows: Callable[[], Iterator[list[str]]]


class ColumnStats:
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
            number = parse_number(value)
            if number is None:
                self.is_numeric = False
            else:
                marker = unit_marker(value)
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
                self.date_min_day_first = min_opt(self.date_min_day_first, day_first)
                self.date_max_day_first = max_opt(self.date_max_day_first, day_first)
                self.date_min_month_first = min_opt(
                    self.date_min_month_first, month_first
                )
                self.date_max_month_first = max_opt(
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
        if ID_VALUE_RE.match(value):
            self.id_hits += 1
            if self.id_min is None or natural_key(value) < natural_key(self.id_min):
                self.id_min = value
            if self.id_max is None or natural_key(value) > natural_key(self.id_max):
                self.id_max = value
        if "@" in value or "://" in value:
            self.contact_hits += 1
        self.text_min = value if self.text_min is None else min(self.text_min, value)
        self.text_max = value if self.text_max is None else max(self.text_max, value)

    def merge(self, other: "ColumnStats") -> None:
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
        self.minimum = min_opt(self.minimum, other.minimum)
        self.maximum = max_opt(self.maximum, other.maximum)
        self.is_date = self.is_date and other.is_date
        self.has_ambiguous_dates = self.has_ambiguous_dates or other.has_ambiguous_dates
        self.day_first_hits += other.day_first_hits
        self.month_first_hits += other.month_first_hits
        self.date_min_day_first = min_opt(
            self.date_min_day_first, other.date_min_day_first
        )
        self.date_max_day_first = max_opt(
            self.date_max_day_first, other.date_max_day_first
        )
        self.date_min_month_first = min_opt(
            self.date_min_month_first, other.date_min_month_first
        )
        self.date_max_month_first = max_opt(
            self.date_max_month_first, other.date_max_month_first
        )
        self.counts.update(other.counts)
        self.counts_complete = self.counts_complete and other.counts_complete
        self.id_hits += other.id_hits
        self.contact_hits += other.contact_hits
        self.text_min = min_opt(self.text_min, other.text_min)
        self.text_max = max_opt(self.text_max, other.text_max)
        for candidate in (other.id_min, other.id_max):
            if candidate is None:
                continue
            if self.id_min is None or natural_key(candidate) < natural_key(self.id_min):
                self.id_min = candidate
            if self.id_max is None or natural_key(candidate) > natural_key(self.id_max):
                self.id_max = candidate

    @property
    def summable(self) -> bool:
        """Whether adding this column's numbers gives a real figure. Percentages
        do not add up, and dollars plus euros are not a total."""
        return self.unit != "%" and not self.units_mixed

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
        many_values = self.distinct > CATEGORY_MAX_DISTINCT or not self.counts_complete
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


class Sums(BaseModel):
    """Running sum and count of each numeric column within one group."""

    sums: list[float]
    counts: list[int]

    @classmethod
    def zeros(cls, size: int) -> "Sums":
        return cls(sums=[0.0] * size, counts=[0] * size)

    def add(self, numbers: list[float | None]) -> None:
        for idx, number in enumerate(numbers):
            if number is not None:
                self.sums[idx] += number
                self.counts[idx] += 1

    def merge(self, other: "Sums") -> None:
        for idx in range(len(self.sums)):
            self.sums[idx] += other.sums[idx]
            self.counts[idx] += other.counts[idx]

    def average(self, idx: int) -> float:
        return self.sums[idx] / self.counts[idx] if self.counts[idx] else 0.0


class Breakdowns(BaseModel):
    """Sums of numeric columns grouped by category values and by month."""

    category_columns: list[int] = Field(default_factory=list)
    numeric_columns: list[int] = Field(default_factory=list)
    date_column: int | None = None
    # How to read the date column's values; see DateOrder.
    date_order: DateOrder | None = None
    # category column -> category value -> (sums, counts) aligned with
    # numeric_columns
    by_category: dict[int, dict[str, "Sums"]] = Field(default_factory=dict)
    # month (YYYY-MM) -> sums aligned with numeric_columns
    by_month: dict[str, "Sums"] = Field(default_factory=dict)
    months_complete: bool = True

    def add(self, cells: list[str]) -> None:
        if not self.numeric_columns:
            return
        numbers = [
            parse_number(cells[col]) if col < len(cells) else None
            for col in self.numeric_columns
        ]
        for col in self.category_columns:
            key = cells[col].strip() if col < len(cells) else ""
            if not key:
                continue
            groups = self.by_category.setdefault(col, {})
            if key not in groups:
                if len(groups) >= CATEGORY_MAX_DISTINCT:
                    continue
                groups[key] = Sums.zeros(len(self.numeric_columns))
            groups[key].add(numbers)
        if self.date_column is not None and self.date_column < len(cells):
            day = date_key(cells[self.date_column], self.date_order)
            if day is not None:
                month = day[:7]
                if month not in self.by_month:
                    if len(self.by_month) >= _MAX_TRACKED_MONTHS:
                        self.months_complete = False
                        return
                    self.by_month[month] = Sums.zeros(len(self.numeric_columns))
                self.by_month[month].add(numbers)

    def merge(self, other: "Breakdowns") -> None:
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
                elif len(mine) < CATEGORY_MAX_DISTINCT:
                    mine[key] = sums.model_copy(deep=True)
        for month, sums in other.by_month.items():
            if month in self.by_month:
                self.by_month[month].merge(sums)
            elif len(self.by_month) < _MAX_TRACKED_MONTHS:
                self.by_month[month] = sums.model_copy(deep=True)
            else:
                self.months_complete = False
        self.months_complete = self.months_complete and other.months_complete


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
    columns: list[ColumnStats] = Field(default_factory=list)
    breakdowns: Breakdowns = Field(default_factory=Breakdowns)
    samples: list[list[str]] = Field(default_factory=list)
    # Formatted rows while they fit the full-rows budget; None once they do not.
    full_rows: list[str] | None = Field(default_factory=list)
    # Values repeat inside another column (a first name inside a full name),
    # so these get no value lists.
    redundant_columns: set[int] = Field(default_factory=set)

    @property
    def is_small(self) -> bool:
        return self.full_rows is not None

    def merge(self, other: "SheetProfile") -> None:
        self.names.extend(other.names)
        self.row_count += other.row_count
        for mine, theirs in zip(self.columns, other.columns, strict=True):
            mine.merge(theirs)
        self.breakdowns.merge(other.breakdowns)
        self.full_rows = None


class Block(BaseModel):
    """Lines that stay together. When a block needs several chunks, its first
    ``repeat`` lines start every one of them."""

    lines: list[str]
    repeat: int = 1
    max_chunks: int = 1
    # Named in the log when the chunk budget drops this block.
    label: str = ""
