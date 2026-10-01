"""The webhook body cap.

The route reads the stream itself instead of declaring a ``Body(...)``
dependency, so these tests exercise that reader directly: the point of the
change is that an oversized body is refused *before* anything parses it or
touches the database.
"""

from typing import Any

import pytest
from starlette.requests import Request

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.flows.api import (
    MAX_WEBHOOK_PAYLOAD_BYTES,
    _read_capped_payload,
)


def make_request(
    body: bytes,
    *,
    headers: dict[str, str] | None = None,
    send_content_length: bool = True,
    chunks: list[bytes] | None = None,
) -> Request:
    """A Starlette request over an in-memory body."""
    raw_headers = [
        (name.lower().encode(), value.encode())
        for name, value in (headers or {}).items()
    ]
    if send_content_length:
        raw_headers.append((b"content-length", str(len(body)).encode()))

    pending = list(chunks) if chunks is not None else [body]

    async def receive() -> dict[str, Any]:
        if not pending:
            return {"type": "http.disconnect"}
        return {
            "type": "http.request",
            "body": pending.pop(0),
            "more_body": bool(pending),
        }

    return Request(
        {"type": "http", "method": "POST", "path": "/", "headers": raw_headers},
        receive,
    )


async def read(request: Request) -> dict[str, Any]:
    return await _read_capped_payload(request)


@pytest.mark.asyncio
async def test_reads_a_json_object() -> None:
    request = make_request(b'{"issue": {"id": 7}, "action": "opened"}')
    assert await read(request) == {"issue": {"id": 7}, "action": "opened"}


@pytest.mark.asyncio
async def test_empty_body_is_an_empty_payload() -> None:
    assert await read(make_request(b"")) == {}
    assert await read(make_request(b"   \n")) == {}


@pytest.mark.asyncio
async def test_rejects_malformed_json() -> None:
    with pytest.raises(OnyxError) as caught:
        await read(make_request(b"{not json"))
    assert caught.value.error_code == OnyxErrorCode.INVALID_INPUT


@pytest.mark.asyncio
async def test_rejects_a_json_array() -> None:
    """`{{ trigger.field }}` only means something over an object."""
    with pytest.raises(OnyxError, match="must be a JSON object"):
        await read(make_request(b"[1, 2, 3]"))


@pytest.mark.asyncio
async def test_rejects_an_oversized_body_from_content_length() -> None:
    body = b'{"x": "' + b"a" * MAX_WEBHOOK_PAYLOAD_BYTES + b'"}'

    with pytest.raises(OnyxError, match="over the"):
        await read(make_request(body))


@pytest.mark.asyncio
async def test_content_length_check_never_reads_the_stream() -> None:
    """A declared-oversize request costs nothing but the headers."""

    async def receive() -> dict[str, Any]:
        raise AssertionError("the body should not have been read")

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/",
            "headers": [
                (b"content-length", str(MAX_WEBHOOK_PAYLOAD_BYTES + 1).encode())
            ],
        },
        receive,
    )

    with pytest.raises(OnyxError, match="over the"):
        await read(request)


@pytest.mark.asyncio
async def test_caps_a_chunked_body_with_no_content_length() -> None:
    """Chunked encoding declares no length, so the stream is capped as it
    arrives rather than trusted."""
    chunk = b"a" * 64_000
    oversized = [chunk] * ((MAX_WEBHOOK_PAYLOAD_BYTES // len(chunk)) + 2)

    request = make_request(b"", send_content_length=False, chunks=oversized)

    with pytest.raises(OnyxError, match="over the"):
        await read(request)


@pytest.mark.asyncio
async def test_accepts_a_body_just_under_the_cap() -> None:
    filler = "a" * (MAX_WEBHOOK_PAYLOAD_BYTES - 100)
    request = make_request(b'{"x": "' + filler.encode() + b'"}')

    assert (await read(request))["x"] == filler


@pytest.mark.asyncio
async def test_rejects_a_non_numeric_content_length() -> None:
    request = make_request(
        b"{}", headers={"content-length": "banana"}, send_content_length=False
    )

    with pytest.raises(OnyxError, match="not a number"):
        await read(request)
