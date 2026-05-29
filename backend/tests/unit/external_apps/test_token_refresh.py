import json
from contextlib import contextmanager
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
import requests

from onyx.external_apps import token_refresh as tr
from onyx.external_apps.providers.base import TokenRefreshTerminalError
from onyx.external_apps.providers.base import TokenRefreshTransientError
from onyx.external_apps.providers.google_calendar import GoogleCalendarProvider

# ---------------------------------------------------------------------------
# Provider.refresh_credentials (RFC-6749 default on OAuthExternalAppProvider)
# ---------------------------------------------------------------------------


def _response(status_code: int, body: dict[str, Any]) -> requests.Response:
    """A real `requests.Response` (the `OAuthTokenResponse` model validates the
    type), with `status_code` set and `.json()` returning `body`."""
    response = requests.Response()
    response.status_code = status_code
    response._content = json.dumps(body).encode()
    return response


def _patch_post(monkeypatch: pytest.MonkeyPatch, response: object) -> None:
    monkeypatch.setattr(
        "onyx.external_apps.providers.base.requests.post",
        lambda *_a, **_k: response,
    )


def test_refresh_maps_response_and_carries_refresh_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_post(
        monkeypatch,
        _response(200, {"access_token": "new", "expires_in": 3600}),
    )
    result = GoogleCalendarProvider().refresh_credentials(
        {"access_token": "old", "refresh_token": "rt"}, "cid", "secret"
    )
    assert result["access_token"] == "new"
    assert result["expires_in"] == 3600
    # No new refresh token in the response → carry the old one forward.
    assert result["refresh_token"] == "rt"
    # Clockless: the orchestrator stamps the absolute expiry, not the provider.
    assert "expires_at" not in result


def test_refresh_uses_rotated_refresh_token(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_post(
        monkeypatch,
        _response(200, {"access_token": "new", "refresh_token": "rt2"}),
    )
    result = GoogleCalendarProvider().refresh_credentials(
        {"refresh_token": "rt"}, "cid", "secret"
    )
    assert result["refresh_token"] == "rt2"


def test_refresh_missing_refresh_token_is_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = MagicMock()
    monkeypatch.setattr("onyx.external_apps.providers.base.requests.post", called)
    with pytest.raises(TokenRefreshTerminalError):
        GoogleCalendarProvider().refresh_credentials({"access_token": "a"}, "c", "s")
    called.assert_not_called()


def test_refresh_invalid_grant_is_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_post(monkeypatch, _response(400, {"error": "invalid_grant"}))
    with pytest.raises(TokenRefreshTerminalError):
        GoogleCalendarProvider().refresh_credentials({"refresh_token": "rt"}, "c", "s")


def test_refresh_5xx_is_transient(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_post(monkeypatch, _response(503, {"error": "server_error"}))
    with pytest.raises(TokenRefreshTransientError):
        GoogleCalendarProvider().refresh_credentials({"refresh_token": "rt"}, "c", "s")


def test_refresh_network_error_is_transient(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*_a: Any, **_k: Any) -> None:
        raise requests.RequestException("connection reset")

    monkeypatch.setattr("onyx.external_apps.providers.base.requests.post", _boom)
    with pytest.raises(TokenRefreshTransientError):
        GoogleCalendarProvider().refresh_credentials({"refresh_token": "rt"}, "c", "s")


# ---------------------------------------------------------------------------
# Template-method extensibility: a provider overrides one hook, reuses the rest
# ---------------------------------------------------------------------------


def _capturing_post(
    monkeypatch: pytest.MonkeyPatch, response: object
) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    def _post(url: str, **kwargs: Any) -> object:
        captured["url"] = url
        captured["data"] = kwargs.get("data")
        return response

    monkeypatch.setattr("onyx.external_apps.providers.base.requests.post", _post)
    return captured


def test_provider_overrides_only_the_refresh_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A provider needing an extra refresh param overrides `build_refresh_request`
    alone — the POST, error handling, and response mapping are inherited."""

    class _ResourceProvider(GoogleCalendarProvider, abstract=True):
        def build_refresh_request(
            self, refresh_token: str, client_id: str, client_secret: str
        ) -> dict[str, str]:
            base = super().build_refresh_request(
                refresh_token, client_id, client_secret
            )
            return {**base, "resource": "r"}

    captured = _capturing_post(monkeypatch, _response(200, {"access_token": "new"}))
    result = _ResourceProvider().refresh_credentials(
        {"refresh_token": "rt"}, "cid", "secret"
    )
    assert captured["data"]["resource"] == "r"  # the override took effect
    assert captured["data"]["grant_type"] == "refresh_token"  # inherited default
    assert result["access_token"] == "new"  # inherited mapping


def test_provider_overrides_only_the_terminal_error_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A provider with different failure semantics overrides
    `terminal_refresh_errors` alone."""

    class _StrictProvider(GoogleCalendarProvider, abstract=True):
        terminal_refresh_errors = frozenset({"consent_required"})

    _patch_post(monkeypatch, _response(400, {"error": "consent_required"}))
    with pytest.raises(TokenRefreshTerminalError):
        _StrictProvider().refresh_credentials({"refresh_token": "rt"}, "c", "s")

    # `invalid_grant` is no longer terminal for this provider → transient.
    _patch_post(monkeypatch, _response(400, {"error": "invalid_grant"}))
    with pytest.raises(TokenRefreshTransientError):
        _StrictProvider().refresh_credentials({"refresh_token": "rt"}, "c", "s")


# ---------------------------------------------------------------------------
# ensure_fresh_credentials orchestration (own short sessions, single-flight)
# ---------------------------------------------------------------------------


def _stale_creds() -> dict[str, Any]:
    return {
        "access_token": "old",
        "refresh_token": "rt",
        "expires_at": "2000-01-01T00:00:00+00:00",
    }


def _fresh_creds() -> dict[str, Any]:
    return {
        "access_token": "ok",
        "refresh_token": "rt",
        "expires_at": "2999-01-01T00:00:00+00:00",
    }


def _cred(values: dict[str, Any]) -> MagicMock:
    cred = MagicMock()
    cred.user_credentials.get_value.return_value = values
    return cred


@contextmanager
def _noop_cm(*_a: Any, **_k: Any):  # type: ignore[no-untyped-def]
    yield MagicMock()


def _setup(
    monkeypatch: pytest.MonkeyPatch,
    *,
    creds_sequence: list[dict[str, Any]],
) -> dict[str, MagicMock]:
    """Patch token_refresh's DB + provider + lock seams. `creds_sequence` is the
    stored credentials returned on successive reads (pre-check, then re-read under
    the lock)."""
    provider = GoogleCalendarProvider()
    app = MagicMock()
    app.skill.name = "Google Calendar"

    monkeypatch.setattr(tr, "redis_shared_lock", _noop_cm)
    monkeypatch.setattr(tr, "get_external_app_by_id", lambda *_a, **_k: app)
    monkeypatch.setattr(tr, "get_provider_for_app", lambda *_a, **_k: provider)
    monkeypatch.setattr(
        tr,
        "get_external_app_user_credential",
        MagicMock(side_effect=[_cred(c) for c in creds_sequence]),
    )
    monkeypatch.setattr(tr, "_client_credentials", lambda _app: ("cid", "secret"))
    upsert = MagicMock()
    delete = MagicMock()
    refresh = MagicMock()
    monkeypatch.setattr(tr, "upsert_external_app_user_credential", upsert)
    monkeypatch.setattr(tr, "delete_external_app_user_credential", delete)
    monkeypatch.setattr(provider, "refresh_credentials", refresh)
    return {"upsert": upsert, "delete": delete, "refresh": refresh}


def _run() -> None:
    # The factory: any callable returning a context manager yielding a session.
    tr.ensure_fresh_credentials(_noop_cm, "public", 1, uuid4())


def test_ensure_fresh_noop_when_token_fresh(monkeypatch: pytest.MonkeyPatch) -> None:
    spies = _setup(monkeypatch, creds_sequence=[_fresh_creds()])
    _run()
    spies["refresh"].assert_not_called()
    spies["upsert"].assert_not_called()


def test_ensure_fresh_double_checked_skips_when_winner_refreshed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Pre-check sees stale; the re-read under the lock sees the winner's fresh
    # token → no network call.
    spies = _setup(monkeypatch, creds_sequence=[_stale_creds(), _fresh_creds()])
    _run()
    spies["refresh"].assert_not_called()
    spies["upsert"].assert_not_called()


def test_ensure_fresh_refreshes_and_upserts_stamped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spies = _setup(monkeypatch, creds_sequence=[_stale_creds(), _stale_creds()])
    spies["refresh"].return_value = {
        "access_token": "new",
        "refresh_token": "rt",
        "expires_in": 3600,
    }
    _run()
    spies["upsert"].assert_called_once()
    stored = spies["upsert"].call_args.kwargs["user_credentials"]
    assert stored["access_token"] == "new"
    assert "expires_at" in stored  # stamped from expires_in


def test_ensure_fresh_terminal_clears_credential_without_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spies = _setup(monkeypatch, creds_sequence=[_stale_creds(), _stale_creds()])
    spies["refresh"].side_effect = TokenRefreshTerminalError("invalid_grant")
    _run()  # does not raise — the app simply reads as disconnected afterwards
    spies["delete"].assert_called_once()
    spies["upsert"].assert_not_called()


def test_ensure_fresh_transient_keeps_existing_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spies = _setup(monkeypatch, creds_sequence=[_stale_creds(), _stale_creds()])
    spies["refresh"].side_effect = TokenRefreshTransientError("503")
    _run()  # does not raise
    spies["upsert"].assert_not_called()
    spies["delete"].assert_not_called()


def test_ensure_fresh_noop_for_non_oauth_app(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tr, "redis_shared_lock", _noop_cm)
    monkeypatch.setattr(tr, "get_external_app_by_id", lambda *_a, **_k: MagicMock())
    monkeypatch.setattr(tr, "get_provider_for_app", lambda *_a, **_k: None)
    cred_reader = MagicMock()
    monkeypatch.setattr(tr, "get_external_app_user_credential", cred_reader)
    _run()
    cred_reader.assert_not_called()  # bailed before reading credentials
