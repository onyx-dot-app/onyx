"""VERTEXAI_EMBED_CONTENT_CONCURRENCY: default 4, env override, never below 1.

Runs in a subprocess so shared_configs.configs is not reloaded in this process.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

_BACKEND_DIR = Path(__file__).resolve().parents[3]
_VAR = "VERTEXAI_EMBED_CONTENT_CONCURRENCY"


@pytest.mark.parametrize(
    "raw,expected",
    [(None, 4), ("", 4), ("8", 8), ("1", 1), ("0", 1), ("-3", 1)],
)
def test_vertex_embed_content_concurrency(raw: str | None, expected: int) -> None:
    env = {k: v for k, v in os.environ.items() if k != _VAR}
    if raw is not None:
        env[_VAR] = raw
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            f"from shared_configs.configs import {_VAR}; print({_VAR})",
        ],
        cwd=_BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert int(result.stdout.strip()) == expected
