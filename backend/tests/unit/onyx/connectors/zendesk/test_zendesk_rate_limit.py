from __future__ import annotations

import types
from typing import Any
from typing import Dict

import pytest


class _FakeTime:
    """A controllable time module replacement.

    - monotonic(): returns an internal counter (seconds)
    - sleep(x): advances the internal counter by x seconds
    """

    def __init__(self) -> None:
        self._t = 0.0

    def monotonic(self) -> float:  # type: ignore[override]
        return self._t

    def sleep(self, seconds: float) -> None:  # type: ignore[override]
        # advance time without real waiting
        self._t += float(seconds)


class _FakeResponse:
    def __init__(self, json_payload: Dict[str, Any], status_code: int = 200) -> None:
        self._json = json_payload
        self.status_code = status_code
        self.headers: Dict[str, str] = {}

    def json(self) -> Dict[str, Any]:
        return self._json

    def raise_for_status(self) -> None:
        # simulate OK
        return None


@pytest.mark.unit
def test_zendesk_client_per_minute_rate_limiting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Import here to allow monkeypatching modules safely
    from onyx.connectors.zendesk.connector import ZendeskClient
    import onyx.connectors.cross_connector_utils.rate_limit_wrapper as rlw
    import onyx.connectors.zendesk.connector as zendesk_mod

    fake_time = _FakeTime()

    # Patch time in both the rate limit wrapper and the zendesk connector module
    monkeypatch.setattr(rlw, "time", fake_time, raising=True)
    monkeypatch.setattr(zendesk_mod, "time", fake_time, raising=True)

    # Stub out requests.get to avoid network and return a minimal valid payload
    calls: list[str] = []

    def _fake_get(url: str, auth: Any, params: Dict[str, Any]) -> _FakeResponse:
        calls.append(url)
        # minimal Zendesk list response (articles path)
        return _FakeResponse({"articles": [], "meta": {"has_more": False}})

    monkeypatch.setattr(
        zendesk_mod, "requests", types.SimpleNamespace(get=_fake_get), raising=True
    )

    # Build client with a small limit: 2 calls per 60 seconds
    client = ZendeskClient("subd", "e", "t", calls_per_minute=2)

    # Make three calls in quick succession. The third should be rate limited
    client.make_request("help_center/articles", {"page[size]": 1})
    client.make_request("help_center/articles", {"page[size]": 1})

    # At this point we've used up the 2 allowed calls within the 60s window
    # The next call should trigger sleeps with exponential backoff until >60s elapsed
    client.make_request("help_center/articles", {"page[size]": 1})

    # Ensure we did not actually wait in real time but logically advanced beyond a minute
    assert fake_time.monotonic() >= 60
    # Ensure the HTTP function was invoked three times
    assert len(calls) == 3
