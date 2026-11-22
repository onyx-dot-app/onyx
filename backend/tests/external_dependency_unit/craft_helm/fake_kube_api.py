"""A minimal Kubernetes API for `helm template --dry-run=server`, so render
tests can exercise Helm `lookup` of Secrets without a cluster."""

import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

_DISCOVERY: dict[str, dict[str, Any]] = {
    "/version": {"major": "1", "minor": "33", "gitVersion": "v1.33.0"},
    "/api": {"kind": "APIVersions", "versions": ["v1"]},
    "/apis": {"kind": "APIGroupList", "apiVersion": "v1", "groups": []},
    "/api/v1": {
        "kind": "APIResourceList",
        "groupVersion": "v1",
        "resources": [
            {
                "name": "secrets",
                "singularName": "secret",
                "namespaced": True,
                "kind": "Secret",
                "verbs": ["get"],
            }
        ],
    },
}


@dataclass
class FakeKubeApi:
    """Secrets keyed by (namespace, name); `kubeconfig` points at the server."""

    kubeconfig: Path
    secrets: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)


def _handler(api: FakeKubeApi) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:  # noqa: ARG002
            """Keep test output quiet."""

        def _send(self, code: int, body: dict[str, Any]) -> None:
            raw = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self) -> None:
            path = self.path.split("?")[0]
            if path in _DISCOVERY:
                return self._send(200, _DISCOVERY[path])
            parts = path.strip("/").split("/")
            if len(parts) == 6 and parts[2] == "namespaces" and parts[4] == "secrets":
                secret = api.secrets.get((parts[3], parts[5]))
                if secret is not None:
                    return self._send(200, secret)
            self._send(
                404,
                {
                    "kind": "Status",
                    "apiVersion": "v1",
                    "reason": "NotFound",
                    "code": 404,
                },
            )

    return Handler


@contextmanager
def fake_kube_api(tmp_path: Path) -> Iterator[FakeKubeApi]:
    api = FakeKubeApi(kubeconfig=tmp_path / "kubeconfig")
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(api))
    port = server.server_address[1]
    api.kubeconfig.write_text(
        json.dumps(
            {
                "apiVersion": "v1",
                "kind": "Config",
                "clusters": [
                    {"name": "fake", "cluster": {"server": f"http://127.0.0.1:{port}"}}
                ],
                "contexts": [
                    {"name": "fake", "context": {"cluster": "fake", "user": "fake"}}
                ],
                "current-context": "fake",
                "users": [{"name": "fake", "user": {}}],
            }
        )
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield api
    finally:
        server.shutdown()
        server.server_close()
