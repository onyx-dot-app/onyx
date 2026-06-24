from collections import Counter
from collections.abc import Iterable
from datetime import date

from dateutil.parser import parse as parse_dt
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from onyx.utils.csv_utils import ParsedRow

CATEGORICAL_DISTINCT_THRESHOLD = 20
ID_NAME_TOKENS = {"id", "uuid", "uid", "guid", "key"}

# Caps that keep analysis memory flat regardless of sheet size. A column with
# more distinct values than the categorical cap is treated as high-cardinality
# (not categorical, since a "most frequent value" is not useful there); id
# uniqueness tracking stops after the id cap (assume unique if no duplicate was
# seen). Both sit well above CATEGORICAL_DISTINCT_THRESHOLD so smaller sheets
# keep their exact classification.
_CATEGORICAL_TRACK_CAP = 1000
_ID_TRACK_CAP = 10000


class NumericAggregate(BaseModel):
    total: float
    count: int
    minimum: float
    maximum: float

    @property
    def average(self) -> float:
        return self.total / self.count if self.count else 0.0


class SheetAnalysis(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    row_count: int
    num_cols: int
    numeric_cols: list[int] = Field(default_factory=list)
    categorical_cols: list[int] = Field(default_factory=list)
    numeric_stats: dict[int, NumericAggregate] = Field(default_factory=dict)
    categorical_counts: dict[int, Counter[str]] = Field(default_factory=dict)
    id_col: int | None = None
    date_min: date | None = None
    date_max: date | None = None

    @property
    def categorical_values(self) -> dict[int, list[str]]:
        return {ci: list(c.keys()) for ci, c in self.categorical_counts.items()}


class _ColumnAccumulator:
    """Running state for one column during a single streaming pass. Numeric and
    date stats are O(1); categorical and id-uniqueness tracking are capped, so a
    high-cardinality column can't grow memory with the row count."""

    __slots__ = (
        "is_id_named",
        "non_empty",
        "is_numeric",
        "total",
        "minimum",
        "maximum",
        "is_date",
        "date_min",
        "date_max",
        "counts",
        "id_seen",
        "has_duplicate",
    )

    def __init__(self, is_id_named: bool) -> None:
        self.is_id_named = is_id_named
        self.non_empty = 0
        self.is_numeric = True
        self.total = 0.0
        self.minimum: float | None = None
        self.maximum: float | None = None
        self.is_date = True
        self.date_min: date | None = None
        self.date_max: date | None = None
        self.counts: Counter[str] | None = Counter()
        self.id_seen: set[str] | None = set() if is_id_named else None
        self.has_duplicate = False

    def observe(self, value: str) -> None:
        self.non_empty += 1

        if self.is_numeric:
            n = _parse_num(value)
            if n is None:
                self.is_numeric = False
            else:
                self.total += n
                self.minimum = n if self.minimum is None else min(self.minimum, n)
                self.maximum = n if self.maximum is None else max(self.maximum, n)

        if self.is_date:
            d = _try_date(value)
            if d is None:
                self.is_date = False
            else:
                self.date_min = d if self.date_min is None else min(self.date_min, d)
                self.date_max = d if self.date_max is None else max(self.date_max, d)

        counts = self.counts
        if counts is not None:
            if value in counts or len(counts) < _CATEGORICAL_TRACK_CAP:
                counts[value] += 1
            else:
                # Past the cap: high cardinality, not a categorical column.
                self.counts = None

        seen = self.id_seen
        if seen is not None and not self.has_duplicate:
            if value in seen:
                self.has_duplicate = True
            elif len(seen) < _ID_TRACK_CAP:
                seen.add(value)


def analyze_sheet(
    headers: list[str], parsed_rows: Iterable[ParsedRow]
) -> SheetAnalysis:
    """Summarize a sheet's columns — types, numeric aggregates, top categorical
    values, date range, identifier — in a single streaming pass over the rows so
    memory stays flat regardless of sheet size."""
    num_cols = len(headers)
    cols = [_ColumnAccumulator(_is_id_name(h)) for h in headers]

    row_count = 0
    for pr in parsed_rows:
        row_count += 1
        row = pr.row
        for idx in range(num_cols):
            value = row[idx].strip() if idx < len(row) else ""
            if value:
                cols[idx].observe(value)

    analysis = SheetAnalysis(row_count=row_count, num_cols=num_cols)
    for idx, col in enumerate(cols):
        if col.non_empty == 0:
            continue

        # Identifier: id-named column with no duplicates. Detected before
        # classification so a numeric `id` column still gets flagged.
        if analysis.id_col is None and col.is_id_named and not col.has_duplicate:
            analysis.id_col = idx

        if col.is_numeric:
            analysis.numeric_cols.append(idx)
            analysis.numeric_stats[idx] = NumericAggregate(
                total=col.total,
                count=col.non_empty,
                minimum=col.minimum if col.minimum is not None else 0.0,
                maximum=col.maximum if col.maximum is not None else 0.0,
            )
            continue

        if col.is_date and col.date_min is not None and col.date_max is not None:
            analysis.date_min = (
                col.date_min
                if analysis.date_min is None
                else min(analysis.date_min, col.date_min)
            )
            analysis.date_max = (
                col.date_max
                if analysis.date_max is None
                else max(analysis.date_max, col.date_max)
            )
            continue

        counts = col.counts
        if counts is not None and len(counts) <= max(
            CATEGORICAL_DISTINCT_THRESHOLD, col.non_empty // 2
        ):
            analysis.categorical_cols.append(idx)
            analysis.categorical_counts[idx] = counts

    return analysis


def _parse_num(value: str) -> float | None:
    try:
        return float(value.replace(",", ""))
    except ValueError:
        return None


def _try_date(value: str) -> date | None:
    if len(value) < 4 or not any(c in value for c in "-/T"):
        return None
    try:
        return parse_dt(value).date()
    except (ValueError, OverflowError, TypeError):
        return None


def _is_id_name(name: str) -> bool:
    lowered = name.lower().strip().replace("-", "_")
    return lowered in ID_NAME_TOKENS or any(
        lowered.endswith(f"_{t}") for t in ID_NAME_TOKENS
    )
