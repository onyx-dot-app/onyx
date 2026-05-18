from __future__ import annotations


def test_files_endpoint_rejects_missing_auth(client) -> None:
    resp = client.get("/files/list?path=.")
    assert resp.status_code == 401


def test_files_endpoint_rejects_wrong_token(client) -> None:
    resp = client.get(
        "/files/list?path=.",
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert resp.status_code == 401


def test_files_endpoint_rejects_non_bearer_scheme(client) -> None:
    resp = client.get(
        "/files/list?path=.",
        headers={"Authorization": "Basic dXNlcjpwYXNz"},
    )
    assert resp.status_code == 401


def test_files_endpoint_accepts_correct_token(client, auth_headers) -> None:
    resp = client.get("/files/list?path=.", headers=auth_headers)
    assert resp.status_code == 200
