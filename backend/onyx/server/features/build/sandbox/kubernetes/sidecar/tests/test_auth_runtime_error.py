from __future__ import annotations

from app.config import get_settings


def test_returns_503_when_load_auth_token_fails(
    client, auth_headers, monkeypatch
) -> None:
    """If the token source disappears mid-flight (e.g. Secret rotation),
    callers should see a retryable 503 rather than an opaque 500.
    """

    def _raise(self) -> str:
        raise RuntimeError("token file vanished")

    monkeypatch.setattr(get_settings().__class__, "load_auth_token", _raise)

    resp = client.get("/files/list?path=.", headers=auth_headers)
    assert resp.status_code == 503
    assert "temporarily unavailable" in resp.json()["detail"]
    assert resp.headers.get("Retry-After") == "1"
