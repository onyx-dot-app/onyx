"""K8s push error mapping tests (pure logic, no K8s needed).

Behavior assertions for ``KubernetesSandboxManager.write_files_to_sandbox``.
We mock ``httpx.Client`` (an external HTTP boundary) and
``CoreV1Api.read_namespaced_pod`` (the K8s API boundary) to inject failure
modes. All assertions target observable outcomes (raised exception types and
tar byte equality), not call lists.
"""

from __future__ import annotations

import base64
import hashlib
import io
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any
from typing import cast
from unittest.mock import MagicMock
from unittest.mock import patch
from uuid import UUID
from uuid import uuid4

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding
from cryptography.hazmat.primitives.serialization import NoEncryption
from cryptography.hazmat.primitives.serialization import PrivateFormat
from kubernetes import client
from kubernetes.client.rest import ApiException

from onyx.server.features.build.sandbox.image.sandbox_daemon.contract import (
    SIDECAR_OPENCODE_HISTORY_MARK_RESTORED_PATH,
)
from onyx.server.features.build.sandbox.image.sandbox_daemon.contract import (
    SIDECAR_OPENCODE_HISTORY_RESTORE_PATH,
)
from onyx.server.features.build.sandbox.image.sandbox_daemon.contract import (
    SIDECAR_PUSH_PATH,
)
from onyx.server.features.build.sandbox.image.sandbox_daemon.contract import (
    SIDECAR_SNAPSHOT_CREATE_PATH,
)
from onyx.server.features.build.sandbox.image.sandbox_daemon.contract import (
    sidecar_snapshot_restore_path,
)
from onyx.server.features.build.sandbox.kubernetes import sidecar_client
from onyx.server.features.build.sandbox.kubernetes.kubernetes_sandbox_manager import (
    _build_targz,
)
from onyx.server.features.build.sandbox.kubernetes.kubernetes_sandbox_manager import (
    KubernetesSandboxManager,
)
from onyx.server.features.build.sandbox.kubernetes.sidecar_client import SidecarClient
from onyx.server.features.build.sandbox.models import FatalWriteError
from onyx.server.features.build.sandbox.models import FileSet
from onyx.server.features.build.sandbox.models import LLMProviderConfig
from onyx.server.features.build.sandbox.models import RetriableWriteError

# Path to httpx.Client as imported inside the sidecar transport module.
_HTTPX_CLIENT_PATH = (
    "onyx.server.features.build.sandbox.kubernetes.sidecar_client.httpx.Client"
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

    ``get_push_key_pair`` caches the key as a module-level global; reset it
    so each test sees a fresh key. The test doesn't care about the actual key
    value, only that signing works.
    """
    import onyx.server.features.build.sandbox.kubernetes.sidecar_client as sidecar

    monkeypatch.setattr(
        sidecar, "SANDBOX_PUSH_PRIVATE_KEY", _generate_dev_push_key_b64()
    )
    monkeypatch.setattr(sidecar, "_push_private_key", None, raising=False)
    monkeypatch.setattr(sidecar, "_push_public_key_b64", None, raising=False)


def _service_host(mgr: KubernetesSandboxManager) -> Callable[[UUID], str]:
    """Mirror the manager's sidecar host resolver: the per-pod Service FQDN."""
    return lambda sandbox_id: (
        f"{mgr._get_pod_name(sandbox_id)}.{mgr._namespace}.svc.cluster.local"
    )


def _make_manager() -> KubernetesSandboxManager:
    """Construct a manager without invoking _initialize (which needs a K8s config).

    ``write_files_to_sandbox`` resolves the sidecar host via the Service FQDN,
    then POSTs over the mocked ``httpx.Client``. Bypass ``__new__`` cache with
    object.__new__.
    """
    mgr: KubernetesSandboxManager = object.__new__(KubernetesSandboxManager)

    core_api = MagicMock()
    pod_obj = MagicMock()
    pod_obj.status.container_statuses = [
        SimpleNamespace(
            name="sandbox",
            ready=True,
            state=SimpleNamespace(running=object(), terminated=None),
        )
    ]
    core_api.read_namespaced_pod.return_value = pod_obj

    mgr._core_api = core_api  # type: ignore[attr-defined]
    mgr._namespace = "sandbox-test"  # type: ignore[attr-defined]
    mgr._sidecar_client = SidecarClient(host=_service_host(mgr))  # type: ignore[attr-defined]
    return mgr


def _mock_httpx_client(
    *,
    response_status: int | None = None,
    response_text: str = "",
    raise_exc: Exception | None = None,
) -> MagicMock:
    """Return a MagicMock suitable for patching ``httpx.Client``.

    The sidecar client uses ``with httpx.Client(timeout=...) as http_client``; the
    mock has to support the context-manager protocol.
    """
    client_instance = MagicMock()
    if raise_exc is not None:
        client_instance.post.side_effect = raise_exc
        client_instance.get.side_effect = raise_exc
    else:
        resp = MagicMock()
        resp.status_code = response_status
        resp.text = response_text
        client_instance.post.return_value = resp
        client_instance.get.return_value = resp

    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=client_instance)
    ctx.__exit__ = MagicMock(return_value=False)

    factory = MagicMock(return_value=ctx)
    return factory


def _mock_httpx_per_url(handler: Callable[[str], MagicMock]) -> MagicMock:
    """httpx.Client factory whose ``.post`` dispatches on the request URL, so a
    test can make one host transport-fail while another responds."""
    client_instance = MagicMock()
    client_instance.post.side_effect = lambda url, **_: handler(url)
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=client_instance)
    ctx.__exit__ = MagicMock(return_value=False)
    return MagicMock(return_value=ctx)


def _resp(status: int, text: str = "") -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.text = text
    return resp


def _mock_httpx_stream_client(response: MagicMock) -> MagicMock:
    client_instance = MagicMock()
    stream_ctx = MagicMock()
    stream_ctx.__enter__ = MagicMock(return_value=response)
    stream_ctx.__exit__ = MagicMock(return_value=False)
    client_instance.stream.return_value = stream_ctx

    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=client_instance)
    ctx.__exit__ = MagicMock(return_value=False)
    return MagicMock(return_value=ctx)


def _stream_context(response: MagicMock) -> MagicMock:
    stream_ctx = MagicMock()
    stream_ctx.__enter__ = MagicMock(return_value=response)
    stream_ctx.__exit__ = MagicMock(return_value=False)
    return stream_ctx


def _sandbox_id() -> UUID:
    return uuid4()


def _files() -> FileSet:
    return {"my-skill/SKILL.md": b"# hello\n"}


def _assert_signature(
    headers: dict[str, str], signing_path: str, sha256_hex: str
) -> None:
    _priv, pub_b64 = sidecar_client.get_push_key_pair()
    pub = Ed25519PublicKey.from_public_bytes(base64.b64decode(pub_b64))
    pub.verify(
        base64.b64decode(headers["X-Push-Signature"]),
        f"{headers['X-Push-Timestamp']}|{signing_path}|{sha256_hex}".encode(),
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


def test_push_archive_sends_signed_mount_path_request() -> None:
    sandbox_id = _sandbox_id()
    mount_path = "/workspace/managed/skills"
    archive = b"skill archive"
    sha256_hex = hashlib.sha256(archive).hexdigest()
    client_instance = MagicMock()
    client_instance.post.return_value = _resp(200, "ok")
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=client_instance)
    ctx.__exit__ = MagicMock(return_value=False)

    with (
        patch(_HTTPX_CLIENT_PATH, MagicMock(return_value=ctx)),
        patch.object(sidecar_client.time, "time", return_value=1234567890),
    ):
        SidecarClient(host=lambda _sandbox_id: "sidecar.local").push_archive(
            sandbox_id=sandbox_id,
            mount_path=mount_path,
            archive=archive,
            sha256_hex=sha256_hex,
            operation_label="Push files",
            timeout_seconds=30.0,
        )

    client_instance.post.assert_called_once()
    url = client_instance.post.call_args.args[0]
    kwargs = client_instance.post.call_args.kwargs
    assert url == f"http://sidecar.local:8731{SIDECAR_PUSH_PATH}"
    assert kwargs["params"] == {"mount_path": mount_path}
    assert kwargs["content"] == archive
    headers = cast(dict[str, str], kwargs["headers"])
    assert headers["Content-Type"] == "application/gzip"
    assert headers["X-Bundle-Sha256"] == sha256_hex
    assert headers["X-Push-Timestamp"] == "1234567890"
    _assert_signature(headers, mount_path, sha256_hex)


def test_stream_new_snapshot_streams_signed_response() -> None:
    sandbox_id = _sandbox_id()
    body = b'{"session_id":"00000000-0000-0000-0000-000000000001"}'
    sha256_hex = hashlib.sha256(body).hexdigest()
    calls: list[tuple[str, dict[str, object]]] = []

    response = MagicMock()
    response.status_code = 200
    response.iter_bytes.return_value = iter([b"tar", b"bytes"])

    def stream_handler(_method: str, url: str, **kwargs: object) -> MagicMock:
        calls.append((url, kwargs))
        return _stream_context(response)

    client_instance = MagicMock()
    client_instance.stream.side_effect = stream_handler
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=client_instance)
    ctx.__exit__ = MagicMock(return_value=False)

    with (
        patch(_HTTPX_CLIENT_PATH, MagicMock(return_value=ctx)),
        patch.object(sidecar_client.time, "time", return_value=1234567890),
    ):
        with SidecarClient(
            host=lambda _sandbox_id: "sidecar.local"
        ).request_and_stream_new_snapshot(
            sandbox_id=sandbox_id,
            endpoint_path=SIDECAR_SNAPSHOT_CREATE_PATH,
            body=body,
            content_type="application/json",
            operation_label="Snapshot create",
            timeout_seconds=30.0,
        ) as stream:
            assert stream is not None
            assert stream.read() == b"tarbytes"

    assert [url for url, _kwargs in calls] == [
        f"http://sidecar.local:8731{SIDECAR_SNAPSHOT_CREATE_PATH}",
    ]
    headers = cast(dict[str, str], calls[-1][1]["headers"])
    assert headers["Content-Type"] == "application/json"
    assert headers["X-Push-Timestamp"] == "1234567890"
    assert calls[-1][1]["content"] == body
    _assert_signature(headers, SIDECAR_SNAPSHOT_CREATE_PATH, sha256_hex)


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


def test_health_check_returns_false_when_sandbox_container_terminated() -> None:
    """The sidecar can stay alive after the agent container is OOMKilled.

    Restore must treat that sandbox as unhealthy so the recovery path
    reprovisions it before exec'ing into the session workspace.
    """
    mgr = _make_manager()
    core_api = cast(Any, mgr)._core_api
    pod = core_api.read_namespaced_pod.return_value
    pod.status.container_statuses = [
        SimpleNamespace(
            name="sandbox",
            ready=False,
            state=SimpleNamespace(
                running=None, terminated=SimpleNamespace(reason="OOMKilled")
            ),
        ),
    ]
    pod.status.init_container_statuses = [
        SimpleNamespace(
            name="sidecar",
            ready=True,
            state=SimpleNamespace(running=object(), terminated=None),
        ),
    ]
    factory = _mock_httpx_client(response_status=200, response_text="ok")

    with patch(_HTTPX_CLIENT_PATH, factory):
        assert mgr.health_check(_sandbox_id(), timeout=1.0) is False
    factory.assert_not_called()


# ---------------------------------------------------------------------------
# Pod readiness: restartable init sidecar failure semantics
# ---------------------------------------------------------------------------


def _pod_with_init_status(
    *,
    init_container: client.V1Container,
    init_status: client.V1ContainerStatus,
) -> client.V1Pod:
    return client.V1Pod(
        metadata=client.V1ObjectMeta(name="sandbox-test-pod"),
        spec=client.V1PodSpec(
            containers=[client.V1Container(name="sandbox")],
            init_containers=[init_container],
        ),
        status=client.V1PodStatus(init_container_statuses=[init_status]),
    )


def test_init_container_nonzero_termination_is_fatal() -> None:
    mgr = _make_manager()
    pod = _pod_with_init_status(
        init_container=client.V1Container(name="sandbox-init"),
        init_status=client.V1ContainerStatus(
            name="sandbox-init",
            image="sandbox",
            image_id="sandbox",
            ready=False,
            restart_count=0,
            state=client.V1ContainerState(
                terminated=client.V1ContainerStateTerminated(exit_code=1)
            ),
        ),
    )

    with patch.object(mgr, "_get_init_container_logs", return_value="iptables failed"):
        error = mgr._check_init_container_status(pod)

    assert error is not None
    assert "sandbox-init" in error
    assert "exit code 1" in error
    assert "iptables failed" in error


def test_restartable_init_container_transient_termination_is_not_fatal() -> None:
    mgr = _make_manager()
    pod = _pod_with_init_status(
        init_container=client.V1Container(name="sidecar", restart_policy="Always"),
        init_status=client.V1ContainerStatus(
            name="sidecar",
            image="sandbox",
            image_id="sandbox",
            ready=False,
            restart_count=1,
            state=client.V1ContainerState(
                terminated=client.V1ContainerStateTerminated(exit_code=1)
            ),
        ),
    )

    with patch.object(mgr, "_get_init_container_logs") as get_logs:
        assert mgr._check_init_container_status(pod) is None

    get_logs.assert_not_called()


def test_restartable_init_container_crashloop_waiting_is_fatal() -> None:
    mgr = _make_manager()
    pod = _pod_with_init_status(
        init_container=client.V1Container(name="sidecar", restart_policy="Always"),
        init_status=client.V1ContainerStatus(
            name="sidecar",
            image="sandbox",
            image_id="sandbox",
            ready=False,
            restart_count=3,
            state=client.V1ContainerState(
                waiting=client.V1ContainerStateWaiting(
                    reason="CrashLoopBackOff",
                    message="back-off restarting failed container",
                )
            ),
        ),
    )

    error = mgr._check_init_container_status(pod)

    assert error is not None
    assert "sidecar" in error
    assert "CrashLoopBackOff" in error


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


# ---------------------------------------------------------------------------
# Sidecar reachability: single Service-FQDN host
# ---------------------------------------------------------------------------


def test_snapshot_restore_raises_when_all_hosts_fail() -> None:
    mgr = _make_manager()
    sandbox_id = _sandbox_id()

    def handler(_url: str) -> MagicMock:
        raise httpx.ConnectError("unreachable")

    archive_body = b"snapshot archive"
    with patch(_HTTPX_CLIENT_PATH, _mock_httpx_per_url(handler)):
        with pytest.raises(RuntimeError, match="Snapshot restore request failed"):
            SidecarClient(host=_service_host(mgr)).post_archive(
                sandbox_id=sandbox_id,
                endpoint_path=sidecar_snapshot_restore_path(_sandbox_id()),
                archive_file=io.BytesIO(archive_body),
                sha256_hex=hashlib.sha256(archive_body).hexdigest(),
                operation_label="Snapshot restore",
                timeout_seconds=0.01,
            )


def test_mark_restored_raises_on_non_204() -> None:
    mgr = _make_manager()
    sandbox_id = _sandbox_id()
    factory = _mock_httpx_per_url(lambda _url: _resp(500, "failed"))

    with patch(_HTTPX_CLIENT_PATH, factory):
        with pytest.raises(
            RuntimeError, match="opencode history restore marker failed"
        ):
            SidecarClient(host=_service_host(mgr)).post_empty(
                sandbox_id=sandbox_id,
                endpoint_path=SIDECAR_OPENCODE_HISTORY_MARK_RESTORED_PATH,
                operation_label="opencode history restore marker",
                timeout_seconds=1.0,
            )


def test_sandbox_service_publishes_not_ready_addresses() -> None:
    mgr = _make_manager()
    service = mgr._create_sandbox_service(_sandbox_id(), "tenant-test")

    assert service.spec is not None
    assert service.spec.publish_not_ready_addresses is True


def test_sidecar_host_is_the_service_fqdn() -> None:
    """The sidecar is reached only via the per-pod Service FQDN (in-cluster)."""
    mgr = _make_manager()
    host = mgr._sidecar_client._host(_sandbox_id())  # type: ignore[attr-defined]
    assert host.endswith(".sandbox-test.svc.cluster.local")


def test_push_connect_error_is_retriable() -> None:
    mgr = _make_manager()
    factory = _mock_httpx_client(raise_exc=httpx.ConnectError("no endpoints"))
    with patch(_HTTPX_CLIENT_PATH, factory):
        with pytest.raises(RetriableWriteError):
            mgr.write_files_to_sandbox(
                sandbox_id=_sandbox_id(),
                mount_path="/workspace/managed/skills",
                files=_files(),
            )


def test_create_opencode_history_snapshot_204_preserves_stable_snapshot() -> None:
    mgr = _make_manager()
    snapshot_manager = MagicMock()
    mgr._snapshot_manager = snapshot_manager  # type: ignore[attr-defined]
    resp = _resp(204)

    with patch(_HTTPX_CLIENT_PATH, _mock_httpx_stream_client(resp)):
        created = mgr.create_opencode_history_snapshot(
            sandbox_id=_sandbox_id(),
            tenant_id="tenant-test",
        )

    assert created is False
    snapshot_manager.delete_opencode_history_snapshot.assert_not_called()


def test_restore_opencode_history_posts_archive_to_sidecar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mgr = _make_manager()
    sandbox_id = _sandbox_id()
    expected_sandbox_id = sandbox_id
    archive_body = b"opencode history archive"
    calls: list[str] = []

    snapshot_manager = MagicMock()
    snapshot_manager.has_opencode_history_snapshot.return_value = True

    def restore_to_stream(
        _storage_path: str,
        write_stream: io.BufferedIOBase,
    ) -> None:
        write_stream.write(archive_body)

    snapshot_manager.restore_snapshot_to_stream.side_effect = restore_to_stream
    mgr._snapshot_manager = snapshot_manager  # type: ignore[attr-defined]

    def fake_post_archive(
        *,
        sandbox_id: UUID,
        endpoint_path: str,
        archive_file: io.BufferedIOBase,
        sha256_hex: str,
        operation_label: str,
        timeout_seconds: float,
    ) -> None:
        assert sandbox_id == expected_sandbox_id
        assert endpoint_path == SIDECAR_OPENCODE_HISTORY_RESTORE_PATH
        assert archive_file.read() == archive_body
        assert sha256_hex == hashlib.sha256(archive_body).hexdigest()
        assert operation_label == "opencode history restore"
        assert timeout_seconds == 300.0
        calls.append("restore")

    sidecar_client = MagicMock()
    sidecar_client.post_archive.side_effect = fake_post_archive
    monkeypatch.setattr(mgr, "_sidecar_client", sidecar_client)

    assert mgr.restore_opencode_history_snapshot(sandbox_id, "tenant-test") is True

    sidecar_client.post_archive.assert_called_once()
    assert calls == ["restore"]


def test_restore_opencode_history_marks_sidecar_ready_when_no_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mgr = _make_manager()
    sandbox_id = _sandbox_id()
    expected_sandbox_id = sandbox_id

    snapshot_manager = MagicMock()
    snapshot_manager.has_opencode_history_snapshot.return_value = False
    mgr._snapshot_manager = snapshot_manager  # type: ignore[attr-defined]

    def fake_mark_restored(
        *,
        sandbox_id: UUID,
        endpoint_path: str,
        operation_label: str,
        timeout_seconds: float,
    ) -> None:
        assert sandbox_id == expected_sandbox_id
        assert endpoint_path == SIDECAR_OPENCODE_HISTORY_MARK_RESTORED_PATH
        assert operation_label == "opencode history restore marker"
        assert timeout_seconds == 300.0

    sidecar_client = MagicMock()
    sidecar_client.post_empty.side_effect = fake_mark_restored
    monkeypatch.setattr(mgr, "_sidecar_client", sidecar_client)

    assert mgr.restore_opencode_history_snapshot(sandbox_id, "tenant-test") is False

    sidecar_client.post_empty.assert_called_once()


def test_provision_cleans_up_pod_when_opencode_history_restore_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import onyx.server.features.build.sandbox.kubernetes.kubernetes_sandbox_manager as ksm

    monkeypatch.setattr(ksm, "SANDBOX_API_SERVER_URL", "http://api-server")
    monkeypatch.setattr(ksm, "SANDBOX_PROXY_HOST", "proxy.local")

    sandbox_id = _sandbox_id()
    mgr = _make_manager()
    mgr._init_serve_state()
    monkeypatch.setattr(mgr, "_pod_exists_and_healthy", MagicMock(return_value=False))
    monkeypatch.setattr(mgr, "_provision_opencode_secret", MagicMock())
    monkeypatch.setattr(mgr, "_create_sandbox_pod", MagicMock(return_value=MagicMock()))
    monkeypatch.setattr(mgr, "_ensure_service_exists", MagicMock())
    monkeypatch.setattr(mgr, "_wait_for_pod_ready", MagicMock(return_value=True))
    monkeypatch.setattr(
        mgr, "_wait_for_opencode_serve_ready", MagicMock(return_value=True)
    )
    monkeypatch.setattr(
        mgr,
        "restore_opencode_history_snapshot",
        MagicMock(side_effect=RuntimeError("restore failed")),
    )
    cleanup_resources_mock = MagicMock()
    monkeypatch.setattr(mgr, "_cleanup_kubernetes_resources", cleanup_resources_mock)

    with pytest.raises(RuntimeError, match="restore failed"):
        mgr.provision(
            sandbox_id=sandbox_id,
            user_id=_sandbox_id(),
            tenant_id="tenant-test",
            llm_config=LLMProviderConfig(
                provider="openai",
                model_name="gpt-5-mini",
                api_key=None,
                api_base=None,
            ),
            onyx_pat="pat",
        )

    cleanup_resources_mock.assert_called_once_with(str(sandbox_id))


def test_provision_existing_healthy_pod_does_not_restore_opencode_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import onyx.server.features.build.sandbox.kubernetes.kubernetes_sandbox_manager as ksm

    monkeypatch.setattr(ksm, "SANDBOX_API_SERVER_URL", "http://api-server")
    monkeypatch.setattr(ksm, "SANDBOX_PROXY_HOST", "proxy.local")

    sandbox_id = _sandbox_id()
    mgr = _make_manager()
    mgr._init_serve_state()
    monkeypatch.setattr(mgr, "_pod_exists_and_healthy", MagicMock(return_value=True))
    monkeypatch.setattr(mgr, "_ensure_service_exists", MagicMock())
    monkeypatch.setattr(mgr, "_wait_for_pod_ready", MagicMock(return_value=True))
    monkeypatch.setattr(
        mgr, "_wait_for_opencode_serve_ready", MagicMock(return_value=True)
    )
    restore_mock = MagicMock()
    monkeypatch.setattr(mgr, "restore_opencode_history_snapshot", restore_mock)

    info = mgr.provision(
        sandbox_id=sandbox_id,
        user_id=_sandbox_id(),
        tenant_id="tenant-test",
        llm_config=LLMProviderConfig(
            provider="openai",
            model_name="gpt-5-mini",
            api_key=None,
            api_base=None,
        ),
        onyx_pat="pat",
    )

    assert info.sandbox_id == sandbox_id
    restore_mock.assert_not_called()


def test_provision_conflicting_healthy_pod_skips_startup_restore(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import onyx.server.features.build.sandbox.kubernetes.kubernetes_sandbox_manager as ksm

    monkeypatch.setattr(ksm, "SANDBOX_API_SERVER_URL", "http://api-server")
    monkeypatch.setattr(ksm, "SANDBOX_PROXY_HOST", "proxy.local")

    sandbox_id = _sandbox_id()
    mgr = _make_manager()
    mgr._init_serve_state()
    core_api = cast(Any, mgr)._core_api
    core_api.create_namespaced_pod.side_effect = ApiException(
        status=409,
        reason="Conflict",
    )

    health_mock = MagicMock(side_effect=[False, True])
    monkeypatch.setattr(mgr, "_pod_exists_and_healthy", health_mock)
    monkeypatch.setattr(mgr, "_provision_opencode_secret", MagicMock())
    monkeypatch.setattr(mgr, "_create_sandbox_pod", MagicMock(return_value=MagicMock()))
    monkeypatch.setattr(mgr, "_ensure_service_exists", MagicMock())
    monkeypatch.setattr(mgr, "_wait_for_pod_ready", MagicMock(return_value=True))
    monkeypatch.setattr(
        mgr, "_wait_for_opencode_serve_ready", MagicMock(return_value=True)
    )
    restore_mock = MagicMock()
    cleanup_resources_mock = MagicMock()
    monkeypatch.setattr(mgr, "restore_opencode_history_snapshot", restore_mock)
    monkeypatch.setattr(mgr, "_cleanup_kubernetes_resources", cleanup_resources_mock)

    info = mgr.provision(
        sandbox_id=sandbox_id,
        user_id=_sandbox_id(),
        tenant_id="tenant-test",
        llm_config=LLMProviderConfig(
            provider="openai",
            model_name="gpt-5-mini",
            api_key=None,
            api_base=None,
        ),
        onyx_pat="pat",
    )

    assert info.sandbox_id == sandbox_id
    restore_mock.assert_not_called()
    cleanup_resources_mock.assert_not_called()


def test_provision_conflicting_not_ready_pod_runs_startup_restore(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import onyx.server.features.build.sandbox.kubernetes.kubernetes_sandbox_manager as ksm

    monkeypatch.setattr(ksm, "SANDBOX_API_SERVER_URL", "http://api-server")
    monkeypatch.setattr(ksm, "SANDBOX_PROXY_HOST", "proxy.local")

    sandbox_id = _sandbox_id()
    mgr = _make_manager()
    mgr._init_serve_state()
    core_api = cast(Any, mgr)._core_api
    core_api.create_namespaced_pod.side_effect = ApiException(
        status=409,
        reason="Conflict",
    )

    calls: list[str] = []
    monkeypatch.setattr(mgr, "_pod_exists_and_healthy", MagicMock(return_value=False))
    monkeypatch.setattr(mgr, "_provision_opencode_secret", MagicMock())
    monkeypatch.setattr(mgr, "_create_sandbox_pod", MagicMock(return_value=MagicMock()))
    monkeypatch.setattr(
        mgr,
        "_ensure_service_exists",
        MagicMock(side_effect=lambda *_args: calls.append("service")),
    )
    monkeypatch.setattr(
        mgr,
        "restore_opencode_history_snapshot",
        MagicMock(side_effect=lambda *_args, **_kwargs: calls.append("restore")),
    )
    monkeypatch.setattr(
        mgr,
        "_wait_for_pod_ready",
        MagicMock(side_effect=lambda _pod_name: calls.append("pod-ready") or True),
    )
    monkeypatch.setattr(
        mgr,
        "_wait_for_opencode_serve_ready",
        MagicMock(
            side_effect=lambda _sandbox_id: calls.append("opencode-ready") or True
        ),
    )

    info = mgr.provision(
        sandbox_id=sandbox_id,
        user_id=_sandbox_id(),
        tenant_id="tenant-test",
        llm_config=LLMProviderConfig(
            provider="openai",
            model_name="gpt-5-mini",
            api_key=None,
            api_base=None,
        ),
        onyx_pat="pat",
    )

    assert info.sandbox_id == sandbox_id
    assert calls == ["service", "restore", "pod-ready", "opencode-ready"]


def test_provision_conflicting_not_ready_pod_restore_failure_does_not_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import onyx.server.features.build.sandbox.kubernetes.kubernetes_sandbox_manager as ksm

    monkeypatch.setattr(ksm, "SANDBOX_API_SERVER_URL", "http://api-server")
    monkeypatch.setattr(ksm, "SANDBOX_PROXY_HOST", "proxy.local")

    sandbox_id = _sandbox_id()
    mgr = _make_manager()
    mgr._init_serve_state()
    core_api = cast(Any, mgr)._core_api
    core_api.create_namespaced_pod.side_effect = ApiException(
        status=409,
        reason="Conflict",
    )

    monkeypatch.setattr(mgr, "_pod_exists_and_healthy", MagicMock(return_value=False))
    monkeypatch.setattr(mgr, "_provision_opencode_secret", MagicMock())
    monkeypatch.setattr(mgr, "_create_sandbox_pod", MagicMock(return_value=MagicMock()))
    monkeypatch.setattr(mgr, "_ensure_service_exists", MagicMock())
    monkeypatch.setattr(
        mgr,
        "restore_opencode_history_snapshot",
        MagicMock(side_effect=RuntimeError("restore failed")),
    )
    cleanup_resources_mock = MagicMock()
    monkeypatch.setattr(mgr, "_cleanup_kubernetes_resources", cleanup_resources_mock)

    with pytest.raises(RuntimeError, match="restore failed"):
        mgr.provision(
            sandbox_id=sandbox_id,
            user_id=_sandbox_id(),
            tenant_id="tenant-test",
            llm_config=LLMProviderConfig(
                provider="openai",
                model_name="gpt-5-mini",
                api_key=None,
                api_base=None,
            ),
            onyx_pat="pat",
        )

    cleanup_resources_mock.assert_not_called()
