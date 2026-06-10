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
from uuid import UUID

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
    _REPO_ROOT / "backend/onyx/server/features/build/sandbox/image/sandbox_daemon"
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
    content_type: str = "application/json",
    bundle_sha256: str | None = None,
    extra_headers: dict[str, str] | None = None,
) -> httpx.Response:
    headers = {
        "Content-Type": content_type,
        "X-Push-Signature": signature,
        "X-Push-Timestamp": timestamp,
    }
    if bundle_sha256 is not None:
        headers["X-Bundle-Sha256"] = bundle_sha256
    if extra_headers:
        headers.update(extra_headers)
    return client.post(
        endpoint_path,
        content=body,
        headers=headers,
    )


def _signed_snapshot_post(
    client: TestClient,
    endpoint_path: str,
    body: bytes,
    priv: Ed25519PrivateKey,
    extra_headers: dict[str, str] | None = None,
) -> httpx.Response:
    ts = str(int(time.time()))
    sig = _sign_snapshot(priv, endpoint_path=endpoint_path, body=body, timestamp=ts)
    return _post_snapshot(
        client,
        endpoint_path,
        body,
        signature=sig,
        timestamp=ts,
        extra_headers=extra_headers,
    )


def _signed_snapshot_restore_post(
    client: TestClient,
    endpoint_path: str,
    body: bytes,
    priv: Ed25519PrivateKey,
    *,
    sha_override: str | None = None,
) -> httpx.Response:
    sha256_hex = sha_override or hashlib.sha256(body).hexdigest()
    ts = str(int(time.time()))
    sig = _sign(
        priv,
        mount_path=endpoint_path,
        sha256_hex=sha256_hex,
        timestamp=ts,
    )
    return _post_snapshot(
        client,
        endpoint_path,
        body,
        signature=sig,
        timestamp=ts,
        content_type="application/gzip",
        bundle_sha256=sha256_hex,
    )


def test_snapshot_create_empty_session_returns_204(
    configured_sandbox_daemon: tuple[ModuleType, ModuleType, Ed25519PrivateKey, Path],
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, server_mod, priv, _ = configured_sandbox_daemon
    captured: dict[str, UUID] = {}

    def fake_compute_snapshot_digest(session_id: UUID) -> str | None:
        captured["session_id"] = session_id
        return None

    monkeypatch.setattr(
        server_mod, "compute_snapshot_digest", fake_compute_snapshot_digest
    )

    body = b'{"session_id":"00000000-0000-0000-0000-000000000001"}'
    resp = _signed_snapshot_post(client, "/snapshot/create", body, priv)

    assert resp.status_code == 204, resp.text
    assert resp.content == b""
    assert captured == {
        "session_id": UUID("00000000-0000-0000-0000-000000000001"),
    }


def test_snapshot_create_streams_archive_when_content_exists(
    configured_sandbox_daemon: tuple[ModuleType, ModuleType, Ed25519PrivateKey, Path],
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, server_mod, priv, _ = configured_sandbox_daemon
    captured: dict[str, UUID] = {}

    def fake_compute_snapshot_digest(session_id: UUID) -> str | None:
        captured["session_id"] = session_id
        return "deadbeef"

    def fake_iter_snapshot_archive(session_id: UUID) -> Generator[bytes, None, None]:
        captured["iter_session_id"] = session_id
        yield b"tar"
        yield b"bytes"

    monkeypatch.setattr(
        server_mod, "compute_snapshot_digest", fake_compute_snapshot_digest
    )
    monkeypatch.setattr(server_mod, "iter_snapshot_archive", fake_iter_snapshot_archive)

    body = b'{"session_id":"00000000-0000-0000-0000-000000000003"}'
    resp = _signed_snapshot_post(client, "/snapshot/create", body, priv)

    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("application/gzip")
    assert resp.headers["ETag"] == "deadbeef"
    assert resp.content == b"tarbytes"
    session_id = UUID("00000000-0000-0000-0000-000000000003")
    assert captured == {"session_id": session_id, "iter_session_id": session_id}


def test_snapshot_create_unchanged_returns_304(
    configured_sandbox_daemon: tuple[ModuleType, ModuleType, Ed25519PrivateKey, Path],
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, server_mod, priv, _ = configured_sandbox_daemon

    def fake_compute_snapshot_digest(_session_id: UUID) -> str | None:
        return "samedigest"

    def fail_iter(_session_id: UUID) -> Generator[bytes, None, None]:
        raise AssertionError("must not archive an unchanged workspace")
        yield b""

    monkeypatch.setattr(
        server_mod, "compute_snapshot_digest", fake_compute_snapshot_digest
    )
    monkeypatch.setattr(server_mod, "iter_snapshot_archive", fail_iter)

    body = b'{"session_id":"00000000-0000-0000-0000-000000000003"}'
    resp = _signed_snapshot_post(
        client, "/snapshot/create", body, priv, {"If-None-Match": "samedigest"}
    )

    assert resp.status_code == 304, resp.text
    assert resp.content == b""


def test_snapshot_create_rejects_stale_storage_fields(
    configured_sandbox_daemon: tuple[ModuleType, ModuleType, Ed25519PrivateKey, Path],
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, server_mod, priv, _ = configured_sandbox_daemon
    called = False

    def fake_compute_snapshot_digest(_session_id: UUID) -> str | None:
        nonlocal called
        called = True
        return "digest"

    monkeypatch.setattr(
        server_mod, "compute_snapshot_digest", fake_compute_snapshot_digest
    )

    body = (
        b'{"session_id":"00000000-0000-0000-0000-000000000003",'
        b'"s3_bucket":"old-sandbox-bucket"}'
    )
    resp = _signed_snapshot_post(client, "/snapshot/create", body, priv)

    assert resp.status_code == 400
    assert called is False


def test_snapshot_restore_streams_body_to_tempfile_and_returns_204(
    configured_sandbox_daemon: tuple[ModuleType, ModuleType, Ed25519PrivateKey, Path],
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, server_mod, priv, _ = configured_sandbox_daemon
    captured: dict[str, object] = {}

    def fake_restore_snapshot(session_id: UUID, archive_path: Path) -> None:
        captured["session_id"] = session_id
        captured["archive_bytes"] = archive_path.read_bytes()
        captured["archive_exists_during_call"] = archive_path.exists()

    monkeypatch.setattr(server_mod, "restore_snapshot", fake_restore_snapshot)

    body = b"snapshot-archive-bytes"
    session_id = UUID("00000000-0000-0000-0000-000000000001")
    resp = _signed_snapshot_restore_post(
        client,
        f"/snapshot/restore/{session_id}",
        body,
        priv,
    )

    assert resp.status_code == 204
    assert resp.content == b""
    assert captured == {
        "session_id": session_id,
        "archive_bytes": body,
        "archive_exists_during_call": True,
    }


def test_snapshot_restore_over_size_cap_returns_413(
    configured_sandbox_daemon: tuple[ModuleType, ModuleType, Ed25519PrivateKey, Path],
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, server_mod, priv, _ = configured_sandbox_daemon
    called = False

    def fake_restore_snapshot(**_kwargs: object) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(server_mod, "MAX_SNAPSHOT_ARCHIVE_BYTES", 4)
    monkeypatch.setattr(server_mod, "restore_snapshot", fake_restore_snapshot)

    body = b"12345"
    session_id = UUID("00000000-0000-0000-0000-000000000001")
    resp = _signed_snapshot_restore_post(
        client,
        f"/snapshot/restore/{session_id}",
        body,
        priv,
    )

    assert resp.status_code == 413
    assert called is False


def test_snapshot_restore_rejects_sha_mismatch(
    configured_sandbox_daemon: tuple[ModuleType, ModuleType, Ed25519PrivateKey, Path],
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, server_mod, priv, _ = configured_sandbox_daemon
    called = False

    def fake_restore_snapshot(**_kwargs: object) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(server_mod, "restore_snapshot", fake_restore_snapshot)

    body = b"snapshot-archive-bytes"
    wrong_sha = hashlib.sha256(b"different").hexdigest()
    session_id = UUID("00000000-0000-0000-0000-000000000001")
    resp = _signed_snapshot_restore_post(
        client,
        f"/snapshot/restore/{session_id}",
        body,
        priv,
        sha_override=wrong_sha,
    )

    assert resp.status_code == 400
    assert "SHA-256" in resp.text or "mismatch" in resp.text.lower()
    assert called is False


def test_snapshot_restore_extracts_valid_archive(
    sandbox_daemon_modules: tuple[ModuleType, ModuleType],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _ = sandbox_daemon_modules
    snapshot_mod = sys.modules["sandbox_daemon.snapshot"]
    sessions_root = tmp_path / "sessions"
    session_id = UUID("00000000-0000-0000-0000-000000000001")
    session_path = sessions_root / str(session_id)
    (session_path / "outputs").mkdir(parents=True)
    (session_path / "outputs" / "old.txt").write_text("old\n")
    monkeypatch.setattr(snapshot_mod, "SESSIONS_ROOT", sessions_root)

    archive = tmp_path / "snapshot.tar.gz"
    archive.write_bytes(
        _build_targz_bytes(
            {
                "outputs/web/page.tsx": b"// hello\n",
                "attachments/note.txt": b"note\n",
                ".opencode-data/state.json": b"{}\n",
            }
        )
    )

    snapshot_mod.restore_snapshot(session_id, archive)

    assert (session_path / "outputs/web/page.tsx").read_text() == "// hello\n"
    assert (session_path / "attachments/note.txt").read_text() == "note\n"
    assert (session_path / ".opencode-data/state.json").read_text() == "{}\n"
    assert not (session_path / "outputs/old.txt").exists()


def test_snapshot_restore_rejects_traversal_and_links(
    sandbox_daemon_modules: tuple[ModuleType, ModuleType],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _ = sandbox_daemon_modules
    snapshot_mod = sys.modules["sandbox_daemon.snapshot"]
    sessions_root = tmp_path / "sessions"
    session_id = UUID("00000000-0000-0000-0000-000000000001")
    session_path = sessions_root / str(session_id)
    (session_path / "outputs").mkdir(parents=True)
    (session_path / "outputs" / "old.txt").write_text("old\n")
    monkeypatch.setattr(snapshot_mod, "SESSIONS_ROOT", sessions_root)

    traversal_archive = tmp_path / "traversal.tar.gz"
    with tarfile.open(traversal_archive, "w:gz") as tar:
        good_payload = b"safe\n"
        good = tarfile.TarInfo(name="outputs/good.txt")
        good.size = len(good_payload)
        tar.addfile(good, io.BytesIO(good_payload))

        evil_payload = b"nope\n"
        evil = tarfile.TarInfo(name="../escape.txt")
        evil.size = len(evil_payload)
        tar.addfile(evil, io.BytesIO(evil_payload))

    with pytest.raises(snapshot_mod.SnapshotError, match="escapes session"):
        snapshot_mod.restore_snapshot(session_id, traversal_archive)
    assert not (tmp_path / "escape.txt").exists()
    assert (session_path / "outputs/old.txt").read_text() == "old\n"
    assert not (session_path / "outputs/good.txt").exists()

    link_archive = tmp_path / "link.tar.gz"
    with tarfile.open(link_archive, "w:gz") as tar:
        link = tarfile.TarInfo(name="outputs/link")
        link.type = tarfile.SYMTYPE
        link.linkname = "/workspace"
        tar.addfile(link)

    with pytest.raises(snapshot_mod.SnapshotError, match="links are not allowed"):
        snapshot_mod.restore_snapshot(session_id, link_archive)


def test_snapshot_restore_rejects_session_root_symlink(
    sandbox_daemon_modules: tuple[ModuleType, ModuleType],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _ = sandbox_daemon_modules
    snapshot_mod = sys.modules["sandbox_daemon.snapshot"]
    sessions_root = tmp_path / "sessions"
    sessions_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    session_id = UUID("00000000-0000-0000-0000-000000000001")
    (sessions_root / str(session_id)).symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr(snapshot_mod, "SESSIONS_ROOT", sessions_root)

    archive = tmp_path / "snapshot.tar.gz"
    archive.write_bytes(_build_targz_bytes({"outputs/file.txt": b"nope\n"}))

    with pytest.raises(snapshot_mod.SnapshotError, match="session path is a symlink"):
        snapshot_mod.restore_snapshot(session_id, archive)
    assert not (outside / "outputs/file.txt").exists()


def test_snapshot_create_rejects_snapshot_root_symlink(
    sandbox_daemon_modules: tuple[ModuleType, ModuleType],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _ = sandbox_daemon_modules
    snapshot_mod = sys.modules["sandbox_daemon.snapshot"]
    sessions_root = tmp_path / "sessions"
    session_id = UUID("00000000-0000-0000-0000-000000000001")
    session_path = sessions_root / str(session_id)
    outside = tmp_path / "outside"
    outside.mkdir(parents=True)
    session_path.mkdir(parents=True)
    (session_path / "outputs").symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr(snapshot_mod, "SESSIONS_ROOT", sessions_root)

    with pytest.raises(snapshot_mod.SnapshotError, match="outputs is a symlink"):
        list(snapshot_mod.iter_snapshot_archive(session_id))


def test_snapshot_create_skips_nested_unsupported_entries(
    sandbox_daemon_modules: tuple[ModuleType, ModuleType],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _, _ = sandbox_daemon_modules
    snapshot_mod = sys.modules["sandbox_daemon.snapshot"]
    sessions_root = tmp_path / "sessions"
    session_id = UUID("00000000-0000-0000-0000-000000000001")
    session_path = sessions_root / str(session_id)
    outputs_path = session_path / "outputs"
    attachments_path = session_path / "attachments"
    outputs_path.mkdir(parents=True)
    attachments_path.mkdir(parents=True)
    (outputs_path / "safe.txt").write_text("safe\n")
    (outputs_path / "link").symlink_to(tmp_path)
    (attachments_path / "attachment.txt").write_text("keep\n")
    (attachments_path / "link").symlink_to(tmp_path)

    fifo_created = False
    if hasattr(os, "mkfifo"):
        os.mkfifo(outputs_path / "fifo")
        fifo_created = True

    hardlink_created = False
    hardlink_source = tmp_path / "hardlink-source.txt"
    hardlink_source.write_text("hardlink\n")
    try:
        os.link(hardlink_source, outputs_path / "hardlinked.txt")
        hardlink_created = True
    except OSError:
        pass

    monkeypatch.setattr(snapshot_mod, "SESSIONS_ROOT", sessions_root)
    caplog.set_level("WARNING", logger="sandbox_daemon.snapshot")

    archive_bytes = b"".join(snapshot_mod.iter_snapshot_archive(session_id))

    with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:gz") as tar:
        members = tar.getnames()
    assert "outputs/safe.txt" in members
    assert "attachments/attachment.txt" in members
    assert "outputs/link" not in members
    assert "attachments/link" not in members
    if fifo_created:
        assert "outputs/fifo" not in members
    if hardlink_created:
        assert "outputs/hardlinked.txt" not in members

    assert "Skipping" in caplog.text
    assert "outputs/link (symlink)" in caplog.text
    assert "attachments/link (symlink)" in caplog.text
    if fifo_created:
        assert "outputs/fifo (special)" in caplog.text
    if hardlink_created:
        assert "outputs/hardlinked.txt (hardlink)" in caplog.text


def test_snapshot_create_excludes_generated_dirs_from_size_check_and_archive(
    sandbox_daemon_modules: tuple[ModuleType, ModuleType],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _ = sandbox_daemon_modules
    snapshot_mod = sys.modules["sandbox_daemon.snapshot"]
    sessions_root = tmp_path / "sessions"
    session_id = UUID("00000000-0000-0000-0000-000000000001")
    session_path = sessions_root / str(session_id)
    (session_path / "outputs/apps/admin/app").mkdir(parents=True)
    (session_path / "outputs/apps/admin/node_modules/pkg").mkdir(parents=True)
    (session_path / "outputs/apps/admin/.next/cache").mkdir(parents=True)
    (session_path / "attachments/node_modules/pkg").mkdir(parents=True)
    (session_path / "outputs/apps/admin/app/page.tsx").write_text("ok\n")
    (session_path / "outputs/apps/admin/node_modules/pkg/index.js").write_bytes(
        b"x" * 1024
    )
    (session_path / "outputs/apps/admin/.next/cache/blob").write_bytes(b"y" * 1024)
    (session_path / "attachments/node_modules/pkg/index.js").write_text("keep\n")
    monkeypatch.setattr(snapshot_mod, "SESSIONS_ROOT", sessions_root)
    monkeypatch.setattr(snapshot_mod, "MAX_SNAPSHOT_UNCOMPRESSED_BYTES", 16)

    archive_bytes = b"".join(snapshot_mod.iter_snapshot_archive(session_id))

    with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:gz") as tar:
        members = tar.getnames()
    assert "outputs/apps/admin/app/page.tsx" in members
    assert "attachments/node_modules/pkg/index.js" in members
    assert not any(
        member.startswith("outputs/apps/admin/node_modules") for member in members
    )
    assert not any(member.startswith("outputs/apps/admin/.next") for member in members)


@pytest.mark.parametrize(
    "endpoint,body",
    [
        ("/snapshot/create", b'{"session_id":"00000000-0000-0000-0000-000000000003"}'),
        ("/snapshot/restore/00000000-0000-0000-0000-000000000003", b"archive"),
    ],
)
def test_snapshot_signature_from_wrong_key_is_rejected(
    configured_sandbox_daemon: tuple[ModuleType, ModuleType, Ed25519PrivateKey, Path],
    client: TestClient,
    endpoint: str,
    body: bytes,
) -> None:
    """The agent shares the pod network namespace and can curl localhost.
    A signature from any key other than the configured public key must fail.
    """
    _, _, _, _ = configured_sandbox_daemon
    ts = str(int(time.time()))
    other_priv, _ = _new_keypair()
    sha256_hex = hashlib.sha256(body).hexdigest()
    sig = _sign(
        other_priv,
        mount_path=endpoint,
        sha256_hex=sha256_hex,
        timestamp=ts,
    )

    resp = _post_snapshot(
        client,
        endpoint,
        body,
        signature=sig,
        timestamp=ts,
        content_type="application/gzip"
        if "restore" in endpoint
        else "application/json",
        bundle_sha256=sha256_hex if "restore" in endpoint else None,
    )
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
    monkeypatch.setattr(server_mod, "compute_snapshot_digest", lambda _session_id: None)

    signed_body = b'{"session_id":"00000000-0000-0000-0000-000000000003"}'
    ts = str(int(time.time()))
    sig = _sign_snapshot(
        priv, endpoint_path="/snapshot/create", body=signed_body, timestamp=ts
    )

    tampered_body = signed_body.replace(
        b"00000000-0000-0000-0000-000000000003",
        b"00000000-0000-0000-0000-000000000004",
    )

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
    body = b'{"session_id":"00000000-0000-0000-0000-000000000003"}'
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


def test_compute_snapshot_digest_stable_and_detects_change(
    sandbox_daemon_modules: tuple[ModuleType, ModuleType],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Digest is stable for an unchanged tree and changes when content changes."""
    _, _ = sandbox_daemon_modules
    snapshot_mod = sys.modules["sandbox_daemon.snapshot"]
    sessions_root = tmp_path / "sessions"
    session_id = UUID("00000000-0000-0000-0000-000000000042")
    outputs = sessions_root / str(session_id) / "outputs"
    outputs.mkdir(parents=True)
    (outputs / "page.tsx").write_text("hello\n")
    monkeypatch.setattr(snapshot_mod, "SESSIONS_ROOT", sessions_root)

    digest_a = snapshot_mod.compute_snapshot_digest(session_id)
    digest_b = snapshot_mod.compute_snapshot_digest(session_id)
    assert digest_a is not None
    assert digest_a == digest_b

    # Editing a file changes the digest (size differs).
    (outputs / "page.tsx").write_text("hello world\n")
    assert snapshot_mod.compute_snapshot_digest(session_id) != digest_a

    # Empty session has no digest.
    empty_id = UUID("00000000-0000-0000-0000-000000000099")
    assert snapshot_mod.compute_snapshot_digest(empty_id) is None


def test_snapshot_digest_survives_restore(
    sandbox_daemon_modules: tuple[ModuleType, ModuleType],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A workspace restored from its own snapshot yields the same digest.

    Restore preserves mtimes, so an idle->sleep->wake cycle without edits is
    detected as unchanged and skips a redundant snapshot.
    """
    _, _ = sandbox_daemon_modules
    snapshot_mod = sys.modules["sandbox_daemon.snapshot"]
    sessions_root = tmp_path / "sessions"
    monkeypatch.setattr(snapshot_mod, "SESSIONS_ROOT", sessions_root)

    # Archive entries carry a fixed mtime (see _build_targz_bytes); restore
    # re-applies it, so two restores of the same archive must produce the same
    # digest -- i.e. an unchanged workspace is recognized across wake cycles.
    archive = tmp_path / "snap.tar.gz"
    archive.write_bytes(
        _build_targz_bytes(
            {
                "outputs/web/page.tsx": b"// hello\n",
                "attachments/note.txt": b"note\n",
            }
        )
    )

    dst1 = UUID("00000000-0000-0000-0000-0000000000a1")
    dst2 = UUID("00000000-0000-0000-0000-0000000000a2")
    snapshot_mod.restore_snapshot(dst1, archive)
    snapshot_mod.restore_snapshot(dst2, archive)

    digest1 = snapshot_mod.compute_snapshot_digest(dst1)
    assert digest1 is not None
    assert digest1 == snapshot_mod.compute_snapshot_digest(dst2)
