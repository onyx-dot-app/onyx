"""HTTP client for the in-pod sandbox sidecar."""

from __future__ import annotations

import base64
import binascii
import hashlib
import time
from collections.abc import Callable
from collections.abc import Iterator
from contextlib import contextmanager
from typing import cast
from typing import IO
from uuid import UUID

import httpx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding
from cryptography.hazmat.primitives.serialization import PublicFormat

from onyx.server.features.build.configs import SANDBOX_PUSH_PRIVATE_KEY
from onyx.server.features.build.sandbox.image.sandbox_daemon.contract import (
    FilesystemListRequest,
)
from onyx.server.features.build.sandbox.image.sandbox_daemon.contract import (
    FilesystemListResponse,
)
from onyx.server.features.build.sandbox.image.sandbox_daemon.contract import (
    PUSH_DAEMON_PORT,
)
from onyx.server.features.build.sandbox.image.sandbox_daemon.contract import (
    SIDECAR_FILESYSTEM_LIST_PATH,
)
from onyx.server.features.build.sandbox.image.sandbox_daemon.contract import (
    SIDECAR_HEALTH_PATH,
)
from onyx.server.features.build.sandbox.image.sandbox_daemon.contract import (
    SIDECAR_PUSH_PATH,
)
from onyx.server.features.build.sandbox.models import FilesystemEntry

_SIDECAR_CHUNK_SIZE = 8 * 1024 * 1024

_push_private_key: Ed25519PrivateKey | None = None
_push_public_key_b64: str | None = None


class SidecarRequestError(RuntimeError):
    """The sidecar could not be reached before the request deadline."""


class SidecarStatusError(RuntimeError):
    """The sidecar responded, but with an unexpected HTTP status."""

    def __init__(self, operation_label: str, status_code: int, body: str) -> None:
        self.operation_label = operation_label
        self.status_code = status_code
        self.body = body
        super().__init__(f"{operation_label} failed: {status_code} {body}")


class _IteratorReader:
    """Adapts an iterator of bytes into a ``read(n)``-based reader."""

    def __init__(self, iterator: Iterator[bytes]) -> None:
        self._iterator = iterator
        self._buf = b""

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            data = self._buf + b"".join(self._iterator)
            self._buf = b""
            return data

        while len(self._buf) < size:
            try:
                self._buf += next(self._iterator)
            except StopIteration:
                break

        data, self._buf = self._buf[:size], self._buf[size:]
        return data

    def readable(self) -> bool:
        return True


def get_push_key_pair() -> tuple[Ed25519PrivateKey, str]:
    global _push_private_key, _push_public_key_b64
    if _push_private_key is not None and _push_public_key_b64 is not None:
        return _push_private_key, _push_public_key_b64

    if not SANDBOX_PUSH_PRIVATE_KEY:
        raise RuntimeError("ONYX_SANDBOX_PUSH_PRIVATE_KEY is not set")

    try:
        seed = base64.b64decode(SANDBOX_PUSH_PRIVATE_KEY)
        _push_private_key = Ed25519PrivateKey.from_private_bytes(seed)
    except (binascii.Error, ValueError) as e:
        raise RuntimeError(
            "ONYX_SANDBOX_PUSH_PRIVATE_KEY is not a valid base64-encoded "
            f"32-byte Ed25519 seed: {e}"
        ) from e

    pub_bytes = _push_private_key.public_key().public_bytes(
        Encoding.Raw, PublicFormat.Raw
    )
    _push_public_key_b64 = base64.b64encode(pub_bytes).decode()
    return _push_private_key, _push_public_key_b64


def _sign_sidecar_request(path: str, sha256_hex: str) -> tuple[str, str]:
    """Sign a sidecar request and return ``(signature_b64, timestamp)``."""
    priv_key, _ = get_push_key_pair()
    ts = str(int(time.time()))
    message = f"{ts}|{path}|{sha256_hex}".encode()
    sig = priv_key.sign(message)
    return base64.b64encode(sig).decode(), ts


class SidecarClient:
    """Signed HTTP client for one sandbox sidecar.

    The manager supplies the host resolver so Kubernetes-specific discovery stays
    outside this transport class. The client owns the repeated request details:
    URL construction, signatures, timeouts, and response status handling.
    """

    def __init__(self, host: Callable[[UUID], str]) -> None:
        self._host = host

    def is_healthy(self, *, sandbox_id: UUID, timeout_seconds: float) -> bool:
        url = self._url(self._host(sandbox_id), SIDECAR_HEALTH_PATH)
        try:
            with httpx.Client(timeout=timeout_seconds) as http_client:
                return http_client.get(url).status_code == 200
        except httpx.TransportError:
            return False

    def list_directory(
        self,
        *,
        sandbox_id: UUID,
        session_id: UUID,
        path: str,
        timeout_seconds: float = 30.0,
    ) -> list[FilesystemEntry]:
        payload = FilesystemListRequest(session_id=session_id, path=path)
        body = payload.model_dump_json().encode()
        sha256_hex = hashlib.sha256(body).hexdigest()

        try:
            with httpx.Client(timeout=timeout_seconds) as http_client:
                resp = http_client.post(
                    self._url(self._host(sandbox_id), SIDECAR_FILESYSTEM_LIST_PATH),
                    content=body,
                    headers=self._signed_headers(
                        signing_path=SIDECAR_FILESYSTEM_LIST_PATH,
                        sha256_hex=sha256_hex,
                        content_type="application/json",
                    ),
                )
        except httpx.TransportError as e:
            raise SidecarRequestError(f"filesystem list request failed: {e}") from e

        if resp.status_code != 200:
            raise SidecarStatusError("filesystem list", resp.status_code, resp.text)

        listing = FilesystemListResponse.model_validate_json(resp.content)
        return [
            FilesystemEntry(
                name=entry.name,
                path=entry.path,
                is_directory=entry.is_directory,
                size=entry.size,
                mime_type=entry.mime_type,
            )
            for entry in listing.entries
        ]

    @contextmanager
    def request_and_stream_new_snapshot(
        self,
        *,
        sandbox_id: UUID,
        endpoint_path: str,
        body: bytes,
        content_type: str,
        operation_label: str,
        timeout_seconds: float,
    ) -> Iterator[IO[bytes] | None]:
        """POST to an archive-creation endpoint and stream its archive response."""
        sha256_hex = hashlib.sha256(body).hexdigest()
        timeout = httpx.Timeout(
            timeout_seconds,
            connect=min(30.0, timeout_seconds),
            read=timeout_seconds,
            write=timeout_seconds,
        )

        try:
            with httpx.Client(timeout=timeout) as http_client:
                with http_client.stream(
                    "POST",
                    self._url(self._host(sandbox_id), endpoint_path),
                    content=body,
                    headers=self._signed_headers(
                        signing_path=endpoint_path,
                        sha256_hex=sha256_hex,
                        content_type=content_type,
                    ),
                ) as resp:
                    if resp.status_code == 204:
                        yield None
                        return
                    if resp.status_code != 200:
                        detail = resp.read().decode(errors="replace")
                        raise SidecarStatusError(
                            operation_label, resp.status_code, detail
                        )

                    adapter = _IteratorReader(
                        resp.iter_bytes(chunk_size=_SIDECAR_CHUNK_SIZE)
                    )
                    yield cast(IO[bytes], adapter)
                    return
        except httpx.TransportError as e:
            raise SidecarRequestError(f"{operation_label} request failed: {e}") from e

    def post_archive(
        self,
        *,
        sandbox_id: UUID,
        endpoint_path: str,
        archive_file: IO[bytes],
        sha256_hex: str,
        operation_label: str,
        timeout_seconds: float = 300.0,
    ) -> None:
        def body() -> Iterator[bytes]:
            archive_file.seek(0)
            return iter(lambda: archive_file.read(_SIDECAR_CHUNK_SIZE), b"")

        self._post(
            endpoint_path=endpoint_path,
            signing_path=endpoint_path,
            body=body,
            sha256_hex=sha256_hex,
            content_type="application/gzip",
            operation_label=operation_label,
            expected_status=204,
            timeout_seconds=timeout_seconds,
            retry_until_deadline=True,
            sandbox_id=sandbox_id,
            headers={"X-Bundle-Sha256": sha256_hex},
        )

    def post_empty(
        self,
        *,
        sandbox_id: UUID,
        endpoint_path: str,
        operation_label: str,
        timeout_seconds: float = 300.0,
    ) -> None:
        body = b""
        self._post(
            endpoint_path=endpoint_path,
            signing_path=endpoint_path,
            body=lambda: body,
            sha256_hex=hashlib.sha256(body).hexdigest(),
            content_type="application/octet-stream",
            operation_label=operation_label,
            expected_status=204,
            timeout_seconds=timeout_seconds,
            retry_until_deadline=True,
            sandbox_id=sandbox_id,
        )

    def push_archive(
        self,
        *,
        sandbox_id: UUID,
        mount_path: str,
        archive: bytes,
        sha256_hex: str,
        operation_label: str,
        timeout_seconds: float,
    ) -> None:
        self._post(
            endpoint_path=SIDECAR_PUSH_PATH,
            signing_path=mount_path,
            body=lambda: archive,
            sha256_hex=sha256_hex,
            content_type="application/gzip",
            operation_label=operation_label,
            expected_status=200,
            timeout_seconds=timeout_seconds,
            retry_until_deadline=False,
            sandbox_id=sandbox_id,
            params={"mount_path": mount_path},
            headers={"X-Bundle-Sha256": sha256_hex},
        )

    def _post(
        self,
        *,
        endpoint_path: str,
        signing_path: str,
        body: Callable[[], bytes | Iterator[bytes]],
        sha256_hex: str,
        content_type: str,
        operation_label: str,
        expected_status: int,
        timeout_seconds: float,
        retry_until_deadline: bool,
        sandbox_id: UUID,
        params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        host = self._host(sandbox_id)
        last_exc: httpx.TransportError | None = None
        deadline = time.monotonic() + timeout_seconds

        while True:
            remaining = deadline - time.monotonic()
            if remaining > 0:
                try:
                    with httpx.Client(
                        timeout=self._timeout_for_post(remaining)
                    ) as http_client:
                        resp = http_client.post(
                            self._url(host, endpoint_path),
                            params=params,
                            content=body(),
                            headers={
                                **self._signed_headers(
                                    signing_path=signing_path,
                                    sha256_hex=sha256_hex,
                                    content_type=content_type,
                                ),
                                **(headers or {}),
                            },
                        )
                except httpx.TransportError as e:
                    last_exc = e
                else:
                    if resp.status_code == expected_status:
                        return
                    raise SidecarStatusError(
                        operation_label, resp.status_code, resp.text
                    )

            if not retry_until_deadline or time.monotonic() >= deadline:
                break
            time.sleep(min(0.5, max(0.0, deadline - time.monotonic())))

        raise SidecarRequestError(
            f"{operation_label} request failed: {last_exc or 'sandbox pod unreachable'}"
        )

    @staticmethod
    def _timeout_for_post(remaining_seconds: float) -> httpx.Timeout:
        return httpx.Timeout(
            remaining_seconds,
            connect=min(5.0, remaining_seconds),
            read=remaining_seconds,
            write=remaining_seconds,
        )

    @staticmethod
    def _signed_headers(
        *,
        signing_path: str,
        sha256_hex: str,
        content_type: str,
    ) -> dict[str, str]:
        sig_b64, ts = _sign_sidecar_request(signing_path, sha256_hex)
        return {
            "Content-Type": content_type,
            "X-Push-Signature": sig_b64,
            "X-Push-Timestamp": ts,
        }

    @staticmethod
    def _url(host: str, endpoint_path: str) -> str:
        return f"http://{host}:{PUSH_DAEMON_PORT}{endpoint_path}"
