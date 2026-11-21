"""Build the chunk set that bench.py embeds.

The default workload is synthetic and needs no data. A seeded generator writes
financial-report documents (headings, prose and Markdown tables). The number of
chunks per document follows CHUNKS_PER_DOC_QUANTILES, which comes from a real
financial-report corpus. Onyx's real Chunker splits each document, with the
tokenizer that docprocessing uses for Google / gemini-embedding-2.

With --corpus-dir, the script chunks real documents instead: a directory of
parsed-document JSON files. Each file has `document.elements`, a list of
`{"type", "content", "bbox": [{"page_id"}]}`. `content` is text or an HTML
table. Each page becomes one TextSection.

The output is one pickle per document (list[DocAwareChunk]) plus index.json.
Trials load only the documents in the current batch, and all trials with the
same index.json fingerprint embed identical chunks.

Usage:
    PYTHONPATH=<onyx backend> python prepare_chunks.py [--docs 300] [--seed 7]
    PYTHONPATH=<onyx backend> python prepare_chunks.py --corpus-dir DIR --out DIR
"""

import argparse
import hashlib
import json
import math
import pickle
import random
import re
import sys
import time
from collections.abc import Iterator
from concurrent.futures import ProcessPoolExecutor
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
DEFAULT_OUT = HERE / ".cache" / "chunks-synthetic"
MODEL_NAME = "gemini-embedding-2"
# Change this when the generator output changes, so that the fingerprint changes.
SYNTHETIC_VERSION = "synthetic-v1"

# (quantile, chunks per document) of a 300-document sample of the source
# corpus, after Onyx chunking. The generator interpolates log-linearly between
# these points. Sample statistics: 120,136 chunks, median 66 per document,
# p90 1,794, max 4,264.
CHUNKS_PER_DOC_QUANTILES: list[tuple[float, int]] = [
    (0.0, 1),
    (0.05, 2),
    (0.1, 4),
    (0.15, 12),
    (0.2, 15),
    (0.25, 20),
    (0.3, 24),
    (0.35, 28),
    (0.4, 36),
    (0.45, 55),
    (0.5, 66),
    (0.55, 87),
    (0.6, 103),
    (0.65, 123),
    (0.7, 145),
    (0.75, 210),
    (0.8, 276),
    (0.825, 392),
    (0.85, 808),
    (0.875, 1274),
    (0.9, 1794),
    (0.925, 2128),
    (0.95, 2614),
    (0.975, 2810),
    (0.99, 2948),
    (1.0, 4264),
]

# Element types in parsed-document JSON that are not body text.
SKIP_TYPES = {"page_header", "page_footer", "page_number"}


# --------------------------------------------------------------------------
# Synthetic documents
# --------------------------------------------------------------------------

AGENCIES = [
    "Department of Agriculture",
    "Department of Commerce",
    "Department of Defense",
    "Department of Education",
    "Department of Energy",
    "Department of Health and Human Services",
    "Department of the Interior",
    "Department of Justice",
    "Department of Labor",
    "Department of State",
    "Department of Transportation",
    "Department of the Treasury",
    "Department of Veterans Affairs",
    "Environmental Protection Agency",
    "General Services Administration",
    "National Aeronautics and Space Administration",
    "National Science Foundation",
    "Office of Personnel Management",
    "Small Business Administration",
    "Social Security Administration",
]
BUREAUS = [
    "Forest Service",
    "Bureau of the Census",
    "National Institutes of Health",
    "Federal Highway Administration",
    "Bureau of Land Management",
    "Internal Revenue Service",
    "Food and Drug Administration",
    "National Park Service",
    "Bureau of Prisons",
    "Federal Aviation Administration",
    "Coast Guard",
    "Geological Survey",
    "Bureau of Reclamation",
    "Patent and Trademark Office",
    "Indian Health Service",
]
FUND_KINDS = [
    "Salaries and Expenses",
    "Operation and Maintenance",
    "Construction",
    "Research and Development",
    "Working Capital Fund",
    "Revolving Fund",
    "Trust Fund",
    "Grants to States",
    "Loan Program Account",
    "Liquidating Account",
    "Miscellaneous Receipts",
    "Payments to Trust Funds",
    "Management Fund",
    "Emergency Fund",
    "Deposit Fund",
]
DOC_KINDS = [
    "Combined Statement of Receipts, Outlays, and Balances",
    "Monthly Treasury Statement",
    "Annual Report of the Secretary of the Treasury",
    "Statement of Public Debt",
    "Budget Appendix",
    "Treasury Bulletin",
]
COLUMNS = [
    "Account symbol",
    "Period of availability",
    "Agency code",
    "Balance, beginning of fiscal year",
    "Appropriations and other obligational authority",
    "Borrowings and transfers",
    "Outlays (net)",
    "Receipts",
    "Transfers in",
    "Transfers out",
    "Balance withdrawn and other transactions",
    "Balance, end of fiscal year",
    "Unobligated balance",
    "Obligated balance",
]
WORDS = (
    "the of and to in for by on is are was were be from with as this that "
    "which fiscal year total net receipts outlays balance account fund trust "
    "appropriation transfer budget authority amount amounts reported shown "
    "statement table includes excludes period month quarter federal agency "
    "program revenue interest debt securities held public estimated actual "
    "increase decrease compared prior current adjusted classified schedule "
    "obligations collections offsetting reimbursements expenditures accrued "
    "unexpended deposits payments credits deficit surplus investment principal"
).split()
EMPTY_CELL = "------------------"


def _amount(rng: random.Random, sparsity: float) -> str:
    if rng.random() < sparsity:
        return EMPTY_CELL
    if rng.random() < 0.05:
        return ""
    value = math.exp(rng.uniform(math.log(10), math.log(5e10))) / 100
    sign = "-" if rng.random() < 0.15 else ""
    return f"{sign}{value:,.2f}"


def _sentence(rng: random.Random) -> str:
    n = rng.randint(9, 26)
    words: list[str] = [rng.choice(WORDS) for _ in range(n)]
    if rng.random() < 0.5:
        words.insert(
            rng.randrange(n), f"${rng.randint(1, 999):,}.{rng.randint(0, 9)} million"
        )
    if rng.random() < 0.3:
        words.insert(rng.randrange(n), str(rng.randint(1900, 2024)))
    if rng.random() < 0.3:
        words.insert(rng.randrange(n), rng.choice(AGENCIES))
    text = " ".join(words)
    return text[0].upper() + text[1:] + "."


def _paragraph(rng: random.Random) -> str:
    return " ".join(_sentence(rng) for _ in range(rng.randint(2, 7)))


def _account_title(rng: random.Random) -> str:
    parts = [rng.choice(FUND_KINDS)]
    if rng.random() < 0.9:
        parts.insert(0, rng.choice(BUREAUS) + ":")
    if rng.random() < 0.9:
        parts.append(", " + rng.choice(AGENCIES))
    return " ".join(parts).replace(" ,", ",")


def _table(rng: random.Random, year: int) -> str:
    n_cols = rng.randint(3, 11)
    # Share of placeholder cells.
    sparsity = rng.uniform(0.0, 0.2)
    cols = ["Title"] + rng.sample(COLUMNS, n_cols)
    lines = [
        "| " + " | ".join(cols) + " |",
        "| " + " | ".join("---" for _ in cols) + " |",
    ]
    for _ in range(rng.randint(4, 30)):
        row = [_account_title(rng) if rng.random() < 0.8 else ""]
        for col in cols[1:]:
            if col == "Account symbol":
                row.append(f"{rng.randint(0, 9999):04d}")
            elif col == "Agency code":
                row.append(str(rng.randint(1, 99)))
            elif col == "Period of availability":
                start = year - rng.randint(0, 4)
                row.append(str(start) if rng.random() < 0.5 else f"{start}-{year}")
            else:
                row.append(_amount(rng, sparsity))
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def synthetic_pages(rng: random.Random, title: str, year: int) -> Iterator[str]:
    page = 0
    while True:
        page += 1
        parts = [f"{title}, page {page}"]
        if rng.random() < 0.5:
            parts.append(
                f"{rng.choice(AGENCIES)}: {rng.choice(FUND_KINDS)}, fiscal year {year}"
                " (in dollars)"
            )
        for _ in range(rng.randint(1, 3)):
            if rng.random() < 0.6:
                parts.append(_paragraph(rng))
            else:
                parts.append(_table(rng, year))
        yield "\n\n".join(parts)


def sample_chunk_count(u: float) -> int:
    """Inverse CDF of CHUNKS_PER_DOC_QUANTILES at u in [0, 1]."""
    q = CHUNKS_PER_DOC_QUANTILES
    for (p0, v0), (p1, v1) in zip(q, q[1:], strict=False):
        if u <= p1:
            f = (u - p0) / (p1 - p0)
            return max(
                1, round(math.exp(math.log(v0) + (math.log(v1) - math.log(v0)) * f))
            )
    return q[-1][1]


# --------------------------------------------------------------------------
# Parsed-document JSON rendering (--corpus-dir)
# --------------------------------------------------------------------------


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[tuple[list[list[str]], int]] = []
        self._rows: list[list[str | None]] = []
        self._header_rows = 0
        self._row: list[str | None] | None = None
        self._row_is_header = False
        self._in_thead = False
        self._cell: list[str] | None = None
        self._span = (1, 1)
        self._carry: dict[tuple[int, int], str] = {}
        self._depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            self._depth += 1
            if self._depth == 1:
                self._rows, self._header_rows, self._carry = [], 0, {}
        elif self._depth != 1:
            return
        elif tag == "thead":
            self._in_thead = True
        elif tag == "tr":
            self._row, self._row_is_header = [], self._in_thead
        elif tag in ("td", "th") and self._row is not None:
            a = dict(attrs)
            self._cell = []
            self._span = (_int(a.get("rowspan")), _int(a.get("colspan")))
            if tag == "th" and not self._row:
                self._row_is_header = True
        elif tag == "br" and self._cell is not None:
            self._cell.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag == "table":
            if self._depth == 1:
                self._finish_table()
            self._depth -= 1
        elif self._depth != 1:
            return
        elif tag == "thead":
            self._in_thead = False
        elif tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._place(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self._fill_carry(len(self._row) + 1000)
            self._rows.append(self._row)
            if self._row_is_header and len(self._rows) == self._header_rows + 1:
                self._header_rows += 1
            self._row = None

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def _fill_carry(self, upto: int) -> None:
        assert self._row is not None
        r = len(self._rows)
        while len(self._row) < upto and (r, len(self._row)) in self._carry:
            self._row.append(self._carry.pop((r, len(self._row))))

    def _place(self, text: str) -> None:
        assert self._row is not None
        self._fill_carry(len(self._row) + 1000)
        r, c = len(self._rows), len(self._row)
        rowspan, colspan = self._span
        for dc in range(colspan):
            self._row.append(text)
            for dr in range(1, rowspan):
                self._carry[(r + dr, c + dc)] = text

    def _finish_table(self) -> None:
        width = max((len(r) for r in self._rows), default=0)
        grid = [[c or "" for c in r] + [""] * (width - len(r)) for r in self._rows]
        self.tables.append((grid, self._header_rows))


def _int(value: str | None) -> int:
    try:
        return max(1, min(int(value or 1), 100))
    except ValueError:
        return 1


def _md_cell(text: str) -> str:
    return text.replace("|", "\\|").strip()


def table_to_markdown(html: str) -> list[str]:
    parser = _TableParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # noqa: BLE001
        return [html.strip()]
    out: list[str] = []
    for grid, header_rows in parser.tables:
        if not grid or not grid[0]:
            continue
        n = max(1, header_rows)
        headers: list[str] = []
        for col in range(len(grid[0])):
            parts: list[str] = []
            for row in grid[:n]:
                if row[col] and (not parts or parts[-1] != row[col]):
                    parts.append(row[col])
            headers.append(" > ".join(parts) or f"col_{col + 1}")
        lines = [
            "| " + " | ".join(_md_cell(h) for h in headers) + " |",
            "| " + " | ".join("---" for _ in headers) + " |",
        ]
        lines += [
            "| " + " | ".join(_md_cell(c) for c in row) + " |" for row in grid[n:]
        ]
        out.append("\n".join(lines))
    return out or [html.strip()]


def _page_id(element: dict[str, Any]) -> int:
    bbox = element.get("bbox")
    if isinstance(bbox, list) and bbox and isinstance(bbox[0], dict):
        page = bbox[0].get("page_id")
        if isinstance(page, int):
            return page
    return 0


def render_pages(parsed: dict[str, Any]) -> dict[int, str]:
    elements = (parsed.get("document") or {}).get("elements") or []
    pages: dict[int, list[str]] = {}
    for el in elements:
        if not isinstance(el, dict) or el.get("type") in SKIP_TYPES:
            continue
        content = el.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        parts = (
            table_to_markdown(content)
            if "<table" in content.lower()
            else [re.sub(r"\r\n?", "\n", content.strip())]
        )
        pages.setdefault(_page_id(el), []).extend(parts)
    return {p: "\n\n".join(parts) for p, parts in sorted(pages.items())}


# --------------------------------------------------------------------------
# Chunking with Onyx's real Chunker
# --------------------------------------------------------------------------

_chunker: Any = None


def _get_chunker() -> Any:
    global _chunker
    if _chunker is None:
        from onyx.indexing.chunker import Chunker
        from onyx.natural_language_processing.utils import get_tokenizer
        from shared_configs.enums import EmbeddingProvider

        tokenizer = get_tokenizer(
            model_name=MODEL_NAME, provider_type=EmbeddingProvider.GOOGLE
        )
        # Defaults match run_indexing_pipeline with multipass and large chunks off.
        _chunker = Chunker(tokenizer=tokenizer)
    return _chunker


def _chunk(doc_id: str, title: str, link: str, pages: list[str]) -> list[Any]:
    from onyx.configs.constants import DocumentSource
    from onyx.connectors.models import IndexingDocument, TextSection

    sections = [
        TextSection(link=f"{link}#page={i + 1}", text=text)
        for i, text in enumerate(pages)
    ] or [TextSection(link=None, text=f"{title}\n\n(no text)")]
    doc = IndexingDocument(
        id=doc_id,
        sections=sections,
        processed_sections=[s.model_copy() for s in sections],
        source=DocumentSource.FILE,
        semantic_identifier=title,
        title=title,
        metadata={"file_name": link.rsplit("/", 1)[-1]},
    )
    return _get_chunker().chunk([doc])


def _write(out_dir: str, stem: str, doc_id: str, chunks: list[Any]) -> dict[str, Any]:
    with open(Path(out_dir) / f"{stem}.pkl", "wb") as f:
        pickle.dump(chunks, f, protocol=pickle.HIGHEST_PROTOCOL)
    lens = [len(c.content) for c in chunks]
    return {
        "doc_id": doc_id,
        "file": f"{stem}.pkl",
        "n_chunks": len(chunks),
        "chars": sum(lens),
        "chunk_chars": lens,
    }


# Mean characters of page text per chunk; only sets the first page estimate.
_CHARS_PER_CHUNK_GUESS = 1100


def synthetic_doc(args: tuple[int, int, int, str]) -> dict[str, Any]:
    i, target, seed, out_dir = args
    rng = random.Random(f"{SYNTHETIC_VERSION}-{seed}-{i}")
    year = rng.randint(1900, 2024)
    title = f"{rng.choice(DOC_KINDS)} {year} part {rng.randint(1, 40)}"
    stem = f"doc{i:05d}"
    link = f"https://example.invalid/{stem}.pdf"
    page_gen = synthetic_pages(rng, title, year)
    pages: list[str] = []
    chunks: list[Any] = []
    if target == 1:
        # One short page: a single chunk of 200-1,100 characters.
        pages.append(next(page_gen)[: rng.randint(200, 1100)])
        chunks = _chunk(f"synthetic__{stem}", title, link, pages)
    while len(chunks) < target:
        want = (target - len(chunks)) * _CHARS_PER_CHUNK_GUESS
        added = 0
        while added < want or not pages:
            pages.append(next(page_gen))
            added += len(pages[-1])
        chunks = _chunk(f"synthetic__{stem}", title, link, pages)
    return _write(out_dir, stem, f"synthetic__{stem}", chunks[:target])


def corpus_doc(args: tuple[str, str]) -> dict[str, Any]:
    src, out_dir = args
    path = Path(src)
    stem = path.stem
    title = stem.replace("_", " ")
    pages = [
        f"{title}, page {p + 1}\n\n{text}"
        for p, text in render_pages(json.loads(path.read_text())).items()
    ]
    doc_id = f"corpus__{stem}"
    chunks = _chunk(doc_id, title, f"https://example.invalid/{stem}.pdf", pages)
    return _write(out_dir, stem, doc_id, chunks)


def select_files(corpus: Path, max_docs: int, n_largest: int, seed: int) -> list[Path]:
    files = sorted(corpus.glob("*.json"))
    if max_docs <= 0 or max_docs >= len(files):
        return files
    by_size = sorted(files, key=lambda p: p.stat().st_size, reverse=True)
    largest = by_size[:n_largest]
    rest = [p for p in files if p not in set(largest)]
    rng = random.Random(seed)
    picked = largest + rng.sample(rest, max_docs - len(largest))
    return sorted(picked)


def _pct(xs: list[int], q: float) -> int:
    return xs[min(len(xs) - 1, int(q * len(xs)))]


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--docs", type=int, default=300, help="documents (0 = all files)")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--procs", type=int, default=8)
    ap.add_argument(
        "--corpus-dir",
        type=Path,
        default=None,
        help="chunk this directory of parsed-document JSON files, not synthetic text",
    )
    ap.add_argument(
        "--n-largest",
        type=int,
        default=15,
        help="with --corpus-dir: always include the N largest files",
    )
    args = ap.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    for old in args.out.glob("*.pkl"):
        old.unlink()
    t0 = time.time()
    if args.corpus_dir is not None:
        files = select_files(args.corpus_dir, args.docs, args.n_largest, args.seed)
        workload: dict[str, Any] = {"corpus": "parsed-json", "files": len(files)}
        fn: Any = corpus_doc
        jobs: list[Any] = [(str(f), str(args.out)) for f in files]
    else:
        n = args.docs or 300
        rng = random.Random(args.seed)
        # Stratified sample of the distribution: one draw in each 1/n interval.
        targets = [sample_chunk_count((i + rng.random()) / n) for i in range(n)]
        rng.shuffle(targets)
        workload = {"corpus": SYNTHETIC_VERSION, "docs": n, "seed": args.seed}
        fn = synthetic_doc
        jobs = [(i, t, args.seed, str(args.out)) for i, t in enumerate(targets)]
        # Start the largest documents first, so that one does not finish last.
        jobs.sort(key=lambda j: -j[1])

    entries: list[dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=args.procs) as pool:
        for i, entry in enumerate(pool.map(fn, jobs)):
            entries.append(entry)
            if (i + 1) % 25 == 0:
                print(f"chunked {i + 1}/{len(jobs)} docs", file=sys.stderr)
    entries.sort(key=lambda e: e["doc_id"])

    all_lens = sorted(n for e in entries for n in e["chunk_chars"])
    counts = sorted(e["n_chunks"] for e in entries)
    for e in entries:
        del e["chunk_chars"]
    fingerprint = hashlib.sha256(
        json.dumps(
            {
                "workload": workload,
                "model": MODEL_NAME,
                "docs": [(e["doc_id"], e["n_chunks"], e["chars"]) for e in entries],
            }
        ).encode()
    ).hexdigest()[:16]
    stats = {
        "docs": len(entries),
        "chunks": len(all_lens),
        "chunk_chars_p10_p50_p90": [_pct(all_lens, q) for q in (0.1, 0.5, 0.9)],
        "chunks_per_doc_p50_p90_max": [
            _pct(counts, 0.5),
            _pct(counts, 0.9),
            counts[-1],
        ],
    }
    index = {
        "fingerprint": fingerprint,
        "model": MODEL_NAME,
        "workload": workload,
        "stats": stats,
        "docs": entries,
    }
    (args.out / "index.json").write_text(json.dumps(index, indent=1))
    print(
        json.dumps(
            {
                "fingerprint": fingerprint,
                **stats,
                "seconds": round(time.time() - t0, 1),
            }
        )
    )


if __name__ == "__main__":
    main()
