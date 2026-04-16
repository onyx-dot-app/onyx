from collections import Counter
from datetime import date
from itertools import zip_longest

from dateutil.parser import parse as parse_dt
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from onyx.utils.csv_utils import ParsedRow


CATEGORICAL_DISTINCT_THRESHOLD = 20
ID_NAME_TOKENS = {"id", "uuid", "uid", "guid", "key"}


class SheetAnalysis(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    row_count: int
    num_cols: int
    numeric_cols: list[int] = Field(default_factory=list)
    categorical_cols: list[int] = Field(default_factory=list)
    numeric_values: dict[int, list[float]] = Field(default_factory=dict)
    categorical_counts: dict[int, Counter[str]] = Field(default_factory=dict)
    id_col: int | None = None
    date_min: date | None = None
    date_max: date | None = None

    @property
    def categorical_values(self) -> dict[int, list[str]]:
        return {ci: list(c.keys()) for ci, c in self.categorical_counts.items()}


def analyze_sheet(headers: list[str], parsed_rows: list[ParsedRow]) -> SheetAnalysis:
    a = SheetAnalysis(row_count=len(parsed_rows), num_cols=len(headers))
    columns = zip_longest(*(pr.row for pr in parsed_rows), fillvalue="")
    for idx, (header, raw_values) in enumerate(zip(headers, columns)):
        values = [v.strip() for v in raw_values if v.strip()]
        if not values:
            continue

        # Identifier: id-named column whose values are all unique. Detected
        # before classification so a numeric `id` column still gets flagged.
        distinct = set(values)
        if a.id_col is None and len(distinct) == len(values) and _is_id_name(header):
            a.id_col = idx

        # Numeric: every value parses as a number.
        nums = _try_all_numeric(values)
        if nums is not None:
            a.numeric_cols.append(idx)
            a.numeric_values[idx] = nums
            continue

        # Date: every value parses as a date — fold into the sheet-wide range.
        dates = _try_all_dates(values)
        if dates:
            dmin = min(dates)
            dmax = max(dates)
            a.date_min = dmin if a.date_min is None else min(a.date_min, dmin)
            a.date_max = dmax if a.date_max is None else max(a.date_max, dmax)
            continue

        # Categorical: low-cardinality column — keep counts for samples + top values.
        if len(distinct) <= max(CATEGORICAL_DISTINCT_THRESHOLD, len(values) // 2):
            a.categorical_cols.append(idx)
            a.categorical_counts[idx] = Counter(values)
    return a


def _try_all_numeric(values: list[str]) -> list[float] | None:
    parsed: list[float] = []
    for v in values:
        n = _parse_num(v)
        if n is None:
            return None
        parsed.append(n)
    return parsed


def _parse_num(value: str) -> float | None:
    try:
        return float(value.replace(",", ""))
    except ValueError:
        return None


def _try_all_dates(values: list[str]) -> list[date] | None:
    parsed: list[date] = []
    for v in values:
        d = _try_date(v)
        if d is None:
            return None
        parsed.append(d)
    return parsed


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
