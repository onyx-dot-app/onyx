"""Spawn a real uvicorn HTTP listener for the CLI test suite.

Every other integration suite drives the api_server in-process via FastAPI
``TestClient``. The Go CLI binary is a separate subprocess and can only
reach the server over the network, so this conftest brings up a real
uvicorn on the loopback address alongside the existing TestClient.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Generator

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient

from tests.integration.common_utils.constants import API_SERVER_HOST
from tests.integration.common_utils.constants import API_SERVER_PORT

# Distinctive token tests assert on; the surrounding text is long enough to
# exceed the small --max-output thresholds the truncation tests use.
MOCK_LLM_TOKEN = "quick brown fox"
MOCK_LLM_RESPONSE = f"The {MOCK_LLM_TOKEN} jumps over the lazy dog. " * 20


@pytest.fixture(scope="session", autouse=True)
def _mock_llm_responses() -> Generator[None, None, None]:
    # The CLI suite exercises the binary, not the model. Pin every chat
    # completion to a fixed response so no test calls a real provider.
    import onyx.llm.multi_llm as multi_llm

    original = multi_llm.MOCK_LLM_RESPONSE
    multi_llm.MOCK_LLM_RESPONSE = MOCK_LLM_RESPONSE
    try:
        yield
    finally:
        multi_llm.MOCK_LLM_RESPONSE = original


@pytest.fixture(scope="session", autouse=True)
def _cli_uvicorn_server(_test_client: TestClient) -> Generator[None, None, None]:
    # Reuse the FastAPI app the parent conftest already built (lifespan has
    # already run via the TestClient context manager). Disable uvicorn's
    # lifespan so we don't double-invoke setup_onyx / Prometheus init.
    app = _test_client.app

    config = uvicorn.Config(
        app,
        host=API_SERVER_HOST,
        port=int(API_SERVER_PORT),
        log_level="warning",
        lifespan="off",
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.monotonic() + 30
    last_err: Exception | None = None
    while time.monotonic() < deadline:
        try:
            r = httpx.get(
                f"http://{API_SERVER_HOST}:{API_SERVER_PORT}/health", timeout=1.0
            )
            if r.status_code == 200:
                break
        except Exception as e:
            last_err = e
        time.sleep(0.25)
    else:
        raise RuntimeError(f"uvicorn /health never responded: {last_err!r}")

    try:
        yield
    finally:
        server.should_exit = True
        thread.join(timeout=10)
