"""Measure Google Drive connector throughput against the mock Drive server.

Runs the connector's checkpoint loop in this process, the way docfetching does,
and reports docs per minute, the quota the run used, the concurrency it reached
and whether every file in the corpus became a document.

Usage:
    cd backend && uv run python -m scripts.benchmark_google_drive_connector \
        [--mock-url http://localhost:9650 | --start-mock] \
        [--corpus '{"num_users": 20, "files_per_user": 500}'] \
        [--config '{"quota": {"model": "requests"}, "latency": {"enabled": false}}'] \
        [--max-docs 5000] [--json-out report.json]

--corpus generates a new corpus (POST /_mock/corpus); --config changes the
quota, latency and fault settings (PATCH /_mock/config). See
tests/integration/mock_services/mock_google_drive_server/README.md.

Tabular files are staged in memory, and text extraction runs without the
Unstructured API, so the run needs no database or file store.
"""

import argparse
import cProfile
import json
import os
import pstats
import re
import resource
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import IO, Any

import httpx

_MOCK_APP_DIR = (
    Path(__file__).resolve().parent.parent
    / "tests"
    / "integration"
    / "mock_services"
    / "mock_google_drive_server"
)
_FILE_ID_PATTERN = re.compile(r"/(?:d|folders)/([A-Za-z0-9_-]+)")


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def start_mock_server(
    config: dict[str, Any] | None = None,
) -> tuple[subprocess.Popen[bytes], str]:
    """Starts the mock server on a free port and waits until it answers."""
    port = _free_port()
    env = dict(os.environ)
    if config:
        env["MOCK_GDRIVE_CONFIG"] = json.dumps(config)
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "mock_gdrive.app:app",
            "--app-dir",
            str(_MOCK_APP_DIR),
            "--port",
            str(port),
            "--log-level",
            "warning",
            "--timeout-keep-alive",
            "120",
        ],
        env=env,
    )
    url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("The mock Drive server exited during startup")
        try:
            if httpx.get(f"{url}/health", timeout=1).status_code == 200:
                return process, url
        except httpx.HTTPError:
            pass
        time.sleep(0.2)
    process.terminate()
    raise RuntimeError("The mock Drive server did not start within 60 seconds")


def _file_id_from_document_id(document_id: str) -> str:
    match = _FILE_ID_PATTERN.search(document_id)
    return match.group(1) if match else document_id


def _no_unstructured_api_key() -> str | None:
    return None


def _discard_raw_file(file: IO[bytes], content_type: str) -> str:  # noqa: ARG001
    file.read()
    return f"benchmark-staged-{time.monotonic_ns()}"


def run_benchmark(
    mock_url: str,
    *,
    include_shared_drives: bool,
    include_my_drives: bool,
    include_files_shared_with_me: bool,
    max_docs: int | None,
    report_every: float,
    include_permissions: bool,
    conversion_workers: int | None = None,
    partitions_per_checkpoint: int | None = None,
    profile_path: str | None = None,
) -> dict[str, Any]:
    if "onyx.configs.app_configs" in sys.modules:
        raise RuntimeError(
            "Onyx was imported before GOOGLE_API_ENDPOINT_OVERRIDE was set; "
            "run the benchmark in a fresh process."
        )
    os.environ["GOOGLE_API_ENDPOINT_OVERRIDE"] = mock_url

    from onyx.configs.app_configs import INDEX_BATCH_SIZE
    from onyx.connectors.connector_runner import ConnectorRunner
    from onyx.connectors.google_drive import connector as drive_connector
    from onyx.connectors.google_drive.connector import GoogleDriveConnector
    from onyx.connectors.google_drive.models import GoogleDriveCheckpoint
    from onyx.file_processing import extract_file_text

    # Text extraction reads the Unstructured API key from the key-value store,
    # the run's only database read; the benchmark extracts locally.
    extract_file_text.get_unstructured_api_key = _no_unstructured_api_key  # ty: ignore[invalid-assignment]

    if conversion_workers is not None:
        drive_connector.DRIVE_CONVERSION_WORKERS = conversion_workers
    if partitions_per_checkpoint is not None:
        drive_connector.PARTITIONS_PER_CHECKPOINT = partitions_per_checkpoint

    client = httpx.Client(base_url=mock_url, timeout=30)
    key = client.get("/_mock/service-account-key").json()
    summary = client.get("/_mock/corpus/summary", params={"include_ids": True}).json()
    expected = set(summary.pop("content_file_ids"))

    connector = GoogleDriveConnector(
        include_shared_drives=include_shared_drives,
        include_my_drives=include_my_drives,
        include_files_shared_with_me=include_files_shared_with_me,
    )
    connector.load_credentials(
        {
            "google_service_account_key": json.dumps(key),
            "google_primary_admin": summary["admin_email"],
            "authentication_method": "uploaded",
        }
    )
    connector.set_raw_file_callback(_discard_raw_file)
    # On Python 3.12+ cProfile runs on sys.monitoring, so one profiler sees
    # every thread, the conversion workers included.
    profiler = cProfile.Profile()
    if profile_path is not None:
        profiler.enable()
    client.post("/_mock/stats/reset")

    retrieved: dict[str, int] = {}
    failures: list[str] = []
    failed_ids: set[str] = set()
    hierarchy_nodes = 0
    connector_calls = 0
    runner: ConnectorRunner[GoogleDriveCheckpoint] = ConnectorRunner(
        connector=connector,
        batch_size=INDEX_BATCH_SIZE,
        include_permissions=include_permissions,
        time_range=(
            datetime.fromtimestamp(0, tz=timezone.utc),
            datetime.now(timezone.utc),
        ),
    )
    checkpoint = connector.build_dummy_checkpoint()
    cpu_before = resource.getrusage(resource.RUSAGE_SELF)
    children_before = resource.getrusage(resource.RUSAGE_CHILDREN)
    started = time.monotonic()
    last_report = started
    done = False
    while checkpoint.has_more and not done:
        connector_calls += 1
        next_checkpoint: GoogleDriveCheckpoint | None = None
        for docs, nodes, failure, loop_checkpoint in runner.run(checkpoint):
            for document in docs or []:
                file_id = _file_id_from_document_id(document.id)
                retrieved[file_id] = retrieved.get(file_id, 0) + 1
            hierarchy_nodes += len(nodes or [])
            if failure is not None:
                failures.append(failure.failure_message[:300])
                if failure.failed_document is not None:
                    failed_ids.add(
                        _file_id_from_document_id(failure.failed_document.document_id)
                    )
            if loop_checkpoint is not None:
                next_checkpoint = loop_checkpoint
            now = time.monotonic()
            if now - last_report >= report_every:
                last_report = now
                _print_progress(client, now - started, len(retrieved), len(failures))
            if max_docs is not None and len(retrieved) >= max_docs:
                done = True
                break
        if next_checkpoint is None:
            break
        # Docfetching stores the checkpoint as JSON between connector calls.
        checkpoint = connector.validate_checkpoint_json(
            next_checkpoint.model_dump_json()
        )
    elapsed = time.monotonic() - started
    if profile_path is not None:
        profiler.disable()
        pstats.Stats(profiler).dump_stats(profile_path)
    cpu_after = resource.getrusage(resource.RUSAGE_SELF)
    children_after = resource.getrusage(resource.RUSAGE_CHILDREN)
    process_cpu = (cpu_after.ru_utime + cpu_after.ru_stime) - (
        cpu_before.ru_utime + cpu_before.ru_stime
    )
    children_cpu = (children_after.ru_utime + children_after.ru_stime) - (
        children_before.ru_utime + children_before.ru_stime
    )
    stats = client.get("/_mock/stats").json()
    config = client.get("/_mock/config").json()

    missing = expected - set(retrieved)
    # Missing with no failure: a later run would not retry them either.
    silently_missing = missing - failed_ids
    return {
        "elapsed_seconds": round(elapsed, 2),
        "documents": len(retrieved),
        "docs_per_minute": round(len(retrieved) / elapsed * 60, 1) if elapsed else 0.0,
        "failures": len(failures),
        "failure_samples": failures[:10],
        "expected_documents": len(expected),
        "missing_documents": len(missing),
        "missing_samples": sorted(missing)[:10],
        "silently_missing_documents": len(silently_missing),
        "silently_missing_samples": sorted(silently_missing)[:10],
        "duplicate_documents": sum(1 for n in retrieved.values() if n > 1),
        "hierarchy_nodes": hierarchy_nodes,
        "connector_calls": connector_calls,
        "conversion_workers": drive_connector.DRIVE_CONVERSION_WORKERS,
        "partitions_per_checkpoint": drive_connector.PARTITIONS_PER_CHECKPOINT,
        # CPU seconds of this process (its threads share one GIL) and of the
        # PDF subprocesses, over the run.
        "process_cpu_seconds": round(process_cpu, 1),
        "subprocess_cpu_seconds": round(children_cpu, 1),
        "stopped_at_max_docs": max_docs is not None and len(retrieved) >= max_docs,
        "corpus": summary,
        "quota_settings": config["quota"],
        "latency_settings": config["latency"],
        "mock_stats": stats,
    }


def _print_progress(
    client: httpx.Client, elapsed: float, documents: int, failures: int
) -> None:
    stats = client.get("/_mock/stats").json()
    print(
        f"[{elapsed:7.1f}s] docs={documents:6d} "
        f"docs/min={documents / elapsed * 60:8.1f} failures={failures} "
        f"requests={stats['requests']} rate_limited={stats['rate_limited']} "
        f"units/min={stats['units_per_minute']:.0f} "
        f"avg_inflight={stats['avg_inflight']}",
        flush=True,
    )


def _print_report(report: dict[str, Any]) -> None:
    stats = report["mock_stats"]
    quota = report["quota_settings"]
    print("\n=== Google Drive connector benchmark ===")
    print(
        f"Documents:        {report['documents']} of {report['expected_documents']} expected"
    )
    print(
        f"Missing:          {report['missing_documents']} "
        f"({report['silently_missing_documents']} without a failure)  "
        f"Duplicates: {report['duplicate_documents']}"
    )
    print(f"Failures:         {report['failures']}")
    print(f"Elapsed:          {report['elapsed_seconds']} s")
    print(
        f"CPU:              {report['process_cpu_seconds']} s in this process, "
        f"{report['subprocess_cpu_seconds']} s in subprocesses"
    )
    print(f"Docs per minute:  {report['docs_per_minute']}")
    print(
        f"Requests:         {stats['requests']} ({stats['rate_limited']} rate limited)"
    )
    if quota["model"] == "units":
        limit = quota["project_units_per_minute"]
        used = stats["units_per_minute"]
        print(
            f"Quota units/min:  {used:.0f} of {limit} per project "
            f"({used / limit * 100:.1f}%), peak minute {stats['peak_minute_units']}"
        )
    print(
        f"Concurrency:      {stats['avg_inflight']} average, "
        f"{stats['max_inflight']} max requests in flight"
    )
    print("Calls:")
    for name, op in stats["ops"].items():
        print(
            f"  {name:28s} {op['count']:7d} calls  {op['avg_ms']:7.1f} ms avg  "
            f"{op['units']:9d} units  {op['rate_limited']:5d} limited  {op['errors']:5d} errors"
        )
    if report["silently_missing_samples"]:
        print(f"Silently missing: {report['silently_missing_samples']}")
    for sample in report["failure_samples"]:
        print(f"Failure:          {sample}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--mock-url", default="http://localhost:9650")
    parser.add_argument(
        "--start-mock", action="store_true", help="Start a mock server for this run"
    )
    parser.add_argument("--corpus", help="JSON corpus settings; generates a new corpus")
    parser.add_argument("--config", help="JSON quota, latency and fault settings")
    parser.add_argument("--max-docs", type=int)
    parser.add_argument("--report-every", type=float, default=15.0)
    parser.add_argument("--json-out")
    parser.add_argument("--no-shared-drives", action="store_true")
    parser.add_argument("--no-my-drives", action="store_true")
    parser.add_argument("--no-shared-with-me", action="store_true")
    parser.add_argument(
        "--conversion-workers",
        type=int,
        help="Files the connector converts at once (DRIVE_CONVERSION_WORKERS)",
    )
    parser.add_argument(
        "--partitions-per-checkpoint",
        type=int,
        help="Drives or users one connector call lists (PARTITIONS_PER_CHECKPOINT)",
    )
    parser.add_argument("--profile", help="Write merged cProfile stats here")
    parser.add_argument(
        "--perm-sync",
        action="store_true",
        help="Fetch permissions during indexing, as for an EE connector with sync access",
    )
    args = parser.parse_args()

    process: subprocess.Popen[bytes] | None = None
    mock_url = args.mock_url.rstrip("/")
    if args.start_mock:
        process, mock_url = start_mock_server()
        print(f"Started the mock Drive server at {mock_url}")
    try:
        with httpx.Client(base_url=mock_url, timeout=120) as control:
            if args.corpus:
                control.post(
                    "/_mock/corpus", json=json.loads(args.corpus)
                ).raise_for_status()
            if args.config:
                control.patch(
                    "/_mock/config", json=json.loads(args.config)
                ).raise_for_status()
        report = run_benchmark(
            mock_url,
            include_shared_drives=not args.no_shared_drives,
            include_my_drives=not args.no_my_drives,
            include_files_shared_with_me=not args.no_shared_with_me,
            max_docs=args.max_docs,
            report_every=args.report_every,
            include_permissions=args.perm_sync,
            conversion_workers=args.conversion_workers,
            partitions_per_checkpoint=args.partitions_per_checkpoint,
            profile_path=args.profile,
        )
    finally:
        if process is not None:
            process.terminate()
            process.wait(timeout=10)
    _print_report(report)
    if args.json_out:
        with open(args.json_out, "w") as f:
            json.dump(report, f, indent=2)
        print(f"\nWrote {args.json_out}")


if __name__ == "__main__":
    main()
