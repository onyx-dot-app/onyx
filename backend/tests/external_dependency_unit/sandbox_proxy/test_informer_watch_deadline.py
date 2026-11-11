"""Pod-watch read deadline against a real Kubernetes client and a local API
server that accepts the watch and then never sends data."""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from kubernetes import client

from onyx.sandbox_proxy.sandbox_identity.kubernetes import K8sInformerLookup


class _SilentWatchApiServer:
    """Local API server whose pod list works and whose watch never sends data.

    Models a half-open watch connection: the server accepts the watch and
    returns headers, then sends nothing and never closes it.
    """

    def __init__(self) -> None:
        self.lists = 0
        self.watches = 0
        self._release = threading.Event()
        server = self

        class _Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(
                self,
                format: str,  # noqa: ARG002 — stdlib API contract
                *args: object,  # noqa: ARG002
            ) -> None:
                return

            def do_GET(self) -> None:
                if "watch=true" in self.path.lower():
                    server.watches += 1
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Transfer-Encoding", "chunked")
                    self.end_headers()
                    self.wfile.flush()
                    server._release.wait()
                    return
                server.lists += 1
                body = json.dumps(
                    {
                        "kind": "PodList",
                        "apiVersion": "v1",
                        "metadata": {"resourceVersion": str(server.lists)},
                        "items": [],
                    }
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self._httpd.daemon_threads = True
        self.url = f"http://127.0.0.1:{self._httpd.server_address[1]}"
        threading.Thread(target=self._httpd.serve_forever, daemon=True).start()

    def close(self) -> None:
        self._release.set()
        self._httpd.shutdown()
        self._httpd.server_close()


def test_silent_watch_hits_read_deadline_and_relists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A watch connection that never sends data or closes must not freeze the
    cache: the read deadline fails it into the reconnect loop, which relists."""
    module = "onyx.sandbox_proxy.sandbox_identity.kubernetes"
    monkeypatch.setattr(f"{module}._WATCH_READ_TIMEOUT_S", 0.5)
    monkeypatch.setattr(f"{module}._RECONNECT_INITIAL_SECONDS", 0.05)
    server = _SilentWatchApiServer()
    configuration = client.Configuration(host=server.url)
    lookup = K8sInformerLookup(
        core_api=client.CoreV1Api(client.ApiClient(configuration)),
        namespace="sandboxes",
    )
    try:
        lookup.start()
        deadline = time.monotonic() + 10
        while server.lists < 2 and time.monotonic() < deadline:
            time.sleep(0.05)
        assert server.lists >= 2
        assert server.watches >= 1
    finally:
        lookup.stop()
        server.close()
