"""Measure docprocessing throughput and check that the result is still correct.

Stages a synthetic corpus as document batches, runs the body of
`docprocessing_task` on a thread pool against real Postgres, Redis, the file
store and OpenSearch, and embeds through a mock model server. It reports
throughput, stage times, CPU and peak memory, then checks the index and
Postgres against a set of gates. The exit status is 1 when a gate fails.

Usage:
    cd backend && uv run python -m scripts.benchmark_docprocessing \
        [--profile mixed] [--docs 1600] [--threads 6] \
        [--passes first,unchanged,updated] [--latency zero|local|api] \
        [--poison-docs 2] [--max-rss-mb 2000] \
        [--update-golden] [--json-out report.json]

Everything it creates has the prefix `docproc_bench`: a Postgres database, an
OpenSearch index and a file store bucket. It uses Redis database 9. It reads
connection settings from the process environment and `.vscode/.env`, and no
other key from that file.

See scripts/docprocessing_bench/README.md.
"""

import argparse
import fcntl
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import psutil
from pydantic import BaseModel

from scripts.docprocessing_bench.corpus import CorpusProfile, CorpusSpec

_BACKEND_DIR = Path(__file__).resolve().parent.parent
_MOCK_APP_DIR = (
    _BACKEND_DIR / "tests" / "integration" / "mock_services" / "mock_model_server"
)
_GOLDEN_PATH = Path(__file__).resolve().parent / "docprocessing_bench" / "golden.json"
_ENV_FILE = _BACKEND_DIR.parent / ".vscode" / ".env"
_PROFILE_DIR = Path(__file__).resolve().parent / "docprocessing_bench" / "profiles"
# Every run uses the same database, index and bucket, and a second run on the
# machine changes the timings of the first. One run at a time.
_LOCK_PATH = Path(tempfile.gettempdir()) / "docproc-bench.lock"
_BENCH_PREFIX = "docproc_bench"

# Only connection settings pass from the env file to the worker. API keys and
# tracing settings stay out, so a run sends nothing to an outside service.
_PASSED_ENV_PREFIXES = ("POSTGRES_", "REDIS_", "S3_", "OPENSEARCH_", "FILE_STORE_")

# Embed latency in the mock model server. `zero` shows the limit of Onyx's own
# code. `local` and `api` are estimates until they are calibrated against a real
# model server and a real provider (see the README).
_LATENCY_PROFILES: dict[str, dict[str, float | int]] = {
    "zero": {
        "base_ms": 0,
        "per_text_ms": 0,
        "per_1k_chars_ms": 0,
        "max_concurrency": 64,
    },
    "local": {
        "base_ms": 10,
        "per_text_ms": 8,
        "per_1k_chars_ms": 4,
        "max_concurrency": 1,
    },
    "api": {
        "base_ms": 150,
        "per_text_ms": 1,
        "per_1k_chars_ms": 0.5,
        "max_concurrency": 64,
    },
}

# Service names of the docker compose stack.
_DEFAULT_CONTAINER_ENV = {
    "POSTGRES_HOST": "relational_db",
    "REDIS_HOST": "cache",
    "OPENSEARCH_HOST": "opensearch",
    "S3_ENDPOINT_URL": "http://object-store:8333",
}

_PASS_REVISION = {"first": 0, "unchanged": 0, "updated": 1}
# SIGKILL: what the kernel OOM killer sends. 137 is the same from a container.
_KILLED_CODES = (-9, 137)


class PhaseKilled(Exception):
    pass


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.removeprefix("export ").strip()
        if key.startswith(_PASSED_ENV_PREFIXES):
            values[key] = value.strip().strip("'\"")
    return values


def _worker_env(mock_port: int, log_level: str) -> dict[str, str]:
    env = _read_env_file(_ENV_FILE)
    env.update(os.environ)
    env.update(_bench_env(mock_port, log_level))
    return env


def _bench_env(mock_port: int, log_level: str) -> dict[str, str]:
    return {
        "POSTGRES_DB": f"{_BENCH_PREFIX}_db",
        "REDIS_DB_NUMBER": "9",
        "S3_FILE_STORE_BUCKET_NAME": "docproc-bench-file-store",
        "MODEL_SERVER_HOST": "127.0.0.1",
        "MODEL_SERVER_PORT": str(mock_port),
        "INDEXING_MODEL_SERVER_HOST": "127.0.0.1",
        "INDEXING_MODEL_SERVER_PORT": str(mock_port),
        "LOG_LEVEL": log_level,
        "DISABLE_TELEMETRY": "true",
        "SKIP_WARM_UP": "true",
        "PYTHONUNBUFFERED": "1",
    }


_BENCH_ENV_KEYS = frozenset(_bench_env(0, ""))


def start_mock_model_server(port: int, host: str) -> subprocess.Popen[bytes]:
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "server:app",
            "--app-dir",
            str(_MOCK_APP_DIR),
            "--host",
            host,
            "--port",
            str(port),
            "--log-level",
            "warning",
        ]
    )
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            if httpx.get(f"http://127.0.0.1:{port}/api/health", timeout=2).is_success:
                return process
        except httpx.HTTPError:
            pass
        if process.poll() is not None:
            raise RuntimeError("The mock model server exited during startup.")
        time.sleep(0.2)
    process.terminate()
    raise RuntimeError("The mock model server did not start in 30 seconds.")


class ContainerLimits(BaseModel):
    """Runs the measured phase in a container with the limits of the pod."""

    image: str
    network: str
    memory: str
    cpus: float
    # Addresses of the services as the container sees them.
    env: dict[str, str]


def _container_command(
    limits: ContainerLimits, env: dict[str, str], log_dir: Path
) -> list[str]:
    container_env = {
        key: value
        for key, value in env.items()
        if key.startswith(_PASSED_ENV_PREFIXES) or key in _BENCH_ENV_KEYS
    }
    container_env.update(limits.env)
    # A file keeps the passwords out of the process list.
    env_file = log_dir / "container.env"
    env_file.write_text("".join(f"{k}={v}\n" for k, v in container_env.items()))
    return [
        "docker",
        "run",
        "--rm",
        f"--memory={limits.memory}",
        # Equal to --memory: no swap, so the limit kills as it does in a pod.
        f"--memory-swap={limits.memory}",
        f"--cpus={limits.cpus}",
        f"--network={limits.network}",
        "--add-host=host.docker.internal:host-gateway",
        f"--env-file={env_file}",
        f"--volume={_BACKEND_DIR}:/app",
        "--workdir=/app",
        limits.image,
        "python",
    ]


def _run_phase(
    phase: str,
    args: list[str],
    env: dict[str, str],
    log_dir: Path,
    limits: ContainerLimits | None = None,
) -> dict[str, Any]:
    """Runs one worker phase in a new process and returns its JSON result."""
    log_path = log_dir / f"{phase}-{int(time.time() * 1000)}.log"
    python = _container_command(limits, env, log_dir) if limits else [sys.executable]
    with open(log_path, "wb") as log:
        completed = subprocess.run(
            [*python, "-m", "scripts.docprocessing_bench.worker", phase, *args],
            cwd=_BACKEND_DIR,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            check=False,
        )
    if completed.returncode in _KILLED_CODES:
        raise PhaseKilled(f"Phase '{phase}' was killed. Log: {log_path}")
    lines = [line for line in log_path.read_text().splitlines() if line.strip()]
    if completed.returncode != 0:
        tail = "\n".join(lines[-25:])
        raise RuntimeError(
            f"Phase '{phase}' exited {completed.returncode}. Log: {log_path}\n{tail}"
        )
    return dict(json.loads(lines[-1]))


def _golden_key(spec: CorpusSpec, pass_name: str, setup: dict[str, Any]) -> str:
    return "|".join(
        [
            spec.corpus_id,
            pass_name,
            str(setup["model_name"]),
            f"dim{setup['embedding_dim']}",
            f"multipass={setup['multipass']}",
            f"large={setup['large_chunks']}",
        ]
    )


def _load_golden() -> dict[str, dict[str, Any]]:
    if not _GOLDEN_PATH.exists():
        return {}
    return dict(json.loads(_GOLDEN_PATH.read_text()))


class Gates:
    def __init__(self) -> None:
        self.results: list[dict[str, Any]] = []

    def check(self, name: str, passed: bool, detail: str = "") -> None:
        self.results.append({"gate": name, "passed": passed, "detail": detail})

    @property
    def failed(self) -> list[dict[str, Any]]:
        return [result for result in self.results if not result["passed"]]


def _check_pass(
    gates: Gates,
    pass_name: str,
    spec: CorpusSpec,
    staged: dict[str, Any],
    run: dict[str, Any],
    verify: dict[str, Any],
    mock_stats: dict[str, Any],
    previous_digest: str | None,
    max_rss_mb: float | None,
) -> None:
    def gate(name: str, passed: bool, detail: str = "") -> None:
        gates.check(f"{pass_name}: {name}", passed, detail)

    gate(
        "all batches complete",
        run["failed_batches"] == 0 and run["completed_batches"] == staged["batches"],
        f"{run['completed_batches']} of {staged['batches']} complete, "
        f"{run['failed_batches']} raised {run['batch_errors'][:2]}",
    )
    gate(
        "no missing document",
        not verify["missing_documents"],
        str(verify["missing_documents"][:5]),
    )
    gate(
        "no unexpected document",
        not verify["unexpected_documents"],
        str(verify["unexpected_documents"][:5]),
    )
    gate(
        "no duplicate chunk",
        verify["duplicate_chunks"] == 0,
        str(verify["duplicate_chunks"]),
    )
    gate(
        "no gap in chunk indexes",
        not verify["documents_with_gaps"],
        str(verify["documents_with_gaps"][:5]),
    )
    gate(
        "Postgres chunk_count equals the index",
        not verify["chunk_count_mismatches"],
        str(verify["chunk_count_mismatches"][:5]),
    )
    gate(
        "every indexed document has a content hash",
        verify["documents_without_content_hash"] == 0,
        str(verify["documents_without_content_hash"]),
    )
    gate(
        "one error row per poisoned document",
        run["error_rows"] == spec.poison_docs,
        f"{run['error_rows']} error rows, {spec.poison_docs} poisoned",
    )
    if spec.poison_docs == 0:
        gate(
            "attempt counted every document",
            run["total_docs_indexed"] == staged["docs"],
            f"{run['total_docs_indexed']} of {staged['docs']}",
        )

    if pass_name == "unchanged":  # noqa: S105
        if spec.poison_docs == 0:
            gate(
                "unchanged corpus embeds nothing",
                mock_stats["texts"] == 0,
                f"{mock_stats['texts']} texts embedded",
            )
        gate(
            "unchanged corpus leaves the index as it was",
            verify["index_digest"] == previous_digest,
            f"{verify['index_digest'][:12]} vs {str(previous_digest)[:12]}",
        )
    if pass_name == "updated":  # noqa: S105
        gate(
            "updated corpus changes the index",
            verify["index_digest"] != previous_digest,
        )

    if max_rss_mb is not None:
        gate(
            "peak RSS within the budget",
            run["rss_peak_mb"] <= max_rss_mb,
            f"{run['rss_peak_mb']} MB, budget {max_rss_mb} MB",
        )


def _check_golden(
    gates: Gates,
    key: str,
    verify: dict[str, Any],
    golden: dict[str, dict[str, Any]],
    update: bool,
) -> None:
    current = {
        "index_digest": verify["index_digest"],
        "index_chunks": verify["index_chunks"],
        "index_documents": verify["index_documents"],
        "postgres_digest": verify["postgres_digest"],
    }
    pass_name = key.split("|")[1]
    if update:
        golden[key] = current
        return
    expected = golden.get(key)
    if expected is None:
        gates.check(
            f"{pass_name}: index equals golden",
            False,
            "no golden value for this corpus and config; run with --update-golden",
        )
        return
    for field, value in current.items():
        gates.check(
            f"{pass_name}: {field} equals golden",
            expected.get(field) == value,
            f"{value} vs golden {expected.get(field)}",
        )


def _summarize(
    staged: dict[str, Any], run: dict[str, Any], mock_stats: dict[str, Any]
) -> dict[str, Any]:
    elapsed = max(run["elapsed_seconds"], 1e-9)
    cpu = run["cpu_user_seconds"] + run["cpu_system_seconds"]
    docs = run["total_docs_indexed"]
    return {
        "docs_per_minute": round(docs / elapsed * 60, 1),
        "chunks_per_minute": round(run["total_chunks"] / elapsed * 60, 1),
        "text_mb_per_minute": round(staged["chars"] / 1e6 / elapsed * 60, 2),
        "cpu_seconds": round(cpu, 2),
        "cpu_ms_per_doc": round(cpu / max(docs, 1) * 1000, 2),
        "cpu_ms_per_chunk": round(cpu / max(run["total_chunks"], 1) * 1000, 3),
        "cpu_utilization": round(cpu / elapsed, 2),
        "embed_requests": mock_stats["requests"],
        "embed_texts": mock_stats["texts"],
        "embed_peak_in_flight": mock_stats["peak_in_flight"],
    }


def _print_pass(name: str, entry: dict[str, Any]) -> None:
    run = entry["run"]
    summary = entry["summary"]
    verify = entry["verify"]
    print(f"\n== Pass: {name} ==")
    print(
        f"Documents:   {run['total_docs_indexed']} indexed "
        f"({run['new_docs_indexed']} new), {run['total_chunks']} chunks, "
        f"{run['error_rows']} error rows"
    )
    print(
        f"Elapsed:     {run['elapsed_seconds']} s on {run['threads']} threads, "
        f"batch p50 {run['batch_seconds_p50']} s, max {run['batch_seconds_max']} s"
    )
    print(
        f"Throughput:  {summary['docs_per_minute']} docs/min, "
        f"{summary['chunks_per_minute']} chunks/min, "
        f"{summary['text_mb_per_minute']} MB text/min"
    )
    print(
        f"CPU:         {summary['cpu_seconds']} s "
        f"({summary['cpu_utilization']} cores), "
        f"{summary['cpu_ms_per_doc']} ms/doc, {summary['cpu_ms_per_chunk']} ms/chunk"
    )
    print(
        f"Memory:      RSS start {run['rss_start_mb']} MB, "
        f"peak {run['rss_peak_mb']} MB, end {run['rss_end_mb']} MB"
        + (
            f", cgroup peak {run['cgroup_memory_peak_mb']} MB"
            if run["cgroup_memory_peak_mb"] is not None
            else ""
        )
    )
    print(
        f"Embedding:   {summary['embed_requests']} requests, "
        f"{summary['embed_texts']} texts, "
        f"peak {summary['embed_peak_in_flight']} in flight"
    )
    print(
        f"Index:       {verify['index_documents']} documents, "
        f"{verify['index_chunks']} chunks, digest {verify['index_digest'][:16]}"
    )
    batch_total = next(
        (m["total_ms"] for m in run["stage_metrics"] if m["stage"] == "BATCH_TOTAL"),
        0,
    )
    print("Stages (mean ms per batch, share of BATCH_TOTAL):")
    for metric in run["stage_metrics"]:
        share = (
            f"{metric['total_ms'] / batch_total * 100:5.1f}%"
            if batch_total
            else "  n/a"
        )
        print(
            f"  {metric['stage']:<34}{metric['mean_ms']:>10.1f}"
            f"{share:>8}   max {metric['max_ms']}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--profile", default="mixed", choices=[p.value for p in CorpusProfile]
    )
    parser.add_argument("--docs", type=int, help="documents in the corpus")
    parser.add_argument("--doc-chars", type=int, help="fixed size of each document")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--poison-docs", type=int, default=0)
    parser.add_argument("--threads", type=int, default=6)
    parser.add_argument("--passes", default="first,unchanged,updated")
    parser.add_argument("--latency", default="zero", choices=sorted(_LATENCY_PROFILES))
    parser.add_argument("--max-rss-mb", type=float, help="fail above this peak RSS")
    parser.add_argument(
        "--max-swap-pct",
        type=float,
        default=50,
        help="refuse to start when the host uses more swap than this",
    )
    parser.add_argument("--allow-swap", action="store_true")
    parser.add_argument("--update-golden", action="store_true")
    parser.add_argument(
        "--cprofile",
        action="store_true",
        help="profile the measured phase; slows it down, so do not compare timings",
    )
    parser.add_argument(
        "--container-image",
        help="run the measured phase in this backend image, with the limits below",
    )
    parser.add_argument("--container-network", help="docker network of the services")
    parser.add_argument("--container-memory", default="12g")
    parser.add_argument("--container-cpus", type=float, default=1.0)
    parser.add_argument(
        "--container-env",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="service address as the container sees it; repeat for each",
    )
    parser.add_argument("--log-level", default="notice")
    parser.add_argument("--json-out")
    args = parser.parse_args()

    passes = [name.strip() for name in args.passes.split(",") if name.strip()]
    for name in passes:
        if name not in _PASS_REVISION:
            parser.error(f"unknown pass '{name}'")

    lock_file = open(_LOCK_PATH, "w")  # noqa: SIM115 - held until the process exits
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("Another benchmark run holds the lock. Waiting...", flush=True)
        fcntl.flock(lock_file, fcntl.LOCK_EX)

    swap_pct = psutil.swap_memory().percent
    if swap_pct > args.max_swap_pct and not args.allow_swap:
        sys.exit(
            f"Host swap is {swap_pct}% used (limit {args.max_swap_pct}%). Timings "
            "would not be valid. Free memory, or pass --allow-swap for a "
            "correctness-only run."
        )

    spec = CorpusSpec(
        profile=CorpusProfile(args.profile),
        docs=args.docs,
        seed=args.seed,
        poison_docs=args.poison_docs,
        doc_chars=args.doc_chars,
    )
    corpus_json = spec.model_dump_json()
    index_name = f"{_BENCH_PREFIX}_index"
    log_dir = Path(tempfile.mkdtemp(prefix="docproc-bench-"))
    mock_port = _free_port()
    mock_url = f"http://127.0.0.1:{mock_port}"
    env = _worker_env(mock_port, args.log_level)

    commit = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=_BACKEND_DIR,
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    limits: ContainerLimits | None = None
    if args.container_image:
        if not args.container_network:
            parser.error("--container-image needs --container-network")
        limits = ContainerLimits(
            image=args.container_image,
            network=args.container_network,
            memory=args.container_memory,
            cpus=args.container_cpus,
            env=_DEFAULT_CONTAINER_ENV
            | {
                "MODEL_SERVER_HOST": "host.docker.internal",
                "INDEXING_MODEL_SERVER_HOST": "host.docker.internal",
            }
            | dict(item.split("=", 1) for item in args.container_env),
        )

    report: dict[str, Any] = {
        "started_at": datetime.now(UTC).isoformat(),
        "commit": commit,
        "corpus": spec.model_dump(mode="json") | {"corpus_id": spec.corpus_id},
        "threads": args.threads,
        "latency_profile": args.latency,
        "container": limits.model_dump(exclude={"env"}) if limits else None,
        "host_swap_pct": swap_pct,
        "timings_valid": swap_pct <= args.max_swap_pct,
        "log_dir": str(log_dir),
        "passes": {},
    }
    gates = Gates()
    golden = _load_golden()
    print(f"Corpus {spec.corpus_id}, {args.threads} threads, logs in {log_dir}")

    # A container reaches the mock through the docker host gateway, which on
    # Linux is not the loopback interface.
    mock = start_mock_model_server(
        mock_port,
        "0.0.0.0" if limits else "127.0.0.1",  # noqa: S104
    )
    try:
        print("Setup: database, migrations, index...")
        setup = _run_phase("setup", ["--index-name", index_name], env, log_dir)
        report["setup"] = setup
        faults = {"fail_text_markers": ["BENCHPOISONEMBED"]} if spec.poison_docs else {}
        httpx.patch(
            f"{mock_url}/_mock/config",
            json={
                "dim": setup["embedding_dim"],
                "latency": _LATENCY_PROFILES[args.latency],
                "faults": faults,
            },
            timeout=10,
        ).raise_for_status()

        previous_digest: str | None = None
        for pass_name in passes:
            print(f"Pass {pass_name}: staging batches...")
            staged = _run_phase(
                "stage",
                [
                    "--corpus",
                    corpus_json,
                    "--revision",
                    str(_PASS_REVISION[pass_name]),
                    "--cc-pair-id",
                    str(setup["cc_pair_id"]),
                ],
                env,
                log_dir,
            )
            httpx.post(f"{mock_url}/_mock/reset-stats", timeout=10).raise_for_status()
            print(
                f"Pass {pass_name}: processing {staged['docs']} documents "
                f"in {staged['batches']} batches..."
            )
            profile_args: list[str] = []
            if args.cprofile:
                _PROFILE_DIR.mkdir(exist_ok=True)
                profile_path = _PROFILE_DIR / f"{pass_name}.prof"
                # Relative to backend/, which is also /app in a container.
                profile_args = [
                    "--cprofile-out",
                    str(profile_path.relative_to(_BACKEND_DIR)),
                ]
                print(f"Pass {pass_name}: profile in {profile_path}")
            try:
                run = _run_phase(
                    "run",
                    [
                        *profile_args,
                        "--attempt-id",
                        str(staged["index_attempt_id"]),
                        "--cc-pair-id",
                        str(setup["cc_pair_id"]),
                        "--batches",
                        str(staged["batches"]),
                        "--threads",
                        str(args.threads),
                    ],
                    env,
                    log_dir,
                    limits,
                )
            except PhaseKilled as e:
                gates.check(f"{pass_name}: worker not killed (OOM)", False, str(e))
                report["passes"][pass_name] = {"staged": staged, "killed": True}
                break
            mock_stats = dict(httpx.get(f"{mock_url}/_mock/stats", timeout=10).json())
            verify = _run_phase(
                "verify",
                [
                    "--corpus",
                    corpus_json,
                    "--index-name",
                    index_name,
                    "--cc-pair-id",
                    str(setup["cc_pair_id"]),
                ],
                env,
                log_dir,
            )

            _check_pass(
                gates,
                pass_name,
                spec,
                staged,
                run,
                verify,
                mock_stats,
                previous_digest,
                args.max_rss_mb,
            )
            _check_golden(
                gates,
                _golden_key(spec, pass_name, setup),
                verify,
                golden,
                args.update_golden,
            )
            previous_digest = verify["index_digest"]
            entry = {
                "staged": staged,
                "run": run,
                "verify": verify,
                "mock_stats": mock_stats,
                "summary": _summarize(staged, run, mock_stats),
            }
            report["passes"][pass_name] = entry
            _print_pass(pass_name, entry)
    finally:
        mock.terminate()
        mock.wait(timeout=10)

    if args.update_golden and not gates.failed:
        _GOLDEN_PATH.write_text(json.dumps(golden, indent=2, sort_keys=True) + "\n")
        print(f"\nWrote golden values to {_GOLDEN_PATH}")

    report["gates"] = gates.results
    print("\n== Gates ==")
    for result in gates.results:
        mark = "PASS" if result["passed"] else "FAIL"
        detail = "" if result["passed"] else f"  ({result['detail']})"
        print(f"  {mark}  {result['gate']}{detail}")
    if not report["timings_valid"]:
        print(
            f"\nHost swap was {swap_pct}% used: the gates are valid, the timings "
            "are not."
        )
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(report, indent=2) + "\n")
        print(f"\nWrote {args.json_out}")
    if gates.failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
