from __future__ import annotations

import base64
from pathlib import Path


def test_write_then_read_roundtrip(client, auth_headers, workspace: Path) -> None:
    content = b"hello sandbox\n"
    resp = client.post(
        "/files/write",
        headers=auth_headers,
        json={
            "path": "session-1/notes.txt",
            "content_b64": base64.b64encode(content).decode(),
        },
    )
    assert resp.status_code == 200
    assert (workspace / "session-1" / "notes.txt").read_bytes() == content

    resp = client.get("/files/read?path=session-1/notes.txt", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["size_bytes"] == len(content)
    assert base64.b64decode(body["content_b64"]) == content


def test_read_missing_file_returns_404(client, auth_headers) -> None:
    resp = client.get("/files/read?path=nope.txt", headers=auth_headers)
    assert resp.status_code == 404


def test_list_directory(client, auth_headers, workspace: Path) -> None:
    (workspace / "a.txt").write_text("a")
    (workspace / "sub").mkdir()
    (workspace / "sub" / "b.txt").write_text("bb")

    resp = client.get("/files/list?path=.", headers=auth_headers)
    assert resp.status_code == 200
    entries = {e["name"]: e for e in resp.json()["entries"]}
    assert entries["a.txt"]["is_dir"] is False
    assert entries["a.txt"]["size_bytes"] == 1
    assert entries["sub"]["is_dir"] is True
    assert entries["sub"]["size_bytes"] is None


def test_path_traversal_is_rejected(client, auth_headers) -> None:
    resp = client.get("/files/read?path=../../etc/passwd", headers=auth_headers)
    assert resp.status_code == 400

    resp = client.post(
        "/files/write",
        headers=auth_headers,
        json={
            "path": "../escape.txt",
            "content_b64": base64.b64encode(b"x").decode(),
        },
    )
    assert resp.status_code == 400


def test_write_invalid_base64_returns_400(client, auth_headers) -> None:
    resp = client.post(
        "/files/write",
        headers=auth_headers,
        json={"path": "x.txt", "content_b64": "not-valid-base64!!!"},
    )
    assert resp.status_code == 400


def test_read_rejects_file_over_max_bytes(
    client, auth_headers, workspace, monkeypatch
) -> None:
    """Bounded read enforces max_read_bytes even when stat() would have lied
    or the file grew under the sidecar's feet (TOCTOU defense)."""
    from app.config import get_settings

    big = workspace / "big.txt"
    big.write_bytes(b"x" * 1024)
    monkeypatch.setattr(get_settings(), "max_read_bytes", 100)

    resp = client.get("/files/read?path=big.txt", headers=auth_headers)
    assert resp.status_code == 413
    assert "max_read_bytes" in resp.json()["detail"]


def test_read_at_exact_limit_succeeds(
    client, auth_headers, workspace, monkeypatch
) -> None:
    from app.config import get_settings

    exact = workspace / "exact.txt"
    exact.write_bytes(b"x" * 100)
    monkeypatch.setattr(get_settings(), "max_read_bytes", 100)

    resp = client.get("/files/read?path=exact.txt", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["size_bytes"] == 100


def test_list_with_broken_symlink_does_not_500(client, auth_headers, workspace) -> None:
    """The sandbox container can create symlinks pointing at deleted files.
    list() must still succeed and report the symlink rather than crashing."""
    (workspace / "real.txt").write_text("data")
    (workspace / "broken").symlink_to(workspace / "does-not-exist")

    resp = client.get("/files/list?path=.", headers=auth_headers)
    assert resp.status_code == 200
    entries = {e["name"]: e for e in resp.json()["entries"]}
    assert "broken" in entries
    assert entries["broken"]["is_dir"] is False
    assert entries["broken"]["size_bytes"] is not None
    assert "real.txt" in entries
