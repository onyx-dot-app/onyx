from __future__ import annotations

import base64


def test_exec_truncates_stdout_over_cap(client, auth_headers, monkeypatch) -> None:
    """A chatty subprocess can't blow the sidecar's memory budget."""
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "max_exec_output_bytes", 64)

    resp = client.post(
        "/exec",
        headers=auth_headers,
        json={
            "argv": ["/bin/sh", "-c", "head -c 1024 /dev/zero | tr '\\0' 'a'"],
            "timeout_seconds": 5,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["exit_code"] == 0
    assert body["stdout_truncated"] is True
    assert len(base64.b64decode(body["stdout_b64"])) == 64


def test_exec_does_not_truncate_under_cap(client, auth_headers, monkeypatch) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "max_exec_output_bytes", 1024)

    resp = client.post(
        "/exec",
        headers=auth_headers,
        json={"argv": ["/bin/echo", "hi"], "timeout_seconds": 5},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["stdout_truncated"] is False
    assert body["stderr_truncated"] is False
    assert base64.b64decode(body["stdout_b64"]).rstrip() == b"hi"


def test_exec_interleaved_stdin_stdout_does_not_deadlock(client, auth_headers) -> None:
    """Regression: a subprocess that produces output while consuming stdin must
    not deadlock on full pipe buffers. cat with > pipe-buffer-size stdin is the
    canonical case (~64 KB on Linux). 200 KB exercises the path safely."""
    payload = b"x" * 200_000
    resp = client.post(
        "/exec",
        headers=auth_headers,
        json={
            "argv": ["/bin/cat"],
            "stdin_b64": base64.b64encode(payload).decode(),
            "timeout_seconds": 5,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["timed_out"] is False
    assert body["exit_code"] == 0
    assert base64.b64decode(body["stdout_b64"]) == payload
