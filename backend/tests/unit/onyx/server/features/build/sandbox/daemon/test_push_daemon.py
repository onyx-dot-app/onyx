"""Cluster I - In-pod push daemon (the FastAPI side of Cluster G).

Behavior tests over the FastAPI push daemon using ``fastapi.testclient``.
The daemon module is loaded dynamically under the ``push_daemon`` package
name because its in-container layout (``COPY daemon/ /workspace/push_daemon``)
isn't reflected in the backend Python path.
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

# Resolve the daemon directory relative to this test file so the path works in
# both local dev and CI. This file lives at:
#   backend/tests/unit/onyx/server/features/build/sandbox/daemon/test_push_daemon.py
# so parents[9] is the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[9]
_DAEMON_DIR = (
    _REPO_ROOT / "backend/onyx/server/features/build/sandbox/kubernetes/docker/daemon"
)


def _load_daemon_modules() -> tuple[ModuleType, ModuleType]:
    """Load ``push_daemon.extract`` and ``push_daemon.server`` from the
    daemon directory.

    The daemon's source imports ``from push_daemon.extract import ...`` because
    in the container the directory is copied to ``/workspace/push_daemon/``.
    The test runner doesn't have that path, so we register the modules under
    the expected names in ``sys.modules`` before loading server.py.
    """
    # If already loaded, return cached.
    if "push_daemon.server" in sys.modules and "push_daemon.extract" in sys.modules:
        return sys.modules["push_daemon.extract"], sys.modules["push_daemon.server"]

    if "push_daemon" not in sys.modules:
        sys.modules["push_daemon"] = types.ModuleType("push_daemon")

    extract_spec = importlib.util.spec_from_file_location(
        "push_daemon.extract", str(_DAEMON_DIR / "extract.py")
    )
    assert extract_spec is not None and extract_spec.loader is not None
    extract_mod = importlib.util.module_from_spec(extract_spec)
    sys.modules["push_daemon.extract"] = extract_mod
    extract_spec.loader.exec_module(extract_mod)

    server_spec = importlib.util.spec_from_file_location(
        "push_daemon.server", str(_DAEMON_DIR / "server.py")
    )
    assert server_spec is not None and server_spec.loader is not None
    server_mod = importlib.util.module_from_spec(server_spec)
    sys.modules["push_daemon.server"] = server_mod
    server_spec.loader.exec_module(server_mod)

    return extract_mod, server_mod


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
def daemon_modules() -> tuple[ModuleType, ModuleType]:
    """Load extract + server modules once per test."""
    return _load_daemon_modules()


@pytest.fixture
def keypair() -> tuple[Ed25519PrivateKey, str]:
    return _new_keypair()


@pytest.fixture
def configured_daemon(
    daemon_modules: tuple[ModuleType, ModuleType],
    keypair: tuple[Ed25519PrivateKey, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[ModuleType, ModuleType, Ed25519PrivateKey, Path]:
    """Daemon with the public key env set and the ALLOWED_PREFIX pointed
    at a temp directory so extraction stays hermetic.
    """
    extract_mod, server_mod = daemon_modules
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
    configured_daemon: tuple[ModuleType, ModuleType, Ed25519PrivateKey, Path],
) -> Generator[TestClient, None, None]:
    _, server_mod, _, _ = configured_daemon
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
    configured_daemon: tuple[ModuleType, ModuleType, Ed25519PrivateKey, Path],
    client: TestClient,
) -> None:
    _, _, priv, allowed_root = configured_daemon
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
    configured_daemon: tuple[ModuleType, ModuleType, Ed25519PrivateKey, Path],
    client: TestClient,
) -> None:
    _, _, priv, allowed_root = configured_daemon
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
    configured_daemon: tuple[ModuleType, ModuleType, Ed25519PrivateKey, Path],
    client: TestClient,
) -> None:
    _, _, priv, allowed_root = configured_daemon
    mount_path = str(allowed_root / "skills")
    body = _build_targz_bytes({"my-skill/SKILL.md": b"x"})
    old_ts = str(int(time.time()) - 120)  # 2 minutes in the past
    resp = _push_request(
        client, priv=priv, mount_path=mount_path, body=body, timestamp_override=old_ts
    )
    assert resp.status_code == 401


def test_push_with_future_timestamp_returns_401(
    configured_daemon: tuple[ModuleType, ModuleType, Ed25519PrivateKey, Path],
    client: TestClient,
) -> None:
    _, _, priv, allowed_root = configured_daemon
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
    configured_daemon: tuple[ModuleType, ModuleType, Ed25519PrivateKey, Path],
    client: TestClient,
) -> None:
    """Header SHA != computed -> 400.

    The signature is over the *header* SHA (not the body bytes), so to reach
    the SHA-mismatch branch the request must pass signature verification with
    the wrong SHA in the header. We sign over the wrong SHA so verification
    passes, then the body hashes to a different value.
    """
    _, _, priv, allowed_root = configured_daemon
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
    configured_daemon: tuple[ModuleType, ModuleType, Ed25519PrivateKey, Path],
    client: TestClient,
) -> None:
    """Content-Length > 100 MiB -> 413, body never streamed."""
    extract_mod, _, priv, allowed_root = configured_daemon
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
    configured_daemon: tuple[ModuleType, ModuleType, Ed25519PrivateKey, Path],
    client: TestClient,
) -> None:
    """mount_path outside ALLOWED_PREFIX (e.g. /etc) is rejected with 400."""
    _, _, priv, _ = configured_daemon
    mount_path = "/etc"
    body = _build_targz_bytes({"shadow": b"oops"})

    resp = _push_request(client, priv=priv, mount_path=mount_path, body=body)
    assert resp.status_code == 400


def test_push_missing_public_key_raises_onyx_error(
    configured_daemon: tuple[ModuleType, ModuleType, Ed25519PrivateKey, Path],
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Daemon without the public-key env var returns a 500 with a descriptive
    detail.

    Note: the in-pod daemon is standalone Python (no Onyx imports) so it
    surfaces this via ``HTTPException(status_code=500, ...)`` rather than
    ``OnyxError``. The behavior asserted here matches the master plan's
    intent (operator-facing error when key is missing) and what the
    FastAPI TestClient can observe.
    """
    _, server_mod, priv, allowed_root = configured_daemon

    # Remove the env var and clear the cached key.
    monkeypatch.delenv("ONYX_SANDBOX_PUSH_PUBLIC_KEY", raising=False)
    monkeypatch.setattr(server_mod, "_public_key", None, raising=False)

    mount_path = str(allowed_root / "skills")
    body = _build_targz_bytes({"x": b"x"})
    resp = _push_request(client, priv=priv, mount_path=mount_path, body=body)

    assert resp.status_code == 500
    assert "public key" in resp.text.lower()
