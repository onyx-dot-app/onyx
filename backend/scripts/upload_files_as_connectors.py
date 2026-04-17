"""
Script to upload files from a directory as individual file connectors in Onyx.
Each file gets its own connector named after the file.

Usage:
    python upload_files_as_connectors.py --data-dir /path/to/files --api-key YOUR_KEY
    python upload_files_as_connectors.py --data-dir /path/to/files --api-key YOUR_KEY --api-base http://onyxserver:3000
    python upload_files_as_connectors.py --data-dir /path/to/files --api-key YOUR_KEY --file-glob '*.zip'

Requires:
    pip install requests
"""

import argparse
import fnmatch
import os
import sys
import threading
import time

import requests

REQUEST_TIMEOUT = 900  # 15 minutes


def _elapsed_printer(label: str, stop_event: threading.Event) -> None:
    """Print a live elapsed-time counter until stop_event is set."""
    start = time.monotonic()
    while not stop_event.wait(timeout=1):
        elapsed = int(time.monotonic() - start)
        m, s = divmod(elapsed, 60)
        print(f"\r  {label} ... {m:02d}:{s:02d}", end="", flush=True)
    elapsed = int(time.monotonic() - start)
    m, s = divmod(elapsed, 60)
    print(f"\r  {label} ... {m:02d}:{s:02d} done")


def _timed_request(label: str, fn: object) -> requests.Response:
    """Run a request function while displaying a live elapsed timer."""
    stop = threading.Event()
    t = threading.Thread(target=_elapsed_printer, args=(label, stop), daemon=True)
    t.start()
    try:
        resp = fn()  # ty: ignore[call-non-callable]
    finally:
        stop.set()
        t.join()
    return resp


def upload_file(
    session: requests.Session, base_url: str, file_path: str
) -> dict | None:
    """Upload a single file and return the response with file_paths and file_names."""
    with open(file_path, "rb") as f:
        resp = _timed_request(
            "Uploading",
            lambda: session.post(
                f"{base_url}/api/manage/admin/connector/file/upload",
                files={"files": (os.path.basename(file_path), f)},
                timeout=REQUEST_TIMEOUT,
            ),
        )
    if not resp.ok:
        print(f"  ERROR uploading: {resp.text}")
        return None
    return resp.json()


def create_connector(
    session: requests.Session,
    base_url: str,
    name: str,
    file_paths: list[str],
    file_names: list[str],
    zip_metadata_file_id: str | None,
) -> int | None:
    """Create a file connector and return its ID."""
    resp = _timed_request(
        "Creating connector",
        lambda: session.post(
            f"{base_url}/api/manage/admin/connector",
            json={
                "name": name,
                "source": "file",
                "input_type": "load_state",
                "connector_specific_config": {
                    "file_locations": file_paths,
                    "file_names": file_names,
                    "zip_metadata_file_id": zip_metadata_file_id,
                },
                "refresh_freq": None,
                "prune_freq": None,
                "indexing_start": None,
                "access_type": "public",
                "groups": [],
            },
            timeout=REQUEST_TIMEOUT,
        ),
    )
    if not resp.ok:
        print(f"  ERROR creating connector: {resp.text}")
        return None
    return resp.json()["id"]


def create_credential(
    session: requests.Session, base_url: str, name: str
) -> int | None:
    """Create a dummy credential for the file connector."""
    resp = session.post(
        f"{base_url}/api/manage/credential",
        json={
            "credential_json": {},
            "admin_public": True,
            "source": "file",
            "curator_public": True,
            "groups": [],
            "name": name,
        },
        timeout=REQUEST_TIMEOUT,
    )
    if not resp.ok:
        print(f"  ERROR creating credential: {resp.text}")
        return None
    return resp.json()["id"]


def link_credential(
    session: requests.Session,
    base_url: str,
    connector_id: int,
    credential_id: int,
    name: str,
) -> bool:
    """Link the connector to the credential (create CC pair)."""
    resp = session.put(
        f"{base_url}/api/manage/connector/{connector_id}/credential/{credential_id}",
        json={
            "name": name,
            "access_type": "public",
            "groups": [],
            "auto_sync_options": None,
            "processing_mode": "REGULAR",
        },
        timeout=REQUEST_TIMEOUT,
    )
    if not resp.ok:
        print(f"  ERROR linking credential: {resp.text}")
        return False
    return True


def run_connector(
    session: requests.Session,
    base_url: str,
    connector_id: int,
    credential_id: int,
) -> bool:
    """Trigger the connector to start indexing."""
    resp = session.post(
        f"{base_url}/api/manage/admin/connector/run-once",
        json={
            "connector_id": connector_id,
            "credentialIds": [credential_id],
            "from_beginning": False,
        },
        timeout=REQUEST_TIMEOUT,
    )
    if not resp.ok:
        print(f"  ERROR running connector: {resp.text}")
        return False
    return True


def process_file(session: requests.Session, base_url: str, file_path: str) -> bool:
    """Process a single file through the full connector creation flow."""
    file_name = os.path.basename(file_path)
    connector_name = file_name
    print(f"Processing: {file_name}")

    # Step 1: Upload
    upload_resp = upload_file(session, base_url, file_path)
    if not upload_resp:
        return False

    # Step 2: Create connector
    connector_id = create_connector(
        session,
        base_url,
        name=f"FileConnector-{connector_name}",
        file_paths=upload_resp["file_paths"],
        file_names=upload_resp["file_names"],
        zip_metadata_file_id=upload_resp.get("zip_metadata_file_id"),
    )
    if connector_id is None:
        return False

    # Step 3: Create credential
    credential_id = create_credential(session, base_url, name=connector_name)
    if credential_id is None:
        return False

    # Step 4: Link connector to credential
    if not link_credential(
        session, base_url, connector_id, credential_id, connector_name
    ):
        return False

    # Step 5: Trigger indexing
    if not run_connector(session, base_url, connector_id, credential_id):
        return False

    print(f"  OK (connector_id={connector_id})")
    return True


def get_authenticated_session(api_key: str) -> requests.Session:
    """Create a session authenticated with an API key."""
    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {api_key}"})
    return session


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Upload files as individual Onyx file connectors."
    )
    parser.add_argument(
        "--data-dir",
        required=True,
        help="Directory containing files to upload.",
    )
    parser.add_argument(
        "--api-base",
        default="http://localhost:3000",
        help="Base URL for the Onyx API (default: http://localhost:3000).",
    )
    parser.add_argument(
        "--api-key",
        required=True,
        help="API key for authentication.",
    )
    parser.add_argument(
        "--file-glob",
        default=None,
        help="Glob pattern to filter files (e.g. '*.json', '*.zip').",
    )
    args = parser.parse_args()

    data_dir = args.data_dir
    base_url = args.api_base.rstrip("/")
    api_key = args.api_key
    file_glob = args.file_glob

    if not os.path.isdir(data_dir):
        print(f"Error: {data_dir} is not a directory")
        sys.exit(1)

    script_path = os.path.realpath(__file__)
    files = sorted(
        os.path.join(data_dir, f)
        for f in os.listdir(data_dir)
        if os.path.isfile(os.path.join(data_dir, f))
        and os.path.realpath(os.path.join(data_dir, f)) != script_path
        and (file_glob is None or fnmatch.fnmatch(f, file_glob))
    )

    if not files:
        print(f"No files found in {data_dir}")
        sys.exit(1)

    print(f"Found {len(files)} file(s) in {data_dir}\n")

    session = get_authenticated_session(api_key)

    success = 0
    failed = 0
    for file_path in files:
        if process_file(session, base_url, file_path):
            success += 1
        else:
            failed += 1
        # Small delay to avoid overwhelming the server
        time.sleep(0.5)

    print(f"\nDone: {success} succeeded, {failed} failed out of {len(files)} files.")


if __name__ == "__main__":
    main()
