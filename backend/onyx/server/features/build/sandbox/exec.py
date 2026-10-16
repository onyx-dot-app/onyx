import copy
import io
import json
import math
import socket
import ssl
import threading
import time
from collections.abc import Generator, Iterator, Sequence
from concurrent.futures import Future
from contextlib import closing
from dataclasses import dataclass
from typing import Any, BinaryIO, Literal, cast

import certifi
from kubernetes import client
from kubernetes.stream.ws_client import get_websocket_url, websocket_proxycare
from websocket import (
    ABNF,
    WebSocket,
    WebSocketConnectionClosedException,
    WebSocketException,
    WebSocketTimeoutException,
)

from onyx.server.features.build.sandbox.image.guest.input import MAX_FRAME_BYTES
from onyx.server.features.build.sandbox.models import ExecResult, SandboxExecError
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import start_thread_future

logger = setup_logger()

_PROTOCOL = "v5.channel.k8s.io"
_CHUNK_BYTES = MAX_FRAME_BYTES
_DIAGNOSTIC_BYTES = 64 * 1024
_CAPTURE_BYTES = 16 * 1024 * 1024
_FRAME_BYTES = 1024 * 1024
_CONNECT_SLOTS = threading.BoundedSemaphore(8)
_UPLOAD_SLOTS = threading.BoundedSemaphore(8)


@dataclass(frozen=True)
class FramedStdin:
    """Finite helper input without closing the CRI stdin channel."""

    source: bytes | BinaryIO | None


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("Sandbox exec deadline exceeded")
    return remaining


def _reserve_slot(
    slots: threading.BoundedSemaphore, deadline: float, operation: str
) -> None:
    if not slots.acquire(timeout=_remaining(deadline)):
        raise TimeoutError(f"Sandbox exec {operation} capacity deadline exceeded")


class _DeadlineWebSocket(WebSocket):
    def __init__(self, deadline: float, ssl_options: dict[str, Any]) -> None:
        super().__init__(sslopt=ssl_options)
        self.deadline = deadline

    def _recv(self, bufsize: int) -> bytes:
        length = self.frame_buffer.length
        if length is not None and length > _FRAME_BYTES:
            raise SandboxExecError("Kubernetes exec frame exceeds limit")
        self.settimeout(_remaining(self.deadline))
        return cast(bytes, super()._recv(bufsize))

    def _send(self, data: str | bytes) -> int:
        self.settimeout(_remaining(self.deadline))
        return cast(int, super()._send(data))


class _ExecApiClient(client.ApiClient):
    """Keep generated Kubernetes authentication and URL encoding per connection."""

    def __init__(self, configuration: client.Configuration, deadline: float) -> None:
        super().__init__(configuration=configuration)
        ssl_options: dict[str, Any] = {
            "cert_reqs": ssl.CERT_REQUIRED
            if configuration.verify_ssl
            else ssl.CERT_NONE,
        }
        if configuration.verify_ssl:
            ssl_options["ca_certs"] = configuration.ssl_ca_cert or certifi.where()
            if configuration.assert_hostname is not None:
                ssl_options["check_hostname"] = configuration.assert_hostname
        if configuration.cert_file:
            ssl_options["certfile"] = configuration.cert_file
        if configuration.key_file:
            ssl_options["keyfile"] = configuration.key_file
        if configuration.tls_server_name:
            ssl_options["server_hostname"] = configuration.tls_server_name
        self.websocket = _DeadlineWebSocket(deadline, ssl_options)
        self.cancelled = threading.Event()

    def request(
        self,
        method: str,
        url: str,
        query_params: list[tuple[str, Any]] | None = None,
        headers: dict[str, str] | None = None,
        post_params: Any = None,
        body: Any = None,
        _preload_content: bool = True,
        _request_timeout: Any = None,
    ) -> _DeadlineWebSocket:
        if method != "GET" or post_params or body is not None:
            raise SandboxExecError("Invalid Kubernetes exec request")
        if self.cancelled.is_set():
            raise TimeoutError("Sandbox exec connection cancelled")
        websocket_url = get_websocket_url(url, query_params)
        options: dict[str, Any] = {
            "header": headers or {},
            "subprotocols": [_PROTOCOL],
            "timeout": _remaining(self.websocket.deadline),
            "redirect_limit": 0,
        }
        if self.configuration.proxy or self.configuration.proxy_headers:
            options = websocket_proxycare(
                options, self.configuration, websocket_url, headers
            )
        try:
            self.websocket.connect(websocket_url, **options)
            _remaining(self.websocket.deadline)
            if self.websocket.getsubprotocol() != _PROTOCOL:
                raise SandboxExecError("Kubernetes exec requires WebSocket v5")
            return self.websocket
        finally:
            if self.cancelled.is_set():
                self.websocket.shutdown()

    def cancel(self, *_args: Any) -> None:
        self.cancelled.set()
        sock = self.websocket.sock
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        self.websocket.shutdown()


class _Output:
    def __init__(self) -> None:
        self.stderr = bytearray()
        self.status = bytearray()

    def receive(self, websocket: _DeadlineWebSocket) -> Iterator[bytes]:
        while True:
            try:
                opcode, data = _receive(websocket)
            except WebSocketConnectionClosedException:
                if not self.status:
                    raise
                return
            if opcode == ABNF.OPCODE_CLOSE:
                return
            if opcode in (ABNF.OPCODE_PING, ABNF.OPCODE_PONG):
                continue
            payload = self.accept(opcode, data)
            if payload:
                yield payload

    def stderr_text(self) -> str:
        return (
            self.stderr.decode("utf-8", errors="replace")
            .encode("utf-8")[:_DIAGNOSTIC_BYTES]
            .decode("utf-8", errors="ignore")
        )

    def accept(self, opcode: int, data: bytes) -> bytes | None:
        if opcode != ABNF.OPCODE_BINARY or not data:
            raise SandboxExecError("Invalid Kubernetes exec binary frame")
        channel, payload = data[0], data[1:]
        if channel == 1:
            return payload
        if channel == 2:
            self.stderr.extend(payload[: max(0, _DIAGNOSTIC_BYTES - len(self.stderr))])
        elif channel == 3:
            if len(self.status) + len(payload) > _DIAGNOSTIC_BYTES:
                raise SandboxExecError("Kubernetes exec status exceeds limit")
            self.status.extend(payload)
        elif channel != 255 or len(payload) != 1 or payload[0] not in (0, 1, 2, 3):
            raise SandboxExecError("Unexpected Kubernetes exec channel")
        return None

    def validate_exit(self) -> None:
        try:
            status = json.loads(self.status)
        except (ValueError, UnicodeError) as exc:
            raise SandboxExecError(
                "Missing or malformed Kubernetes exec status"
            ) from exc
        if not isinstance(status, dict):
            raise SandboxExecError("Malformed Kubernetes exec status")
        if status.get("status") == "Success" and status.get("code", 0) == 0:
            return
        if (
            status.get("status") == "Failure"
            and status.get("reason") == "NonZeroExitCode"
        ):
            details = status.get("details")
            causes = details.get("causes") if isinstance(details, dict) else None
            if isinstance(causes, list):
                exit_codes = [
                    cause.get("message")
                    for cause in causes
                    if isinstance(cause, dict) and cause.get("reason") == "ExitCode"
                ]
                if len(exit_codes) == 1:
                    value = exit_codes[0]
                    if (
                        isinstance(value, str)
                        and len(value) <= 3
                        and value.isascii()
                        and value.isdecimal()
                    ):
                        returncode = int(value)
                        if 1 <= returncode <= 255:
                            raise SandboxExecError(
                                f"Sandbox command exited with status {returncode}",
                                returncode=returncode,
                                stderr=self.stderr_text(),
                            )
        message = status.get("message")
        if status.get("status") == "Failure" and isinstance(message, str):
            raise SandboxExecError(f"Kubernetes exec failed: {message[:1024]}")
        raise SandboxExecError("Invalid Kubernetes exec completion status")


def _stdin_chunks(stdin: bytes | BinaryIO | None) -> Iterator[bytes]:
    if isinstance(stdin, bytes):
        for offset in range(0, len(stdin), _CHUNK_BYTES):
            yield stdin[offset : offset + _CHUNK_BYTES]
    elif stdin is not None:
        while True:
            chunk = stdin.read(_CHUNK_BYTES)
            if not isinstance(chunk, bytes) or len(chunk) > _CHUNK_BYTES:
                raise SandboxExecError("Sandbox exec stdin must return bounded bytes")
            if not chunk:
                return
            yield chunk


def _receive(websocket: _DeadlineWebSocket) -> tuple[int, bytes]:
    frame = websocket.recv_frame()
    if not frame.fin:
        raise SandboxExecError("Fragmented Kubernetes exec frame")
    data = cast(bytes, frame.data)
    opcode = frame.opcode
    if not isinstance(opcode, int):
        raise SandboxExecError("Invalid Kubernetes exec opcode")
    if opcode == ABNF.OPCODE_PING:
        websocket.pong(data)
    return opcode, data


def _start_upload(
    api_client: _ExecApiClient, stdin: bytes | BinaryIO | FramedStdin
) -> Future[Literal["complete", "cancelled"]]:
    def upload() -> Literal["complete", "cancelled"]:
        bytes_sent = 0
        outcome: Literal["complete", "cancelled", "failure"] = "failure"
        try:
            logger.info("Sandbox exec transport stage=upload outcome=start")
            framed = isinstance(stdin, FramedStdin)
            source = stdin.source if isinstance(stdin, FramedStdin) else stdin
            chunks = _stdin_chunks(source)
            while not api_client.cancelled.is_set():
                chunk = next(chunks, None)
                if chunk is None:
                    break
                if api_client.cancelled.is_set():
                    outcome = "cancelled"
                    return "cancelled"
                payload = len(chunk).to_bytes(4, "big") + chunk if framed else chunk
                api_client.websocket.send(b"\x00" + payload, opcode=ABNF.OPCODE_BINARY)
                bytes_sent += len(chunk)
            if api_client.cancelled.is_set():
                outcome = "cancelled"
                return "cancelled"
            api_client.websocket.send(
                b"\x00\x00\x00\x00\x00" if framed else b"\xff\x00",
                opcode=ABNF.OPCODE_BINARY,
            )
            outcome = "complete"
            return "complete"
        finally:
            _UPLOAD_SLOTS.release()
            logger.info(
                "Sandbox exec transport stage=upload outcome=%s bytes_sent=%d "
                "terminator_written=%s",
                outcome,
                bytes_sent,
                outcome == "complete",
            )

    def cancel_failed_upload(result: Future[Literal["complete", "cancelled"]]) -> None:
        if result.exception() is not None:
            api_client.cancel()

    result = start_thread_future(upload, name="sandbox-exec-stdin")
    result.add_done_callback(cancel_failed_upload)
    return result


class ExecClient:
    """Transport immutable guest commands; guest operations consume stdin first."""

    def __init__(self, configuration: client.Configuration, namespace: str) -> None:
        self.configuration = copy.deepcopy(configuration)
        self.namespace = namespace

    def _exchange(
        self,
        pod_name: str,
        command: Sequence[object],
        stdin: bytes | BinaryIO | FramedStdin | None,
        timeout: float,
        output: _Output,
    ) -> Generator[bytes, None, None]:
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("Sandbox exec timeout must be finite and positive")
        if not command or any(
            not isinstance(arg, str) or "\0" in arg for arg in command
        ):
            raise ValueError("Sandbox exec requires a nonempty argument list")
        deadline = time.monotonic() + timeout
        api_client = _ExecApiClient(self.configuration, deadline)
        websocket = api_client.websocket
        upload_result: Future[Literal["complete", "cancelled"]] | None = None
        upload_slot_reserved = False
        inline_input = isinstance(stdin, FramedStdin) and stdin.source is None

        def connect() -> _DeadlineWebSocket:
            try:
                return cast(
                    _DeadlineWebSocket,
                    client.CoreV1Api(api_client).connect_get_namespaced_pod_exec(
                        pod_name,
                        self.namespace,
                        command=list(command),
                        stdin=stdin is not None,
                        stdout=True,
                        stderr=True,
                        tty=False,
                        _preload_content=False,
                        _request_timeout=_remaining(deadline),
                    ),
                )
            finally:
                _CONNECT_SLOTS.release()

        try:
            if stdin is not None and not inline_input:
                _reserve_slot(_UPLOAD_SLOTS, deadline, "upload")
                upload_slot_reserved = True
            # Bound DNS, TLS, authentication, and upgrade as one connection operation.
            _reserve_slot(_CONNECT_SLOTS, deadline, "connection")
            try:
                connection = start_thread_future(connect, name="sandbox-exec-connect")
            except BaseException:
                _CONNECT_SLOTS.release()
                raise
            connection.result(timeout=_remaining(deadline))
            logger.info("Sandbox exec transport stage=connection outcome=complete")

            # Receive while uploading so early guest failures cannot block behind stdin.
            if inline_input:
                logger.info("Sandbox exec transport stage=upload outcome=start")
                websocket.send(b"\x00\x00\x00\x00\x00", opcode=ABNF.OPCODE_BINARY)
                logger.info(
                    "Sandbox exec transport stage=upload outcome=complete "
                    "bytes_sent=0 terminator_written=True"
                )
            elif stdin is not None:
                upload_result = _start_upload(api_client, stdin)
                upload_slot_reserved = False
            receive_outcome = "failure"
            logger.info("Sandbox exec transport stage=receive outcome=start")
            try:
                yield from output.receive(websocket)
                receive_outcome = "complete"
            finally:
                logger.info(
                    "Sandbox exec transport stage=receive outcome=%s status_bytes=%d",
                    receive_outcome,
                    len(output.status),
                )
            output.validate_exit()
            if upload_result is not None:
                if upload_result.result(timeout=_remaining(deadline)) != "complete":
                    raise SandboxExecError("Sandbox exec stdin upload cancelled")
        except SandboxExecError as exc:
            if not exc.stderr:
                exc.stderr = output.stderr_text()
            raise
        except (TimeoutError, WebSocketTimeoutException) as exc:
            raise SandboxExecError(
                "Sandbox exec deadline exceeded", stderr=output.stderr_text()
            ) from exc
        except (OSError, WebSocketException) as exc:
            if upload_result is not None and upload_result.done():
                upload_error = upload_result.exception()
                if upload_error is not None:
                    raise SandboxExecError(
                        "Sandbox exec stdin upload failed", stderr=output.stderr_text()
                    ) from upload_error
            raise SandboxExecError(
                "Kubernetes exec connection failed", stderr=output.stderr_text()
            ) from exc
        finally:
            try:
                api_client.cancel()
                api_client.close()
            finally:
                if upload_slot_reserved:
                    _UPLOAD_SLOTS.release()

    def run(
        self,
        pod_name: str,
        command: Sequence[str],
        *,
        stdin: bytes | BinaryIO | FramedStdin | None = None,
        timeout: float,
    ) -> ExecResult:
        """Capture stdout; FramedStdin holds CRI stdin open until completion.

        Raw input ends with v5 EOF. The caller owns and cancels blocked source reads.
        """
        output = _Output()
        with (
            io.BytesIO() as stdout,
            closing(
                self._exchange(pod_name, command, stdin, timeout, output)
            ) as chunks,
        ):
            for chunk in chunks:
                if stdout.tell() + len(chunk) > _CAPTURE_BYTES:
                    raise SandboxExecError(
                        "Sandbox exec output exceeds 16 MiB capture limit",
                        stderr=output.stderr_text(),
                    )
                stdout.write(chunk)
            return ExecResult(
                stdout=stdout.getvalue(), stderr=output.stderr_text(), returncode=0
            )

    def stream(
        self,
        pod_name: str,
        command: Sequence[str],
        *,
        stdin: bytes | BinaryIO | FramedStdin | None = None,
        timeout: float,
    ) -> Iterator[bytes]:
        """Close abandoned iterators and cancel blocked caller-owned source reads.

        FramedStdin holds CRI stdin open. Raw None disables stdin; bytes use v5 EOF.
        """
        yield from self._exchange(pod_name, command, stdin, timeout, _Output())
