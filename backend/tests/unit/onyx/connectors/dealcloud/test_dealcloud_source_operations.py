import json
from collections.abc import Callable, Iterator
from datetime import datetime, timedelta, timezone
from io import BytesIO
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import requests

from onyx.configs.constants import DocumentSource
from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
from onyx.connectors.dealcloud import source_operations
from onyx.connectors.dealcloud.source_operations import (
    DEALCLOUD_API_KEY,
    DEALCLOUD_CLIENT_ID,
    DealCloudApiError,
    DealCloudSourceOperations,
)
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialInvalidError,
    InsufficientPermissionsError,
    RateLimitedValidationError,
)
from onyx.utils.url import SSRFException

_BASE_URL = "https://example.dealcloud.com"
_TOKEN_URL = f"{_BASE_URL}/api/rest/v1/oauth/token"


def _response(status: int, body: Any = None) -> requests.Response:
    response = requests.Response()
    response.status_code = status
    # The gateway streams the body, so it is served through `raw`.
    response.raw = BytesIO(b"" if body is None else json.dumps(body).encode())
    return response


class _CountingBody(BytesIO):
    bytes_read: int = 0

    def read(self, size: int | None = -1) -> bytes:
        data = super().read(size)
        self.bytes_read += len(data)
        return data


def _token_response(token: str = "token-1") -> requests.Response:
    return _response(200, {"access_token": token, "expires_in": 900})


Transport = Callable[..., MagicMock]


class _Clock:
    """Stands in for the time module in the gateway: a sleep moves the clock
    at once, so waits are instant and their length can be read back."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.slept: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


@pytest.fixture
def clock() -> Iterator[_Clock]:
    fake = _Clock()
    with patch.object(source_operations, "time", fake):
        yield fake


@pytest.fixture
def gateway(clock: _Clock) -> DealCloudSourceOperations:  # noqa: ARG001
    return DealCloudSourceOperations(
        credentials_provider=OnyxStaticCredentialsProvider(
            None,
            DocumentSource.DEALCLOUD.value,
            {DEALCLOUD_CLIENT_ID: "106", DEALCLOUD_API_KEY: "key"},
        ),
        connector_specific_config={"base_url": _BASE_URL},
    )


@pytest.fixture
def transport() -> Iterator[Transport]:
    """Patches the SSRF-safe transport. Token requests get `tokens` in order
    (one fresh token each by default), and API requests get `answers`."""
    with patch.object(source_operations, "ssrf_safe_request") as send:

        def install(
            answers: list[requests.Response],
            tokens: list[requests.Response] | None = None,
        ) -> MagicMock:
            api = iter(answers)
            token = iter(tokens) if tokens is not None else None

            def route(url: str, **_kwargs: Any) -> requests.Response:
                if url != _TOKEN_URL:
                    return next(api)
                return next(token) if token is not None else _token_response()

            send.side_effect = route
            return send

        yield install


def _api_calls(send: MagicMock) -> list[Any]:
    return [call for call in send.call_args_list if call.args[0] != _TOKEN_URL]


def _token_calls(send: MagicMock) -> list[Any]:
    return [call for call in send.call_args_list if call.args[0] == _TOKEN_URL]


def test_one_token_serves_many_calls(
    gateway: DealCloudSourceOperations, transport: Transport
) -> None:
    send = transport([_response(200, []), _response(200, [])])

    gateway.list_entry_types()
    gateway.list_entry_types()

    (token_call,) = _token_calls(send)
    assert token_call.kwargs["method"] == "POST"
    assert token_call.kwargs["data"] == {
        "grant_type": "client_credentials",
        "scope": "data",
        "client_id": "106",
        "client_secret": "key",
    }
    assert "Authorization" not in token_call.kwargs["headers"]
    api_call = _api_calls(send)[-1]
    assert api_call.args[0] == f"{_BASE_URL}/api/rest/v4/schema/entrytypes"
    assert api_call.kwargs["headers"]["Authorization"] == "Bearer token-1"
    assert api_call.kwargs["https_only"] is True


def test_a_401_buys_a_new_token_once(
    gateway: DealCloudSourceOperations, transport: Transport
) -> None:
    send = transport(
        [_response(401), _response(200, [])],
        tokens=[_token_response("token-1"), _token_response("token-2")],
    )

    assert gateway.list_entry_types() == []

    assert len(_token_calls(send)) == 2
    assert _api_calls(send)[-1].kwargs["headers"]["Authorization"] == "Bearer token-2"


@pytest.mark.parametrize(
    "answers, error",
    [
        ([_response(401), _response(401)], CredentialInvalidError),
        ([_response(403)], InsufficientPermissionsError),
        ([_response(302)], DealCloudApiError),
        ([_response(404)], DealCloudApiError),
    ],
    ids=["401 twice", "403", "redirect", "404"],
)
def test_each_status_maps_to_its_error(
    gateway: DealCloudSourceOperations,
    transport: Transport,
    answers: list[requests.Response],
    error: type[Exception],
) -> None:
    transport(answers)

    with pytest.raises(error):
        gateway.list_entry_types()


def test_a_rejected_key_is_an_invalid_credential(
    gateway: DealCloudSourceOperations, transport: Transport
) -> None:
    transport([], tokens=[_response(400)])

    with pytest.raises(CredentialInvalidError):
        gateway.list_entry_types()


def test_an_unsafe_site_url_is_a_validation_error(
    gateway: DealCloudSourceOperations,
) -> None:
    with (
        patch.object(
            source_operations,
            "ssrf_safe_request",
            side_effect=SSRFException("private address"),
        ),
        pytest.raises(ConnectorValidationError, match="Invalid DealCloud URL"),
    ):
        gateway.list_entry_types()


def test_an_answer_read_whole_fails_past_the_size_cap(
    gateway: DealCloudSourceOperations, transport: Transport
) -> None:
    transport([_response(200, [{"id": n, "apiName": "x" * 50} for n in range(100)])])

    with (
        patch.object(source_operations, "MAX_RESPONSE_BYTES", 1024),
        patch.object(source_operations, "_READ_CHUNK_BYTES", 256),
        pytest.raises(DealCloudApiError, match="larger than"),
    ):
        gateway.list_entry_types()


def test_an_entry_too_large_to_read_comes_back_marked(
    gateway: DealCloudSourceOperations, transport: Transport
) -> None:
    """Raising would stop the run at this entry on every retry."""
    transport(
        [
            _response(
                200, {"rows": [{"EntryId": n, "Notes": "x" * 50} for n in range(100)]}
            )
        ]
    )

    with (
        patch.object(source_operations, "MAX_RESPONSE_BYTES", 1024),
        patch.object(source_operations, "_READ_CHUNK_BYTES", 256),
    ):
        rows = gateway.get_rows(entry_type_id=2014, entry_ids=[1])

    assert [(row.entry_id, row.is_too_large, row.values) for row in rows] == [
        (1, True, {})
    ]


def test_an_id_listing_is_parsed_across_chunks_without_a_size_cap(
    gateway: DealCloudSourceOperations, transport: Transport
) -> None:
    listing = [
        {"id": n, "name": f"Entry {n} é]}}[", "entryListId": 2014} for n in (3, 1, 2)
    ]
    transport([_response(200, listing)])

    with (
        # Above the token answer, below the listing.
        patch.object(source_operations, "MAX_RESPONSE_BYTES", 64),
        patch.object(source_operations, "_READ_CHUNK_BYTES", 7),
    ):
        assert gateway.list_entry_ids(entry_type_id=2014) == [1, 2, 3]


def test_an_object_with_too_many_entries_fails(
    gateway: DealCloudSourceOperations, transport: Transport
) -> None:
    transport([_response(200, [{"id": n} for n in range(5)])])

    with (
        patch.object(source_operations, "MAX_LISTED_ENTRIES", 3),
        pytest.raises(DealCloudApiError, match="more than 3 entries"),
    ):
        gateway.list_entry_ids(entry_type_id=2014)


def test_a_listing_cut_off_mid_answer_fails(
    gateway: DealCloudSourceOperations, transport: Transport
) -> None:
    cut = _response(200)
    cut.raw = BytesIO(b'[{"id": 1}, {"id": 2')
    transport([cut])

    with pytest.raises(DealCloudApiError, match="ended before"):
        gateway.list_entry_ids(entry_type_id=2014)


def test_a_connection_lost_while_the_answer_is_read_is_tried_again(
    gateway: DealCloudSourceOperations, transport: Transport
) -> None:
    class _Dropping(BytesIO):
        def read(self, size: int | None = -1) -> bytes:  # noqa: ARG002
            raise requests.ConnectionError("reset")

    dropped = _response(200)
    dropped.raw = _Dropping()
    send = transport([dropped, _response(200, [])])

    assert gateway.list_entry_types() == []
    assert len(_api_calls(send)) == 2


def test_a_throttled_token_request_is_tried_again(
    gateway: DealCloudSourceOperations, transport: Transport
) -> None:
    send = transport(
        [_response(200, [])], tokens=[_response(429), _response(503), _token_response()]
    )

    assert gateway.list_entry_types() == []
    assert len(_token_calls(send)) == 3


def test_a_rate_limit_wait_ends_at_the_reset_dealcloud_names(
    gateway: DealCloudSourceOperations, transport: Transport
) -> None:
    limited = _response(429)
    limited.headers["X-Rate-Limit-Reset"] = (
        datetime.now(timezone.utc) + timedelta(milliseconds=400)
    ).isoformat()
    transport([limited, _response(200, [])])

    with patch.object(
        source_operations, "bound_server_wait", return_value=0.0
    ) as bound:
        gateway.list_entry_types()

    waited = bound.call_args.args[0]
    assert 0.0 < waited <= 0.4


def test_only_the_start_of_an_error_body_is_read(
    gateway: DealCloudSourceOperations, transport: Transport
) -> None:
    body = _CountingBody(b"x" * 10_000)
    denied = _response(403)
    denied.raw = body
    transport([denied])

    with pytest.raises(InsufficientPermissionsError) as error:
        gateway.list_entry_types()

    assert len(str(error.value)) < 700
    assert body.bytes_read == 500


def test_a_rate_limited_call_is_sent_again(
    gateway: DealCloudSourceOperations, transport: Transport
) -> None:
    send = transport([_response(429), _response(200, [])])

    with patch.object(
        source_operations, "bound_server_wait", return_value=1.0
    ) as bound:
        assert gateway.list_entry_types() == []

    assert len(_api_calls(send)) == 2
    # No reset header on the answer, so the wait is the one second window.
    bound.assert_called_once_with(1.0, "dealcloud")


def test_refusals_wait_without_using_up_the_retries_for_failures(
    gateway: DealCloudSourceOperations, transport: Transport
) -> None:
    send = transport([_response(429) for _ in range(10)] + [_response(200, [])])

    assert gateway.list_entry_types() == []
    assert len(_api_calls(send)) == 11


def test_a_site_that_keeps_refusing_ends_the_run(
    gateway: DealCloudSourceOperations, transport: Transport
) -> None:
    transport([_response(429) for _ in range(4)])

    with (
        patch.object(source_operations, "_MAX_RATE_LIMIT_WAITS", 3),
        pytest.raises(RateLimitedValidationError),
    ):
        gateway.list_entry_types()


def test_a_refusal_holds_back_the_whole_gateway(
    gateway: DealCloudSourceOperations, transport: Transport, clock: _Clock
) -> None:
    transport([_response(429), _response(200, [])])
    plain_sleep = clock.sleep
    other_call_waited: list[float] = []

    def sleep_while_another_call_arrives(seconds: float) -> None:
        if not other_call_waited and seconds >= 30.0:
            # Another thread asks for its turn while this one waits out the
            # refusal.
            other_call_waited.append(0.0)
            arrived = clock.now
            gateway._wait_for_turn()
            other_call_waited[0] = clock.now - arrived
        plain_sleep(seconds)

    with (
        patch.object(source_operations, "bound_server_wait", return_value=30.0),
        patch.object(clock, "sleep", sleep_while_another_call_arrives),
    ):
        gateway.list_entry_types()

    assert other_call_waited[0] >= 30.0


def test_a_call_already_waiting_for_its_turn_obeys_a_pause_that_arrives(
    gateway: DealCloudSourceOperations, clock: _Clock
) -> None:
    gateway._next_request_at = clock.now + 0.2
    started = clock.now
    plain_sleep = clock.sleep

    def sleep_then_refuse(seconds: float) -> None:
        plain_sleep(seconds)
        if len(clock.slept) == 1:
            # Another thread got a 429 while this call slept for its slot.
            gateway._pause(10.0)

    with patch.object(clock, "sleep", sleep_then_refuse):
        gateway._wait_for_turn()

    assert clock.now >= started + 10.0


def test_a_site_that_asks_for_long_waits_ends_the_run_without_waiting_them_out(
    gateway: DealCloudSourceOperations, transport: Transport, clock: _Clock
) -> None:
    transport([_response(429), _response(429)])
    before = clock.now

    with (
        patch.object(source_operations, "bound_server_wait", return_value=200.0),
        pytest.raises(RateLimitedValidationError),
    ):
        gateway.list_entry_types()

    # The first wait fits the 300 second budget. The second would pass it.
    assert clock.now - before < 300.0


def test_a_short_page_of_rows_is_read_again_in_halves(
    gateway: DealCloudSourceOperations, transport: Transport
) -> None:
    def rows(*entry_ids: int) -> dict[str, Any]:
        return {
            "totalRecords": len(entry_ids),
            "rows": [{"EntryId": n} for n in entry_ids],
        }

    send = transport(
        [
            _response(
                200, {"totalRecords": 4, "rows": [{"EntryId": 1}, {"EntryId": 2}]}
            ),
            _response(200, rows(1, 2)),
            _response(200, rows(3, 4)),
        ]
    )

    read = gateway.get_rows(entry_type_id=2014, entry_ids=[1, 2, 3, 4])

    assert [row.entry_id for row in read] == [1, 2, 3, 4]
    assert [call.kwargs["json"]["query"] for call in _api_calls(send)] == [
        "EntryId in (1,2,3,4)",
        "EntryId in (1,2)",
        "EntryId in (3,4)",
    ]


def test_a_matched_row_that_never_arrives_fails_the_batch(
    gateway: DealCloudSourceOperations, transport: Transport
) -> None:
    transport(
        [
            _response(200, {"totalRecords": 2, "rows": [{"EntryId": 1}]}),
            _response(200, {"totalRecords": 1, "rows": [{"EntryId": 1}]}),
            _response(200, {"totalRecords": 1, "rows": []}),
        ]
    )

    with pytest.raises(DealCloudApiError, match="matched entry 2"):
        gateway.get_rows(entry_type_id=2014, entry_ids=[1, 2])


def test_a_batch_whose_answer_is_too_large_is_read_in_halves(
    gateway: DealCloudSourceOperations, transport: Transport
) -> None:
    wide = {"EntryId": 1, "Notes": "x" * 200}
    send = transport(
        [
            _response(200, {"totalRecords": 2, "rows": [wide, {**wide, "EntryId": 2}]}),
            _response(200, {"totalRecords": 1, "rows": [wide]}),
            _response(200, {"totalRecords": 1, "rows": [{**wide, "EntryId": 2}]}),
        ]
    )

    with (
        # Above one row and the token answer, below two rows.
        patch.object(source_operations, "MAX_RESPONSE_BYTES", 400),
        patch.object(source_operations, "_READ_CHUNK_BYTES", 64),
    ):
        rows = gateway.get_rows(entry_type_id=2014, entry_ids=[1, 2])

    assert [row.entry_id for row in rows] == [1, 2]
    assert len(_api_calls(send)) == 3


def test_a_listed_entry_that_never_closes_fails_instead_of_filling_memory(
    gateway: DealCloudSourceOperations, transport: Transport
) -> None:
    endless = _response(200)
    endless.raw = BytesIO(b'[{"id": 1, "name": "' + b"x" * 5000)
    transport([endless])

    with (
        patch.object(source_operations, "_MAX_LISTED_ENTRY_CHARS", 1000),
        patch.object(source_operations, "_READ_CHUNK_BYTES", 256),
        pytest.raises(DealCloudApiError, match="longer than 1000"),
    ):
        gateway.list_entry_ids(entry_type_id=2014)


def test_rows_are_queried_by_entry_id(
    gateway: DealCloudSourceOperations, transport: Transport
) -> None:
    answer = {
        "totalRecords": 1,
        "rows": [{"EntryId": 7, "CompanyName": {"id": 7, "name": "Acme"}}],
    }
    send = transport([_response(200, answer)])

    rows = gateway.get_rows(entry_type_id=2014, entry_ids=[7, 9])

    (call,) = _api_calls(send)
    assert call.args[0] == f"{_BASE_URL}/api/rest/v4/data/entrydata/rows/query/2014"
    assert call.kwargs["method"] == "POST"
    assert call.kwargs["json"] == {
        "query": "EntryId in (7,9)",
        "limit": 2,
        "skip": 0,
        "wrapIntoArrays": True,
        "resolveReferenceUrls": True,
    }
    assert [(row.entry_id, row.values) for row in rows] == [
        (7, {"CompanyName": {"id": 7, "name": "Acme"}})
    ]


def test_changed_entries_send_the_time_format_dealcloud_accepts(
    gateway: DealCloudSourceOperations, transport: Transport
) -> None:
    send = transport(
        [
            _response(
                200,
                [
                    {"id": 9, "isDeleted": False},
                    {"id": 5, "isDeleted": True},
                    {"id": 2, "isDeleted": False},
                ],
            )
        ]
    )

    changed = gateway.list_changed_entry_ids(
        entry_type_id=2014,
        modified_since=datetime(2026, 4, 26, 1, 16, 40, 30_000, tzinfo=timezone.utc),
    )

    (call,) = _api_calls(send)
    assert call.kwargs["params"] == {"modifiedSince": "2026-04-26T01:16:40.030Z"}
    # Ascending, without the deleted entry.
    assert changed == [2, 9]
