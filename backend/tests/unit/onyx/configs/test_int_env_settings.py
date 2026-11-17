"""An int setting that is not an integer must not stop the import of
app_configs: every service imports it. Each case imports the module in a new
process with the bad value set."""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

_BACKEND_DIR = Path(__file__).resolve().parents[4]


def _import_app_configs(env: dict[str, str], names: list[str]) -> dict[str, Any]:
    script = (
        "import json\n"
        "from onyx.configs import app_configs\n"
        f"print(json.dumps({{n: getattr(app_configs, n) for n in {names!r}}}))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=_BACKEND_DIR,
        env={**os.environ, **env},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize(
    "name",
    [
        "GOOGLE_DRIVE_QUOTA_PER_PROJECT",
        "GOOGLE_DRIVE_QUOTA_PER_USER",
        "GOOGLE_DOCS_READS_PER_PROJECT",
        "GOOGLE_DOCS_READS_PER_USER",
    ],
)
def test_a_bad_limiter_budget_turns_the_limiter_off(name: str) -> None:
    values = _import_app_configs(
        {"ENABLE_SOURCE_API_LIMITER": "true", name: "12,000"},
        ["ENABLE_SOURCE_API_LIMITER"],
    )

    assert values == {"ENABLE_SOURCE_API_LIMITER": False}


def test_valid_limiter_budgets_keep_the_limiter_on() -> None:
    values = _import_app_configs(
        {
            "ENABLE_SOURCE_API_LIMITER": "true",
            "GOOGLE_DRIVE_QUOTA_PER_PROJECT": "12000",
        },
        ["ENABLE_SOURCE_API_LIMITER", "GOOGLE_DRIVE_QUOTA_PER_PROJECT"],
    )

    assert values == {
        "ENABLE_SOURCE_API_LIMITER": True,
        "GOOGLE_DRIVE_QUOTA_PER_PROJECT": 12000,
    }


@pytest.mark.parametrize(
    "name, default",
    [
        ("CELERY_WORKER_DOCCONVERSION_CONCURRENCY", 2),
        ("DOCCONVERSION_WINDOW_BATCHES", 32),
        ("DOCCONVERSION_STALL_SECONDS", 300),
    ],
)
def test_a_bad_conversion_setting_gives_its_default(name: str, default: int) -> None:
    assert _import_app_configs({name: "two"}, [name]) == {name: default}
