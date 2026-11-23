"""Print a comparison table of bench.py trials.

Usage:
    python summarize.py [results.jsonl] [--label SUBSTR] [--last N]
"""

import argparse
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent

COLUMNS = [
    ("label", lambda r: r["label"]),
    ("status", lambda r: r["status"]),
    (
        "git",
        lambda r: (
            r["git"]["head"][:8]
            + (
                ""
                if r["git"]["diff_sha"] == "clean"
                else "+" + r["git"]["diff_sha"][:6]
            )
        ),
    ),
    ("profile", lambda r: r["config"]["profile"]),
    ("P", lambda r: r["config"]["pod_concurrency"]),
    (
        "env",
        lambda r: (
            " ".join(
                f"{k}={v}"
                for k, v in r["config"]["env"].items()
                if k not in ("MULTI_TENANT", "LOG_LEVEL", "SKIP_WARM_UP")
            )
            or "-"
        ),
    ),
    ("dur", lambda r: int(r["config"]["duration"])),
    ("inputs/min", lambda r: r["metrics"].get("steady_inputs_per_min")),
    ("inflight", lambda r: r["metrics"].get("client_avg_in_flight")),
    ("lat_p50", lambda r: r["metrics"].get("call_latency_p50_s")),
    ("done_chunks", lambda r: r["metrics"].get("pipeline_chunks_ok")),
    ("fail_chunks", lambda r: r["metrics"].get("failed_chunks")),
    ("exc", lambda r: r["metrics"].get("batch_exceptions")),
    ("peakGB", lambda r: r["metrics"].get("peak_rss_gb")),
    ("p95GB", lambda r: r["metrics"].get("p95_rss_gb")),
    ("dGB", lambda r: r["metrics"].get("peak_rss_delta_gb")),
    ("cpu", lambda r: r["metrics"].get("cpu_cores_used")),
    ("thr", lambda r: r["metrics"].get("max_os_threads")),
    ("req", lambda r: r["mock"].get("requests")),
    ("429", lambda r: r["mock"].get("throttled_429")),
    ("5xx", lambda r: r["mock"].get("errors_5xx")),
    ("tok", lambda r: r["mock"].get("token_requests")),
    ("m_peak", lambda r: r["mock"].get("peak_in_flight")),
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("results", nargs="?", type=Path, default=HERE / "results.jsonl")
    ap.add_argument("--label", default="", help="only labels containing this")
    ap.add_argument("--last", type=int, default=0)
    args = ap.parse_args()
    rows = [
        json.loads(line)
        for line in args.results.read_text().splitlines()
        if line.strip()
    ]
    rows = [r for r in rows if args.label in r["label"]]
    if args.last:
        rows = rows[-args.last :]
    table = [[name for name, _ in COLUMNS]]
    for r in rows:
        cells = []
        for _, get in COLUMNS:
            try:
                v = get(r)
            except (KeyError, TypeError):
                v = None
            cells.append("-" if v is None else str(v))
        table.append(cells)
    widths = [max(len(row[i]) for row in table) for i in range(len(COLUMNS))]
    for i, row in enumerate(table):
        print("  ".join(c.ljust(w) for c, w in zip(row, widths, strict=True)))
        if i == 0:
            print("  ".join("-" * w for w in widths))


if __name__ == "__main__":
    main()
