"""The api server and the legacy MinIO copy Job wait for the bundled object
store before they start, so neither crash-loops while SeaweedFS comes up. An
install on external object storage has no bundled store to wait for.

Lives in the ``craft_helm`` shard, the lane that provides ``helm`` and builds
the chart dependencies."""

import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
import yaml

from tests.external_dependency_unit.craft_helm.rendering import (
    render_chart,
    skip_or_fail,
)

_WAIT_CONTAINER = "wait-for-object-store"
_HEALTH_URL = "http://onyx-object-store:8333/healthz"
_API_TEMPLATE = "templates/api-deployment.yaml"
_COPY_TEMPLATE = "templates/object-store-legacy-copy.yaml"


def _pod_spec(template: str, extra_args: list[str] | None = None) -> dict | None:
    """The template's pod spec, or None when the template renders nothing."""
    result = render_chart([*(extra_args or []), "--show-only", template])
    if result.returncode != 0:
        # --show-only on an empty template is a helm error, not empty output.
        if "could not find template" in result.stderr:
            return None
        if "missing in charts/" in result.stderr:
            skip_or_fail(f"chart dependencies not built: {result.stderr.strip()}")
        pytest.fail(f"helm template failed: {result.stderr.strip()}")
    doc = next(d for d in yaml.safe_load_all(result.stdout) if d)
    return doc["spec"]["template"]["spec"]


def _assert_waits(spec: dict | None) -> None:
    assert spec is not None
    init = spec["initContainers"]
    guarded = spec["containers"][0]
    assert [container["name"] for container in init] == [_WAIT_CONTAINER]
    # The app image and the guarded container's limits and privileges, so the
    # wait adds no image to mirror and changes neither admission nor the pod's request.
    assert init[0]["image"] == guarded["image"]
    assert init[0]["securityContext"] == guarded["securityContext"]
    assert init[0]["resources"] == guarded["resources"]
    script = init[0]["command"][-1]
    assert _HEALTH_URL in script
    compile(script, "<wait-for-object-store>", "exec")


def test_api_waits_for_the_object_store() -> None:
    _assert_waits(_pod_spec(_API_TEMPLATE))


def test_api_waits_when_reused_values_have_no_object_store_key() -> None:
    # `helm upgrade --reuse-values` from a release before the object store.
    _assert_waits(_pod_spec(_API_TEMPLATE, ["--set", "objectStore=null"]))


def test_legacy_copy_waits_for_the_object_store() -> None:
    _assert_waits(_pod_spec(_COPY_TEMPLATE))


class _StartingStoreHandler(BaseHTTPRequestHandler):
    """Answers 503 once, as a store still starting, then 200."""

    answered = 0

    def do_GET(self) -> None:
        type(self).answered += 1
        self.send_response(503 if type(self).answered == 1 else 200)
        self.end_headers()


def test_wait_script_retries_until_the_store_answers() -> None:
    spec = _pod_spec(_API_TEMPLATE)
    assert spec is not None
    script = spec["initContainers"][0]["command"][-1]
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    wait = subprocess.Popen(
        [
            sys.executable,
            "-c",
            script.replace(_HEALTH_URL, f"http://127.0.0.1:{port}/healthz"),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    # Nothing listens yet, so the first try is refused.
    time.sleep(1)
    server = HTTPServer(("127.0.0.1", port), _StartingStoreHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        output, _ = wait.communicate(timeout=30)
    finally:
        server.shutdown()
        server.server_close()

    assert wait.returncode == 0
    assert "Connection refused" in output
    assert "503" in output
    assert _StartingStoreHandler.answered == 2


def test_external_object_storage_has_no_wait() -> None:
    args = ["--set", "minio.enabled=false"]
    spec = _pod_spec(_API_TEMPLATE, args)
    assert spec is not None
    assert "initContainers" not in spec
    assert _pod_spec(_COPY_TEMPLATE, args) is None
