"""``bound_sdk_requests`` must stop the office365 SDK waiting forever on a silent socket."""

import socket
import threading
import time
from collections.abc import Iterator
from types import SimpleNamespace

import pytest
import requests
from office365.graph_client import GraphClient
from office365.runtime.http.request_options import RequestOptions
from office365.sharepoint.client_context import ClientContext

from onyx.connectors.microsoft_utils.sdk_timeout import bound_sdk_requests


@pytest.fixture
def silent_server() -> Iterator[str]:
    """Accepts TCP connections and never answers, like a dropped half-open flow."""
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(5)
    accepted: list[socket.socket] = []
    stop = threading.Event()

    def accept_loop() -> None:
        server.settimeout(0.2)
        while not stop.is_set():
            try:
                accepted.append(server.accept()[0])
            except OSError:
                continue

    thread = threading.Thread(target=accept_loop, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.getsockname()[1]}"
    stop.set()
    thread.join()
    for conn in accepted:
        conn.close()
    server.close()


def test_graph_client_request_times_out(silent_server: str) -> None:
    client = bound_sdk_requests(GraphClient(lambda: {"access_token": "t"}), 1)
    start = time.monotonic()
    with pytest.raises(requests.exceptions.Timeout):
        client.pending_request().execute_request_direct(
            RequestOptions(f"{silent_server}/v1.0/sites/root")
        )
    assert time.monotonic() - start < 5


def test_sharepoint_context_request_times_out(silent_server: str) -> None:
    context = bound_sdk_requests(
        ClientContext(silent_server).with_access_token(
            lambda: SimpleNamespace(tokenType="Bearer", accessToken="t")
        ),
        1,
    )
    with pytest.raises(requests.exceptions.Timeout):
        context.pending_request().execute_request_direct(
            RequestOptions(f"{silent_server}/_api/web")
        )


def test_before_execute_handlers_still_run(silent_server: str) -> None:
    client = bound_sdk_requests(GraphClient(lambda: {"access_token": "t"}), 1)
    seen: list[str] = []
    client.pending_request().beforeExecute += lambda request: seen.append(request.url)
    with pytest.raises(requests.exceptions.Timeout):
        client.pending_request().execute_request_direct(RequestOptions(silent_server))
    assert seen == [silent_server]
