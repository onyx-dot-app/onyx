from collections import Counter

from onyx.indexing.chunking.tabular_section_chunker.analysis import SheetAnalysis
from onyx.indexing.chunking.tabular_section_chunker.util import label
from onyx.indexing.chunking.tabular_section_chunker.util import pack_lines
from onyx.natural_language_processing.utils import BaseTokenizer

TOTALS_HEADER = (
    "Totals and overall aggregates across all rows. This sheet can answer "
    "whole-dataset questions about total, overall, grand total, sum across "
    "all, average, combined, mean, minimum, maximum, and count of values."
)


def build_total_descriptor_chunks(
    headers: list[str],
    analysis: SheetAnalysis,
    heading: str,
    tokenizer: BaseTokenizer,
    max_tokens: int,
) -> list[str]:
    if analysis.row_count == 0:
        return []

    lines: list[str] = []
    for idx in analysis.numeric_cols:
        lines.append(_numeric_totals_line(headers[idx], analysis.numeric_values[idx]))
    for idx in analysis.categorical_cols:
        line = _categorical_top_line(headers[idx], analysis.categorical_counts[idx])
        if line:
            lines.append(line)

    # No meaningful information - leave early
    if not lines:
        return []

    lines.append(f"Total row count: {analysis.row_count}.")

    prefix = (f"{heading}\n" if heading else "") + TOTALS_HEADER
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
        f"Column {label(name)}: total (sum across all rows) = {_fmt(total)}, "
        f"average = {_fmt(avg)}, minimum = {_fmt(min(values))}, "
        f"maximum = {_fmt(max(values))}, count = {len(values)}."
    )


def _categorical_top_line(name: str, counts: Counter[str]) -> str:
    top = counts.most_common(1)
    if not top:
        return ""
    val, n = top[0]
    return f"Column {label(name)} most frequent value: {val} ({n} occurrences)."


def _fmt(num: float) -> str:
    if abs(num) < 1e15 and num == int(num):
        return str(int(num))
    return f"{num:.6g}"
