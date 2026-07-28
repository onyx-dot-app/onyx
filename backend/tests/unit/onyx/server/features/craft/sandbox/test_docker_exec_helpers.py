"""Unit tests for Docker exec helper plumbing."""

from __future__ import annotations

import socket
from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest

import onyx.server.features.build.sandbox.docker.internal.exec_helpers as exec_helpers


class _FakeSocket:
    def __init__(self) -> None:
        self.sent_payload = b""
        self.shutdown_how: int | None = None
        self.closed = False

    def sendall(self, payload: bytes) -> None:
        self.sent_payload += payload

    def shutdown(self, how: int) -> None:
        self.shutdown_how = how

    def close(self) -> None:
        self.closed = True


def test_streamed_exec_passes_environment_to_exec_create(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = {"HOME": "/home/sandbox", "USER": "sandbox"}
    fake_socket = _FakeSocket()
    api = MagicMock()
    api.exec_create.return_value = {"Id": "exec-id"}
    api.exec_start.return_value = fake_socket
    api.exec_inspect.return_value = {"ExitCode": 0}
    client = MagicMock()
    client.api = api
    container = MagicMock()
    container.id = "container-id"
    container.client = client

    def unwrap_socket(sock: object) -> _FakeSocket:
        assert isinstance(sock, _FakeSocket)
        return sock

    def iter_frames(
        sock: socket.socket, *, chunk_size: int
    ) -> Iterator[tuple[int, bytes]]:
        assert sock is fake_socket
        assert chunk_size == 64 * 1024
        return iter(())

    monkeypatch.setattr(exec_helpers, "_unwrap_socket", unwrap_socket)
    monkeypatch.setattr(exec_helpers, "_iter_frames", iter_frames)

    result = exec_helpers.stream_stdin_to_container(
        container,
        ["tar", "-xzf", "-"],
        b"payload",
        user="1000:1000",
        workdir="/workspace",
        environment=env,
    )

    assert result.exit_code == 0
    api.exec_create.assert_called_once_with(
        "container-id",
        cmd=["tar", "-xzf", "-"],
        stdin=True,
        stdout=True,
        stderr=True,
        tty=False,
        user="1000:1000",
        workdir="/workspace",
        environment=env,
    )
    assert fake_socket.sent_payload == b"payload"
    assert fake_socket.shutdown_how == socket.SHUT_WR
    assert fake_socket.closed is True
