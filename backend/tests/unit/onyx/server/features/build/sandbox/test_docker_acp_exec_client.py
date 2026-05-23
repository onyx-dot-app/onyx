"""Unit tests for the Docker ACP exec client framing.

These tests stub out the Docker exec socket with a pair of in-memory queues
so we can exercise JSON-RPC frame parsing without touching Docker. The
client speaks multiplexed docker-style frames over the socket; the test
shim re-creates that wire format.
"""

from __future__ import annotations

import json
import socket
import struct
import threading
from typing import Any
from typing import cast

import pytest
from docker import DockerClient

from onyx.server.features.build.sandbox.docker.internal.acp_exec_client import (
    DockerACPExecClient,
)
from onyx.server.features.build.sandbox.docker.internal.exec_helpers import (
    _FRAME_STDOUT,
)


def _frame(payload: bytes, stream_type: int = _FRAME_STDOUT) -> bytes:
    """Build a docker multiplexed-stream frame."""
    return bytes([stream_type, 0, 0, 0]) + struct.pack(">I", len(payload)) + payload


class _FakeSocket:
    """In-memory socket pair backing the client's reader."""

    def __init__(self) -> None:
        self._inbound = bytearray()
        self._cond = threading.Condition()
        self._closed = False
        self.sent: bytearray = bytearray()
        self._timeout: float | None = None

    # ---- Methods used by client._send_raw / shutdown / close -----------
    def sendall(self, data: bytes) -> None:
        self.sent.extend(data)

    def shutdown(self, _flag: int) -> None:
        pass

    def close(self) -> None:
        with self._cond:
            self._closed = True
            self._cond.notify_all()

    def settimeout(self, t: float | None) -> None:
        self._timeout = t

    # ---- Methods used by the reader thread -----------------------------
    def recv(self, n: int) -> bytes:
        with self._cond:
            while not self._inbound and not self._closed:
                # Honor the timeout: raise socket.timeout matching the client
                # contract so the polling loop continues.
                if self._timeout is not None:
                    if not self._cond.wait(timeout=self._timeout):
                        raise socket.timeout()
                else:
                    self._cond.wait()
            if self._closed and not self._inbound:
                return b""
            chunk = bytes(self._inbound[:n])
            del self._inbound[:n]
            return chunk

    # ---- Test helper ---------------------------------------------------
    def push(self, data: bytes) -> None:
        with self._cond:
            self._inbound.extend(data)
            self._cond.notify_all()


class _FakeAPI:
    """Stand-in for ``docker.DockerClient.api`` covering only ``exec_*``."""

    def __init__(self, sock: _FakeSocket) -> None:
        self._sock = sock
        self.exec_create_calls: list[dict[str, Any]] = []
        self.exec_inspect_response = {"ExitCode": 0}

    def exec_create(self, container: str, **kwargs: Any) -> dict[str, str]:
        self.exec_create_calls.append({"container": container, **kwargs})
        return {"Id": "exec-abc"}

    def exec_start(self, _exec_id: str, **_kwargs: Any) -> _FakeSocket:
        return self._sock

    def exec_inspect(self, _exec_id: str) -> dict[str, Any]:
        return self.exec_inspect_response


class _FakeDockerClient:
    def __init__(self, api: _FakeAPI) -> None:
        self.api = api


def _patch_unwrap(monkeypatch: pytest.MonkeyPatch, sock: _FakeSocket) -> None:
    """``_unwrap_socket`` expects a real socket; bypass it for the fake."""
    from onyx.server.features.build.sandbox.docker.internal import acp_exec_client

    monkeypatch.setattr(acp_exec_client, "_unwrap_socket", lambda _s: sock)


def test_initialize_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    """A well-formed ``initialize`` request returns the agent's capabilities."""
    sock = _FakeSocket()
    api = _FakeAPI(sock)
    _patch_unwrap(monkeypatch, sock)

    # The reader thread will see the initialize response framed in stdout.
    init_response = (
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 0,
                "result": {
                    "agentCapabilities": {"fs": True},
                    "agentInfo": {"name": "fake-agent"},
                },
            }
        )
        + "\n"
    )
    sock.push(_frame(init_response.encode("utf-8")))

    client = DockerACPExecClient(
        docker_client=cast(DockerClient, _FakeDockerClient(api)),
        container_name="sandbox-abc12345",
    )
    try:
        client.start(cwd="/workspace/sessions/x")
        assert client._state.initialized is True
        assert client._state.agent_capabilities == {"fs": True}
        # The initialize request should have been sent as the first message.
        first_line = sock.sent.split(b"\n", 1)[0].decode("utf-8")
        msg = json.loads(first_line)
        assert msg["method"] == "initialize"
        assert msg["params"]["protocolVersion"] == 1
    finally:
        client.stop()


def test_stop_is_idempotent_and_closes_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    """Calling stop twice should not raise; ``is_running`` flips to False."""
    sock = _FakeSocket()
    api = _FakeAPI(sock)
    _patch_unwrap(monkeypatch, sock)
    sock.push(
        _frame(
            (
                json.dumps(
                    {"jsonrpc": "2.0", "id": 0, "result": {"agentCapabilities": {}}}
                )
                + "\n"
            ).encode("utf-8")
        )
    )

    client = DockerACPExecClient(
        docker_client=cast(DockerClient, _FakeDockerClient(api)),
        container_name="sandbox-abc12345",
    )
    client.start()
    assert client.is_running is True
    client.stop()
    assert client.is_running is False
    client.stop()


def test_send_request_fails_when_socket_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """A closed transport surfaces as a clean RuntimeError, not an opaque OSError."""
    sock = _FakeSocket()
    api = _FakeAPI(sock)
    _patch_unwrap(monkeypatch, sock)
    sock.push(
        _frame(
            (json.dumps({"jsonrpc": "2.0", "id": 0, "result": {}}) + "\n").encode(
                "utf-8"
            )
        )
    )

    client = DockerACPExecClient(
        docker_client=cast(DockerClient, _FakeDockerClient(api)),
        container_name="sandbox-abc12345",
    )
    client.start()
    client.stop()
    with pytest.raises(RuntimeError):
        client._send_request("noop", None)
