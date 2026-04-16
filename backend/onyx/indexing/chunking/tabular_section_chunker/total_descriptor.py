from collections import Counter

from onyx.connectors.models import Section
from onyx.indexing.chunking.tabular_section_chunker.analysis import analyze_sheet
from onyx.indexing.chunking.tabular_section_chunker.util import pack_lines
from onyx.natural_language_processing.utils import BaseTokenizer
from onyx.utils.csv_utils import parse_csv_string


TOTALS_HEADER = (
    "Totals and overall aggregates across all rows. This sheet can answer "
    "whole-dataset questions about total, overall, grand total, sum across "
    "all, average, combined, mean, minimum, maximum, and count of values."
)


def build_total_descriptor_chunks(
    section: Section,
    tokenizer: BaseTokenizer,
    max_tokens: int,
) -> list[str]:
    parsed_rows = list(parse_csv_string(section.text or ""))
    if not parsed_rows:
        return []
    headers = parsed_rows[0].header

    a = analyze_sheet(headers, parsed_rows)

    lines: list[str] = []
    for idx in a.numeric_cols:
        lines.append(_numeric_totals_line(headers[idx], a.numeric_values[idx]))
    for idx in a.categorical_cols:
        line = _categorical_top_line(headers[idx], a.categorical_counts[idx])
        if line:
            lines.append(line)
    lines.append(f"Total row count: {a.row_count}.")

    if not lines:
        return []

    prefix = (f"{section.heading}\n" if section.heading else "") + TOTALS_HEADER
    return pack_lines(
        lines=lines,
        prefix=prefix,
        tokenizer=tokenizer,
        max_tokens=max_tokens,
    )


def _numeric_totals_line(name: str, values: list[float]) -> str:
    total = sum(values)
    avg = total / len(values)
    return (
        f"Column {_label(name)}: total (sum across all rows) = {_fmt(total)}, "
        f"average = {_fmt(avg)}, minimum = {_fmt(min(values))}, "
        f"maximum = {_fmt(max(values))}, count = {len(values)}."
    )


def _categorical_top_line(name: str, counts: Counter[str]) -> str:
    top = counts.most_common(1)
    if not top:
        return ""
    val, n = top[0]
    return f"Column {_label(name)} most frequent value: {val} ({n} occurrences)."


def _label(name: str) -> str:
    return f"{name} ({name.replace('_', ' ')})" if "_" in name else name


def _fmt(num: float) -> str:
    if num == int(num) and abs(num) < 1e15:
        return str(int(num))
    return f"{num:.6g}"
