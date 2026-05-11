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
