from __future__ import annotations


def test_exec_returns_400_when_executable_missing(client, auth_headers) -> None:
    resp = client.post(
        "/exec",
        headers=auth_headers,
        json={"argv": ["/nonexistent/binary-xyz"]},
    )
    assert resp.status_code == 400
    assert "Cannot start subprocess" in resp.json()["detail"]


def test_exec_returns_400_when_cwd_missing(client, auth_headers) -> None:
    resp = client.post(
        "/exec",
        headers=auth_headers,
        json={"argv": ["/bin/echo", "hi"], "cwd": "/nonexistent-dir-xyz-123"},
    )
    assert resp.status_code == 400


def test_exec_runs_simple_command(client, auth_headers) -> None:
    import base64

    resp = client.post(
        "/exec",
        headers=auth_headers,
        json={"argv": ["/bin/echo", "hello"]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["exit_code"] == 0
    assert base64.b64decode(body["stdout_b64"]).rstrip() == b"hello"
