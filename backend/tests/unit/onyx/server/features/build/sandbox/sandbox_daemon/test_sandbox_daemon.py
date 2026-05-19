"""In-pod sandbox_daemon server tests.

Behavior tests over the FastAPI sandbox_daemon (push + snapshot endpoints) using
``fastapi.testclient``. The sandbox_daemon module is loaded dynamically under the
``sandbox_daemon`` package name because its in-container layout (``COPY sandbox_daemon/
/workspace/sandbox_daemon``) isn't reflected in the backend Python path.
"""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import io
import os
import sys
import tarfile
import time
import types
from collections.abc import Generator
from pathlib import Path
from types import ModuleType

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding
from cryptography.hazmat.primitives.serialization import PublicFormat
from fastapi.testclient import TestClient

# Resolve the sandbox_daemon directory relative to this test file so the path works in
# both local dev and CI. This file lives at:
#   backend/tests/unit/onyx/server/features/build/sandbox/sandbox_daemon/test_sandbox_daemon.py
# so parents[9] is the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[9]
_DAEMON_DIR = (
    _REPO_ROOT
    / "backend/onyx/server/features/build/sandbox/kubernetes/docker/sandbox_daemon"
)


def _load_sandbox_daemon_modules() -> tuple[ModuleType, ModuleType]:
    """Load ``sandbox_daemon.extract`` and ``sandbox_daemon.server`` from the sandbox_daemon
    directory.

    The sandbox_daemon's source imports ``from sandbox_daemon.extract import ...`` because
    in the container the directory is copied to ``/workspace/sandbox_daemon/``.
    The test runner doesn't have that path, so we register the modules under
    the expected names in ``sys.modules`` before loading server.py.
    """
    if (
        "sandbox_daemon.server" in sys.modules
        and "sandbox_daemon.extract" in sys.modules
    ):
        return sys.modules["sandbox_daemon.extract"], sys.modules[
            "sandbox_daemon.server"
        ]

    if "sandbox_daemon" not in sys.modules:
        sys.modules["sandbox_daemon"] = types.ModuleType("sandbox_daemon")

    for name in ("models", "extract", "snapshot", "server"):
        spec = importlib.util.spec_from_file_location(
            f"sandbox_daemon.{name}", str(_DAEMON_DIR / f"{name}.py")
        )
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        sys.modules[f"sandbox_daemon.{name}"] = mod
        spec.loader.exec_module(mod)

    return sys.modules["sandbox_daemon.extract"], sys.modules["sandbox_daemon.server"]


# ---------------------------------------------------------------------------
# Key / signing helpers
# ---------------------------------------------------------------------------


def _new_keypair() -> tuple[Ed25519PrivateKey, str]:
    """Generate a fresh Ed25519 key and return (private_key, public_key_b64)."""
    priv = Ed25519PrivateKey.generate()
    pub_bytes = priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return priv, base64.b64encode(pub_bytes).decode()


def _sign(
    priv: Ed25519PrivateKey,
    *,
    mount_path: str,
    sha256_hex: str,
    timestamp: str,
) -> str:
    message = f"{timestamp}|{mount_path}|{sha256_hex}".encode()
    return base64.b64encode(priv.sign(message)).decode()


def _build_targz_bytes(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz", compresslevel=6) as tar:
        for name in sorted(entries):
            info = tarfile.TarInfo(name=name)
            data = entries[name]
            info.size = len(data)
            info.mtime = 0
            info.mode = 0o644
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sandbox_daemon_modules() -> tuple[ModuleType, ModuleType]:
    """Load extract + server modules once per test."""
    return _load_sandbox_daemon_modules()


@pytest.fixture
def keypair() -> tuple[Ed25519PrivateKey, str]:
    return _new_keypair()


@pytest.fixture
def configured_sandbox_daemon(
    sandbox_daemon_modules: tuple[ModuleType, ModuleType],
    keypair: tuple[Ed25519PrivateKey, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[ModuleType, ModuleType, Ed25519PrivateKey, Path]:
    """Sidecar with the public key env set and the ALLOWED_PREFIX pointed
    at a temp directory so extraction stays hermetic.
    """
    extract_mod, server_mod = sandbox_daemon_modules
    priv, pub_b64 = keypair

    # Point ALLOWED_PREFIX at a tmp dir for hermetic extraction. Resolve to
    # the canonical path because extract.py uses ``Path.resolve()`` for its
    # prefix check, and macOS tmp paths contain ``/var -> /private/var``.
    allowed_root = (tmp_path / "managed").resolve()
    allowed_root.mkdir(parents=True)
    # Trailing slash to match the production constant shape.
    monkeypatch.setattr(extract_mod, "ALLOWED_PREFIX", str(allowed_root) + os.sep)

    # Set public key env and clear the daemon's cached key.
    monkeypatch.setenv("ONYX_SANDBOX_PUSH_PUBLIC_KEY", pub_b64)
    monkeypatch.setattr(server_mod, "_public_key", None, raising=False)

    return extract_mod, server_mod, priv, allowed_root


@pytest.fixture
def client(
    configured_sandbox_daemon: tuple[ModuleType, ModuleType, Ed25519PrivateKey, Path],
) -> Generator[TestClient, None, None]:
    _, server_mod, _, _ = configured_sandbox_daemon
    with TestClient(server_mod.app) as c:
        yield c


def _push_request(
    client: TestClient,
    *,
    priv: Ed25519PrivateKey,
    mount_path: str,
    body: bytes,
    sha_override: str | None = None,
    signature_override: str | None = None,
    timestamp_override: str | None = None,
) -> httpx.Response:
    """Send a signed (or intentionally-broken) push request and return the response."""
    sha = sha_override if sha_override is not None else hashlib.sha256(body).hexdigest()
    ts = timestamp_override if timestamp_override is not None else str(int(time.time()))
    sig_input_sha = hashlib.sha256(body).hexdigest()
    sig = (
        signature_override
        if signature_override is not None
        else _sign(priv, mount_path=mount_path, sha256_hex=sig_input_sha, timestamp=ts)
    )
    headers = {
        "Content-Type": "application/gzip",
        "X-Bundle-Sha256": sha,
        "X-Push-Signature": sig,
        "X-Push-Timestamp": ts,
    }
    return client.post(
        "/push",
        params={"mount_path": mount_path},
        content=body,
        headers=headers,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_health_returns_200(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_push_with_valid_signature_extracts(
    configured_sandbox_daemon: tuple[ModuleType, ModuleType, Ed25519PrivateKey, Path],
    client: TestClient,
) -> None:
    _, _, priv, allowed_root = configured_sandbox_daemon
    mount_path = str(allowed_root / "skills")
    body = _build_targz_bytes({"my-skill/SKILL.md": b"# hello\n"})

    resp = _push_request(client, priv=priv, mount_path=mount_path, body=body)

    assert resp.status_code == 200, resp.text
    # The mount_path is a symlink into .versions/<ts>-<sha>/, which contains
    # the extracted files. The behavior we care about: the file lands at the
    # symlinked location.
    extracted = Path(mount_path) / "my-skill" / "SKILL.md"
    assert extracted.read_bytes() == b"# hello\n"


def test_push_with_invalid_signature_returns_401(
    configured_sandbox_daemon: tuple[ModuleType, ModuleType, Ed25519PrivateKey, Path],
    client: TestClient,
) -> None:
    _, _, priv, allowed_root = configured_sandbox_daemon
    mount_path = str(allowed_root / "skills")
    body = _build_targz_bytes({"my-skill/SKILL.md": b"# hi\n"})

    # Sign with a *different* private key.
    other_priv, _ = _new_keypair()
    ts = str(int(time.time()))
    bad_sig = _sign(
        other_priv,
        mount_path=mount_path,
        sha256_hex=hashlib.sha256(body).hexdigest(),
        timestamp=ts,
    )
    resp = _push_request(
        client,
        priv=priv,
        mount_path=mount_path,
        body=body,
        signature_override=bad_sig,
        timestamp_override=ts,
    )
    assert resp.status_code == 401


def test_push_with_old_timestamp_returns_401(
    configured_sandbox_daemon: tuple[ModuleType, ModuleType, Ed25519PrivateKey, Path],
    client: TestClient,
) -> None:
    _, _, priv, allowed_root = configured_sandbox_daemon
    mount_path = str(allowed_root / "skills")
    body = _build_targz_bytes({"my-skill/SKILL.md": b"x"})
    old_ts = str(int(time.time()) - 120)  # 2 minutes in the past
    resp = _push_request(
        client, priv=priv, mount_path=mount_path, body=body, timestamp_override=old_ts
    )
    assert resp.status_code == 401


def test_push_with_future_timestamp_returns_401(
    configured_sandbox_daemon: tuple[ModuleType, ModuleType, Ed25519PrivateKey, Path],
    client: TestClient,
) -> None:
    _, _, priv, allowed_root = configured_sandbox_daemon
    mount_path = str(allowed_root / "skills")
    body = _build_targz_bytes({"my-skill/SKILL.md": b"x"})
    future_ts = str(int(time.time()) + 120)
    resp = _push_request(
        client,
        priv=priv,
        mount_path=mount_path,
        body=body,
        timestamp_override=future_ts,
    )
    assert resp.status_code == 401


def test_push_with_sha_mismatch_returns_400(
    configured_sandbox_daemon: tuple[ModuleType, ModuleType, Ed25519PrivateKey, Path],
    client: TestClient,
) -> None:
    """Header SHA != computed -> 400.

    The signature is over the *header* SHA (not the body bytes), so to reach
    the SHA-mismatch branch the request must pass signature verification with
    the wrong SHA in the header. We sign over the wrong SHA so verification
    passes, then the body hashes to a different value.
    """
    _, _, priv, allowed_root = configured_sandbox_daemon
    mount_path = str(allowed_root / "skills")
    body = _build_targz_bytes({"my-skill/SKILL.md": b"real body"})
    wrong_sha = hashlib.sha256(b"different body").hexdigest()
    ts = str(int(time.time()))
    sig = _sign(priv, mount_path=mount_path, sha256_hex=wrong_sha, timestamp=ts)
    resp = client.post(
        "/push",
        params={"mount_path": mount_path},
        content=body,
        headers={
            "Content-Type": "application/gzip",
            "X-Bundle-Sha256": wrong_sha,
            "X-Push-Signature": sig,
            "X-Push-Timestamp": ts,
        },
    )
    assert resp.status_code == 400
    assert "SHA-256" in resp.text or "mismatch" in resp.text.lower()


def test_push_over_size_cap_returns_413(
    configured_sandbox_daemon: tuple[ModuleType, ModuleType, Ed25519PrivateKey, Path],
    client: TestClient,
) -> None:
    """Content-Length > 100 MiB -> 413, body never streamed."""
    extract_mod, _, priv, allowed_root = configured_sandbox_daemon
    mount_path = str(allowed_root / "skills")

    # Use a small body but advertise a huge Content-Length. The daemon rejects
    # based on the header before reading the body.
    body = _build_targz_bytes({"x": b"x"})
    huge = str(extract_mod.MAX_BUNDLE_BYTES + 1)
    sha = hashlib.sha256(body).hexdigest()
    ts = str(int(time.time()))
    sig = _sign(priv, mount_path=mount_path, sha256_hex=sha, timestamp=ts)

    resp = client.post(
        "/push",
        params={"mount_path": mount_path},
        content=body,
        headers={
            "Content-Type": "application/gzip",
            "Content-Length": huge,
            "X-Bundle-Sha256": sha,
            "X-Push-Signature": sig,
            "X-Push-Timestamp": ts,
        },
    )
    assert resp.status_code == 413


def test_push_to_mount_path_outside_allowed_prefix_returns_400(
    configured_sandbox_daemon: tuple[ModuleType, ModuleType, Ed25519PrivateKey, Path],
    client: TestClient,
) -> None:
    """mount_path outside ALLOWED_PREFIX (e.g. /etc) is rejected with 400."""
    _, _, priv, _ = configured_sandbox_daemon
    mount_path = "/etc"
    body = _build_targz_bytes({"shadow": b"oops"})

    resp = _push_request(client, priv=priv, mount_path=mount_path, body=body)
    assert resp.status_code == 400


def test_push_missing_public_key_raises_onyx_error(
    configured_sandbox_daemon: tuple[ModuleType, ModuleType, Ed25519PrivateKey, Path],
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Daemon without the public-key env var returns a 500 with a descriptive
    detail.

    Note: the in-pod daemon is standalone Python (no Onyx imports) so it
    surfaces this via ``HTTPException(status_code=500, ...)`` rather than
    ``OnyxError``. The behavior asserted here is the operator-facing error
    when the key is missing, as observed through the FastAPI TestClient.
    """
    _, server_mod, priv, allowed_root = configured_sandbox_daemon

    # Remove the env var and clear the cached key.
    monkeypatch.delenv("ONYX_SANDBOX_PUSH_PUBLIC_KEY", raising=False)
    monkeypatch.setattr(server_mod, "_public_key", None, raising=False)

    mount_path = str(allowed_root / "skills")
    body = _build_targz_bytes({"x": b"x"})
    resp = _push_request(client, priv=priv, mount_path=mount_path, body=body)

    assert resp.status_code == 500
    assert "public key" in resp.text.lower()


# ---------------------------------------------------------------------------
# Snapshot endpoint tests
#
# Snapshot endpoints share signing infra with /push but use a different
# signing format: {ts}|{endpoint_path}|{sha256(body)}. The path acts as a
# domain separator so a captured push signature can't be replayed against
# a snapshot endpoint (and vice versa).
# ---------------------------------------------------------------------------


def _sign_snapshot(
    priv: Ed25519PrivateKey,
    *,
    endpoint_path: str,
    body: bytes,
    timestamp: str,
) -> str:
    sha256_hex = hashlib.sha256(body).hexdigest()
    message = f"{timestamp}|{endpoint_path}|{sha256_hex}".encode()
    return base64.b64encode(priv.sign(message)).decode()


def _post_snapshot(
    client: TestClient,
    endpoint_path: str,
    body: bytes,
    *,
    signature: str,
    timestamp: str,
) -> httpx.Response:
    return client.post(
        endpoint_path,
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Push-Signature": signature,
            "X-Push-Timestamp": timestamp,
        },
    )


def _signed_snapshot_post(
    client: TestClient,
    endpoint_path: str,
    body: bytes,
    priv: Ed25519PrivateKey,
) -> httpx.Response:
    ts = str(int(time.time()))
    sig = _sign_snapshot(priv, endpoint_path=endpoint_path, body=body, timestamp=ts)
    return _post_snapshot(client, endpoint_path, body, signature=sig, timestamp=ts)


def test_snapshot_create_parses_body_and_returns_storage_path(
    configured_sandbox_daemon: tuple[ModuleType, ModuleType, Ed25519PrivateKey, Path],
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The endpoint deserializes the JSON body, hands all four fields to
    the snapshot function, and surfaces its return value as the response.

    Verifying the args round-trip catches schema drift (e.g. a renamed
    field silently being dropped by pydantic).
    """
    from uuid import UUID

    _, server_mod, priv, _ = configured_sandbox_daemon
    captured: dict[str, object] = {}

    def fake_create(**kwargs: object) -> tuple[str, str]:
        captured.update(kwargs)
        return (
            "created",
            "t-1/snapshots/00000000-0000-0000-0000-000000000001/00000000-0000-0000-0000-000000000002.tar.gz",
        )

    monkeypatch.setattr(server_mod, "create_snapshot", fake_create)

    body = (
        b'{"session_id":"00000000-0000-0000-0000-000000000001","tenant_id":"t-1",'
        b'"s3_bucket":"buck","snapshot_id":"00000000-0000-0000-0000-000000000002"}'
    )
    resp = _signed_snapshot_post(client, "/snapshot/create", body, priv)

    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "status": "created",
        "storage_path": "t-1/snapshots/00000000-0000-0000-0000-000000000001/00000000-0000-0000-0000-000000000002.tar.gz",
        "size_bytes": 0,
    }
    assert captured == {
        "session_id": UUID("00000000-0000-0000-0000-000000000001"),
        "tenant_id": "t-1",
        "s3_bucket": "buck",
        "snapshot_id": UUID("00000000-0000-0000-0000-000000000002"),
    }


def test_snapshot_create_passes_through_empty_status(
    configured_sandbox_daemon: tuple[ModuleType, ModuleType, Ed25519PrivateKey, Path],
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty session yields status="empty" with no storage_path.

    The caller (api-server) uses this to skip persisting a snapshot record,
    so misreporting it as "created" would create dangling DB rows pointing
    at nonexistent S3 keys.
    """
    _, server_mod, priv, _ = configured_sandbox_daemon
    monkeypatch.setattr(server_mod, "create_snapshot", lambda **_: ("empty", ""))

    body = b'{"session_id":"00000000-0000-0000-0000-000000000003","tenant_id":"t","s3_bucket":"b","snapshot_id":"00000000-0000-0000-0000-000000000004"}'
    resp = _signed_snapshot_post(client, "/snapshot/create", body, priv)

    assert resp.status_code == 200
    assert resp.json()["status"] == "empty"
    assert resp.json()["storage_path"] == ""


def test_snapshot_restore_passes_body_through_and_returns_204(
    configured_sandbox_daemon: tuple[ModuleType, ModuleType, Ed25519PrivateKey, Path],
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Restore has no response body — success is the 204. The endpoint
    deserializes the JSON request and hands fields to the snapshot
    function unchanged. The storage_path validator requires it to live
    under the tenant's snapshot prefix.
    """
    from uuid import UUID

    _, server_mod, priv, _ = configured_sandbox_daemon
    captured: dict[str, object] = {}

    def fake_restore(**kwargs: object) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(server_mod, "restore_snapshot", fake_restore)

    body = (
        b'{"session_id":"00000000-0000-0000-0000-000000000001",'
        b'"tenant_id":"t-1","s3_bucket":"buck",'
        b'"storage_path":"t-1/snapshots/x/y.tar.gz"}'
    )
    resp = _signed_snapshot_post(client, "/snapshot/restore", body, priv)

    assert resp.status_code == 204
    assert resp.content == b""
    assert captured == {
        "session_id": UUID("00000000-0000-0000-0000-000000000001"),
        "s3_bucket": "buck",
        "storage_path": "t-1/snapshots/x/y.tar.gz",
    }


@pytest.mark.parametrize(
    "storage_path,defends_against",
    [
        # Prefix-share covers BOTH "different tenant" AND "the trailing `/`
        # in the validator matters". A subtler bug than a totally different
        # prefix, so it's the more interesting case to pin.
        ("t-1-evil/snapshots/x/y.tar.gz", "prefix-share"),
        # The startswith check alone wouldn't reject this — defends the
        # separate `..`-segment guard.
        ("t-1/snapshots/../../etc/passwd", "parent-traversal"),
    ],
)
def test_snapshot_restore_rejects_unsafe_storage_path(
    configured_sandbox_daemon: tuple[ModuleType, ModuleType, Ed25519PrivateKey, Path],
    client: TestClient,
    storage_path: str,
    defends_against: str,
) -> None:
    """Pin the cross-tenant + traversal guards in
    ``SnapshotRestoreRequest._storage_path_under_tenant``. Without these,
    a bug or compromise on the api-server side could route one tenant's
    restore onto another tenant's key, or escape the session dir via
    ``..``.
    """
    _, _, priv, _ = configured_sandbox_daemon
    body = (
        b'{"session_id":"00000000-0000-0000-0000-000000000001",'
        b'"tenant_id":"t-1","s3_bucket":"buck",'
        b'"storage_path":"' + storage_path.encode() + b'"}'
    )
    resp = _signed_snapshot_post(client, "/snapshot/restore", body, priv)
    assert resp.status_code == 400, (
        f"{defends_against}: expected 400, got {resp.status_code}"
    )
    assert "storage_path" in resp.text


@pytest.mark.parametrize(
    "tenant_id,defends_against",
    [
        # A `/` would let tenant_id smuggle path segments into the S3 key
        # (e.g. `tenant_id="t-1/../other"`). This is the security-relevant
        # case for the charset.
        ("t-1/evil", "slash-in-charset"),
        # Empty would slip past the validator if the `{1,...}` bound were
        # dropped, producing storage paths that start with `/snapshots/`.
        ("", "empty-lower-bound"),
    ],
)
def test_snapshot_create_rejects_invalid_tenant_id(
    configured_sandbox_daemon: tuple[ModuleType, ModuleType, Ed25519PrivateKey, Path],
    client: TestClient,
    tenant_id: str,
    defends_against: str,
) -> None:
    """The wire model constrains tenant_id to a safe character set so it
    can't be used to inject path segments into the S3 key (snapshot create)
    or smuggle other shell-significant chars into the path.
    """
    _, _, priv, _ = configured_sandbox_daemon
    body = (
        b'{"session_id":"00000000-0000-0000-0000-000000000001",'
        b'"tenant_id":"' + tenant_id.encode() + b'","s3_bucket":"buck",'
        b'"snapshot_id":"00000000-0000-0000-0000-000000000002"}'
    )
    resp = _signed_snapshot_post(client, "/snapshot/create", body, priv)
    assert resp.status_code == 400, (
        f"{defends_against}: expected 400, got {resp.status_code}"
    )


@pytest.mark.parametrize("endpoint", ["/snapshot/create", "/snapshot/restore"])
def test_snapshot_signature_from_wrong_key_is_rejected(
    configured_sandbox_daemon: tuple[ModuleType, ModuleType, Ed25519PrivateKey, Path],
    client: TestClient,
    endpoint: str,
) -> None:
    """The agent shares the pod network namespace and can curl localhost.
    A signature from any key other than the configured public key must fail.
    """
    _, _, _, _ = configured_sandbox_daemon
    body = b'{"session_id":"00000000-0000-0000-0000-000000000003","tenant_id":"t","s3_bucket":"b","snapshot_id":"00000000-0000-0000-0000-000000000004"}'
    ts = str(int(time.time()))
    other_priv, _ = _new_keypair()
    sig = _sign_snapshot(other_priv, endpoint_path=endpoint, body=body, timestamp=ts)

    resp = _post_snapshot(client, endpoint, body, signature=sig, timestamp=ts)
    assert resp.status_code == 401


def test_snapshot_body_tampering_after_signing_is_rejected(
    configured_sandbox_daemon: tuple[ModuleType, ModuleType, Ed25519PrivateKey, Path],
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mutating any byte of the body after signing must invalidate the
    signature — otherwise a network attacker (or compromised agent) could
    redirect a snapshot to a different tenant by swapping tenant_id.
    """
    _, server_mod, priv, _ = configured_sandbox_daemon
    monkeypatch.setattr(server_mod, "create_snapshot", lambda **_: ("created", "p"))

    signed_body = b'{"session_id":"00000000-0000-0000-0000-000000000003","tenant_id":"t","s3_bucket":"b","snapshot_id":"00000000-0000-0000-0000-000000000004"}'
    ts = str(int(time.time()))
    sig = _sign_snapshot(
        priv, endpoint_path="/snapshot/create", body=signed_body, timestamp=ts
    )

    tampered_body = signed_body.replace(b'"tenant_id":"t"', b'"tenant_id":"VICTIM"')

    resp = _post_snapshot(
        client, "/snapshot/create", tampered_body, signature=sig, timestamp=ts
    )
    assert resp.status_code == 401


def test_push_signature_cannot_be_replayed_against_snapshot_endpoint(
    configured_sandbox_daemon: tuple[ModuleType, ModuleType, Ed25519PrivateKey, Path],
    client: TestClient,
) -> None:
    """A captured /push signature signs {ts}|{mount_path}|{sha} — the path
    component differs from a snapshot signature ({ts}|{endpoint}|{sha}).
    Without that domain separation, a leaked push signature could be
    replayed to trigger arbitrary snapshot operations.
    """
    _, _, priv, _ = configured_sandbox_daemon
    body = b'{"session_id":"00000000-0000-0000-0000-000000000003","tenant_id":"t","s3_bucket":"b","snapshot_id":"00000000-0000-0000-0000-000000000004"}'
    ts = str(int(time.time()))

    # Sign as if this were a push to /snapshot/create (mount_path = endpoint).
    # The daemon should still reject because the snapshot endpoint signs over
    # the SHA of the request body, not the SHA passed in a header.
    push_style_sig = _sign(
        priv,
        mount_path="/snapshot/create",
        sha256_hex="0" * 64,  # arbitrary — push signs over header SHA, not body
        timestamp=ts,
    )
    resp = _post_snapshot(
        client, "/snapshot/create", body, signature=push_style_sig, timestamp=ts
    )
    assert resp.status_code == 401
