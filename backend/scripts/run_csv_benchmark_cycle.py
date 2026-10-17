"""
File-connector benchmark cycle for spreadsheet retrieval:

1. Upload a zip of spreadsheets; the server unzips it into individual files.
2. Create a file credential + connector over those files, producing a CC pair.
3. Wait for the CC pair to finish its first indexing run.
4. Run scripts.benchmark_csv_retrieval against the indexed corpus, retrying
   on non-zero exit. Output file is named from --label.
5. Delete the CC pair, wait for it to go, then delete the credential.

Each run therefore scores one chunking variant against a freshly built index.
Celery workers cache code at start, so restart docprocessing after editing the
chunker and before the next cycle.

Usage:
    export ONYX_BENCH_EMAIL=... ONYX_BENCH_PASSWORD=...
    cd backend && uv run python -m scripts.run_csv_benchmark_cycle \
        --zip ~/Downloads/corpus.zip \
        --questions ~/Documents/questions_improved.csv \
        --label fieldvalue_baseline
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import requests

from scripts.benchmark_api import REQUEST_TIMEOUT_S, login

INDEXING_POLL_INTERVAL_S = 10
INDEXING_TIMEOUT_S = 60 * 60  # 1 hour

DELETION_POLL_INTERVAL_S = 5
DELETION_TIMEOUT_S = 30 * 60  # 30 min

BACKEND_DIR = Path(__file__).resolve().parents[1]
BENCHMARK_TIMEOUT_S = 60 * 60
MAX_BENCHMARK_ATTEMPTS = 3

# Indexing finished, from the caller's point of view. A partial run still
# yields a scoreable index, so it does not hold the cycle for an hour.
TERMINAL_INDEX_STATUSES = {"success", "completed_with_errors"}


def upload_zip(
    base_url: str, headers: dict[str, str], zip_path: Path
) -> tuple[list[str], list[str], str | None]:
    """Upload the zip and let the server expand it. Returns
    (file_locations, file_names, zip_metadata_file_id)."""
    upload_headers = {k: v for k, v in headers.items() if k != "Content-Type"}
    with zip_path.open("rb") as fh:
        resp = requests.post(
            f"{base_url}/api/manage/admin/connector/file/upload",
            params={"unzip": "true"},
            files=[
                (
                    "files",
                    (zip_path.name, fh, "application/zip"),
                )
            ],
            headers=upload_headers,
            timeout=600,
        )
    if not resp.ok:
        raise RuntimeError(f"upload_zip failed: {resp.status_code} {resp.text}")
    body = resp.json()
    file_paths: list[str] = body["file_paths"]
    file_names: list[str] = body["file_names"]
    print(f"Uploaded {zip_path.name} → {len(file_paths)} files")
    return file_paths, file_names, body.get("zip_metadata_file_id")


def create_credential(base_url: str, headers: dict[str, str], name: str) -> int:
    body = {
        "name": name,
        "credential_json": {},
        "admin_public": True,
        "source": "file",
        "curator_public": True,
        "groups": [],
    }
    resp = requests.post(
        f"{base_url}/api/manage/credential",
        json=body,
        headers=headers,
        timeout=REQUEST_TIMEOUT_S,
    )
    if not resp.ok:
        raise RuntimeError(f"create_credential failed: {resp.status_code} {resp.text}")
    credential_id = int(resp.json()["id"])
    print(f"Created credential id={credential_id}")
    return credential_id


def create_connector(
    base_url: str,
    headers: dict[str, str],
    name: str,
    file_locations: list[str],
    file_names: list[str],
    zip_metadata_file_id: str | None,
) -> int:
    body = {
        "name": name,
        "source": "file",
        "input_type": "load_state",
        "connector_specific_config": {
            "file_locations": file_locations,
            "file_names": file_names,
            "zip_metadata_file_id": zip_metadata_file_id,
        },
        "refresh_freq": None,
        "prune_freq": None,
        "indexing_start": None,
        "access_type": "public",
        "groups": [],
    }
    resp = requests.post(
        f"{base_url}/api/manage/admin/connector",
        json=body,
        headers=headers,
        timeout=REQUEST_TIMEOUT_S,
    )
    if not resp.ok:
        raise RuntimeError(f"create_connector failed: {resp.status_code} {resp.text}")
    connector_id = int(resp.json()["id"])
    print(f"Created connector id={connector_id}")
    return connector_id


def link_connector_to_credential(
    base_url: str,
    headers: dict[str, str],
    connector_id: int,
    credential_id: int,
    name: str,
) -> int:
    body = {
        "name": name,
        "access_type": "public",
        "auto_sync_options": None,
        "groups": [],
    }
    resp = requests.put(
        f"{base_url}/api/manage/connector/{connector_id}/credential/{credential_id}",
        json=body,
        headers=headers,
        timeout=REQUEST_TIMEOUT_S,
    )
    if not resp.ok:
        raise RuntimeError(
            f"link_connector_to_credential failed: {resp.status_code} {resp.text}"
        )
    cc_pair_id = int(resp.json()["data"])
    print(f"Linked → cc_pair_id={cc_pair_id}")
    return cc_pair_id


def get_cc_pair(
    base_url: str, headers: dict[str, str], cc_pair_id: int
) -> dict[str, Any] | None:
    resp = requests.get(
        f"{base_url}/api/manage/admin/cc-pair/{cc_pair_id}",
        headers=headers,
        timeout=REQUEST_TIMEOUT_S,
    )
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return dict(resp.json())


def wait_for_indexing_complete(
    base_url: str, headers: dict[str, str], cc_pair_id: int
) -> None:
    """Wait until the pair is ACTIVE, idle, and holds documents.

    status == 'ACTIVE' alone only means the pair is enabled; it flips to
    ACTIVE before indexing has actually started.
    """
    print(f"Waiting for cc_pair {cc_pair_id} to finish indexing...")
    deadline = time.time() + INDEXING_TIMEOUT_S
    last_summary = ""
    while time.time() < deadline:
        item = get_cc_pair(base_url, headers, cc_pair_id)
        if item is None:
            print("  cc_pair not found yet, waiting...")
        else:
            status = item.get("status")
            indexing = item.get("indexing")
            last_status = item.get("last_index_attempt_status")
            docs = item.get("num_docs_indexed", 0)
            summary = (
                f"  status={status} indexing={indexing} "
                f"last_status={last_status} docs={docs}"
            )
            if summary != last_summary:
                print(summary)
                last_summary = summary

            if (
                status == "ACTIVE"
                and indexing is False
                and last_status in TERMINAL_INDEX_STATUSES
                and docs > 0
            ):
                if last_status != "success":
                    print(f"WARNING: indexing finished as {last_status}")
                print(f"Indexing complete: {docs} docs.")
                return
            if item.get("in_repeated_error_state"):
                raise RuntimeError(f"cc_pair entered repeated error state: {item}")
        time.sleep(INDEXING_POLL_INTERVAL_S)
    raise TimeoutError(
        f"Indexing did not complete within {INDEXING_TIMEOUT_S}s "
        f"for cc_pair {cc_pair_id}"
    )


def run_benchmark(
    label: str, questions: Path, base_url: str, email: str, password: str
) -> Path:
    """Score the indexed corpus. Credentials go through the environment so the
    password never appears in the child's command line."""
    output_path = (Path.cwd() / f"benchmark_results_{label}.txt").resolve()
    cmd = [
        sys.executable,
        "-m",
        "scripts.benchmark_csv_retrieval",
        "--input",
        str(questions),
        "--base-url",
        base_url,
        "--output",
        str(output_path),
    ]
    env = {
        **os.environ,
        "ONYX_BENCH_EMAIL": email,
        "ONYX_BENCH_PASSWORD": password,
    }
    for attempt in range(1, MAX_BENCHMARK_ATTEMPTS + 1):
        print(
            f"\n[Benchmark attempt {attempt}/{MAX_BENCHMARK_ATTEMPTS}] {' '.join(cmd)}"
        )
        result = subprocess.run(
            cmd, cwd=BACKEND_DIR, env=env, timeout=BENCHMARK_TIMEOUT_S
        )
        if result.returncode == 0 and output_path.exists():
            print(f"Benchmark succeeded → {output_path}")
            return output_path
        print(
            f"Benchmark attempt {attempt} failed (rc={result.returncode}); retrying..."
        )
    raise RuntimeError(f"Benchmark failed after {MAX_BENCHMARK_ATTEMPTS} attempts")


def trigger_deletion(
    base_url: str, headers: dict[str, str], connector_id: int, credential_id: int
) -> None:
    body = {"connector_id": connector_id, "credential_id": credential_id}
    resp = requests.post(
        f"{base_url}/api/manage/admin/deletion-attempt",
        json=body,
        headers=headers,
        timeout=REQUEST_TIMEOUT_S,
    )
    if not resp.ok:
        raise RuntimeError(f"trigger_deletion failed: {resp.status_code} {resp.text}")
    print(f"Deletion triggered for connector={connector_id}, cred={credential_id}")


def delete_credential(
    base_url: str, headers: dict[str, str], credential_id: int
) -> None:
    resp = requests.delete(
        f"{base_url}/api/manage/admin/credential/{credential_id}",
        headers=headers,
        timeout=REQUEST_TIMEOUT_S,
    )
    if not resp.ok:
        raise RuntimeError(f"delete_credential failed: {resp.status_code} {resp.text}")
    print(f"Deleted credential {credential_id}")


def wait_for_deletion(base_url: str, headers: dict[str, str], cc_pair_id: int) -> None:
    print(f"Waiting for cc_pair {cc_pair_id} to be deleted...")
    deadline = time.time() + DELETION_TIMEOUT_S
    last_status = ""
    while time.time() < deadline:
        item = get_cc_pair(base_url, headers, cc_pair_id)
        if item is None:
            print("  cc_pair gone — deletion complete.")
            return
        status = str(item.get("status"))
        if status != last_status:
            print(f"  status={status}")
            last_status = status
        time.sleep(DELETION_POLL_INTERVAL_S)
    raise TimeoutError(f"cc_pair {cc_pair_id} not deleted within {DELETION_TIMEOUT_S}s")


def cleanup(
    base_url: str,
    headers: dict[str, str],
    keep: bool,
    connector_id: int | None,
    credential_id: int | None,
    cc_pair_id: int | None,
) -> Exception | None:
    """Remove whatever setup managed to create. Returns the failure instead of
    raising, so it cannot replace an exception already on its way out."""
    if cc_pair_id is None:
        if connector_id is not None or credential_id is not None:
            print(
                f"Setup failed before linking. Left behind: "
                f"connector={connector_id} credential={credential_id}",
                file=sys.stderr,
            )
        return None
    if keep:
        print(f"--keep set; leaving cc_pair {cc_pair_id} in place.")
        return None
    if connector_id is None or credential_id is None:
        return None
    try:
        trigger_deletion(base_url, headers, connector_id, credential_id)
        wait_for_deletion(base_url, headers, cc_pair_id)
        # Deleting the pair leaves the credential, so remove it explicitly.
        delete_credential(base_url, headers, credential_id)
    except Exception as e:
        print(f"Cleanup failed for cc_pair {cc_pair_id}: {e!r}", file=sys.stderr)
        return e
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", required=True, help="Names the output report")
    parser.add_argument(
        "--zip", required=True, type=Path, help="Zip of spreadsheets to index"
    )
    parser.add_argument(
        "--questions", required=True, type=Path, help="question,file CSV"
    )
    parser.add_argument("--base-url", default="http://localhost:3000")
    parser.add_argument("--email", default=os.environ.get("ONYX_BENCH_EMAIL"))
    parser.add_argument("--password", default=os.environ.get("ONYX_BENCH_PASSWORD"))
    parser.add_argument(
        "--keep",
        action="store_true",
        help="Leave the connector in place instead of deleting it",
    )
    args = parser.parse_args()

    if not args.email or not args.password:
        print(
            "Set ONYX_BENCH_EMAIL and ONYX_BENCH_PASSWORD "
            "(or pass --email/--password).",
            file=sys.stderr,
        )
        sys.exit(1)

    zip_path: Path = args.zip.expanduser()
    questions: Path = args.questions.expanduser()
    for path in (zip_path, questions):
        if not path.exists():
            print(f"No such file: {path}", file=sys.stderr)
            sys.exit(1)

    name = f"csv-benchmark-{args.label}"
    headers = login(args.base_url, args.email, args.password)

    file_locations, file_names, zip_metadata_file_id = upload_zip(
        args.base_url, headers, zip_path
    )
    credential_id: int | None = None
    connector_id: int | None = None
    cc_pair_id: int | None = None
    body_failed = False
    try:
        credential_id = create_credential(args.base_url, headers, name)
        connector_id = create_connector(
            args.base_url,
            headers,
            name,
            file_locations,
            file_names,
            zip_metadata_file_id,
        )
        cc_pair_id = link_connector_to_credential(
            args.base_url, headers, connector_id, credential_id, name
        )
        wait_for_indexing_complete(args.base_url, headers, cc_pair_id)
        run_benchmark(args.label, questions, args.base_url, args.email, args.password)
    except BaseException:
        body_failed = True
        raise
    finally:
        cleanup_error = cleanup(
            base_url=args.base_url,
            headers=headers,
            keep=args.keep,
            connector_id=connector_id,
            credential_id=credential_id,
            cc_pair_id=cc_pair_id,
        )
        # A leaked connector must fail the run, but never mask the real error.
        if cleanup_error is not None and not body_failed:
            raise cleanup_error


if __name__ == "__main__":
    main()
