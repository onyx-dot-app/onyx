"""Unit tests for the DocMost HTTP client.

These mock ``requests.Session.post`` so no live DocMost instance is needed.
They cover the response-envelope unwrapping, cursor pagination, auth-error
mapping, and the 429/5xx retry/backoff behavior.
"""

from typing import Any
from unittest.mock import MagicMock

import pytest

from onyx.connectors.docmost import client as client_module
from onyx.connectors.docmost.client import DocmostAuthError
from onyx.connectors.docmost.client import DocmostClient
from onyx.connectors.docmost.client import DocmostClientError


def _response(
    status_code: int,
    *,
    json_body: Any = None,
    text: str = "",
    headers: dict[str, str] | None = None,
) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.ok = 200 <= status_code < 300
    resp.headers = headers or {}
    resp.text = text
    resp.json = MagicMock(return_value=json_body)
    return resp


def _client(monkeypatch: pytest.MonkeyPatch, responses: list[Any]) -> DocmostClient:
    """Build a client whose session.post returns the queued responses in order.

    Backoff sleeps are patched out so retry tests run instantly.
    """
    monkeypatch.setattr(client_module.time, "sleep", lambda *_: None)

    c = DocmostClient(base_url="https://docmost.test", api_token="tok")
    post = MagicMock(side_effect=responses)
    monkeypatch.setattr(c._session, "post", post)
    # Expose the mock so tests can assert on call args.
    c._session.post = post  # type: ignore[method-assign]
    return c


class TestBaseUrlNormalization:
    def test_strips_trailing_slash_and_adds_api(self) -> None:
        c = DocmostClient(base_url="https://docmost.test/", api_token="t")
        assert c._api_base == "https://docmost.test/api"

    def test_does_not_double_api_suffix(self) -> None:
        c = DocmostClient(base_url="https://docmost.test/api", api_token="t")
        assert c._api_base == "https://docmost.test/api"

    def test_sets_bearer_header(self) -> None:
        c = DocmostClient(base_url="https://docmost.test", api_token="secret")
        assert c._session.headers["Authorization"] == "Bearer secret"


class TestPostEnvelope:
    def test_unwraps_data_field(self, monkeypatch: pytest.MonkeyPatch) -> None:
        c = _client(
            monkeypatch,
            [_response(200, json_body={"data": {"x": 1}, "success": True})],
        )
        assert c.post("pages/info", {"pageId": "p1"}) == {"x": 1}

    def test_tolerates_bare_body_without_envelope(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        c = _client(monkeypatch, [_response(200, json_body=[1, 2, 3])])
        assert c.post("whatever") == [1, 2, 3]

    def test_sends_payload_as_json(self, monkeypatch: pytest.MonkeyPatch) -> None:
        c = _client(monkeypatch, [_response(200, json_body={"data": {}})])
        c.post("pages/info", {"pageId": "p1"})
        _, kwargs = c._session.post.call_args
        assert kwargs["json"] == {"pageId": "p1"}


class TestAuthErrors:
    @pytest.mark.parametrize("code", [401, 403])
    def test_maps_auth_codes(
        self, monkeypatch: pytest.MonkeyPatch, code: int
    ) -> None:
        c = _client(monkeypatch, [_response(code, text="nope")])
        with pytest.raises(DocmostAuthError):
            c.post("spaces")

    def test_does_not_retry_on_auth_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        c = _client(monkeypatch, [_response(401)])
        with pytest.raises(DocmostAuthError):
            c.post("spaces")
        assert c._session.post.call_count == 1


class TestErrorsAndRetries:
    def test_non_retryable_4xx_raises_client_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        c = _client(monkeypatch, [_response(400, text="bad request")])
        with pytest.raises(DocmostClientError):
            c.post("pages/recent")
        assert c._session.post.call_count == 1

    def test_retries_on_500_then_succeeds(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        c = _client(
            monkeypatch,
            [
                _response(500, text="boom"),
                _response(200, json_body={"data": {"ok": True}}),
            ],
        )
        assert c.post("spaces") == {"ok": True}
        assert c._session.post.call_count == 2

    def test_retries_on_429_then_succeeds(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        c = _client(
            monkeypatch,
            [
                _response(429, headers={"Retry-After": "2"}),
                _response(200, json_body={"data": "done"}),
            ],
        )
        assert c.post("spaces") == "done"
        assert c._session.post.call_count == 2

    def test_exhausts_retries_and_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        c = _client(
            monkeypatch,
            [_response(503) for _ in range(client_module._MAX_RETRIES)],
        )
        with pytest.raises(DocmostClientError):
            c.post("spaces")
        assert c._session.post.call_count == client_module._MAX_RETRIES

    def test_retries_on_request_exception(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        c = _client(
            monkeypatch,
            [
                client_module.requests.RequestException("conn reset"),
                _response(200, json_body={"data": "recovered"}),
            ],
        )
        assert c.post("spaces") == "recovered"
        assert c._session.post.call_count == 2


class TestPaginate:
    def test_follows_cursor_across_pages(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        c = _client(
            monkeypatch,
            [
                _response(
                    200,
                    json_body={
                        "data": {
                            "items": [{"id": "a"}, {"id": "b"}],
                            "meta": {"hasNextPage": True, "nextCursor": "C2"},
                        }
                    },
                ),
                _response(
                    200,
                    json_body={
                        "data": {
                            "items": [{"id": "c"}],
                            "meta": {"hasNextPage": False},
                        }
                    },
                ),
            ],
        )
        items = list(c.paginate("pages/recent"))
        assert [i["id"] for i in items] == ["a", "b", "c"]

        # Second request must carry the cursor returned by the first.
        second_call = c._session.post.call_args_list[1]
        assert second_call.kwargs["json"]["cursor"] == "C2"

    def test_stops_when_next_cursor_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        c = _client(
            monkeypatch,
            [
                _response(
                    200,
                    json_body={
                        "data": {
                            "items": [{"id": "a"}],
                            "meta": {"hasNextPage": True, "nextCursor": None},
                        }
                    },
                ),
            ],
        )
        assert [i["id"] for i in c.paginate("pages/recent")] == ["a"]
        assert c._session.post.call_count == 1

    def test_tolerates_bare_list_data(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        c = _client(
            monkeypatch,
            [_response(200, json_body={"data": [{"id": "a"}, {"id": "b"}]})],
        )
        assert [i["id"] for i in c.paginate("spaces")] == ["a", "b"]

    def test_clamps_limit_to_max(self, monkeypatch: pytest.MonkeyPatch) -> None:
        c = _client(
            monkeypatch,
            [_response(200, json_body={"data": {"items": [], "meta": {}}})],
        )
        list(c.paginate("spaces", limit=9999))
        sent = c._session.post.call_args.kwargs["json"]["limit"]
        assert sent == client_module.MAX_PAGE_LIMIT
