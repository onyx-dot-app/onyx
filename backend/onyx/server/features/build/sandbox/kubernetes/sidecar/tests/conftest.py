from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import reset_settings_for_tests
from app.main import create_app

_TEST_TOKEN = "test-token-do-not-use-in-prod"  # noqa: S105 — test fixture token, not a real credential


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    root.mkdir()
    return root


@pytest.fixture
def client(workspace: Path) -> Iterator[TestClient]:
    os.environ["SIDECAR_AUTH_TOKEN"] = _TEST_TOKEN
    os.environ["SIDECAR_WORKSPACE_ROOT"] = str(workspace)
    os.environ["SIDECAR_IDLE_TIMEOUT_SECONDS"] = "3600"
    os.environ["SIDECAR_IDLE_CHECK_INTERVAL_SECONDS"] = "60"
    reset_settings_for_tests()
    app = create_app()
    with TestClient(app) as c:
        yield c
    reset_settings_for_tests()
    for var in (
        "SIDECAR_AUTH_TOKEN",
        "SIDECAR_WORKSPACE_ROOT",
        "SIDECAR_IDLE_TIMEOUT_SECONDS",
        "SIDECAR_IDLE_CHECK_INTERVAL_SECONDS",
    ):
        os.environ.pop(var, None)


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_TEST_TOKEN}"}
