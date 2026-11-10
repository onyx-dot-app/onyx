"""Indexes the mock Google Drive corpus with the real connector, through
GOOGLE_API_ENDPOINT_OVERRIDE, and checks that every file becomes a document.

The benchmark runs in a subprocess: the override is read when Onyx is imported.
"""

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

_BACKEND_DIR = Path(__file__).resolve().parents[4]
_SMALL_CORPUS = {
    "num_users": 3,
    "num_groups": 2,
    "num_shared_drives": 2,
    "files_per_shared_drive": 15,
    "files_per_user": 8,
    "folders_per_container": 3,
}


def _run_benchmark(tmp_path: Path, config: dict[str, Any]) -> dict[str, Any]:
    report_path = tmp_path / "report.json"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.benchmark_google_drive_connector",
            "--start-mock",
            "--corpus",
            json.dumps(_SMALL_CORPUS),
            "--config",
            json.dumps(config),
            "--json-out",
            str(report_path),
        ],
        cwd=_BACKEND_DIR,
        check=True,
        timeout=600,
    )
    return json.loads(report_path.read_text())


def test_full_crawl_indexes_every_mock_file(tmp_path: Path) -> None:
    report = _run_benchmark(tmp_path, {"latency": {"enabled": False}})

    assert report["expected_documents"] > 0
    assert report["failures"] == 0, report["failure_samples"]
    assert report["missing_documents"] == 0, report["missing_samples"]
    assert report["duplicate_documents"] == 0
    assert report["mock_stats"]["rate_limited"] == 0
