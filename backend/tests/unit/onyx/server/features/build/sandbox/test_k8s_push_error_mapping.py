"""K8s push error mapping tests (pure logic, no K8s needed).

Behavior assertions for ``KubernetesSandboxManager.write_files_to_sandbox``.
We mock ``httpx.Client`` (an external HTTP boundary) and
``CoreV1Api.read_namespaced_pod`` (the K8s API boundary) to inject failure
modes. All assertions target observable outcomes (raised exception types and
tar byte equality), not call lists.
"""

from __future__ import annotations

import base64
from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch
from uuid import UUID
from uuid import uuid4

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding
from cryptography.hazmat.primitives.serialization import NoEncryption
from cryptography.hazmat.primitives.serialization import PrivateFormat
from kubernetes.client.rest import ApiException

from onyx.server.features.build.sandbox.kubernetes.kubernetes_sandbox_manager import (
    _build_targz,
)
from onyx.server.features.build.sandbox.kubernetes.kubernetes_sandbox_manager import (
    KubernetesSandboxManager,
)
from onyx.server.features.build.sandbox.models import FatalWriteError
from onyx.server.features.build.sandbox.models import FileSet
from onyx.server.features.build.sandbox.models import RetriableWriteError

# Path to httpx.Client as imported inside the manager module. Mocking it there
# replaces the symbol used by write_files_to_sandbox without affecting other
# httpx users in the process.
_HTTPX_CLIENT_PATH = (
    "onyx.server.features.build.sandbox.kubernetes."
    "kubernetes_sandbox_manager.httpx.Client"
)
_MANAGER_MODULE = (
    "onyx.server.features.build.sandbox.kubernetes.kubernetes_sandbox_manager"
)


def _generate_dev_push_key_b64() -> str:
    """Generate a fresh Ed25519 private key seed encoded for the manager env var."""
    key = Ed25519PrivateKey.generate()
    seed = key.private_bytes(
        encoding=Encoding.Raw,
        format=PrivateFormat.Raw,
        encryption_algorithm=NoEncryption(),
    )
    return base64.b64encode(seed).decode()


@pytest.fixture(autouse=True)
def _push_private_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set the push private key env var and clear the cached key module globals.

    ``_get_push_key_pair`` caches the key as a module-level global; reset it
    so each test sees a fresh key. The test doesn't care about the actual key
    value, only that signing works.
    """
    import onyx.server.features.build.sandbox.kubernetes.kubernetes_sandbox_manager as ksm

    monkeypatch.setenv("ONYX_SANDBOX_PUSH_PRIVATE_KEY", _generate_dev_push_key_b64())
    monkeypatch.setattr(ksm, "_push_private_key", None, raising=False)
    monkeypatch.setattr(ksm, "_push_public_key_b64", None, raising=False)


def _make_manager(
    *, pod_ip: str | None = "10.0.0.1", read_pod_exc: Exception | None = None
) -> KubernetesSandboxManager:
    """Construct a manager without invoking _initialize (which needs a K8s config).

    The only attributes write_files_to_sandbox touches are ``_core_api`` and
    ``_namespace``. Bypass ``__new__`` cache with object.__new__ so each test
    gets a fresh instance (singleton would otherwise leak between tests).
    """
    mgr: KubernetesSandboxManager = object.__new__(KubernetesSandboxManager)

    core_api = MagicMock()
    if read_pod_exc is not None:
        core_api.read_namespaced_pod.side_effect = read_pod_exc
    else:
        pod_obj = MagicMock()
        pod_obj.status.pod_ip = pod_ip
        core_api.read_namespaced_pod.return_value = pod_obj

    mgr._core_api = core_api  # type: ignore[attr-defined]
    mgr._namespace = "sandbox-test"  # type: ignore[attr-defined]
    return mgr


def _mock_httpx_client(
    *,
    response_status: int | None = None,
    response_text: str = "",
    raise_exc: Exception | None = None,
) -> MagicMock:
    """Return a MagicMock suitable for patching ``httpx.Client``.

    The manager uses ``with httpx.Client(timeout=...) as http_client``; the
    mock has to support the context-manager protocol.
    """
    client_instance = MagicMock()
    if raise_exc is not None:
        client_instance.post.side_effect = raise_exc
    else:
        resp = MagicMock()
        resp.status_code = response_status
        resp.text = response_text
        client_instance.post.return_value = resp

    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=client_instance)
    ctx.__exit__ = MagicMock(return_value=False)

    factory = MagicMock(return_value=ctx)
    return factory


def _sandbox_id() -> UUID:
    return uuid4()


def _files() -> FileSet:
    return {"my-skill/SKILL.md": b"# hello\n"}


# ---------------------------------------------------------------------------
# Pod-read failure modes
# ---------------------------------------------------------------------------


def test_pod_404_raises_fatal_write_error() -> None:
    mgr = _make_manager(read_pod_exc=ApiException(status=404, reason="Not Found"))
    with pytest.raises(FatalWriteError, match="not found"):
        mgr.write_files_to_sandbox(
            sandbox_id=_sandbox_id(),
            mount_path="/workspace/managed/skills",
            files=_files(),
        )


def test_pod_has_no_ip_yet_raises_retriable() -> None:
    mgr = _make_manager(pod_ip=None)
    with pytest.raises(RetriableWriteError, match="no IP"):
        mgr.write_files_to_sandbox(
            sandbox_id=_sandbox_id(),
            mount_path="/workspace/managed/skills",
            files=_files(),
        )


def test_pod_non_404_api_error_raises_retriable() -> None:
    """500 from the K8s API is transient -> retriable.

    Follows the same contract; kept under the same file because it shares
    the read-pod seam.
    """
    mgr = _make_manager(read_pod_exc=ApiException(status=500, reason="Server Error"))
    with pytest.raises(RetriableWriteError, match="Failed to read pod"):
        mgr.write_files_to_sandbox(
            sandbox_id=_sandbox_id(),
            mount_path="/workspace/managed/skills",
            files=_files(),
        )


# ---------------------------------------------------------------------------
# Daemon HTTP response mapping
# ---------------------------------------------------------------------------


def test_daemon_5xx_raises_retriable() -> None:
    mgr = _make_manager()
    factory = _mock_httpx_client(response_status=503, response_text="overloaded")
    with patch(_HTTPX_CLIENT_PATH, factory):
        with pytest.raises(RetriableWriteError, match="503"):
            mgr.write_files_to_sandbox(
                sandbox_id=_sandbox_id(),
                mount_path="/workspace/managed/skills",
                files=_files(),
            )


def test_daemon_401_raises_fatal() -> None:
    mgr = _make_manager()
    factory = _mock_httpx_client(response_status=401, response_text="bad signature")
    with patch(_HTTPX_CLIENT_PATH, factory):
        with pytest.raises(FatalWriteError, match="401"):
            mgr.write_files_to_sandbox(
                sandbox_id=_sandbox_id(),
                mount_path="/workspace/managed/skills",
                files=_files(),
            )


def test_daemon_400_raises_fatal() -> None:
    mgr = _make_manager()
    factory = _mock_httpx_client(response_status=400, response_text="sha mismatch")
    with patch(_HTTPX_CLIENT_PATH, factory):
        with pytest.raises(FatalWriteError, match="400"):
            mgr.write_files_to_sandbox(
                sandbox_id=_sandbox_id(),
                mount_path="/workspace/managed/skills",
                files=_files(),
            )


def test_daemon_413_raises_fatal() -> None:
    mgr = _make_manager()
    factory = _mock_httpx_client(response_status=413, response_text="too big")
    with patch(_HTTPX_CLIENT_PATH, factory):
        with pytest.raises(FatalWriteError, match="413"):
            mgr.write_files_to_sandbox(
                sandbox_id=_sandbox_id(),
                mount_path="/workspace/managed/skills",
                files=_files(),
            )


@pytest.mark.parametrize(
    "exc",
    [
        # Timeout family.
        httpx.TimeoutException("timeout"),
        # Network family (refused / reset / DNS).
        httpx.ConnectError("connection refused"),
        # Protocol family — raised when the sidecar accepts a TCP connection
        # but sends a malformed/partial HTTP response (typical during uvicorn
        # startup or graceful shutdown). Subclass of httpx.ProtocolError,
        # NOT of NetworkError; only a TransportError catch picks it up.
        httpx.RemoteProtocolError("server disconnected without sending a response"),
    ],
    ids=["timeout", "connect-error", "remote-protocol-error"],
)
def test_transport_error_raises_retriable(exc: httpx.HTTPError) -> None:
    mgr = _make_manager()
    factory = _mock_httpx_client(raise_exc=exc)
    with patch(_HTTPX_CLIENT_PATH, factory):
        with pytest.raises(RetriableWriteError, match="failed"):
            mgr.write_files_to_sandbox(
                sandbox_id=_sandbox_id(),
                mount_path="/workspace/managed/skills",
                files=_files(),
            )


def test_2xx_returns_success() -> None:
    mgr = _make_manager()
    factory = _mock_httpx_client(response_status=200, response_text="ok")
    with patch(_HTTPX_CLIENT_PATH, factory):
        # No exception = success.
        mgr.write_files_to_sandbox(
            sandbox_id=_sandbox_id(),
            mount_path="/workspace/managed/skills",
            files=_files(),
        )


# ---------------------------------------------------------------------------
# health_check: must always return a bool, never propagate transport errors
# ---------------------------------------------------------------------------


def test_health_check_returns_false_on_remote_protocol_error() -> None:
    """RemoteProtocolError is the realistic failure mode during sidecar
    startup/shutdown (TCP accepts, partial HTTP response). It's a subclass
    of httpx.ProtocolError, not NetworkError — a narrow ``(TimeoutException,
    NetworkError)`` catch would let it propagate and break the bool
    contract.
    """
    mgr = _make_manager()
    factory = _mock_httpx_client(
        raise_exc=httpx.RemoteProtocolError("server disconnected")
    )
    with patch(_HTTPX_CLIENT_PATH, factory):
        # Bool contract: any transport failure becomes False.
        assert mgr.health_check(_sandbox_id(), timeout=1.0) is False


# ---------------------------------------------------------------------------
# Bundle building
# ---------------------------------------------------------------------------


def test_bundle_over_100mib_rejected_before_send(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Oversized FileSet raises FatalWriteError before httpx is invoked.

    Patches _MAX_BUNDLE_BYTES down to keep the test fast while still asserting
    the size-cap behavior: ``_build_targz`` rejects oversized input. We also
    patch ``httpx.Client`` to a factory that fails if called, proving the
    rejection happens before any network attempt.
    """
    monkeypatch.setattr(f"{_MANAGER_MODULE}._MAX_BUNDLE_BYTES", 1024)

    mgr = _make_manager()
    httpx_called = False

    def _fail_factory(*_: Any, **__: Any) -> Any:
        nonlocal httpx_called
        httpx_called = True
        raise AssertionError(
            "httpx.Client should not be constructed for oversized bundles"
        )

    with patch(_HTTPX_CLIENT_PATH, _fail_factory):
        with pytest.raises(FatalWriteError, match="exceeds"):
            mgr.write_files_to_sandbox(
                sandbox_id=_sandbox_id(),
                mount_path="/workspace/managed/skills",
                files={"big.bin": b"x" * 2048},
            )

    assert httpx_called is False


def test_tar_build_is_byte_for_byte_deterministic() -> None:
    """Same fileset built twice produces identical tar bytes."""
    files: FileSet = {
        "skill-a/SKILL.md": b"alpha contents\n",
        "skill-b/SKILL.md": b"beta contents\n",
        "skill-a/nested/file.txt": b"nested\n",
    }
    raw1, sha1 = _build_targz(files)
    raw2, sha2 = _build_targz(files)

    assert raw1 == raw2
    assert sha1 == sha2
