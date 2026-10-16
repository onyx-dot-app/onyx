from __future__ import annotations

import io
import logging
import threading
import time
from collections.abc import Generator
from contextlib import closing
from typing import BinaryIO, Literal, cast
from unittest.mock import Mock

import pytest
from kubernetes import client
from websocket import ABNF, WebSocketConnectionClosedException

from onyx.server.features.build.sandbox import exec as transport
from onyx.server.features.build.sandbox.exec import ExecClient, FramedStdin
from onyx.server.features.build.sandbox.models import SandboxExecError
from shared_configs.contextvars import ONYX_REQUEST_ID_CONTEXTVAR

_PREFIX = "Sandbox exec transport "
_STATUS = b'{"status":"Success"}'


@pytest.mark.parametrize(
    ("protocol", "negotiated"),
    [
        ("v4.channel.k8s.io", "v4.channel.k8s.io"),
        ("v5.channel.k8s.io", "v5.channel.k8s.io"),
        ("v4.channel.k8s.io", "v5.channel.k8s.io"),
        ("v5.channel.k8s.io", "v4.channel.k8s.io"),
        ("v4.channel.k8s.io", "v3.channel.k8s.io"),
        ("v5.channel.k8s.io", "v3.channel.k8s.io"),
        ("v4.channel.k8s.io", None),
        ("v5.channel.k8s.io", None),
    ],
)
def test_request_advertises_one_protocol_and_requires_exact_negotiation(
    monkeypatch: pytest.MonkeyPatch,
    protocol: Literal["v4.channel.k8s.io", "v5.channel.k8s.io"],
    negotiated: str | None,
) -> None:
    websocket = Mock(spec=transport._DeadlineWebSocket)
    websocket.deadline = time.monotonic() + 3.0
    websocket.getsubprotocol.return_value = negotiated
    monkeypatch.setattr(transport, "_DeadlineWebSocket", Mock(return_value=websocket))
    with transport._ExecApiClient(
        client.Configuration(), websocket.deadline, protocol
    ) as api_client:
        if negotiated == protocol:
            assert api_client.request("GET", "https://test.invalid/exec") is websocket
        else:
            with pytest.raises(SandboxExecError, match=protocol):
                api_client.request("GET", "https://test.invalid/exec")

    assert websocket.connect.call_args.kwargs["subprotocols"] == [protocol]


@pytest.fixture
def peer(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[ExecClient, Mock, threading.BoundedSemaphore, threading.BoundedSemaphore]:
    connection_slots = threading.BoundedSemaphore(1)
    upload_slots = threading.BoundedSemaphore(1)
    api_client = Mock(spec=transport._ExecApiClient)
    api_client.cancelled = threading.Event()
    api_client.cancel.side_effect = api_client.cancelled.set
    websocket = Mock(spec=transport._DeadlineWebSocket)
    api_client.websocket = websocket
    terminated = threading.Event()

    def send(payload: bytes, *, opcode: int) -> int:
        assert opcode == ABNF.OPCODE_BINARY
        if payload in (b"\xff\x00", b"\x00\x00\x00\x00\x00"):
            terminated.set()
        return len(payload)

    frames = iter(
        [
            ABNF.create_frame(b"\x01stdout-secret", ABNF.OPCODE_BINARY),
            ABNF.create_frame(b"\x02stderr-secret", ABNF.OPCODE_BINARY),
            ABNF.create_frame(b"\x03" + _STATUS, ABNF.OPCODE_BINARY),
            ABNF.create_frame(b"", ABNF.OPCODE_CLOSE),
        ]
    )

    def receive() -> ABNF:
        assert terminated.wait(2.0), "upload did not send its terminator"
        return next(frames)

    websocket.send.side_effect = send
    websocket.recv_frame.side_effect = receive
    core = Mock()
    core.connect_get_namespaced_pod_exec.return_value = websocket
    monkeypatch.setattr(transport, "_ExecApiClient", Mock(return_value=api_client))
    monkeypatch.setattr(transport.client, "CoreV1Api", Mock(return_value=core))
    monkeypatch.setattr(transport, "_CONNECT_SLOTS", connection_slots)
    monkeypatch.setattr(transport, "_UPLOAD_SLOTS", upload_slots)
    configuration = client.Configuration()
    configuration.host = "https://url-secret.invalid"
    configuration.api_key["authorization"] = "Bearer auth-secret"
    return (
        ExecClient(configuration, "namespace-secret"),
        api_client,
        connection_slots,
        upload_slots,
    )


def _assert_slot_released(slot: threading.BoundedSemaphore) -> None:
    assert slot.acquire(blocking=False)
    try:
        assert not slot.acquire(blocking=False)
    finally:
        slot.release()


@pytest.mark.parametrize(
    ("stdin", "protocol", "payloads"),
    [
        (
            b"stdin-secret",
            "v5.channel.k8s.io",
            [b"\x00stdin-secret", b"\xff\x00"],
        ),
        (
            io.BytesIO(b"stdin-secret"),
            "v5.channel.k8s.io",
            [b"\x00stdin-secret", b"\xff\x00"],
        ),
        (b"", "v5.channel.k8s.io", [b"\xff\x00"]),
        (io.BytesIO(), "v5.channel.k8s.io", [b"\xff\x00"]),
        (
            FramedStdin(b"stdin-secret"),
            "v4.channel.k8s.io",
            [b"\x00\x00\x00\x00\x0cstdin-secret", b"\x00\x00\x00\x00\x00"],
        ),
        (
            FramedStdin(io.BytesIO(b"stdin-secret")),
            "v4.channel.k8s.io",
            [b"\x00\x00\x00\x00\x0cstdin-secret", b"\x00\x00\x00\x00\x00"],
        ),
        (FramedStdin(None), "v4.channel.k8s.io", [b"\x00\x00\x00\x00\x00"]),
        (FramedStdin(b""), "v4.channel.k8s.io", [b"\x00\x00\x00\x00\x00"]),
        (
            FramedStdin(io.BytesIO()),
            "v4.channel.k8s.io",
            [b"\x00\x00\x00\x00\x00"],
        ),
    ],
)
def test_completion_preserves_wire_result_and_private_log_fields(
    peer: tuple[
        ExecClient, Mock, threading.BoundedSemaphore, threading.BoundedSemaphore
    ],
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    stdin: bytes | BinaryIO | FramedStdin,
    protocol: str,
    payloads: list[bytes],
) -> None:
    exec_client, api_client, connection_slots, upload_slots = peer
    api_client_factory = Mock(return_value=api_client)
    monkeypatch.setattr(transport, "_ExecApiClient", api_client_factory)
    with caplog.at_level(logging.INFO):
        result = exec_client.run(
            "pod-secret",
            ["command-secret", "metadata-secret"],
            stdin=stdin,
            timeout=3.0,
        )

    assert result.stdout == b"stdout-secret"
    assert result.stderr == "stderr-secret"
    assert result.returncode == 0
    assert api_client_factory.call_args.args[2] == protocol
    assert [
        call.args[0] for call in api_client.websocket.send.call_args_list
    ] == payloads
    byte_count = 12 if len(payloads) == 2 else 0
    assert sorted(caplog.messages) == sorted(
        [
            _PREFIX + "stage=connection outcome=complete",
            _PREFIX + "stage=upload outcome=start",
            _PREFIX
            + f"stage=upload outcome=complete bytes_sent={byte_count} terminator_written=True",
            _PREFIX + "stage=receive outcome=start",
            _PREFIX + "stage=receive outcome=complete status_bytes=20",
        ]
    )
    assert all(
        record.exc_info is None and record.levelno == logging.INFO
        for record in caplog.records
    )
    _assert_slot_released(connection_slots)
    _assert_slot_released(upload_slots)


def test_no_stdin_retains_v5_without_an_upload(
    peer: tuple[
        ExecClient, Mock, threading.BoundedSemaphore, threading.BoundedSemaphore
    ],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exec_client, api_client, connection_slots, upload_slots = peer
    api_client_factory = Mock(return_value=api_client)
    monkeypatch.setattr(transport, "_ExecApiClient", api_client_factory)
    api_client.websocket.recv_frame.side_effect = [
        ABNF.create_frame(b"\x01stdout-secret", ABNF.OPCODE_BINARY),
        ABNF.create_frame(b"\x03" + _STATUS, ABNF.OPCODE_BINARY),
        ABNF.create_frame(b"", ABNF.OPCODE_CLOSE),
    ]

    result = exec_client.run("pod-secret", ["command-secret"], timeout=3.0)

    assert result.stdout == b"stdout-secret"
    assert result.returncode == 0
    assert api_client_factory.call_args.args[2] == "v5.channel.k8s.io"
    api_client.websocket.send.assert_not_called()
    _assert_slot_released(connection_slots)
    _assert_slot_released(upload_slots)


@pytest.mark.parametrize("failure", ["source", "data_send", "terminator"])
def test_upload_failure_preserves_future_exception_and_releases_one_slot(
    peer: tuple[
        ExecClient, Mock, threading.BoundedSemaphore, threading.BoundedSemaphore
    ],
    caplog: pytest.LogCaptureFixture,
    failure: str,
) -> None:
    _, api_client, _, upload_slots = peer
    error = OSError("exception-message-secret")
    source = Mock(spec=io.BytesIO)
    source.read.side_effect = (
        [b"stdin-secret", error] if failure == "source" else [b"stdin-secret", b""]
    )
    if failure == "data_send":
        api_client.websocket.send.side_effect = error
    elif failure == "terminator":
        api_client.websocket.send.side_effect = [17, error]
    assert upload_slots.acquire(blocking=False)

    with caplog.at_level(logging.INFO):
        future = transport._start_upload(api_client, FramedStdin(source))
        with pytest.raises(OSError) as caught:
            future.result(timeout=2.0)
        assert api_client.cancelled.wait(2.0)

    assert caught.value is error
    assert future.exception() is error
    byte_count = 0 if failure == "data_send" else 12
    assert caplog.messages == [
        _PREFIX + "stage=upload outcome=start",
        _PREFIX
        + f"stage=upload outcome=failure bytes_sent={byte_count} terminator_written=False",
    ]
    assert all(record.exc_info is None for record in caplog.records)
    _assert_slot_released(upload_slots)


@pytest.mark.parametrize("cancel_during_read", [False, True])
def test_cancelled_upload_keeps_cancelled_future_and_omits_terminator(
    peer: tuple[
        ExecClient, Mock, threading.BoundedSemaphore, threading.BoundedSemaphore
    ],
    caplog: pytest.LogCaptureFixture,
    cancel_during_read: bool,
) -> None:
    _, api_client, _, upload_slots = peer
    source = Mock(spec=io.BytesIO)

    def read(_size: int) -> bytes:
        api_client.cancelled.set()
        return b"stdin-secret"

    source.read.side_effect = read
    if not cancel_during_read:
        api_client.cancelled.set()
    assert upload_slots.acquire(blocking=False)
    with caplog.at_level(logging.INFO):
        result = transport._start_upload(api_client, FramedStdin(source)).result(
            timeout=2.0
        )

    assert result == "cancelled"
    assert api_client.websocket.send.call_args_list == []
    assert source.read.call_count == int(cancel_during_read)
    assert caplog.messages == [
        _PREFIX + "stage=upload outcome=start",
        _PREFIX
        + "stage=upload outcome=cancelled bytes_sent=0 terminator_written=False",
    ]
    _assert_slot_released(upload_slots)


def test_receiver_failure_preserves_error_identity_and_partial_status_count(
    peer: tuple[
        ExecClient, Mock, threading.BoundedSemaphore, threading.BoundedSemaphore
    ],
    caplog: pytest.LogCaptureFixture,
) -> None:
    exec_client, api_client, connection_slots, upload_slots = peer
    error = SandboxExecError("receiver-error-secret")
    api_client.websocket.recv_frame.side_effect = [
        ABNF.create_frame(b"\x03private-status-secret", ABNF.OPCODE_BINARY),
        error,
    ]
    with caplog.at_level(logging.INFO), pytest.raises(SandboxExecError) as caught:
        exec_client.run(
            "pod-secret", ["command-secret"], stdin=FramedStdin(None), timeout=3.0
        )

    assert caught.value is error
    assert caplog.messages[-2:] == [
        _PREFIX + "stage=receive outcome=start",
        _PREFIX + "stage=receive outcome=failure status_bytes=21",
    ]
    assert "secret" not in caplog.text
    _assert_slot_released(connection_slots)
    _assert_slot_released(upload_slots)


def test_connection_failure_keeps_original_cause_and_releases_reserved_slots(
    peer: tuple[
        ExecClient, Mock, threading.BoundedSemaphore, threading.BoundedSemaphore
    ],
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exec_client, _, connection_slots, upload_slots = peer
    error = WebSocketConnectionClosedException("connection-secret")
    core = Mock()
    core.connect_get_namespaced_pod_exec.side_effect = error
    monkeypatch.setattr(transport.client, "CoreV1Api", Mock(return_value=core))
    with caplog.at_level(logging.INFO), pytest.raises(SandboxExecError) as caught:
        exec_client.run(
            "pod-secret",
            ["command-secret"],
            stdin=FramedStdin(b"stdin-secret"),
            timeout=3.0,
        )

    assert str(caught.value) == "Kubernetes exec connection failed"
    assert caught.value.__cause__ is error
    assert caplog.messages == []
    _assert_slot_released(connection_slots)
    _assert_slot_released(upload_slots)


def test_abandoned_stream_cancels_without_waiting_for_completion(
    peer: tuple[
        ExecClient, Mock, threading.BoundedSemaphore, threading.BoundedSemaphore
    ],
    caplog: pytest.LogCaptureFixture,
) -> None:
    exec_client, api_client, connection_slots, upload_slots = peer
    chunks = cast(
        Generator[bytes, None, None],
        exec_client.stream(
            "pod-secret", ["command-secret"], stdin=FramedStdin(None), timeout=3.0
        ),
    )
    with caplog.at_level(logging.INFO), closing(chunks):
        assert next(chunks) == b"stdout-secret"

    assert api_client.cancelled.is_set()
    assert (
        caplog.messages[-1] == _PREFIX + "stage=receive outcome=failure status_bytes=0"
    )
    assert next(chunks, b"closed") == b"closed"
    _assert_slot_released(connection_slots)
    _assert_slot_released(upload_slots)


def test_request_context_reaches_upload_thread(
    peer: tuple[
        ExecClient, Mock, threading.BoundedSemaphore, threading.BoundedSemaphore
    ],
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exec_client, _, _, _ = peer
    monkeypatch.setattr("onyx.utils.logger.JSON_LOGGING", False)
    token = ONYX_REQUEST_ID_CONTEXTVAR.set("safe-request-id")
    try:
        with caplog.at_level(logging.INFO):
            result = exec_client.run(
                "pod-secret",
                ["command-secret"],
                stdin=FramedStdin(b"stdin-secret"),
                timeout=3.0,
            )
    finally:
        ONYX_REQUEST_ID_CONTEXTVAR.reset(token)

    assert result.stdout == b"stdout-secret"
    assert len(caplog.messages) == 5
    assert all(
        message.startswith("[safe-request-id] " + _PREFIX)
        for message in caplog.messages
    )
    upload_records = [
        record for record in caplog.records if "stage=upload" in record.getMessage()
    ]
    assert [record.threadName for record in upload_records] == [
        "sandbox-exec-stdin",
        "sandbox-exec-stdin",
    ]
